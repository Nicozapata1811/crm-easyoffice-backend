#!/usr/bin/env bash

### Load into staging the bundle copy_local_db.sh uploaded. Run on the VM.
###
### Usage: scripts/staging/restore_copy.sh <bundle directory>

set -o errexit
set -o pipefail
set -o nounset

bundle="${1:?Usage: $0 <bundle directory>}"
raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${raiz}"

compose() {
  docker compose -f docker-compose.staging.yml "$@"
}

echo "==> Backing up staging first"
"${raiz}/scripts/staging/backup.sh"

echo "==> Stopping the services that use the database"
compose stop django celeryworker celerybeat

echo "==> Restoring the database"
archivo="copia_$(date +'%Y_%m_%dT%H_%M_%S').sql.gz"
compose cp "${bundle}/copia.sql.gz" "postgres:/backups/${archivo}"
compose exec -T postgres restore "${archivo}"
compose exec -T postgres rm -f "/backups/${archivo}"
compose exec -T redis redis-cli FLUSHALL

echo "==> Replacing the private files"
compose run --rm --no-deps -T --entrypoint sh django -c \
  'find /app/private_media -mindepth 1 -delete && tar -xzf - --no-same-owner -C /app/private_media' \
  <"${bundle}/private_media.tar.gz"

echo "==> Registering the generated people in the test PSC"
compose cp "${bundle}/identidades.json" firma-sandbox:/tmp/identidades.json
compose exec -T firma-sandbox python manage.py seed_identidades_demo --archivo /tmp/identidades.json
compose exec -T firma-sandbox rm -f /tmp/identidades.json

echo "==> Migrating and creating the demo users"
compose run --rm -T django python manage.py migrate --noinput
compose run --rm -T django python manage.py seed_demo_usuarios --force

echo "==> Starting everything"
compose up -d --no-build --wait --wait-timeout 180

rm -rf "${bundle}"
