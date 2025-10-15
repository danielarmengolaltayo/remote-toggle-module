#!/usr/bin/env bash
set -euo pipefail

# entra en server/scripts
cd "$(dirname "$0")"
# sube a server/
cd ..

# Crear venv si no existe (en server/.venv)
[[ -d ".venv" ]] || python3 -m venv .venv

# Activar venv
source .venv/bin/activate

# arrancar con gunicorn + gevent (1 worker es suficiente)
# app = objeto Flask en server/server.py
exec gunicorn -k gevent -w 1 -b 127.0.0.1:5000 server:app