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
BOARD_LED_SERVERONLINE = 29
BOARD_LED_INTERNET = 16

# Botones (a GND, con pull-up interno)
BOARD_BTN_TOGGLE  = 37
BOARD_BTN_CLIENT1 = 22
BOARD_BTN_CLIENT2 = 36

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
lock = threading.RLock()

_server_online_lock = threading.Lock()
_last_server_ok_monotonic = 0.0  # instante (time.monotonic) del último GET exitoso

# ---- GPIO ----
def gpio_setup():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    # LEDs
    GPIO.setup(BOARD_LED_TOGGLE,  GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_LED_CLIENT1, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_LED_CLIENT2, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_LED_SERVERONLINE, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_LED_INTERNET, GPIO.OUT, initial=GPIO.LOW)
    # Botones (pull-up => reposo 1, pulsado 0)
    GPIO.setup(BOARD_BTN_TOGGLE,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BOARD_BTN_CLIENT1, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BOARD_BTN_CLIENT2, GPIO.IN, pull_up_down=GPIO.PUD_UP)

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

def put_key(key: str, value: bool, ts_ms: int):
    base = read_server_base()
    if not base:
        print(f"[HTTP] base URL vacía", flush=True)
        return False
    try:
        r = requests.put(
            f"{base}/api/state/{key}",
            json={"value": bool(value), "ts": int(ts_ms)},
            timeout=HTTP_TIMEOUT
        )
        print(f"[HTTP] PUT {key}={value} ts={ts_ms} -> {r.status_code} {r.text[:120]}", flush=True)
        return r.ok
    except Exception as e:
        print(f"[HTTP] EXC {key}: {e}", flush=True)
        return False

# --- Reconciliación local → servidor tras recuperar conexión ---
_last_pushed = {"toggle": 0, "client1": 0, "client2": 0}

def reconcile_with_server(snap: dict):
    """
    Si local.ts > server.ts empuja estado local (toggle, client1).
    Evita reintentos duplicados con _last_pushed.
    """
    if not snap: 
        return
    to_push = []
    with lock:
        for key in ("toggle", "client1", "client2"):
            s_ts = int(snap.get("ts", {}).get(key, 0))
            l_ts = int(state["ts"].get(key, 0))
            if l_ts > s_ts and l_ts != _last_pushed.get(key, 0):
                to_push.append((key, state[key], l_ts))

    for key, val, ts_ms in to_push:
        ok = put_key(key, val, ts_ms)
        if ok:
            _last_pushed[key] = ts_ms


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
            time.sleep(POLL_BTN_MS / 1000.0)

# callbacks de botones
def on_press_toggle(ts_ms: int):
    print(f"[CALL] toggle -> value will be {not state['toggle']} ts={ts_ms}", flush=True)
    with lock:
        state["toggle"] = not state["toggle"]
        state["ts"]["toggle"] = ts_ms
        state_save()
    leds_apply()
    # llamada directa (sin hilo) para ver el log [HTTP]
    put_key("toggle", state["toggle"], ts_ms)

def on_press_client1(ts_ms: int):
    print(f"[CALL] client1 -> value will be {not state['client1']} ts={ts_ms}", flush=True)
    with lock:
        state["client1"] = not state["client1"]
        state["ts"]["client1"] = ts_ms
        state_save()
    leds_apply()
    # llamada directa con cabecera
    put_key("client1", state["client1"], ts_ms)

def on_press_client2(ts_ms: int):
    print(f"[CALL] client2 -> value will be {not state['client2']} ts={ts_ms}", flush=True)
    with lock:
        state["client2"] = not state["client2"]
        state["ts"]["client2"] = ts_ms
        state_save()
    leds_apply()
    put_key("client2", state["client2"], ts_ms)

def merge_from_server_snapshot(snap: dict):
    if not snap: 
        return False
    changed = False
    with lock:
        for k in ("toggle","client1","client2"):
            s_ts = int(snap.get("ts", {}).get(k, 0))
            if s_ts >= state["ts"].get(k, 0):
                nv = bool(snap.get(k, False))
                if nv != state[k]:
                    changed = True
                state[k] = nv
                state["ts"][k] = s_ts
        state_save()
    leds_apply()
    return True

def initial_sync(timeout_sec=5.0):
    t0 = time.time()
    snap = None
    while time.time() - t0 < timeout_sec:
        snap = get_state()
        if snap and merge_from_server_snapshot(snap):
            print("[SYNC] initial server snapshot applied", flush=True)
            global _last_server_ok_monotonic
            with _server_online_lock:
                _last_server_ok_monotonic = time.monotonic()
            reconcile_with_server(snap)
            return True
        time.sleep(0.3)
    print("[SYNC] initial snapshot not available (will sync in background)", flush=True)
    return False


# ---- Hilo de sincronización ----
class SyncLoop(threading.Thread):
    def run(self):
        # Espera opcional al boot-ready
        for _ in range(200):
            if BOOT_READY_FLAG.exists():
                break
            time.sleep(0.1)

        global _last_server_ok_monotonic

        while True:
            snap = get_state()
            if snap:
                # 1) aplica servidor → local (LWW)
                merge_from_server_snapshot(snap)
                with _server_online_lock:
                    _last_server_ok_monotonic = time.monotonic()
                # 2) empuja local → servidor si local era más nuevo (offline edits)
                reconcile_with_server(snap)
            time.sleep(PULL_INTERVAL)

class ServerOnlineLedLoop(threading.Thread):
    def __init__(self, on_timeout_sec=5.0, period=0.5):
        super().__init__(daemon=True, name="LED_SERVER_ONLINE")
        self.on_timeout_sec = float(on_timeout_sec)  # cuánto dura “OK” tras el último GET exitoso
        self.period = float(period)

    def run(self):
        while True:
            now = time.monotonic()
            with _server_online_lock:
                last_ok = _last_server_ok_monotonic
            is_ok = (now - last_ok) <= self.on_timeout_sec
            GPIO.output(BOARD_LED_SERVERONLINE, GPIO.HIGH if is_ok else GPIO.LOW)
            time.sleep(self.period)

import socket

class InternetLedLoop(threading.Thread):
    """
    Enciende BOARD_LED_INTERNET si hay Internet. Estrategia ligera:
    - Cada 'period' intenta socket a 1.1.1.1:53 (DNS) con timeout corto.
    - Si tiene éxito, considera 'online' durante 'alive_window_sec' (histeresis).
    """
    def __init__(self, period=2.0, alive_window_sec=5.0, timeout=1.5):
        super().__init__(daemon=True, name="LED_INTERNET")
        self.period = float(period)
        self.alive_window_sec = float(alive_window_sec)
        self.timeout = float(timeout)
        self._last_ok_monotonic = 0.0

    def _probe(self) -> bool:
        try:
            with socket.create_connection(("1.1.1.1", 53), self.timeout):
                return True
        except Exception:
            return False

    def run(self):
        while True:
            # Probar conexión
            if self._probe():
                self._last_ok_monotonic = time.monotonic()

            # Decidir LED con ventana de vida para evitar parpadeos
            is_ok = (time.monotonic() - self._last_ok_monotonic) <= self.alive_window_sec
            GPIO.output(BOARD_LED_INTERNET, GPIO.HIGH if is_ok else GPIO.LOW)

            time.sleep(self.period)


# ---- Main / señales ----
def main():
    gpio_setup()
    state_dir_prepare()
    state_load()
    initial_sync(timeout_sec=5.0)
    try:
        _BtnWatcher(BOARD_BTN_TOGGLE,  on_press_toggle,  name="BTN_TOGGLE").start()
        _BtnWatcher(BOARD_BTN_CLIENT1, on_press_client1, name="BTN_CLIENT1").start()
        _BtnWatcher(BOARD_BTN_CLIENT2, on_press_client2, name="BTN_CLIENT2").start()
        ServerOnlineLedLoop(on_timeout_sec=5.0, period=0.5).start()
        InternetLedLoop(period=2.0, alive_window_sec=5.0, timeout=1.5).start()
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
