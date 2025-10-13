#!/usr/bin/env python3
import RPi.GPIO as GPIO

# mismos pines que arriba
SAFE_LOW_PINS = [13, 16, 18]  # BOARD

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)
for p in SAFE_LOW_PINS:
    try:
        GPIO.setup(p, GPIO.OUT, initial=GPIO.LOW)
        GPIO.output(p, GPIO.LOW)
        print(f"[gpio_all_low] pin {p} -> LOW")
    except Exception as e:
        print(f"[gpio_all_low] pin {p}: {e}")
GPIO.cleanup()
print("[gpio_all_low] done")
