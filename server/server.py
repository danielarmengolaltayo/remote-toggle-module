# server/scripts/server.py
#!/usr/bin/env python3
from flask import Flask, jsonify, request, render_template
from pathlib import Path
import json, time, threading

# === RUTAS BASE ===
APP_ROOT = Path(__file__).resolve().parent          # .../server
STATE_FILE = APP_ROOT / "state.json"                # .../server/state.json

# --- Estado in-memory ---
# Estructura canónica
DEFAULT_STATE = {
    "toggle": False,
    "client1": False,
    "client2": False,
    "ts": {
        "toggle": 0,
        "client1": 0,
        "client2": 0
    }
}
_state_lock = threading.Lock()
_state = None  # se carga desde disco o DEFAULT_STATE

def _now_ts() -> int:
    return int(time.time() * 1000)

def load_state():
    global _state
    if STATE_FILE.exists():
        try:
            with STATE_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = DEFAULT_STATE.copy()
    else:
        data = DEFAULT_STATE.copy()

    # normaliza claves obligatorias
    for k in ("toggle","client1","client2"):
        if k not in data: data[k] = False
    if "ts" not in data or not isinstance(data["ts"], dict):
        data["ts"] = {}
    for k in ("toggle","client1","client2"):
        if k not in data["ts"]: data["ts"][k] = 0
    _state = data

def save_state():
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)

app = Flask(
    __name__,
    template_folder=str(APP_ROOT / "templates"),    # .../server/templates/index.html
    static_folder=None
)

@app.before_first_request
def _init():
    load_state()

# --- Helpers de autorización mínima (placeholder) ---
def get_client_id():
    # Para más adelante: cabeceras X-Client / X-Token.
    # De momento solo retornamos None y no restringimos nada.
    return request.headers.get("X-Client")

# --- Rutas HTML ---
@app.get("/")
def page_index():
    # Render de página de pruebas con 3 toggles
    return render_template("index.html")

# --- API REST ---
@app.get("/api/state")
def api_get_state():
    with _state_lock:
        return jsonify(_state)

@app.put("/api/state/<key>")
def api_put_key(key):
    key = key.strip().lower()
    if key not in ("toggle","client1","client2"):
        return jsonify({"error":"unknown key"}), 400

    body = request.get_json(silent=True) or {}
    if "value" not in body:
        return jsonify({"error":"missing 'value'"}), 400

    # Reglas de autorización (placeholder, sin aplicar aún):
    # - toggle: cualquier cliente
    # - client1: solo c1
    # - client2: solo c2
    # Aquí de momento no bloqueamos nada (lo haremos en un paso posterior).
    # client_id = get_client_id()

    val = bool(body["value"])
    ts  = int(body.get("ts", _now_ts()))

    with _state_lock:
        # Actualiza valor y timestamp por clave
        _state[key] = val
        _state["ts"][key] = ts
        save_state()

        # Para compatibilidad, retornamos el estado completo
        return jsonify(_state), 200

if __name__ == "__main__":
    # Solo para desarrollo local manual
    app.run(host="0.0.0.0", port=5000, debug=False)
