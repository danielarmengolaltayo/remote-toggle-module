#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import os
import subprocess
import signal
import sys
from pathlib import Path

# ---------- Config ----------
LED_PIN = 18                 # BOARD 18 (GPIO24)
STATE_FILE = Path("/home/danielarmengolaltayo/Desktop/remote-toggle-module/server/state.json")  # ajusta si tu ruta es otra
SERVICE_NAME = "toggle.service"

CHECK_SVC_EVERY = 1.0        # s: frecuencia de chequeo del servicio
CHECK_FILE_EVERY = 0.2       # s: frecuencia de chequeo de mtime del archivo
BLINK_OFF_MS = 150           # ms: tiempo que el LED se apaga para indicar cambio
# ----------------------------

def led_setup():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)

def led_on(on: bool):
    GPIO.output(LED_PIN, GPIO.HIGH if on else GPIO.LOW)

def service_is_active(name: str) -> bool:
    # systemctl is-active --quiet devuelve 0 si está "active"
    return subprocess.run(
        ["/bin/systemctl", "is-active", "--quiet", name],
        check=False
    ).returncode == 0

def cleanup(*_):
    try:
        led_on(False)
        GPIO.cleanup()
    finally:
        sys.exit(0)

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    led_setup()

    last_mtime = None
    last_svc_state = None
    last_blink = 0.0

    t_svc = 0.0
    t_file = 0.0

    while True:
        now = time.monotonic()

        # 1) Chequeo de servicio (cada CHECK_SVC_EVERY)
        if now - t_svc >= CHECK_SVC_EVERY:
            t_svc = now
            svc_on = service_is_active(SERVICE_NAME)
            if svc_on != last_svc_state:
                led_on(svc_on)   # estado base = ON si servicio activo
                last_svc_state = svc_on

        # 2) Chequeo de cambios en state.json (cada CHECK_FILE_EVERY)
        if now - t_file >= CHECK_FILE_EVERY:
            t_file = now
            try:
                mtime = STATE_FILE.stat().st_mtime_ns
            except FileNotFoundError:
                mtime = None

            if mtime is not None and last_mtime is not None and mtime != last_mtime:
                # Blink OFF breve para indicar escritura
                # (solo si el servicio está encendido, para que se note)
                if last_svc_state:
                    led_on(False)
                    time.sleep(BLINK_OFF_MS / 1000.0)
                    led_on(True)
                # si el servicio está apagado, no hacemos nada visual
            last_mtime = mtime

        time.sleep(0.02)  # pequeño respiro del bucle

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
