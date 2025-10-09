#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/danielarmengolaltayo/Desktop/remote-toggle-module"
SERVER_DIR="$REPO_DIR/server"
BRANCH="main"

# Servicios a reiniciar si hay cambios (ajusta si añades/quitás)
SERVICES=("toggle.service" "server-led.service" "gpio-server-switch.service" "buttons-power.service" "internet-led.service")

log(){ echo "[$(date '+%F %T')] $*"; }

wait_for_network() {
  for _ in {1..30}; do getent hosts github.com >/dev/null && return 0; sleep 1; done
  log "Sin red. Salgo."
  exit 0
}

hard_reset() {
  cd "$REPO_DIR"
  git fetch origin "$BRANCH"
  before="$(git rev-parse HEAD || echo none)"
  git reset --hard "origin/$BRANCH"
  after="$(git rev-parse HEAD)"
  echo "$before $after"
}

maybe_setup_venv() {
  cd "$SERVER_DIR"
  [[ -d ".venv" ]] || python3 -m venv .venv
  # Si usas requirements.txt, puedes descomentar estas 2 líneas:
  # source .venv/bin/activate
  # pip install --upgrade pip && pip install -r requirements.txt
}

restart_services() {
  for s in "${SERVICES[@]}"; do
    sudo systemctl try-restart "$s" || true
  done
}

main() {
  wait_for_network
  read -r before after < <(hard_reset)
  maybe_setup_venv
  if [[ "$before" != "$after" ]]; then
    log "Cambios detectados: $before -> $after"
    restart_services
  else
    log "Sin cambios."
  fi
}
main "$@"
