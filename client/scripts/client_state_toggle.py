#!/usr/bin/env python3
# Cliente: LED y botón para 'toggle' (REST)
import time, json, http.client, ssl, socket, sys
from pathlib import Path
import RPi.GPIO as GPIO

# === Pines (BOARD) ===
LED_TOGGLE = 33   # ya lo usas para el LED de 'toggle'
BTN_TOGGLE = 31   # ya lo usas para el botón de 'toggle'

# === Config ===
CONFIG_DIR = Path("/home/pi/Desktop/config-local")
SERVER_TXT = CONFIG_DIR / "server.txt"      # contiene host o URL (p.ej. pinya.ws o https://pinya.ws/)
STATE_LOCAL = Path("/home/pi/Desktop/remote-toggle-module/client/state_local.json")
BOOT_READY_FLAG = Path("/run/boot-ready")
POLL_OK = 0.5      # s entre lecturas si OK
POLL_KO = 2.0      # s entre reintentos si KO
TIMEOUT = 3.0

# === Utilidades HTTP (sin dependencias externas) ===
def load_target():
    txt = SERVER_TXT.read_text(encoding="utf-8").strip()
    if "://" not in txt:
        txt = "https://" + txt
    # parse manual mínimo
    use_https = txt.startswith("https://")
    host_path = txt.split("://", 1)[1]
    if "/" in host_path:
        host, path = host_path.split("/", 1)
        path = "/" + path
    else:
        host, path = host_path, "/"
    return use_https, host, path

def http_get_json(host, use_https):
    if use_https:
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, timeout=TIMEOUT, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, timeout=TIMEOUT)
    try:
        conn.request("GET", "/api/state")
        resp = conn.getresponse()
        if 200 <= resp.status < 300:
            data = resp.read()
            return json.loads(data.decode("utf-8"))
        return None
    finally:
        try: conn.close()
        except: pass

def http_put_toggle(host, use_https, new_value, ts_ms):
    body = json.dumps({"value": bool(new_value), "ts": int(ts_ms)}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if use_https:
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, timeout=TIMEOUT, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, timeout=TIMEOUT)
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

# === Persistencia local sencilla (opcional, para futuro) ===
def local_write(state):
    try:
        STATE_LOCAL.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def local_read():
    try:
        return json.loads(STATE_LOCAL.read_text(encoding="utf-8"))
    except:
        return {}

# === Main loop ===
def main():
    # Espera a boot listo para no encender LED antes de tiempo
    for _ in range(200):
        if BOOT_READY_FLAG.exists():
            break
        time.sleep(0.1)

    use_https, host, _ = load_target()
    print(f"[CFG] server={'https' if use_https else 'http'}://{host}", flush=True)

    gpio_setup()

    last_toggle = None

    def on_button(channel):
        # Pulsación activa a LOW (pull-up interno)
        try:
            # lee estado actual del LED para inferir el próximo
            current = GPIO.input(LED_TOGGLE) == GPIO.HIGH
            new_val = not current
            ok = http_put_toggle(host, use_https, new_val, time.time()*1000)
            if ok:
                # optimista: refleja ya en LED
                led_set(new_val)
                print(f"[BTN] toggle -> {new_val}", flush=True)
            else:
                print("[BTN] PUT failed", flush=True)
        except Exception as e:
            print(f"[BTN] error: {e}", flush=True)

    # Detecta flanco de bajada (pulsador a GND)
    GPIO.add_event_detect(BTN_TOGGLE, GPIO.FALLING, callback=on_button, bouncetime=200)

    try:
        while True:
            try:
                data = http_get_json(host, use_https)
                if data is not None and "toggle" in data:
                    if data["toggle"] != last_toggle:
                        led_set(bool(data["toggle"]))
                        last_toggle = bool(data["toggle"])
                time.sleep(POLL_OK if data is not None else POLL_KO)
            except (socket.timeout, ssl.SSLError, OSError, ConnectionError, json.JSONDecodeError):
                time.sleep(POLL_KO)
    except KeyboardInterrupt:
        pass
    finally:
        try: GPIO.cleanup()
        except: pass

if __name__ == "__main__":
    main()
