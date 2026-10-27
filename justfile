export COMPOSE_FILE := "docker-compose.local.yml"

## Just does not yet manage signals for subprocesses reliably, which can lead to unexpected behavior.
## Exercise caution before expanding its usage in production environments.
## For more information, see https://github.com/casey/just/issues/2473 .


# Default command to list all available commands.
default:
    @just --list

# build: Build python image.
build *args:
    @echo "Building python image..."
    @docker compose build {{args}}

# up: Start up containers.
up:
    @echo "Starting up containers..."
    @docker compose up -d --remove-orphans

# down: Stop containers.
down:
    @echo "Stopping containers..."
    @docker compose down

# prune: Remove containers and their volumes.
prune *args:
    @echo "Killing containers and removing volumes..."
    @docker compose down -v {{args}}

# logs: View container logs
logs *args:
    @docker compose logs -f {{args}}

# manage: Executes `manage.py` command.
manage +args:
    @docker compose run --rm django python ./manage.py {{args}}

# pytest: Run tests with pytest.
pytest *args:
    @docker compose run --rm django pytest {{args}}

# firma-pytest: Run the test PSC's own tests (firma_sandbox/).
firma-pytest *args:
    @docker compose run --rm --no-deps -e FIRMA_SANDBOX_ENV=test -e FIRMA_SANDBOX_DATA_DIR=/tmp/data -e FIRMA_SANDBOX_PKI_DIR=/tmp/pki firma-sandbox pytest {{args}}

# e2e-firma: Sign a warehouse case end to end through the test PSC (no legal validity).
e2e-firma:
    @docker compose up -d --wait firma-sandbox
    @docker compose up -d
    @docker compose run --rm django python manage.py migrate
    @docker compose run --rm django python manage.py seed_demo_firma_avanzada
    @docker compose run --rm django pytest -o addopts="" -p no:django -m e2e e2e
