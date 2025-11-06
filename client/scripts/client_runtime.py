#!/usr/bin/env python3
import time, threading, json, signal, sys
from pathlib import Path
from urllib.parse import urlparse

import RPi.GPIO as GPIO
import requests

# ------------ Config (BOARD numbering) ------------
BOARD_LED   = 33      # LED variable (toggle)
BOARD_BTN   = 31      # Botón (a GND, pull-up interno)

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

# Estado local (mantiene espejo y timestamps)
state = {
    "toggle": False,
    "client1": False,
    "client2": False,
    "ts": {"toggle": 0, "client1": 0, "client2": 0}
}
lock = threading.Lock()

# ---- Utilidades GPIO ----
def gpio_setup():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BOARD_LED, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def led_set(on: bool):
    GPIO.output(BOARD_LED, GPIO.HIGH if on else GPIO.LOW)

# ---- Persistencia local opcional ----
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
    led_set(state["toggle"])

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

def put_toggle(value: bool, ts_ms: int):
    """Empuja toggle (no requiere X-Client según la auth mínima actual)."""
    base = read_server_base()
    if not base: return False
    try:
        r = requests.put(
            f"{base}/api/state/toggle",
            json={"value": bool(value), "ts": int(ts_ms)},
            timeout=HTTP_TIMEOUT
        )
        return r.ok
    except Exception:
        return False

# ---- Hilos ----
class ButtonWatcher(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._last_change_ms = self._now_ms()
        self._last_stable = GPIO.input(BOARD_BTN)  # 1=libre, 0=pulsado

    def _now_ms(self):
        return int(time.time() * 1000)

    def run(self):
        while True:
            level = GPIO.input(BOARD_BTN)
            now_ms = self._now_ms()

            if level != self._last_stable:
                if (now_ms - self._last_change_ms) >= DEBOUNCE_MS:
                    self._last_stable = level
                    self._last_change_ms = now_ms
                    if level == GPIO.LOW:  # pulsado
                        with lock:
                            state["toggle"] = not state["toggle"]
                            state["ts"]["toggle"] = now_ms
                            led_set(state["toggle"])
                            state_save()
                        # Empuje best-effort (no bloqueante)
                        threading.Thread(
                            target=put_toggle,
                            args=(state["toggle"], now_ms),
                            daemon=True
                        ).start()
            time.sleep(POLL_BTN_MS / 1000.0)

class SyncLoop(threading.Thread):
    def run(self):
        # Espera opcional: coherente con otros servicios
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
                    led_set(state["toggle"])
                    state_save()
            time.sleep(PULL_INTERVAL)

# ---- Main / señales ----
def main():
    gpio_setup()
    state_dir_prepare()
    state_load()
    try:
        ButtonWatcher().start()
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
