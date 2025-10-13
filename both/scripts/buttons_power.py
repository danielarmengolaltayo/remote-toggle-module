#!/usr/bin/env python3
import time, subprocess, sys
import RPi.GPIO as GPIO

# --- Config ---
BTN_REBOOT   = 11  # BOARD 11 (BCM17)
BTN_SHUTDOWN = 15  # BOARD 15 (BCM22)
ACTIVE_LEVEL = GPIO.LOW
DEBOUNCE_SEC = 0.05
CHECK_INTERVAL = 0.01
THRESHOLD_SEC = 1.00
DRY_RUN = False
# --------------

def do_reboot():
    print("[ACTION] REBOOT NOW")
    if not DRY_RUN:
        # ignora inhibidores, más fiable en algunos entornos
        subprocess.Popen(["/bin/systemctl", "reboot", "-i"])

def do_shutdown():
    print("[ACTION] SHUTDOWN NOW")
    if not DRY_RUN:
        subprocess.Popen(["/bin/systemctl", "poweroff", "-i"])

def pressed(pin): return GPIO.input(pin) == ACTIVE_LEVEL

def main():
    print("[BOOT] buttons_power hold-to-act starting…")
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BTN_REBOOT,   GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BTN_SHUTDOWN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    state = {
        BTN_REBOOT:   {"pressed": False, "t0": 0.0, "fired": False, "name": "REBOOT"},
        BTN_SHUTDOWN: {"pressed": False, "t0": 0.0, "fired": False, "name": "SHUTDOWN"},
    }

    try:
        while True:
            now = time.monotonic()
            for pin, st in state.items():
                pnow = pressed(pin)

                if not st["pressed"] and pnow:
                    st["pressed"] = True
                    st["t0"] = now
                    st["fired"] = False
                    print(f"[{st['name']}] pressed")
                    time.sleep(DEBOUNCE_SEC)
                    continue

                if st["pressed"] and not pnow:
                    if not st["fired"]:
                        held = now - st["t0"]
                        print(f"[{st['name']}] released at {held:.2f}s (no fire)")
                    st["pressed"] = False
                    st["fired"] = False
                    continue

                if st["pressed"] and not st["fired"]:
                    held = now - st["t0"]
                    if held >= THRESHOLD_SEC:
                        st["fired"] = True
                        print(f"[{st['name']}] threshold reached {held:.2f}s → FIRE")
                        if pin == BTN_REBOOT:
                            do_reboot()
                        else:
                            do_shutdown()

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        try: GPIO.cleanup()
        except Exception: pass
        print("[EXIT] buttons_power stopped")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--dry-run","--dry_run"):
        DRY_RUN = True
        print("[MODE] DRY_RUN = True")
    main()
