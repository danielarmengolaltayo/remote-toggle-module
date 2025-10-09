#!/usr/bin/env bash
set -euo pipefail

# Este script vive en server/scripts/ -> nos movemos al raíz de server/
cd "$(dirname "$0")/.."

# Crear venv si no existe (en server/.venv)
[[ -d ".venv" ]] || python3 -m venv .venv

# Activar venv
source .venv/bin/activate

# Ejecutar el servidor, está en server/server.py
exec python3 server.py