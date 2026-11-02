#!/usr/bin/env bash

### Deploy the latest main of both repos, restoring the previous images if the
### new ones fail their health checks. The restricted deploy key runs this.
###
### Usage: scripts/staging/deploy.sh [--rollback]
### Environment: FRONTEND_DIR (default: the sibling crm-easyoffice-frontend).

set -o errexit
set -o pipefail
set -o nounset

BACKEND_DIR="${DEPLOY_BACKEND_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
export FRONTEND_DIR="${FRONTEND_DIR:-$(dirname "${BACKEND_DIR}")/crm-easyoffice-frontend}"
ESTADO_ANTERIOR="$(dirname "${BACKEND_DIR}")/.deploy-anterior"
LOCK="$(dirname "${BACKEND_DIR}")/.deploy.lock"
IMAGENES=(django postgres traefik nginx frontend firma_sandbox)

compose() {
  docker compose -f "${BACKEND_DIR}/docker-compose.staging.yml" "$@"
}

registrar() {
  echo "==> $*"
}

actualizar_y_reejecutar() {
  # The two repos deploy from separate workflows, and GitHub's concurrency
  # groups do not cross repositories: this lock is what keeps them apart.
  exec 9>"${LOCK}"
  flock --wait 1800 9

  local anterior_backend anterior_frontend
  anterior_backend="$(git -C "${BACKEND_DIR}" rev-parse HEAD)"
  anterior_frontend="$(git -C "${FRONTEND_DIR}" rev-parse HEAD)"
  git -C "${BACKEND_DIR}" fetch --quiet origin main
  git -C "${FRONTEND_DIR}" fetch --quiet origin main
  git -C "${BACKEND_DIR}" reset --quiet --hard origin/main
  git -C "${FRONTEND_DIR}" reset --quiet --hard origin/main

  # The reset above can rewrite this very file while bash is reading it.
  local copia
  copia="$(mktemp)"
  cp "${BACKEND_DIR}/scripts/staging/deploy.sh" "${copia}"
  DEPLOY_BACKEND_DIR="${BACKEND_DIR}" \
    DEPLOY_ACTUALIZADO=1 \
    DEPLOY_COPIA="${copia}" \
    DEPLOY_ANTERIOR_BACKEND="${anterior_backend}" \
    DEPLOY_ANTERIOR_FRONTEND="${anterior_frontend}" \
    exec bash "${copia}"
}

etiquetar_anteriores() {
  local imagen
  for imagen in "${IMAGENES[@]}"; do
    imagen="crm_easyoffice_staging_${imagen}"
    if docker image inspect "${imagen}:latest" >/dev/null 2>&1; then
      docker tag "${imagen}:latest" "${imagen}:previous"
    fi
  done
}

host_de_staging() {
  sed -n 's/^STAGING_HOST=//p' "${BACKEND_DIR}/.envs/.staging/.traefik"
}

estado_http() {
  curl --silent --insecure --output /dev/null --write-out '%{http_code}' --max-time 10 \
    --resolve "$1:443:127.0.0.1" "https://$1$2" || true
}

esperar_estado() {
  local esperado="$1" host="$2" ruta="$3" obtenido=""
  for _ in {1..30}; do
    obtenido="$(estado_http "${host}" "${ruta}")"
    if [[ "${obtenido}" == "${esperado}" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "https://${host}${ruta} answered ${obtenido}, expected ${esperado}." >&2
  return 1
}

revisar_rutas() {
  local host
  host="$(host_de_staging)"
  esperar_estado 401 "${host}" / || return 1
  esperar_estado 401 "firma.${host}" / || return 1
  esperar_estado 401 "correo.${host}" / || return 1
  esperar_estado 303 "${host}" /api/pagos/retorno/0/ || return 1
}

desplegar() {
  registrar "Building"
  COMPOSE_PARALLEL_LIMIT=1 compose build || return 1
  compose up -d --wait postgres redis || return 1

  if ! compose run --rm -T django python manage.py migrate --check >/dev/null 2>&1; then
    registrar "Migrations pending: backing up the database first"
    compose exec -T postgres backup || return 1
  fi
  registrar "Migrating"
  compose run --rm -T django python manage.py migrate --noinput || return 1

  registrar "Restarting"
  compose up -d --wait --wait-timeout 180 --remove-orphans || return 1
  registrar "Checking the routes"
  revisar_rutas || return 1
}

restaurar() {
  local anterior_backend="$1" anterior_frontend="$2" imagen
  registrar "Restoring ${anterior_backend:0:8} and ${anterior_frontend:0:8}"
  git -C "${BACKEND_DIR}" reset --quiet --hard "${anterior_backend}"
  git -C "${FRONTEND_DIR}" reset --quiet --hard "${anterior_frontend}"
  for imagen in "${IMAGENES[@]}"; do
    imagen="crm_easyoffice_staging_${imagen}"
    if docker image inspect "${imagen}:previous" >/dev/null 2>&1; then
      docker tag "${imagen}:previous" "${imagen}:latest"
    fi
  done
  compose up -d --no-build --wait --wait-timeout 180 --remove-orphans
}

volver_atras_a_mano() {
  exec 9>"${LOCK}"
  flock --wait 1800 9
  local anterior_backend anterior_frontend
  read -r anterior_backend anterior_frontend <"${ESTADO_ANTERIOR}"
  restaurar "${anterior_backend}" "${anterior_frontend}"
  registrar "Rolled back. Migrations are not reversed: see docs/staging.md."
}

if [[ "${1:-}" == "--rollback" ]]; then
  volver_atras_a_mano
  exit 0
fi

if [[ -z "${DEPLOY_ACTUALIZADO:-}" ]]; then
  actualizar_y_reejecutar
fi

trap 'rm -f "${DEPLOY_COPIA}"' EXIT
echo "${DEPLOY_ANTERIOR_BACKEND} ${DEPLOY_ANTERIOR_FRONTEND}" >"${ESTADO_ANTERIOR}"
etiquetar_anteriores

if desplegar; then
  registrar "Pruning old images and build cache"
  docker image prune --force >/dev/null
  docker builder prune --force --filter until=168h >/dev/null
  registrar "Deployed $(git -C "${BACKEND_DIR}" rev-parse --short HEAD) and $(git -C "${FRONTEND_DIR}" rev-parse --short HEAD)"
  exit 0
fi

echo "The deploy failed; restoring the previous images." >&2
restaurar "${DEPLOY_ANTERIOR_BACKEND}" "${DEPLOY_ANTERIOR_FRONTEND}"
registrar "Rolled back. Migrations are not reversed: see docs/staging.md."
exit 1
