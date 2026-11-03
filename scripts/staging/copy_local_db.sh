#!/usr/bin/env bash

### Copy the local database to staging, anonymized before it leaves this machine.
###
### Usage: scripts/staging/copy_local_db.sh <user@host>
### Run from an up-to-date main, with the local stack's postgres running.
### Environment: STAGING_SSH_KEY_FILE (default ~/.ssh/crm_staging),
### STAGING_BACKEND_DIR (default /srv/crm-easyoffice/crm-easyoffice-backend).

set -o errexit
set -o pipefail
set -o nounset

destino="${1:-}"
if [[ -z "${destino}" ]]; then
  echo "Usage: $0 <user@host>" >&2
  exit 2
fi
clave="${STAGING_SSH_KEY_FILE:-${HOME}/.ssh/crm_staging}"
remoto="${STAGING_BACKEND_DIR:-/srv/crm-easyoffice/crm-easyoffice-backend}"
postgres_local=crm_easyoffice_local_postgres

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${raiz}"

git fetch --quiet origin main
if [[ "$(git branch --show-current)" != "main" ]] \
  || [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]]; then
  echo "Run this from an up-to-date main: the copy must match staging's migrations." >&2
  exit 1
fi
if [[ "$(docker inspect -f '{{.State.Running}}' "${postgres_local}" 2>/dev/null)" != "true" ]]; then
  echo "The local postgres is not running: docker compose -f docker-compose.local.yml up -d postgres" >&2
  exit 1
fi

copia() {
  docker compose -f scripts/staging/docker-compose.copia.yml "$@"
}

trabajo="$(mktemp -d)"
limpiar() {
  copia down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${trabajo}"
}
trap limpiar EXIT

echo "==> Starting the throwaway copy"
docker compose -f docker-compose.local.yml build django postgres
copia up -d --wait postgres-copia

echo "==> Dumping the local database into it"
docker exec "${postgres_local}" sh -c \
  'pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | copia exec -T postgres-copia psql --quiet -v ON_ERROR_STOP=1 -U copia crm_copia >/dev/null

echo "==> Anonymizing the copy"
copia run --rm -T --no-deps --entrypoint sh anonimizador -c \
  'mkdir -p /copia/private_media/plantillas'
COPYFILE_DISABLE=1 tar --no-xattrs -C private_media -cf - plantillas \
  | copia run --rm -T --no-deps --entrypoint tar anonimizador -xf - -C /copia/private_media
copia run --rm -T anonimizador python manage.py migrate --noinput
copia run --rm -T anonimizador python manage.py anonimizar_datos \
  --es-copia --identidades /copia/identidades.json

echo "==> Packing it"
# The audit log's rows hold original values, so they stay behind with the copy.
copia exec -T postgres-copia pg_dump --no-owner --no-privileges \
  --exclude-table-data=core_registroauditoria -U copia crm_copia \
  | gzip >"${trabajo}/copia.sql.gz"
copia run --rm -T --no-deps --entrypoint tar anonimizador -czf - -C /copia/private_media . \
  >"${trabajo}/private_media.tar.gz"
copia run --rm -T --no-deps --entrypoint cat anonimizador /copia/identidades.json \
  >"${trabajo}/identidades.json"

echo "==> Uploading it to ${destino}"
remoto_tmp="$(ssh -i "${clave}" "${destino}" mktemp -d)"
scp -q -i "${clave}" "${trabajo}/copia.sql.gz" "${trabajo}/private_media.tar.gz" \
  "${trabajo}/identidades.json" "${destino}:${remoto_tmp}/"

echo "==> Restoring it in staging"
ssh -i "${clave}" "${destino}" "${remoto}/scripts/staging/restore_copy.sh ${remoto_tmp}"

echo "Done. Staging holds the anonymized copy."
