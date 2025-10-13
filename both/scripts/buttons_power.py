#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import subprocess
import signal
import sys

# ---------------- Configuración ----------------
GPIO.setmode(GPIO.BOARD)

BTN_REBOOT = 11      # pin físico 11 (BCM 17)
BTN_SHUTDN = 12      # pin físico 12 (BCM 18)

PULL_MODE = GPIO.PUD_UP     # botón a GND -> pull-up interno
ACTIVE_LEVEL = GPIO.LOW     # con pull-up, pulsado = LOW

HOLD_SECONDS = 1.0          # tiempo mínimo de pulsación para actuar
STABLE_MS = 30              # ms de estabilidad para validar cambio (debounce)
POLL_SEC = 0.005            # 5 ms entre lecturas

DRY_RUN = False             # pon a False cuando quieras que ejecute de verdad
# ------------------------------------------------

def is_active(pin: int) -> bool:
    return GPIO.input(pin) == ACTIVE_LEVEL

def wait_for_level(pin: int, level: int):
    """Espera hasta que el pin se mantenga 'level' estable al menos STABLE_MS."""
    while True:
        if GPIO.input(pin) == level:
            t0 = time.monotonic()
            # comprobar estabilidad
            while (time.monotonic() - t0) < (STABLE_MS / 1000.0):
                if GPIO.input(pin) != level:
                    break
                time.sleep(POLL_SEC)
            else:
                # estable todo el intervalo
                return
        time.sleep(POLL_SEC)

def measure_press_duration(pin: int) -> float:
    """Espera una pulsación estable y devuelve su duración (hasta soltar)."""
    # Esperar a pulsación (nivel activo estable)
    wait_for_level(pin, ACTIVE_LEVEL)
    t0 = time.monotonic()

    # Esperar a suelta (nivel inactivo estable)
    inactive_level = GPIO.HIGH if ACTIVE_LEVEL == GPIO.LOW else GPIO.LOW
    wait_for_level(pin, inactive_level)
    t1 = time.monotonic()
    return t1 - t0

def action_reboot():
    print("[ACTION] REBOOT requested")
    if not DRY_RUN:
        subprocess.run(["/usr/bin/systemctl", "reboot"], check=False)

def action_shutdown():
    print("[ACTION] SHUTDOWN requested")
    if not DRY_RUN:
        subprocess.run(["/usr/bin/systemctl", "poweroff"], check=False)

def cleanup_and_exit(*_):
    try:
        GPIO.cleanup()
    finally:
        sys.exit(0)

def main():
    GPIO.setwarnings(False)
    GPIO.setup(BTN_REBOOT, GPIO.IN, pull_up_down=PULL_MODE)
    GPIO.setup(BTN_SHUTDN, GPIO.IN, pull_up_down=PULL_MODE)

    signal.signal(signal.SIGINT, cleanup_and_exit)
    signal.signal(signal.SIGTERM, cleanup_and_exit)

    print("[INFO] Buttons monitor running. Hold ~1s to trigger.")
    print(f"[INFO] Reboot on pin {BTN_REBOOT} | Shutdown on pin {BTN_SHUTDN}")
    print(f"[INFO] DRY_RUN = {DRY_RUN}")

    while True:
        # Sondeo simple: prioriza el que se pulse primero.
        if is_active(BTN_REBOOT):
            dur = measure_press_duration(BTN_REBOOT)
            print(f"[DEBUG] Reboot button held {dur:.2f}s")
            if dur >= HOLD_SECONDS:
                action_reboot()
                time.sleep(5)
        elif is_active(BTN_SHUTDN):
            dur = measure_press_duration(BTN_SHUTDN)
            print(f"[DEBUG] Shutdown button held {dur:.2f}s")
            if dur >= HOLD_SECONDS:
                action_shutdown()
                time.sleep(5)
        else:
            time.sleep(POLL_SEC)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup_and_exit()

