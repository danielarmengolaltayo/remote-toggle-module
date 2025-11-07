#!/usr/bin/env python3
import time, sys, signal
from pathlib import Path
import RPi.GPIO as GPIO

# --- Config ---
PIN_ACTIVITY = 38           # BOARD 38 (GPIO20)
ON_TIME_SEC  = 0.5          # encendido breve
# --------------

def cleanup(*_):
    try:
        GPIO.output(PIN_ACTIVITY, GPIO.LOW)
        GPIO.cleanup()
    finally:
        sys.exit(0)

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(PIN_ACTIVITY, GPIO.OUT, initial=GPIO.LOW)

    GPIO.output(PIN_ACTIVITY, GPIO.HIGH)
    time.sleep(ON_TIME_SEC)
    GPIO.output(PIN_ACTIVITY, GPIO.LOW)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
