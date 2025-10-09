#!/usr/bin/env bash
set -euo pipefail

# === Config ===
REPO_DIR="/home/pi/Desktop/remote-toggle-module"
CLIENT_DIR="$REPO_DIR/client"
REMOTE_URL="https://github.com/danielarmengolaltayo/remote-toggle-module.git"
BRANCH="main"

VENV_DIR="$CLIENT_DIR/.venv"
REQ_FILE="$CLIENT_DIR/requirements.txt"
POST_HOOK="$CLIENT_DIR/scripts/post_update.sh"
# ==============

log(){ echo "[$(date '+%F %T')] $*"; }

wait_for_network() {
  log "Esperando red (github.com resoluble)…"
  for _ in {1..30}; do
    if getent hosts github.com >/dev/null 2>&1; then
      log "Red OK"
      return 0
    fi
    sleep 1
  done
  log "No hay red. Salgo sin error."
  exit 0
}

ensure_repo_exists() {
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "Repo no encontrado. Clonando…"
    git clone "$REMOTE_URL" "$REPO_DIR"
    cd "$REPO_DIR"
    git checkout "$BRANCH" || true
  fi
}

fetch_and_reset_hard() {
  cd "$REPO_DIR"
  git fetch origin "$BRANCH"
  local before after
  before="$(git rev-parse HEAD || echo none)"
  git reset --hard "origin/$BRANCH"
  after="$(git rev-parse HEAD)"
  echo "$before $after"
}

maybe_install_requirements() {
  if [[ -f "$REQ_FILE" ]]; then
    log "Instalando requirements (si procede)…"
    if [[ ! -d "$VENV_DIR" ]]; then
      python3 -m venv "$VENV_DIR"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install -r "$REQ_FILE"
  fi
}

main() {
  wait_for_network
  ensure_repo_exists
  read -r before after < <(fetch_and_reset_hard)

  if [[ "$before" != "$after" ]]; then
    log "Cambios detectados: $before -> $after"
    maybe_install_requirements
  else
    log "Sin cambios."
    # Si quieres forzar reinstall de deps aunque no haya commit nuevo:
    # maybe_install_requirements
  fi

  if [[ -x "$POST_HOOK" ]]; then
    log "Ejecutando post_update.sh…"
    "$POST_HOOK" || true
  fi
  log "Auto-update cliente finalizado."
}

main "$@"