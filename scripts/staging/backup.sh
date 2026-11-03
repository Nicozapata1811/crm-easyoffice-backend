#!/usr/bin/env bash

### Back up staging: database, private files and the test PSC's data. Run by cron.
### Keeps 7 days. Environment: STAGING_BACKUP_DIR (default: next to the repo clones).

set -o errexit
set -o pipefail
set -o nounset

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
destino="${STAGING_BACKUP_DIR:-$(dirname "${raiz}")/backups}"
fecha="$(date +'%Y_%m_%dT%H_%M_%S')"
cd "${raiz}"

compose() {
  docker compose -f docker-compose.staging.yml "$@"
}

registrar() {
  echo "$(date +'%Y-%m-%d %H:%M:%S') $*"
}

al_salir() {
  local estado=$?
  compose start firma-sandbox firma-sandbox-worker >/dev/null 2>&1 || true
  if [[ ${estado} -eq 0 ]]; then
    registrar "OK: backup ${fecha} finished"
  else
    registrar "FAILED: backup ${fecha} exited with ${estado}"
  fi
}
trap al_salir EXIT

mkdir -p "${destino}"
registrar "Backing up the database"
compose exec -T postgres backup

registrar "Backing up the private files"
compose run --rm --no-deps -T --entrypoint tar django -czf - -C /app/private_media . \
  >"${destino}/private_media_${fecha}.tar.gz"

# SQLite: stopped, so the copy is consistent.
registrar "Backing up the test PSC's data"
compose stop firma-sandbox-worker firma-sandbox
compose run --rm --no-deps -T --entrypoint tar firma-sandbox -czf - -C /data . \
  >"${destino}/firma_sandbox_${fecha}.tar.gz"

registrar "Deleting what is older than 7 days"
compose exec -T postgres find /backups -name 'backup_*.sql.gz' -mtime +6 -delete
find "${destino}" -name '*.tar.gz' -mtime +6 -delete
