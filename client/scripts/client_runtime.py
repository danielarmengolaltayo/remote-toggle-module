#!/usr/bin/env python3
import asyncio, json, os, signal, sys, time, random
from pathlib import Path
from urllib.parse import urlparse

import RPi.GPIO as GPIO
import websockets  # pip install websockets

# ------------ Config ------------
BOARD_LED   = 33      # LED variable (BOARD numbering)
BOARD_BTN   = 31      # Botón toggle (a GND, pull-up interno)

STATE_FILE  = Path("/home/pi/Desktop/remote-toggle-module/client/state.json")
SERVER_TXT  = Path("/home/pi/Desktop/config-local/server.txt")
BOOT_READY_FLAG = Path("/run/boot-ready")

# Botón
DEBOUNCE_SEC    = 0.05
POLL_INTERVAL   = 0.01
HOLD_MIN_SEC    = 0.02   # basta un “tap” breve

# WS
PING_INTERVAL   = 20
RECONNECT_BASE  = 1.0     # backoff inicial
RECONNECT_MAX   = 30.0    # backoff máximo
# --------------------------------

# Estado local (persistido)
_local_value   = False
_local_version = "local-0"   # versión local “no authed”; en WS adoptaremos la del servidor
_last_btn_state = 1          # pull-up → 1=libre, 0=pulsado
_btn_pressed_t0 = None

def gpio_setup():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BOARD_LED, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(BOARD_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def led_set(on: bool):
    GPIO.output(BOARD_LED, GPIO.HIGH if on else GPIO.LOW)

def state_dir_prepare():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

def state_load():
    global _local_value, _local_version
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "value" in data:
                _local_value = bool(data["value"])
                _local_version = data.get("version", _local_version)
        except Exception as e:
            print("[WARN] state_load:", e)
    led_set(_local_value)

def state_save():
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"value": _local_value, "version": _local_version}), encoding="utf-8")
    tmp.replace(STATE_FILE)

def read_server_url():
    raw = SERVER_TXT.read_text(encoding="utf-8").strip()
    if "://" not in raw:
        raw = "https://" + raw
    u = urlparse(raw)
    scheme = "wss" if u.scheme.lower().startswith("https") else "ws"
    host = u.netloc or u.path
    return f"{scheme}://{host}/ws"

async def ws_client_loop():
    """Mantiene WS con reconexión; sincroniza estado en tiempo real."""
    global _local_value, _local_version

    # Espera opcional al boot-ready (coherencia con tus otros servicios)
    for _ in range(200):
        if BOOT_READY_FLAG.exists():
            break
        await asyncio.sleep(0.1)

    backoff = RECONNECT_BASE

    while True:
        url = read_server_url()
        try:
            print(f"[WS] connecting to {url}")
            async with websockets.connect(url, ping_interval=PING_INTERVAL, ping_timeout=10) as ws:
                print("[WS] connected")
                backoff = RECONNECT_BASE

                # Al conectar: recibimos un snapshot del servidor
                raw = await ws.recv()
                snap = json.loads(raw)
                if snap.get("type") == "snapshot":
                    srv_value   = bool(snap.get("value", False))
                    srv_version = snap.get("version", "srv-0")
                    # Política simple: al conectar, empujamos nuestro estado local al servidor
                    # (si no quieres sobreescribir siempre, aquí podrías comparar y decidir)
                    if _local_value != srv_value:
                        await ws.send(json.dumps({"type": "set", "value": _local_value}))
                        print(f"[WS] sent local set -> {_local_value}")
                    else:
                        # Alineamos versión local a la del servidor
                        _local_version = srv_version
                        state_save()
                        led_set(_local_value)

                # Bucle receptor
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    t = msg.get("type")
                    if t == "update":
                        srv_value   = bool(msg.get("value", False))
                        srv_version = msg.get("version", "srv-0")
                        # Adoptamos el estado del servidor como fuente de verdad
                        _local_value   = srv_value
                        _local_version = srv_version
                        state_save()
                        led_set(_local_value)
                        print(f"[WS] update -> value={_local_value} version={_local_version}")
                    elif t == "ping":
                        await ws.send(json.dumps({"type":"pong"}))
        except (OSError, websockets.exceptions.InvalidURI, websockets.exceptions.InvalidHandshake) as e:
            print("[WS] connect error:", e)
        except websockets.exceptions.ConnectionClosedError as e:
            print("[WS] closed:", e)
        except Exception as e:
            print("[WS] error:", e)

        # Reconexión con backoff + jitter
        jitter = random.uniform(0, 0.3 * backoff)
        wait = min(RECONNECT_MAX, backoff + jitter)
        print(f"[WS] reconnect in {wait:.1f}s")
        await asyncio.sleep(wait)
        backoff = min(RECONNECT_MAX, backoff * 2)

async def button_loop():
    """Lee el botón por polling con antirrebote; al pulsar, alterna valor local y lo envía por WS (vía archivo “mailbox”)."""
    global _last_btn_state, _btn_pressed_t0, _local_value, _local_version

    # “Mailbox” simple para que el loop WS lea el pedido? Aquí simplificamos:
    # enviamos directamente al servidor desde este loop usando una pequeña conexión efímera HTTP como fallback,
    # pero como queremos WS, mejor: dejamos al loop WS empujar en (re)conexión y aquí sólo cambiamos local.
    # Para respuesta inmediata sub-segundo, hacemos también un “try WS fire-and-forget” usando un archivo señal.
    # Para no complicar, aquí sólo cambiamos local + guardamos; el loop WS al estar conectado ya envió en snapshot,
    # y si ya estaba conectado, el servidor nos devolverá el "update". Para empuje inmediato, abrimos una conexión WS corta.

    # Mini truco: si quieres empujar inmediato, crea un archivo “wanted_state.json” y el loop WS podría leerlo en cada iter.
    # Por simplicidad mantenemos el modelo optimista: cambiamos local y ya.

    while True:
        v = GPIO.input(BOARD_BTN)  # 1 libre, 0 pulsado
        now = time.monotonic()

        # Flanco de bajada: empieza pulsación
        if _last_btn_state == 1 and v == 0:
            _btn_pressed_t0 = now

        # Manteniendo pulsado
        if _btn_pressed_t0 is not None and v == 0:
            held = now - _btn_pressed_t0
            if held >= HOLD_MIN_SEC:
                # Toggle inmediato (una sola vez por pulsación)
                _btn_pressed_t0 = None  # evita repetir
                new_val = not _local_value
                _local_value = new_val
                _local_version = f"local-{int(time.time())}"
                state_save()
                led_set(_local_value)
                print(f"[BTN] toggle -> {_local_value} (enviado al servidor al conectar/actualmente conectado por eco)")
                # Intento “best-effort” de empuje inmediato si hay conexión abierta:
                # Creamos un flag para que el loop WS (si conectado) lo envíe cuanto antes.
                Path("/run/client-ws-push").write_text(json.dumps({"value": _local_value}), encoding="utf-8")

        # Flanco de subida: fin de pulsación
        if _last_btn_state == 0 and v == 1:
            # pequeño debounce
            await asyncio.sleep(DEBOUNCE_SEC)

        _last_btn_state = v
        await asyncio.sleep(POLL_INTERVAL)

async def ws_push_helper():
    """Ayudante: si existe /run/client-ws-push, intenta enviar “set” sobre una conexión efímera.
       Esto nos da empuje inmediato incluso si el bucle principal está entre awaits.
    """
    flag = Path("/run/client-ws-push")
    while True:
        if flag.exists():
            try:
                data = json.loads(flag.read_text(encoding="utf-8"))
                flag.unlink(missing_ok=True)
            except Exception:
                await asyncio.sleep(0.2)
                continue
            # Enviar set en una conexión WS efímera (rápida). Si falla, no pasa nada; el bucle principal sincroniza luego.
            try:
                url = read_server_url()
                async with websockets.connect(url, ping_interval=None) as ws:
                    # consume snapshot
                    try:
                        await ws.recv()
                    except Exception:
                        pass
                    await ws.send(json.dumps({"type": "set", "value": bool(data.get("value", False))}))
                    # no es necesario esperar “update”
            except Exception as e:
                # ignoramos: el bucle principal sincronizará
                pass
        await asyncio.sleep(0.2)

async def main():
    gpio_setup()
    state_dir_prepare()
    state_load()

    # Limpia flag de push antiguo
    try:
        Path("/run/client-ws-push").unlink(missing_ok=True)
    except Exception:
        pass

    # Ejecuta bucles concurrentes
    await asyncio.gather(
        ws_client_loop(),
        button_loop(),
        ws_push_helper(),
    )

def shutdown(signum, frame):
    try:
        GPIO.cleanup()
    except Exception:
        pass
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        asyncio.run(main())
    finally:
        try:
            GPIO.cleanup()
        except Exception:
            pass
