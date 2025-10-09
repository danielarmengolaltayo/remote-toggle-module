#!/usr/bin/env python3
import time, sys, signal, subprocess, traceback
import RPi.GPIO as GPIO

# --- Configuración ---
PIN_SWITCH = 22            # BOARD 22
ACTIVE_LEVEL = GPIO.LOW    # interruptor a GND = ON
DEBOUNCE_SEC = 0.10        # 100 ms
SERVICE_NAME = "toggle.service"

# Polling fallback
POLL_INTERVAL = 0.02       # 20 ms
STABLE_SEC = 0.03          # 30 ms para estabilizar
# ----------------------

def svc(action: str):
    subprocess.run(["/bin/systemctl", action, SERVICE_NAME], check=False)

def desired_on() -> bool:
    return GPIO.input(PIN_SWITCH) == ACTIVE_LEVEL

def apply_state(on: bool, reason=""):
    print(f"[APPLY] {'START' if on else 'STOP'} {SERVICE_NAME} {reason}")
    svc("start" if on else "stop")

def on_edge(_channel):
    time.sleep(DEBOUNCE_SEC)  # debounce simple
    apply_state(desired_on(), reason="[edge]")

def setup_gpio():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(PIN_SWITCH, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def try_edge_detection() -> bool:
    # Limpia por si acaso (no falla si no había)
    try:
        GPIO.remove_event_detect(PIN_SWITCH)
    except Exception:
        pass
    try:
        GPIO.add_event_detect(PIN_SWITCH, GPIO.BOTH, callback=on_edge,
                              bouncetime=int(DEBOUNCE_SEC * 1000))
        print("[INFO] Edge detection ACTIVATED")
        return True
    except RuntimeError as e:
        print("[WARN] Failed to add edge detection:", e)
        return False

def loop_polling():
    print("[INFO] Falling back to POLLING")
    last_state = desired_on()
    while True:
        cur = desired_on()
        if cur != last_state:
            # Espera estabilidad breve
            t0 = time.monotonic()
            while time.monotonic() - t0 < STABLE_SEC:
                if desired_on() != cur:
                    break
                time.sleep(POLL_INTERVAL)
            else:
                last_state = cur
                apply_state(cur, reason="[poll]")
        time.sleep(POLL_INTERVAL)

def main():
    print("[BOOT] gpio-server-switch starting…")
    setup_gpio()
    initial = desired_on()
    print(f"[INIT] switch={'ON' if initial else 'OFF'} (pin BOARD {PIN_SWITCH})")
    apply_state(initial, reason="[init]")

    if try_edge_detection():
        signal.pause()   # duerme; on_edge hará el trabajo
    else:
        loop_polling()   # fallback si no se pudo activar edge

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass
