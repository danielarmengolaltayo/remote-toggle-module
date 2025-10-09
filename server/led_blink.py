import RPi.GPIO as GPIO
import time

ledPin = 7
GPIO.setmode(GPIO.BOARD)
GPIO.setup(ledPin, GPIO.OUT)

for i in range(5):
    GPIO.output(ledPin, GPIO.HIGH)
    time.sleep(0.5)
    GPIO.output(ledPin, GPIO.LOW)
    time.sleep(0.5)

GPIO.cleanup()
print("Done")
