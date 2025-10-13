#!/usr/bin/env bash
set -euo pipefail

# === Carga de configuración (.env local) ==========================
# Ruta por defecto del .env (puedes cambiarla si algún día mueves config-local)
ENV_FILE="${ENV_FILE:-/home/pi/Desktop/config-local/auto-update.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

# === Defaults sensatos (si faltan en el .env) =====================
REPO_DIR="${REPO_DIR:-/home/pi/Desktop/remote-toggle-module}"
BRANCH="${BRANCH:-main}"
ROLE="${ROLE:-client}"                       # 'server' o 'client'
RESET_HARD="${RESET_HARD:-true}"             # true/false

# Rutas opcionales para deps Python (solo si quieres gestionar venv/requirements)
VENV_DIR="${VENV_DIR:-}"                     # p.ej. "$REPO_DIR/server/.venv" o "$REPO_DIR/client/.venv"
REQ_FILE="${REQ_FILE:-}"                     # p.ej. "$REPO_DIR/server/requirements.txt"

# Hook opcional post-update (script ejecutable)
POST_HOOK="${POST_HOOK:-}"

# Servicios a reiniciar si hay cambios (solo server normalmente)
# Ejemplo: SERVICES="toggle.service server-led.service gpio-server-switch.service buttons-power.service internet-led.service"
SERVICES="${SERVICES:-}"

log(){ echo "[$(date '+%F %T')] $*"; }

wait_for_network() {
  log "Esperando red…"
  for _ in {1..30}; do
    getent hosts github.com >/dev/null 2>&1 && { log "Red OK"; return 0; }
    sleep 1
  done
  log "Sin red. Salgo sin error."
  exit 0
}

git_update() {
  cd "$REPO_DIR"
  log "Actualizando repo en $REPO_DIR (branch $BRANCH)…"
  git fetch origin "$BRANCH"
  local before after
  before="$(git rev-parse HEAD || echo none)"
  if [[ "$RESET_HARD" == "true" ]]; then
    git reset --hard "origin/$BRANCH"
  else
    git pull --ff-only origin "$BRANCH"
  fi
  after="$(git rev-parse HEAD || echo none)"
  echo "$before $after"
}

maybe_python_deps() {
  # Instala deps si tienes VENV_DIR y REQ_FILE definidos
  if [[ -n "$VENV_DIR" && -n "$REQ_FILE" && -f "$REQ_FILE" ]]; then
    log "Instalando dependencias Python (venv: $VENV_DIR)…"
    [[ -d "$VENV_DIR" ]] || python3 -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install -r "$REQ_FILE"
  fi
}

restart_services() {
  if [[ -n "$SERVICES" ]]; then
    for s in $SERVICES; do
      log "Reiniciando $s (try-restart)…"
      sudo /bin/systemctl try-restart "$s" || true
    done
  else
    log "No hay servicios definidos en SERVICES. Nada que reiniciar."
  fi
}

main() {
  wait_for_network
  # Asegura que el repo existe (por si esta máquina está “virgen”)
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "Repo no encontrado en $REPO_DIR; intentando clonar…"
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone "https://github.com/danielarmengolaltayo/remote-toggle-module.git" "$REPO_DIR"
    cd "$REPO_DIR" && git checkout "$BRANCH" || true
  fi
  read -r before after < <(git_update)
  if [[ "$before" != "$after" ]]; then
    log "Cambios detectados: $before -> $after"
    maybe_python_deps
    restart_services
  else
    log "Sin cambios."
    # Opcional: instalar deps aunque no haya commits nuevos
    # maybe_python_deps
  fi

  if [[ -n "$POST_HOOK" && -x "$POST_HOOK" ]]; then
    log "Ejecutando POST_HOOK: $POST_HOOK"
    "$POST_HOOK" || true
  fi
  log "Auto-update finalizado (ROLE=$ROLE)."
}

main "$@"
