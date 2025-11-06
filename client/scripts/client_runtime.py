#!/usr/bin/env python3
import time, threading, json, signal, sys
from pathlib import Path
from urllib.parse import urlparse

import RPi.GPIO as GPIO
import requests

# ------------ Config (BOARD numbering) ------------
# LEDs
BOARD_LED_TOGGLE  = 33
BOARD_LED_CLIENT1 = 31
BOARD_LED_CLIENT2 = 32

# Botones (a GND, con pull-up interno)
BOARD_BTN_TOGGLE  = 37   # ya instalado y comprobado
BOARD_BTN_CLIENT1 = 22   # NUEVO botón para modificar la clave 'client1'

STATE_FILE  = Path("/home/pi/Desktop/remote-toggle-module/client/state.json")
SERVER_TXT  = Path("/home/pi/Desktop/config-local/server.txt")
BOOT_READY_FLAG = Path("/run/boot-ready")

# Botón
DEBOUNCE_MS    = 50
POLL_BTN_MS    = 10

# Sync REST
PULL_INTERVAL  = 0.2   # segundos
HTTP_TIMEOUT   = 1.0   # segundos
# --------------------------------------------------

# Estado local (espejo con timestamps)
state = {
    "toggle": False,
    "client1": False,
    "client2": False,
    "ts": {"toggle": 0, "client1": 0, "client2": 0}
}
lock = threading.Lock()

# ---- GPIO ----
def gpio_setup():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    # LEDs
    GPIO.setup(BOARD_LED_TOGGLE,  GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_LED_CLIENT1, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_LED_CLIENT2, GPIO.OUT, initial=GPIO.LOW)
    # Botones (pull-up => reposo 1, pulsado 0)
    GPIO.setup(BOARD_BTN_TOGGLE,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BOARD_BTN_CLIENT1, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def leds_apply():
    with lock:
        GPIO.output(BOARD_LED_TOGGLE,  GPIO.HIGH if state["toggle"]  else GPIO.LOW)
        GPIO.output(BOARD_LED_CLIENT1, GPIO.HIGH if state["client1"] else GPIO.LOW)
        GPIO.output(BOARD_LED_CLIENT2, GPIO.HIGH if state["client2"] else GPIO.LOW)

# ---- Persistencia local (opcional) ----
def state_dir_prepare():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

def state_load():
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with lock:
                    for k in ("toggle", "client1", "client2"):
                        state[k] = bool(data.get(k, state[k]))
                    ts_in = data.get("ts", {})
                    for k in ("toggle", "client1", "client2"):
                        state["ts"][k] = int(ts_in.get(k, state["ts"][k]))
    except Exception as e:
        print("[WARN] state_load:", e, flush=True)
    leds_apply()

def state_save():
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except Exception as e:
        print("[WARN] state_save:", e, flush=True)

# ---- Server base URL ----
def read_server_base():
    if not SERVER_TXT.exists():
        return None
    raw = SERVER_TXT.read_text(encoding="utf-8").strip()
    if "://" not in raw:
        raw = "https://" + raw
    u = urlparse(raw)
    scheme = u.scheme.lower()
    if scheme not in ("http", "https"):
        scheme = "https"
    host = u.netloc or u.path
    return f"{scheme}://{host}"

# ---- REST helpers ----
def get_state():
    base = read_server_base()
    if not base: return None
    try:
        r = requests.get(f"{base}/api/state", timeout=HTTP_TIMEOUT)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return None

def put_key(key: str, value: bool, ts_ms: int, xclient=None):
    base = read_server_base()
    if not base:
        print(f"[HTTP] base URL vacía", flush=True)
        return False
    headers = {"Content-Type": "application/json"}
    if xclient:
        headers["X-Client"] = xclient
    try:
        r = requests.put(
            f"{base}/api/state/{key}",
            json={"value": bool(value), "ts": int(ts_ms)},
            headers=headers,
            timeout=HTTP_TIMEOUT
        )
        print(f"[HTTP] PUT {key}={value} ts={ts_ms} -> {r.status_code} {r.text[:120]}", flush=True)
        return r.ok
    except Exception as e:
        print(f"[HTTP] EXC {key}: {e}", flush=True)
        return False


# ---- Hilos de botones ----
class _BtnWatcher(threading.Thread):
    def __init__(self, pin, on_press_callback, name="BTN"):
        super().__init__(daemon=True, name=name)
        self.pin = pin
        self.on_press = on_press_callback
        self._last_change_ms = self._now_ms()
        self._last_stable = GPIO.input(self.pin)  # 1=libre, 0=pulsado

    def _now_ms(self): return int(time.time() * 1000)

    def run(self):
        while True:
            level = GPIO.input(self.pin)
            now_ms = self._now_ms()
            if level != self._last_stable:
                if (now_ms - self._last_change_ms) >= DEBOUNCE_MS:
                    self._last_stable = level
                    self._last_change_ms = now_ms
                    if level == GPIO.LOW:
                        print(f"[{self.name}] PRESS pin={self.pin}", flush=True)
                        try:
                            self.on_press(now_ms)
                        except Exception as e:
                            print(f"[{self.name}] error callback:", e, flush=True)
            # << añade esta línea para ver vida:
            if now_ms % 500 < 10:
                print(f"[{self.name}] pin={self.pin} level={level} stable={self._last_stable}", flush=True)
            time.sleep(POLL_BTN_MS / 1000.0)

# callbacks de botones
def on_press_toggle(ts_ms: int):
    with lock:
        state["toggle"] = not state["toggle"]
        state["ts"]["toggle"] = ts_ms
        leds_apply()
        state_save()
    # empuje best-effort (toggle es libre)
    threading.Thread(target=put_key, args=("toggle", state["toggle"], ts_ms, None), daemon=True).start()

def on_press_client1(ts_ms: int):
    with lock:
        state["client1"] = not state["client1"]
        state["ts"]["client1"] = ts_ms
        leds_apply()
        state_save()
    # empuje con auth mínima (X-Client: client1)
    threading.Thread(target=put_key, args=("client1", state["client1"], ts_ms, "client1"), daemon=True).start()

# ---- Hilo de sincronización ----
class SyncLoop(threading.Thread):
    def run(self):
        # Espera opcional a boot-ready para coherencia con otros servicios
        for _ in range(200):
            if BOOT_READY_FLAG.exists():
                break
            time.sleep(0.1)

        while True:
            s = get_state()
            if s:
                # Merge LWW por clave con timestamps
                with lock:
                    for k in ("toggle", "client1", "client2"):
                        s_ts = int(s.get("ts", {}).get(k, 0))
                        if s_ts >= state["ts"].get(k, 0):
                            state[k] = bool(s.get(k, False))
                            state["ts"][k] = s_ts
                    leds_apply()
                    state_save()
            time.sleep(PULL_INTERVAL)

# ---- Main / señales ----
def main():
    import __main__, os
    print(f"[BOOT] running={__main__.__file__} cwd={os.getcwd()}", flush=True)
    gpio_setup()
    state_dir_prepare()
    state_load()
    try:
        _BtnWatcher(BOARD_BTN_TOGGLE,  on_press_toggle,  name="BTN_TOGGLE").start()
        _BtnWatcher(BOARD_BTN_CLIENT1, on_press_client1, name="BTN_CLIENT1").start()
        SyncLoop().start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass

def shutdown(signum, frame):
    try:
        GPIO.cleanup()
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    main()
