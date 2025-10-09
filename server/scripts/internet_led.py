#!/usr/bin/env python3
import RPi.GPIO as GPIO
import socket
import time
import signal
import sys

# --- Configuración ---
LED_PIN = 16             # Modo BOARD: pin físico 16
CHECK_INTERVAL = 3.0     # segundos entre comprobaciones
TIMEOUT = 1.5            # timeout de conexión, en segundos
TARGETS = [              # destinos para probar conectividad (TCP)
    ("1.1.1.1", 53),     # Cloudflare DNS
    ("8.8.8.8", 53),     # Google DNS
    ("9.9.9.9", 53),     # Quad9
    ("208.67.222.222", 53),  # OpenDNS
]

def check_internet() -> bool:
    """Devuelve True si se puede abrir TCP a alguno de los objetivos."""
    for host, port in TARGETS:
        try:
            with socket.create_connection((host, port), TIMEOUT):
                return True
        except OSError:
            continue
    return False

def cleanup(*_):
    try:
        GPIO.output(LED_PIN, GPIO.LOW)
        GPIO.cleanup()
    finally:
        sys.exit(0)

def main():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)  # usamos numeración física
    GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)

    # Salida limpia con Ctrl+C o `systemctl stop` (SIGTERM)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    last_state = None
    while True:
        online = check_internet()
        if online != last_state:
            GPIO.output(LED_PIN, GPIO.HIGH if online else GPIO.LOW)
            print(f"[{time.strftime('%H:%M:%S')}] Internet {'ONLINE' if online else 'OFFLINE'}; LED {'ON' if online else 'OFF'}")
            last_state = online
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cleanup()
