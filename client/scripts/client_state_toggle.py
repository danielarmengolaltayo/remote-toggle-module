#!/usr/bin/env python3
# Cliente: LED y botón para 'toggle' (REST) con respuesta inmediata (threads)
import time, json, http.client, ssl, socket, threading
from pathlib import Path
import RPi.GPIO as GPIO

# === Pines (BOARD) ===
LED_TOGGLE = 33   # LED de 'toggle'
BTN_TOGGLE = 31   # Botón de 'toggle' (a GND, pull-up interno)

# === Config ===
CONFIG_DIR   = Path("/home/pi/Desktop/config-local")
SERVER_TXT   = CONFIG_DIR / "server.txt"   # p.ej. 'pinya.ws' o 'https://pinya.ws/'
BOOT_READY   = Path("/run/boot-ready")
POLL_OK      = 0.2     # s entre lecturas del servidor si OK
POLL_KO      = 1.0     # s si KO
TIMEOUT      = 3.0
DEBOUNCE_S   = 0.04    # 40 ms

# === HTTP helpers ===
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

# === Estado compartido ===
state_lock = threading.Lock()
cached_toggle = None
stop_flag = False

# === Hilo: botón inmediato ===
def button_thread(host, use_https):
    global cached_toggle
    # Intenta interrupción; si falla, usa sondeo rápido
    try:
        def on_edge(_ch):
            try:
                with state_lock:
                    current = (GPIO.input(LED_TOGGLE) == GPIO.HIGH)
                new_val = not current
                ok = http_put_toggle(host, use_https, new_val, time.time()*1000)
                if ok:
                    with state_lock:
                        cached_toggle = new_val
                    led_set(new_val)  # feedback instantáneo
                    print(f"[BTN] toggle -> {new_val}", flush=True)
                else:
                    print("[BTN] PUT failed", flush=True)
            except Exception as e:
                print(f"[BTN] error: {e}", flush=True)
        # limpia posible registro previo y registra
        try:
            GPIO.remove_event_detect(BTN_TOGGLE)
        except Exception:
            pass
        GPIO.add_event_detect(BTN_TOGGLE, GPIO.FALLING, callback=on_edge, bouncetime=200)
        print("[GPIO] edge-detect ENABLED", flush=True)
        # solo duerme; el callback hará el trabajo
        while not stop_flag:
            time.sleep(0.2)
        return
    except RuntimeError:
        print("[GPIO] edge-detect FAILED, falling back to POLLING", flush=True)

    # Polling rápido con debounce software
    last_btn = GPIO.input(BTN_TOGGLE)
    stable_since = time.time()
    pressed_handled = False
    while not stop_flag:
        now = time.time()
        val = GPIO.input(BTN_TOGGLE)  # 1=libre, 0=presionado
        if val != last_btn:
            last_btn = val
            stable_since = now
            pressed_handled = False
        if (now - stable_since) >= DEBOUNCE_S:
            if val == 0 and not pressed_handled:
                try:
                    with state_lock:
                        current = (GPIO.input(LED_TOGGLE) == GPIO.HIGH)
                    new_val = not current
                    ok = http_put_toggle(host, use_https, new_val, time.time()*1000)
                    if ok:
                        with state_lock:
                            cached_toggle = new_val
                        led_set(new_val)
                        print(f"[BTN] toggle -> {new_val}", flush=True)
                    else:
                        print("[BTN] PUT failed", flush=True)
                except Exception as e:
                    print(f"[BTN] error: {e}", flush=True)
                pressed_handled = True
        time.sleep(0.01)  # 10 ms

# === Hilo: poll del servidor ===
def server_poll_thread(host, use_https):
    global cached_toggle
    while not stop_flag:
        try:
            data = http_get_json(host, use_https)
            if data is not None and "toggle" in data:
                t = bool(data["toggle"])
                with state_lock:
                    if t != cached_toggle:
                        cached_toggle = t
                        led_set(t)
            time.sleep(POLL_OK if data is not None else POLL_KO)
        except (socket.timeout, ssl.SSLError, OSError, ConnectionError, json.JSONDecodeError):
            time.sleep(POLL_KO)

def main():
    # Espera a boot listo
    for _ in range(200):
        if BOOT_READY.exists(): break
        time.sleep(0.1)

    use_https, host, _ = load_target()
    print(f"[CFG] server={'https' if use_https else 'http'}://{host}", flush=True)

    gpio_setup()

    # Inicializa LED según estado del servidor (si responde)
    try:
        data = http_get_json(host, use_https)
        if data and "toggle" in data:
            t = bool(data["toggle"])
            with state_lock:
                global cached_toggle
                cached_toggle = t
            led_set(t)
    except Exception:
        pass

    # Lanza hilos
    tb = threading.Thread(target=button_thread, args=(host, use_https), daemon=True)
    ts = threading.Thread(target=server_poll_thread, args=(host, use_https), daemon=True)
    tb.start(); ts.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        global stop_flag
        stop_flag = True
        try: GPIO.cleanup()
        except: pass

if __name__ == "__main__":
    main()
