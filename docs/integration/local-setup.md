# Website integration: local environment

Reproduces the production arrangement from `website-contract.md` on one
machine, over plain HTTP:

| Host | Serves | Stands in for |
|---|---|---|
| `http://easyoffice.local` | Mock public site (`dev/sitio-simulado/`) | easyoffice.cl (WordPress) |
| `http://tramites.easyoffice.local` | Frontend dev server, running on your machine | the client portal |
| `http://api.easyoffice.local` | Django: API, admin, webhook | the API |

A Caddy container (`proxy`) listens on port 80 and routes by host name. It is
defined in `docker-compose.local.integration.yml`, which is used **together
with** `docker-compose.local.yml`. The base file is unchanged.

The mock site's contact form posts to `/enviar-formulario` on its own host.
Caddy adds the token and forwards the submission to the webhook, the way
Elementor's webhook action does from the WordPress server. The token never
appears in the browser.

---

## 1. One-time setup

### Hosts entries

Add these lines to `/etc/hosts` (it needs `sudo`):

```
127.0.0.1  easyoffice.local tramites.easyoffice.local api.easyoffice.local
::1        easyoffice.local tramites.easyoffice.local api.easyoffice.local
```

On macOS, `.local` is also the mDNS domain. Without the `::1` line, the
first request to each host can hang for about five seconds.

Remove the lines when you no longer need them.

### Env variables

`.envs/.local/.django` must have the variables from
`.envs.example/.local/.django`, including:

```
SITIO_BASE_URL=http://easyoffice.local
PORTAL_BASE_URL=http://tramites.easyoffice.local
WEBHOOK_SITIO_TOKEN=localdev-webhook-token
```

The Caddy proxy reads `WEBHOOK_SITIO_TOKEN` from the same file, so the relay
and Django always agree on it.

---

## 2. Start

Backend, from this repository:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.local.integration.yml up -d
```

To avoid typing both `-f` flags every time, set this in your shell:

```bash
export COMPOSE_FILE=docker-compose.local.yml:docker-compose.local.integration.yml
```

Commands that use only the base file report `proxy` and `sitio-simulado` as
orphan containers. That's harmless. But `just up` passes `--remove-orphans` and
sets `COMPOSE_FILE` itself, so it **removes** them. Use the `docker compose`
command above while working on the integration.

Frontend, from the frontend repository, **bound to 127.0.0.1**:

```bash
npm run dev -- --host 127.0.0.1
```

Plain `npm run dev` binds to `localhost`, which on macOS is IPv6 `[::1]` only.
Containers reach the host only over IPv4 through `host.docker.internal`, so
the portal host answers 502. Binding to `127.0.0.1` fixes that without
exposing the dev server to your network.

To stop only the integration containers and leave the rest of the stack
running:

```bash
docker compose -f docker-compose.local.yml -f docker-compose.local.integration.yml stop proxy sitio-simulado
```

---

## 3. Try it in a browser

1. Open `http://easyoffice.local`.
2. **Deep links:** "Contratar plan anual" and "Contratar plan semestral" open
   the portal with that plan preselected. Under "Enlaces de prueba",
   "Plan inexistente" and "Sin plan" must show the plan selector without an
   error, and "Servicio inexistente" must land on the catalogue.
3. **Webhook:** fill in "Contáctanos" with made-up data and send it. The page
   shows the result.
4. Log in at `http://api.easyoffice.local/admin/` and open *Prospectos*. The
   submission is there. Sending the same form again the same day shows "ya lo
   habíamos recibido" and creates no second record.

Create an admin user first if you have none:

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py createsuperuser
```

---

## 4. Try it with curl

These commands work even before you edit `/etc/hosts`, because
`--resolve` points the host names at 127.0.0.1 for that one command. Once
the hosts entries are in place, you can drop the `--resolve` flags.

```bash
R="--resolve easyoffice.local:80:127.0.0.1 --resolve api.easyoffice.local:80:127.0.0.1"
URL="http://api.easyoffice.local/api/integraciones/sitio/prospectos/"
TOKEN=localdev-webhook-token
```

(In zsh, write `R=(--resolve … --resolve …)` as an array, otherwise the
flags reach curl as a single argument.)

Catalogue:

```bash
curl $R http://api.easyoffice.local/api/catalogo/
```

Form-encoded submission. This should return `201 {"resultado":"creado"}`,
and running it again should return `200 {"resultado":"duplicado"}`:

```bash
curl -i $R -X POST "$URL?token=$TOKEN" \
  -d "nombre=Persona Prueba&email=persona.prueba@example.com&servicio=domicilio-tributario&plan=anual&origen=curl"
```

JSON. `trimestral` is accepted but flagged as an unknown plan:

```bash
curl -i $R -X POST "$URL?token=$TOKEN" -H "Content-Type: application/json" \
  -d '{"nombre":"Persona JSON","telefono":"+56 9 0000 0001","servicio":"domicilio-tributario","plan":"trimestral"}'
```

Multipart:

```bash
curl -i $R -X POST "$URL?token=$TOKEN" \
  -F nombre="Persona Multipart" -F email=multipart@example.com
```

Wrong token. This should return `403`, and nothing is created:

```bash
curl -i $R -X POST "$URL?token=incorrecto" -d "nombre=X&email=x@example.com"
```

Through the mock site's relay, exactly as the browser form does it:

```bash
curl -i $R -X POST http://easyoffice.local/enviar-formulario \
  -d "nombre=Persona Relay&email=relay@example.com&origen=sitio-contacto"
```

Use only made-up data. Everything you send is stored in your local database.

---

## 5. Testing against a real Elementor form through a tunnel

This is for the future test with the agency. Its purpose is to capture what
Elementor Pro actually sends, so an `elementor` adapter can be written from a
real payload instead of a guess.

**Before you start:**

- A tunnel makes your local Django reachable from the internet, **admin and
  debug pages included**. Open it only for the test and close it right after.
- Use a throwaway token for the session, not `localdev-webhook-token`:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
  Put it in `WEBHOOK_SITIO_TOKEN` in `.envs/.local/.django`, then run
  `docker compose … up -d django proxy` so both containers pick it up.
- The test form sends only made-up data. Never commit a capture that holds
  real personal data.
- It needs Elementor Pro on their site, and someone at the agency to add a
  webhook action to a test form.

Any tunnelling tool works. These are not project dependencies. Examples:
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
or [ngrok](https://ngrok.com/docs/).

### Step 1: capture the raw payload

The current webhook would reject an unknown payload shape with a 400 and
store nothing, so the first step captures the raw request instead:

```bash
python3 dev/capturar_webhook.py 8081
cloudflared tunnel --url http://localhost:8081
# or: ngrok http 8081
```

Give the agency the public HTTPS URL the tunnel prints. Any path works. They
submit the test form once, and the script prints the headers and body. Save
that output. It is the input for writing
`integrations/sitio_web/elementor.py` and its registry entry.

### Step 2: end-to-end against the real webhook

Once the adapter exists, tunnel the proxy and rewrite the host name, so Caddy
routes to Django:

```bash
cloudflared tunnel --url http://localhost:80 --http-host-header api.easyoffice.local
# or: ngrok http 80 --host-header=api.easyoffice.local
```

The webhook URL for the agency is:

```
https://<tunnel-host>/api/integraciones/sitio/prospectos/?token=<throwaway token>&formato=elementor
```

Afterwards: stop the tunnel, restore your local token, and delete the test
prospectos if you don't need them.
