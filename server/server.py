#!/usr/bin/env python3
from flask import Flask, jsonify, request, render_template
from pathlib import Path
import json, time, threading

# === RUTAS BASE ===
APP_ROOT = Path(__file__).resolve().parent          # .../server
STATE_FILE = APP_ROOT / "state.json"                # .../server/state.json

# --- Estado in-memory ---
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


def _safe_merge_defaults(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}
    # valores por defecto
    for k in ("toggle", "client1", "client2"):
        data.setdefault(k, False)
    ts = data.get("ts")
    if not isinstance(ts, dict):
        ts = {}
    for k in ("toggle", "client1", "client2"):
        ts.setdefault(k, 0)
    data["ts"] = ts
    return data


def _now_ts() -> int:
    return int(time.time() * 1000)


def load_state():
    """Carga estado desde disco; si está corrupto, hace backup y usa defaults."""
    global _state
    with _state_lock:
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            else:
                data = DEFAULT_STATE.copy()
        except Exception:
            # backup con timestamp para no pisar backups previos
            try:
                backup = STATE_FILE.with_suffix(f".bad.{int(time.time())}")
                STATE_FILE.rename(backup)
            except Exception:
                pass
            data = DEFAULT_STATE.copy()
        _state = _safe_merge_defaults(data)


def save_state():
    """Escritura atómica: primero .tmp y luego replace."""
    with _state_lock:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)


app = Flask(
    __name__,
    template_folder=str(APP_ROOT / "templates"),  # .../server/templates/index.html
    static_folder=None
)

# Carga estado al arrancar módulo (Flask 3 ya no tiene before_first_request)
load_state()


# --- Rutas HTML ---
@app.get("/")
def page_index():
    return render_template("index.html")


# --- API REST ---
@app.get("/api/state")
def api_get_state():
    with _state_lock:
        return jsonify(_state)


@app.put("/api/state/<key>")
def api_put_key(key):
    key = key.strip().lower()
    if key not in ("toggle", "client1", "client2"):
        return jsonify({"error": "unknown key"}), 400

    body = request.get_json(silent=True) or {}
    if "value" not in body:
        return jsonify({"error": "missing 'value'"}), 400

    val = bool(body["value"])
    try:
        ts = int(body.get("ts", _now_ts()))
    except Exception:
        ts = _now_ts()

    with _state_lock:
        _state[key] = val
        _state["ts"][key] = ts
        # guardado atómico
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
        return jsonify(_state), 200


if __name__ == "__main__":
    # Solo para desarrollo local manual (en producción lo lanzas con systemd/gunicorn)
    app.run(host="0.0.0.0", port=5000, debug=False)

