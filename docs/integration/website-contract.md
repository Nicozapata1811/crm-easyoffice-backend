# Website integration contract

Status: **draft, pending approval**. Nothing described here is implemented yet.

Easy Office's public site (easyoffice.cl, WordPress + Elementor, maintained by
an external agency) stays as it is. This platform does not replace it, embed it
or scrape it. The two are connected in exactly two ways:

1. **Deep links.** The site's buttons for automated services link into the
   client portal with the service and plan already chosen.
2. **Inbound webhook.** The site's other forms post their submissions to this
   API, and each submission becomes a *prospecto* (lead) in the CRM.

Everything the agency or Easy Office has to change on their side is
configuration: a link target on a button, and a webhook URL on a form. No code
is deployed on their site.

Assumptions are marked `ASSUMPTION: pending validation with Easy Office`.

---

## 1. Hosts

| Role | Production | Local (see `local-setup.md`) |
|---|---|---|
| Public website (theirs) | `https://easyoffice.cl` | `http://easyoffice.local` (mock) |
| Client portal (SPA) | `https://tramites.easyoffice.cl` | `http://tramites.easyoffice.local` |
| API and admin | `https://api.easyoffice.cl` | `http://api.easyoffice.local` |

The portal keeps calling the API **same-origin** through `/api`, as it does
today (Vite dev proxy locally, the reverse proxy in production). That keeps
the session cookie first-party. `api.` is the host that external callers such
as the webhook use.

ASSUMPTION: pending validation with Easy Office. The `tramites.` and `api.`
subdomain names, and a DNS record for them, have not been agreed.

Configuration (env vars, see §6): `SITIO_BASE_URL`, `PORTAL_BASE_URL`.

---

## 2. Deep links

### Format

```
{PORTAL_BASE_URL}/{servicio}?plan={plan}&origen={origen}
```

Example:

```
https://tramites.easyoffice.cl/domicilio-tributario?plan=anual&origen=sitio
```

| Part | Required | Rule |
|---|---|---|
| `servicio` | yes | A service slug from the catalogue (§4). |
| `plan` | no | A plan slug of that service. |
| `origen` | no | `^[a-z0-9_-]{1,50}$`. Identifies which button or page sent the visitor. |

`plan` and `origen` are matched after trimming and lower-casing. Other query
parameters are ignored and preserved, so the agency can add `utm_*` without
breaking anything.

The public path `/{servicio}` is a stable entry point. The portal resolves it
to whatever internal route handles that service, so internal routes can change
without breaking links already published on the site.

### Behaviour

| Case | Result |
|---|---|
| Known service, known plan | The service's form opens with that plan preselected. |
| Known service, `plan` missing | The form opens with the plan selector and nothing preselected. |
| Known service, unknown plan | Same as missing. No error is shown to the visitor, because a stale link on the site must not dead-end a customer. |
| Unknown service | Redirects to the portal catalogue (`/`). No error page. |
| `origen` missing or invalid | Treated as absent. |

`origen` is carried through the portal flow so it can be recorded on the
trámite once one is created (see §7, open question 1).

Prices shown in the portal come from the catalogue and are displayed as
reference prices, never as final ones (§4, `precio_confirmado`).

---

## 3. Inbound webhook

### Endpoint

```
POST /api/integraciones/sitio/prospectos/?token=<secret>[&formato=<adapter>]
```

The rest of the API lives under `/api/` and has no version segment. This
endpoint follows the same rule instead of introducing `/v1/` on its own.

### Authentication

- The shared secret goes in the `token` query parameter, because not every form
  builder can set custom headers.
- It is compared in constant time against the `WEBHOOK_SITIO_TOKEN` env var.
- If `WEBHOOK_SITIO_TOKEN` is unset or empty, every request is rejected with
  403. The endpoint fails closed.
- No session authentication and no CSRF on this endpoint. It is called
  server-to-server, and holds no user session.
- The secret appears in the URL, so it can end up in proxy access logs. Treat
  it as a revocable credential: generate it randomly (≥ 32 bytes), give it
  only to the agency, and rotate it by changing the env var and the form
  configuration together.

### Request

Accepted content types, all carrying the same fields:

- `application/x-www-form-urlencoded`
- `multipart/form-data` (file parts are ignored and never stored)
- `application/json`

Anything else gets `415 Unsupported Media Type`.

`formato` chooses the source adapter (§5). It defaults to `generico`. An
unknown value gets 400.

### Generic format (`formato=generico`)

A flat set of fields:

| Field | Required | Max | Notes |
|---|---|---|---|
| `nombre` | yes | 200 | |
| `email` | one of email/telefono | 254 | Must be a valid address if present. |
| `telefono` | one of email/telefono | 30 | Free text. The digits are used for de-duplication. |
| `servicio` | no | 100 | Service slug from the catalogue. |
| `plan` | no | 50 | Plan slug of that service. |
| `origen` | no | 50 | `^[a-z0-9_-]{1,50}$`. Invalid or missing becomes `sitio`. |
| `mensaje` | no | 5000 | |
| `id_envio` | no | 100 | The source's own submission id, if it has one (see de-duplication). |

- Unknown fields are ignored for processing and kept in the stored original
  payload.
- ASSUMPTION: pending validation with Easy Office. Requiring `nombre` plus
  either `email` or `telefono` is a guess at the minimum a lead needs to be
  contactable. Many Chilean customers give only a phone number (WhatsApp).
- `servicio` or `plan` values not in the catalogue are **accepted and
  flagged**, never rejected. A lead is worth more than a clean field.

### Responses

Response bodies carry no personal data and no record ids.

| Status | When | Body |
|---|---|---|
| `201 Created` | New prospecto recorded | `{"resultado": "creado"}` |
| `200 OK` | Same submission already recorded; nothing changed | `{"resultado": "duplicado"}` |
| `400 Bad Request` | Missing or invalid required fields, or unknown `formato` | DRF's usual `{"campo": ["mensaje"]}` |
| `403 Forbidden` | Missing or wrong token, or no token configured | `{"detail": "..."}` |
| `415 Unsupported Media Type` | Content type not listed above | `{"detail": "..."}` |
| `429 Too Many Requests` | Rate limit exceeded | `{"detail": "..."}` plus a `Retry-After` header |

### Rate limiting

- Scoped throttle `webhook_sitio`. The rate comes from the env var
  `WEBHOOK_SITIO_THROTTLE_RATE` and defaults to `60/min`.
- The throttle is applied **before** the token check, so guessing tokens is
  throttled too. By default DRF checks permissions first; this view reverses
  that order.
- Clients are identified by IP. Elementor webhooks are sent by the WordPress
  server, so every submission from the real site shares one IP. The rate is a
  ceiling for the whole site, not per visitor, and must be sized for that.
- Behind a reverse proxy, DRF's `NUM_PROXIES` must match the deployment,
  otherwise the client IP comes from a spoofable `X-Forwarded-For`. It is
  configurable via env (§6).

### De-duplication (idempotency)

Webhooks get retried and forms get double-submitted. Each prospecto stores a
unique `dedup_key` (SHA-256 hex):

- If the adapter supplies a source submission id: `sha256(formato + id_envio)`.
- Otherwise: `sha256(formato + normalised email + digits of telefono +
  servicio + plan + normalised mensaje + reception date in America/Santiago)`.

The same content on the same day counts as a duplicate. The same person
writing again on a later day creates a new prospecto. Concurrent duplicates are
resolved by the database's unique constraint, not by a check-then-insert.

ASSUMPTION: pending validation with Easy Office. The one-day window is a
judgement call.

### What is stored

The **Prospecto** record holds:

- `estado`: one of `nuevo`, `contactado`, `convertido`, `descartado`. It starts
  as `nuevo` and is edited by staff in the admin. No transition rules are
  enforced yet (ASSUMPTION: pending validation with Easy Office).
- `formato`: the adapter used.
- `origen`: from the payload, as described above.
- `nombre`, `email`, `telefono`, `servicio_interes`, `plan`, `mensaje`.
- `servicio_desconocido`, `plan_desconocido`: flags for values that were
  provided but are not in the catalogue.
- `recibido_en`: server time of reception. Timestamps supplied by the client
  are ignored.
- `payload_original`: the request data as received, excluding file contents
  and the `token` parameter.
- `dedup_key`: unique.
- `cliente`: optional link to `clientes.Cliente`, set by staff once the lead
  converts.

Every field that came from the webhook is read-only in the admin.

This is personal data under Ley 21.719. Only these fields are kept, and no
retention period is defined yet (§7, open question 5).

---

## 4. Service and plan catalogue

### Endpoint

```
GET /api/catalogo/
```

Public and read-only. The portal needs it before login to resolve deep links.

```json
{
  "servicios": [
    {
      "slug": "domicilio-tributario",
      "nombre": "Domicilio tributario",
      "planes": [
        {
          "slug": "anual",
          "nombre": "Anual",
          "meses": 12,
          "precio": 59990,
          "moneda": "CLP",
          "precio_confirmado": false,
          "enlace": "https://tramites.easyoffice.cl/domicilio-tributario?plan=anual&origen=sitio"
        },
        {
          "slug": "semestral",
          "nombre": "Semestral",
          "meses": 6,
          "precio": 39990,
          "moneda": "CLP",
          "precio_confirmado": false,
          "enlace": "https://tramites.easyoffice.cl/domicilio-tributario?plan=semestral&origen=sitio"
        }
      ]
    }
  ]
}
```

- `precio` is an integer number of CLP.
- `enlace` is the deep link to put on the site's button, built from
  `PORTAL_BASE_URL`. The agency can copy it from here.
- The source is a small settings-driven catalogue. When `TipoTramite` exists,
  this endpoint reads from it instead and the response shape stays the same.
- ASSUMPTION: public website prices, pending confirmation by Easy Office. The
  seeded plans are the two published on the public site. The unpublished
  `trimestral` option is **not** seeded (§7, open question 2).

---

## 5. Source adapters

Each source's payload is translated into one canonical shape before
validation and storage.

### Canonical shape: `ProspectoEntrante`

| Field | Type |
|---|---|
| `nombre` | str |
| `email` | str |
| `telefono` | str |
| `servicio_interes` | str |
| `plan` | str |
| `origen` | str |
| `mensaje` | str |
| `recibido_en` | aware datetime (set by the view, not the adapter) |
| `payload_original` | dict |

It also carries `id_envio: str | None`, which is used only for de-duplication.

### Flow

```
request.data ──▶ adapter.parse() ──▶ serializer (validation) ──▶ ProspectoEntrante ──▶ registrar_prospecto()
                 maps field names     required / lengths /                             dedup, catalogue flags,
                 per source           email / origen pattern                           save
```

An adapter only maps field names and structure. Validation is shared, so every
source is held to the same rules.

### Registry

Adapters are registered by name, and `formato` selects one:

| Name | Status |
|---|---|
| `generico` | Implemented. The format in §3. |
| `elementor` | **Not implemented.** Reserved. It will be written only after a real Elementor Pro webhook payload has been captured. |

Adding a source means writing one adapter class and one registry entry. No
changes to the view, the model or the validation.

---

## 6. Configuration

| Env var | Purpose | Default |
|---|---|---|
| `WEBHOOK_SITIO_TOKEN` | Webhook shared secret | *(empty: webhook disabled)* |
| `WEBHOOK_SITIO_THROTTLE_RATE` | Webhook rate limit | `60/min` |
| `SITIO_BASE_URL` | Public website origin | `https://easyoffice.cl` |
| `PORTAL_BASE_URL` | Portal origin, used to build `enlace` | `https://tramites.easyoffice.cl` |
| `DJANGO_CORS_ALLOWED_ORIGINS` | Cross-origin API callers | *(empty)* |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origins trusted for CSRF | *(empty)* |
| `DJANGO_SESSION_COOKIE_DOMAIN` | Cookie domain if the portal and API ever split origins | *(unset: host-only cookie)* |
| `DJANGO_NUM_PROXIES` | Reverse proxies in front of Django | *(unset)* |

None of these hold a real value in the repository. The env example files carry
placeholders only.

---

## 7. Open questions

1. **Recording `origen` on the trámite.** No trámite creation endpoint exists
   yet. The portal carries `origen` through the flow. The backend's trámite
   endpoint, when it is defined, should accept it.
2. **`trimestral` plan.** Mentioned but not published on the site. Does it
   exist, and at what price?
3. **Prices.** Are 59.990 and 39.990 CLP current, and do they include VAT?
4. **Elementor Pro.** The webhook action requires Elementor Pro. Does the
   site have it, and can the agency add a webhook to the existing popups?
5. **Retention.** How long are unconverted and discarded prospectos kept?
   (Ley 21.719.)
6. **Who handles leads.** Is there a notification when a new prospecto
   arrives, and who is assigned to it?
7. **DNS and subdomains.** Who creates `tramites.` and `api.`, and when?
8. **"Plan anual de bodega virtual".** The domicilio tributario page on the
   public site has a third "Contrate aquí" card for this plan. Is it a
   separate service to add to the catalogue, or should it keep going to the
   contact popup?
