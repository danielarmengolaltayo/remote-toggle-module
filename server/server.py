from flask import Flask, jsonify, request, render_template
from threading import Lock
import json
import os

app = Flask(__name__)

# Archivo de persistencia en la carpeta del proyecto
DATA_FILE = os.path.join(os.path.dirname(__file__), "state.json")
state_lock = Lock()
state = False  # valor por defecto

def load_state():
    global state
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                state = bool(data.get("state", False))
        except Exception:
            state = False

def save_state():
    tmp_file = DATA_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump({"state": state}, f)
    os.replace(tmp_file, DATA_FILE)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/state", methods=["GET"])
def get_state():
    return jsonify({"state": state})

@app.route("/toggle", methods=["POST"])
def toggle():
    global state
    with state_lock:
        state = not state
        save_state()
        return jsonify({"state": state})

if __name__ == "__main__":
    load_state()
    app.run(host="0.0.0.0", port=5000)

