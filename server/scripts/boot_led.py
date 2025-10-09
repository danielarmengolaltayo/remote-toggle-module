#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import subprocess
import signal
import sys

# Configuración
LED_PIN = 13           # numeración física (BOARD): pin 13
BLINK_INTERVAL = 0.25  # segundos entre cambios durante el arranque

def system_is_ready() -> bool:
    """
    Devuelve True cuando systemd reporta que el sistema está 'running' (o 'degraded').
    Mientras arranca suele devolver 'initializing' o 'starting'.
    """
    try:
        out = subprocess.run(
            ["systemctl", "is-system-running"],
            capture_output=True, text=True, timeout=1
        )
        status = out.stdout.strip()
        return status in ("running", "degraded")
    except Exception:
        # Si falla la consulta (muy temprano), asumimos que aún no está listo
        return False

def sigterm_handler(signum, frame):
    # Si nos paran antes de terminar, apagamos y limpiamos
    try:
        GPIO.output(LED_PIN, GPIO.LOW)
        GPIO.cleanup()
    finally:
        sys.exit(0)

def main():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)

    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)

    led_on = False

    # Parpadea mientras el sistema no está listo
    while not system_is_ready():
        led_on = not led_on
        GPIO.output(LED_PIN, GPIO.HIGH if led_on else GPIO.LOW)
        time.sleep(BLINK_INTERVAL)

    # Sistema listo: LED fijo encendido 
    GPIO.output(LED_PIN, GPIO.HIGH)

    # Señal de "boot listo" para systemd.path
    try:
        with open("/run/boot-ready", "w", encoding="utf-8") as f:
            f.write(f"ready {int(time.time())}\n")
    except Exception:
        pass

    # No llamamos a  GPIO.cleanup() para mantener el LED encendido

if __name__ == "__main__":
    main()
