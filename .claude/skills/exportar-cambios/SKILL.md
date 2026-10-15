---
name: exportar-cambios
description: Export a Spanish, ready-to-paste prompt that summarises every change made in this repo (code, models, migrations, API, config, dependencies, tests, docs), so it can be pasted into another Claude chat to update the project documentation. Use it at the end of any task that changed this repo, before the final reply, the commit or the PR. Also use it on request ("exporta los cambios", "genera el prompt de documentación", "resumen de cambios para la documentación", "export the changes").
---

# Exportar cambios

Every change to this repo has to reach the documentation. The team keeps it in
a separate Claude chat, so each task ends with a prompt that chat can act on.
This skill builds that prompt.

## When

- At the end of any task that changed code, models, migrations, API contracts,
  settings, dependencies, Docker files, tests or docs.
- On request, for the current branch, a PR or a range of commits.
- Not for questions, reviews or investigations that changed nothing.

## Steps

1. **Collect what changed.** Cover the uncommitted work and the branch:
   `git status --short`, `git diff`, `git diff origin/main...HEAD --stat`,
   `git log origin/main..HEAD --format=%B`. Read the changed files that matter;
   do not summarise from file names alone. If the task spans several commits or
   PRs, read them all.
2. **Classify** each change using the sections below. Drop the sections with
   nothing in them.
3. **Write the prompt** in Spanish, in one fenced `markdown` block, so the user
   copies it with one click. Put one line before the block saying what it
   covers, and nothing after it.
4. **Check it** against the rules below before sending.

## Output template

````markdown
Actualiza la documentación del proyecto CRM Easy Office (repositorio
backend) con los cambios siguientes. Revisa y ajusta el README, el
CLAUDE.md y cualquier documento que los mencione, mantén el estilo y el idioma
de cada documento, y no inventes nada que no esté aquí. Al terminar, lista qué
documentos cambiaste y qué dudas quedan.

## Contexto y trazabilidad
Historias (HU-xx), requisitos (RF/RN), issues y PRs, con su estado.

## Modelos y migraciones
Cada modelo nuevo o modificado con sus campos clave, restricciones y la
migración que lo introduce.

## Lógica de dominio
Servicios, tareas, reglas de negocio y cambios de comportamiento.

## API / pantallas
Rutas, métodos, cuerpos, respuestas y permisos (backend); rutas, pantallas,
componentes y tipos (frontend).

## Configuración, infraestructura y dependencias
Variables de entorno nuevas (solo los nombres), servicios de Docker,
paquetes añadidos con el motivo.

## Pruebas
Qué se cubre y cuántas pasan. Di si algo no se ejecutó.

## Decisiones y suposiciones
Decisiones de diseño con su porqué; todo lo marcado como
`ASSUMPTION: pending validation with Easy Office`.

## Pendientes
Lo que queda fuera de este cambio.
````

Use the repo's domain vocabulary as is (`Tramite`, `Cliente`, `Venta`, ...).
Code, paths and identifiers stay as written; the prose is in Spanish.

## Rules

- **The repos are public.** Never include secrets, API keys, tokens, real
  personal data or real URLs of private environments. Name environment
  variables, never their values. Use synthetic examples only.
- **Report only what is true.** If tests did not run, a check was skipped or a
  behaviour was not verified, say so. Do not describe intent as result.
- **Do not invent** requirement IDs, issue numbers or PR links. Use only the
  ones in the commits, branch names or the conversation.
- Mark assumptions exactly as the code does, and keep the project's open
  questions open (payment provider, prices, final case states, ...).
- Do not promise a measured time reduction anywhere.
- Be complete but compact: a changed field, endpoint or setting is one line.
  Do not paste diffs.
- Do not write the prompt to a file in the repo unless the user asks.

## What to look at in this repo (backend)

Models and migrations (`*/models.py`, `*/migrations/`), services and Celery
tasks, DRF views, serializers and URLs, permissions and the roles seed,
settings and `.envs.example`, `pyproject.toml` (new packages and why),
`docker-compose*.yml` and `compose/`, `integrations/`, and the OpenAPI schema
when an endpoint changes. For every endpoint give method, path, who may call it
and the main response codes.
