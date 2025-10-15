# --- imports habituales ---
from flask import Flask, jsonify, request
import json, threading, time, os
from datetime import datetime, timezone
from flask import render_template

# === WS: Flask-Sock ===
from flask_sock import Sock

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(APP_DIR, "state.json")   # servidor guarda aquí {value, version}

app = Flask(__name__)
sock = Sock(app)   # <- WS

# Estado en memoria + lock
_state_lock = threading.Lock()
_state = {"value": False, "version": "1970-01-01T00:00:00Z"}

# Conexiones WS activas (objetos WebSocket)
_ws_peers = set()
_ws_peers_lock = threading.Lock()

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _load_state():
    global _state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "value" in data and "version" in data:
                    _state = data
        except Exception as e:
            print("[WARN] load_state:", e)

def _save_state():
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)

def _broadcast_update():
    """Difunde el estado actual a todos los WS conectados."""
    msg = json.dumps({"type": "update", "value": _state["value"], "version": _state["version"]})
    with _ws_peers_lock:
        dead = []
        for ws in list(_ws_peers):
            try:
                ws.send(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _ws_peers.discard(ws)

# Cargar estado al arrancar
_load_state()

# --- 

@app.get("/")
def index():
    # Puedes añadir headers para evitar cache agresivo detrás de CF si quieres
    resp = render_template("index.html")
    return resp

# --- API HTTP existente (ajusta nombres si difiere) ---

@app.get("/api/state")
def api_get_state():
    # Devuelve estado actual y ETag simple con version
    with _state_lock:
        data = dict(_state)
    resp = jsonify(data)
    resp.headers["ETag"] = data["version"]
    return resp, 200

@app.put("/api/state")
def api_put_state():
    """Actualiza el estado desde HTTP (p.ej., admin o cliente vía polling).
       También difunde por WS.
    """
    body = request.get_json(silent=True) or {}
    if "value" not in body:
        return jsonify({"error": "missing 'value'"}), 400
    val = bool(body["value"])
    with _state_lock:
        _state["value"] = val
        _state["version"] = _now_iso()
        _save_state()
        print(f"[STATE] HTTP PUT -> value={_state['value']} version={_state['version']}")
    _broadcast_update()
    return jsonify(_state), 200

# --- WS endpoint ---
@sock.route("/ws")
def ws_endpoint(ws):
    """Protocolo:
       <- {"type":"snapshot","value":bool,"version":"..."}
       <- {"type":"update","value":bool,"version":"..."} (cuando cambie)
       -> {"type":"set","value":bool} (de un cliente)
       (Opcional futuro: "ping"/"pong")
    """
    # Registrar peer
    with _ws_peers_lock:
        _ws_peers.add(ws)

    # Enviar snapshot inicial
    with _state_lock:
        snap = json.dumps({"type": "snapshot", "value": _state["value"], "version": _state["version"]})
    try:
        ws.send(snap)
    except Exception:
        with _ws_peers_lock:
            _ws_peers.discard(ws)
        return

    # Bucle de mensajes
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break  # conexión cerrada
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            # Mensaje del cliente para cambiar estado
            if msg.get("type") == "set" and "value" in msg:
                val = bool(msg["value"])
                with _state_lock:
                    _state["value"] = val
                    _state["version"] = _now_iso()
                    _save_state()
                    print(f"[STATE] WS SET -> value={_state['value']} version={_state['version']}")
                _broadcast_update()
            # (si quieres aceptar "pong", ignóralo o registra)
    except Exception as e:
        print("[WS] error:", e)
    finally:
        with _ws_peers_lock:
            _ws_peers.discard(ws)
