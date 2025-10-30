#!/usr/bin/env python3
# Cliente: LED y botón para 'toggle' (REST) con fallback a polling si falla la interrupción.
import time, json, http.client, ssl, socket
from pathlib import Path
import RPi.GPIO as GPIO

# === Pines (BOARD) ===
LED_TOGGLE = 33   # LED de 'toggle'
BTN_TOGGLE = 31   # Botón de 'toggle' (a GND, pull-up interno)

# === Config ===
CONFIG_DIR = Path("/home/pi/Desktop/config-local")
SERVER_TXT = CONFIG_DIR / "server.txt"      # p.ej. 'pinya.ws' o 'https://pinya.ws/'
STATE_LOCAL = Path("/home/pi/Desktop/remote-toggle-module/client/state_local.json")
BOOT_READY_FLAG = Path("/run/boot-ready")
POLL_OK = 0.5      # s entre lecturas si OK
POLL_KO = 2.0      # s entre reintentos si KO
TIMEOUT = 3.0

# === Utilidades HTTP ===
def load_target():
    txt = SERVER_TXT.read_text(encoding="utf-8").strip()
    if "://" not in txt:
        txt = "https://" + txt
    use_https = txt.startswith("https://")
    host_path = txt.split("://", 1)[1]
    if "/" in host_path:
        host, path = host_path.split("/", 1)
        path = "/" + path
    else:
        host, path = host_path, "/"
    return use_https, host, path

def http_get_json(host, use_https):
    conn = (http.client.HTTPSConnection(host, timeout=TIMEOUT, context=ssl.create_default_context())
            if use_https else http.client.HTTPConnection(host, timeout=TIMEOUT))
    try:
        conn.request("GET", "/api/state")
        resp = conn.getresponse()
        if 200 <= resp.status < 300:
            return json.loads(resp.read().decode("utf-8"))
        return None
    finally:
        try: conn.close()
        except: pass

def http_put_toggle(host, use_https, new_value, ts_ms):
    body = json.dumps({"value": bool(new_value), "ts": int(ts_ms)}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    conn = (http.client.HTTPSConnection(host, timeout=TIMEOUT, context=ssl.create_default_context())
            if use_https else http.client.HTTPConnection(host, timeout=TIMEOUT))
    try:
        conn.request("PUT", "/api/state/toggle", body=body, headers=headers)
        resp = conn.getresponse()
        return (200 <= resp.status < 300)
    finally:
        try: conn.close()
        except: pass

# === GPIO ===
def gpio_setup():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(LED_TOGGLE, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BTN_TOGGLE, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def led_set(on: bool):
    GPIO.output(LED_TOGGLE, GPIO.HIGH if on else GPIO.LOW)

# === Persistencia local (no imprescindible ahora) ===
def local_write(state):
    try:
        STATE_LOCAL.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def main():
    # Espera a boot listo
    for _ in range(200):
        if BOOT_READY_FLAG.exists():
            break
        time.sleep(0.1)

    use_https, host, _ = load_target()
    print(f"[CFG] server={'https' if use_https else 'http'}://{host}", flush=True)

    gpio_setup()

    # Estado cacheado para LED
    last_toggle = None

    # --- Intento de interrupción + callback ---
    use_polling_button = False
    def on_button(_ch=None):
        try:
            current = (GPIO.input(LED_TOGGLE) == GPIO.HIGH)
            new_val = not current
            ok = http_put_toggle(host, use_https, new_val, time.time()*1000)
            if ok:
                led_set(new_val)
                print(f"[BTN] toggle -> {new_val}", flush=True)
            else:
                print("[BTN] PUT failed", flush=True)
        except Exception as e:
            print(f"[BTN] error: {e}", flush=True)

    try:
        GPIO.add_event_detect(BTN_TOGGLE, GPIO.FALLING, callback=on_button, bouncetime=200)
        print("[GPIO] edge-detect ENABLED", flush=True)
    except RuntimeError:
        use_polling_button = True
        print("[GPIO] edge-detect FAILED, falling back to POLLING", flush=True)

    # Variables para polling del botón (si hiciera falta)
    last_btn = GPIO.input(BTN_TOGGLE)  # 1=libre, 0=presionado
    last_change_t = time.time()

    try:
        while True:
            # 1) Sincroniza LED con el servidor
            try:
                data = http_get_json(host, use_https)
                if data is not None and "toggle" in data:
                    if data["toggle"] != last_toggle:
                        led_set(bool(data["toggle"]))
                        last_toggle = bool(data["toggle"])
                interval = POLL_OK if data is not None else POLL_KO
            except (socket.timeout, ssl.SSLError, OSError, ConnectionError, json.JSONDecodeError):
                interval = POLL_KO

            # 2) Si no hay interrupción, sondea el botón con debounce simple
            if use_polling_button:
                now = time.time()
                btn = GPIO.input(BTN_TOGGLE)
                if btn != last_btn:
                    last_btn = btn
                    last_change_t = now
                # estable durante 40 ms y flanco de bajada => “pulsado”
                if (now - last_change_t) >= 0.04 and btn == 0:
                    on_button()                 # ejecuta acción
                    # espera a que se suelte para evitar repeticiones
                    while GPIO.input(BTN_TOGGLE) == 0:
                        time.sleep(0.02)
                    last_btn = 1
                    last_change_t = time.time()

            time.sleep(interval)

    except KeyboardInterrupt:
        pass
    finally:
        try: GPIO.cleanup()
        except: pass

if __name__ == "__main__":
    main()
