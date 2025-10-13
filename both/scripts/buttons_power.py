#!/usr/bin/env python3
import time, subprocess, sys
import RPi.GPIO as GPIO

# --- Configuración ---
# Pines (modo BOARD)
BTN_REBOOT   = 11  # a GND (pull-up interno)
BTN_SHUTDOWN = 15  # a GND (pull-up interno)

ACTIVE_LEVEL = GPIO.LOW   # pulsador a GND
DEBOUNCE_SEC = 0.05       # 50 ms
CHECK_INTERVAL = 0.01     # 10 ms
THRESHOLD_SEC = 1.00      # disparo a los 1.0 s sin esperar suelta

DRY_RUN = False  # pon True para pruebas sin ejecutar reboot/poweroff
# ---------------------

def do_reboot():
    print("[ACTION] Reboot NOW")
    if not DRY_RUN:
        subprocess.Popen(["/sbin/reboot"])

def do_shutdown():
    print("[ACTION] Shutdown NOW")
    if not DRY_RUN:
        subprocess.Popen(["/sbin/poweroff", "-h", "now"])

def read_pressed(pin: int) -> bool:
    return GPIO.input(pin) == ACTIVE_LEVEL

def main():
    print("[BOOT] buttons_power (hold-to-act) starting…")
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BTN_REBOOT,   GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BTN_SHUTDOWN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Estado por botón
    state = {
        BTN_REBOOT:   {"pressed": False, "t0": 0.0, "fired": False, "name": "REBOOT"},
        BTN_SHUTDOWN: {"pressed": False, "t0": 0.0, "fired": False, "name": "SHUTDOWN"},
    }

    try:
        while True:
            now = time.monotonic()

            for pin, st in state.items():
                pressed_now = read_pressed(pin)

                if not st["pressed"] and pressed_now:
                    # transición: suelto -> pulsado
                    st["pressed"] = True
                    st["t0"] = now
                    st["fired"] = False
                    # pequeña espera de debounce inicial
                    time.sleep(DEBOUNCE_SEC)
                    continue

                if st["pressed"] and not pressed_now:
                    # transición: pulsado -> suelto (reset)
                    st["pressed"] = False
                    st["fired"] = False
                    continue

                if st["pressed"] and not st["fired"]:
                    held = now - st["t0"]
                    if held >= THRESHOLD_SEC:
                        st["fired"] = True  # evita re-disparo continuo
                        if pin == BTN_REBOOT:
                            do_reboot()
                        else:
                            do_shutdown()
                        # No esperamos a soltar; acción inmediata.
                        # El proceso continuará hasta que systemd detenga el servicio por el reboot/apagado.
                        # Si DRY_RUN=True, seguirá el bucle hasta soltar.

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass
        print("[EXIT] buttons_power stopped")

if __name__ == "__main__":
    # Permite activar DRY_RUN por argumento: python buttons_power.py --dry-run
    if len(sys.argv) > 1 and sys.argv[1] in ("--dry-run", "--dry_run"):
        DRY_RUN = True
        print("[MODE] DRY_RUN = True")
    main()
