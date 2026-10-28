# The test PSC (PSC de pruebas). Local development only: it is not part of
# docker-compose.production.yml and refuses to start outside development.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/venv PATH="/venv/bin:$PATH" PYTHONUNBUFFERED=1

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=firma_sandbox/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=firma_sandbox/uv.lock,target=uv.lock \
    uv sync --locked

COPY firma_sandbox /app

COPY compose/local/firma_sandbox/start /start
COPY compose/local/firma_sandbox/start-worker /start-worker
RUN sed -i 's/\r$//g' /start /start-worker && chmod +x /start /start-worker

EXPOSE 8100
CMD ["/start"]
