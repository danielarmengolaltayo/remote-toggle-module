#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import subprocess
import signal
import sys

# ---------- Config ----------
LED_PIN = 18                 # BOARD 18 (GPIO24) -> LED "server" (estado UP/DOWN)
SERVICE_NAME = "toggle.service"
CHECK_SVC_EVERY = 1.0        # s: frecuencia de chequeo del servicio
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

    last_svc_state = None
    next_check = 0.0

    while True:
        now = time.monotonic()

        # Chequeo periódico del estado del servicio
        if now >= next_check:
            next_check = now + CHECK_SVC_EVERY
            svc_on = service_is_active(SERVICE_NAME)
            if svc_on != last_svc_state:
                led_on(svc_on)   # ON si servicio activo, OFF si no
                last_svc_state = svc_on

        time.sleep(0.05)  # pequeño respiro del bucle

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
