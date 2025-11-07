#!/usr/bin/env python3
import time, socket, ssl, http.client
import RPi.GPIO as GPIO
import sys
from pathlib import Path
from urllib.parse import urlparse

# === Config ===
LED_PIN_BOARD = 29                      # BOARD 29 (BCM5)
CONFIG_FILE = Path("/home/pi/Desktop/config-local/server.txt")
TIMEOUT = 5.0                           # segundos para la petición (subido a 5s)
INTERVAL_OK = 5.0                       # reintento si está OK
INTERVAL_FAIL = 5.0                     # reintento si está KO
BOOT_READY_FLAG = Path("/run/boot-ready")  # arrancar tras boot (opcional)
API_PATH = "/api/state"                 # endpoint real para comprobar el server
# ==============

def load_target():
    """Lee host/URL del archivo de config y devuelve (host, path, use_https).
       Ignoramos cualquier path del archivo y forzamos API_PATH.
    """
    text = CONFIG_FILE.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{CONFIG_FILE} está vacío.")
    # Acepta 'pinya.ws' o URL completa
    if "://" not in text:
        text = "https://" + text
    u = urlparse(text)
    host = u.hostname
    use_https = (u.scheme.lower() == "https")
    if not host:
        raise ValueError(f"No se pudo parsear host en {text}")
    return host, API_PATH, use_https

def check_http_get(host: str, path: str, use_https: bool, timeout: float) -> bool:
    """True si el origen responde (no 5xx). Usamos GET a /api/state."""
    headers = {"Connection": "close", "Accept": "application/json"}
    if use_https:
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(host, timeout=timeout)
    try:
        conn.request("GET", path or "/", headers=headers)
        resp = conn.getresponse()
        # Consideramos "online" si no es 5xx (puedes endurecer a 200–399 si prefieres)
        return resp.status < 500
    except (ssl.SSLError, socket.timeout, socket.gaierror, ConnectionError, OSError):
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass

_prev_led = None
def set_led(on: bool):
    global _prev_led
    GPIO.output(LED_PIN_BOARD, GPIO.HIGH if on else GPIO.LOW)
    if _prev_led is None or _prev_led != on:
        print(f"[SERVER LED] -> {'ON' if on else 'OFF'}", flush=True)
        _prev_led = on

def main():
    # Espera opcional a que el sistema haya anunciado boot listo
    for _ in range(200):  # ~20s máx
        if BOOT_READY_FLAG.exists():
            break
        time.sleep(0.1)

    host, path, https = load_target()
    print(f"[CFG] target={('https' if https else 'http')}://{host}{path}", flush=True)

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(LED_PIN_BOARD, GPIO.OUT, initial=GPIO.LOW)

    try:
        while True:
            ok = check_http_get(host, path, https, TIMEOUT)
            set_led(ok)
            time.sleep(INTERVAL_OK if ok else INTERVAL_FAIL)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass

if __name__ == "__main__":
    main()
