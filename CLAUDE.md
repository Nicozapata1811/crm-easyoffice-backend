# CLAUDE.md — CRM Easy Office · Backend

Context file for Claude Code. Read this before touching anything.

---

## What this project is

A web platform for **Easy Office**, a Chilean company that provides business
formalisation services (tax domicile, notarised-equivalent documents, advisory)
to entrepreneurs and small companies, with offices in three regions.

Today their process is manual: clients send data over WhatsApp, an executive
retypes it into a template, generates the document, sends it back as a draft,
waits for confirmation, then batches documents and signs them with an advanced
electronic signature. That round trip takes three to four hours per service, and
their client records live in Excel spreadsheets with no access control and no
record of who changed what.

This platform replaces that. It centralises clients and cases in a relational
database, records every action, and automates the generation and signing of
standardisable documents.

**Academic context.** This is a capstone project (Duoc UC, Ingeniería en
Informática, PTY4614), built by three students over 18 weeks. The repository is
public and audited by the school. Code quality and traceability are graded.

---

## Stack

- Python + Django + Django REST Framework
- PostgreSQL
- Celery + Redis for asynchronous work (document generation, external webhooks)
- Docker / docker-compose for local and production parity
- Scaffolded from `cookiecutter-django`

The React frontend lives in a **separate repository**. This repo exposes a REST
API and the Django admin; it renders no application UI.

---

## Architecture: modular monolith

One Django project, one database, one deployment. Internally split into apps with
explicit boundaries:

```
core/           users, roles, permissions, audit log
clientes/       persona, empresa, representante legal
inmuebles/      properties (oficina / bodega), rol de avalúo, autorizantes
configuracion/  the issuing company (Easy Office), brands, payment accounts
tramites/       tipo de trámite (configuration), trámite, state machine
documentos/     plantillas (versioned), documento generation, hashing
integrations/   SignatureService, PaymentService + implementations
migracion/      Excel → PostgreSQL import pipeline
panel/          dashboard indicators and their Excel export (no models)
ventas/         price list, sales, payment attempts, payments, webhook log
contratos/      contract, contracted services, folio counter, terms
```

**Rules for the boundaries**

- Apps talk to each other through service functions, not by importing and
  querying each other's models directly.
- Dependency direction: `documentos` may depend on `tramites`; `tramites` must not
  depend on `documentos`. `core` depends on nothing.
- Do **not** propose microservices. Three developers, one product, one semester.
  The team has to defend this decision in an oral exam.

---

## Domain model decisions (already made — do not relitigate)

These are deliberate and each one exists for a reason. Preserve them.

1. **Versioned templates.** `PlantillaDocumento` has immutable versions. Every
   emitted `Documento` points at the exact version it was generated from. If the
   company fixes a clause in March, documents issued in February must not change.

2. **Frozen data snapshot.** When a document is generated, the data used is
   copied into the document record (JSONB). Updating a client's address later
   must not alter an already-issued contract.

3. **SHA-256 integrity hash.** Stored for the generated file and again for the
   signed file returned by the provider.

4. **Append-only audit log.** User, action, timestamp, affected record, old
   value, new value. No updates, no deletes. Prefer database triggers over Django
   signals — harder to bypass and easier to defend.

5. **Persona / Empresa / Representante legal are distinct entities.** A contract
   is signed by a company's legal representative, not by "the client". The
   representation has a validity period.

6. **Oficina / inmueble is its own entity**, with its `rol de avalúo` (Chilean
   property tax roll number), address, and the set of companies currently
   domiciled there.

7. **Multiple signers per document.** The counterpart explicitly requires it.

8. **Explicit state machine.** A table of allowed transitions (from state, to
   state, authorising role, conditions) — not `if` statements scattered through
   views.

9. **Idempotent external events.** `Pago` and `SolicitudFirma` carry a unique
   external id and a log of received events. Webhooks arrive duplicated and out
   of order.

---

## The configurable engine (the project's differentiator)

A *tipo de trámite* is **configuration**, not code. It defines: form fields,
validation rules, document template, states, whether payment is required, whether
signature is required, and who is responsible.

The system interprets that configuration to build the flow at runtime.

**Build order — follow it.**

1. Implement `domicilio tributario` as directly as possible. Near-hardcoded is
   fine.
2. Implement the second document by copying the first. Yes, duplicating.
3. Only then extract the engine from what actually repeats.

Generalising before two or three concrete cases produces invented abstractions.
This ordering is a deliberate decision.

**Do not build a visual flow editor.** The configuration is a JSONB record edited
through the Django admin. A drag-and-drop designer is a project in itself and
nobody asked for it.

**Do not claim the engine handles any future document.** It covers the family of
standardisable documents. Business rules outside the model require extending it.

---

## External integrations

Both sit behind interfaces defined by us, in `integrations/`:

```python
class SignatureProvider(ABC): ...


class PaymentProvider(ABC): ...
```

- **Signature.** Provider is `tufirma.digital`. Credentials are **not available
  yet** (TA-07) and are being requested by the company.
  - **Level per case type.** `TipoTramite.configuracion["firma"]["nivel"]` is
    `asistida` (default, tramites 0006: the executive uploads the signed PDF)
    or `avanzada`. `firma.firmantes` optionally orders the roles, and may add
    `representante_emisor`, Easy Office's representative.
  - **Provider.** `SIGNATURE_PROVIDER=http|simulated` (`integrations/signature/registry.py`).
    `http.py` (`HttpSignatureProvider`) talks to any provider over HTTP;
    every provider-specific name sits in its mapping section, so tufirma is a
    copy with another mapping, URL and key. Tests use the simulated provider.
  - **The test PSC (`firma_sandbox/`).** A separate Django project, standing
    in for an external provider; not a CRM microservice. It has its own
    `pyproject.toml`/`uv.lock`, SQLite, compose services under the `firma`
    profile (local only) and tests (`just firma-pytest`), and shares no tables
    or imports with the CRM (ruff `banned-api` both ways, plus a test).
    - **What it does:** a test CA, TSA, CRL and OCSP; an identity check
      against a fictitious registry; single-use certificates; OTP by email;
      PAdES B-LT per signer, B-LTA at the end; HMAC webhooks with retries.
    - **No legal validity**, and never in production:
      - the service refuses to start outside development;
      - `production.py` refuses its URL (`exigir_proveedor_real`);
      - `SIGNATURE_ALLOW_SANDBOX` is true only in local and test settings.
    - **Docs.** Its API is documented as a provider's in `firma_sandbox/README.md`.
  - **Flow** (`documentos/firma.py`):
    1. Entering (pendiente, firma) sends `tramites.signals.firma_requerida`.
       For `avanzada`, `enviar_a_firma` (Celery) sends the PDF and the
       `Firmante` rows in order, storing a `SolicitudFirma`.
    2. Webhooks arrive at `/api/firma/webhooks/<proveedor>/`. They are
       verified with HMAC and a 300 s window, deduplicated by event id in the
       append-only `EventoFirma`, then `procesar_evento_firma` reads the
       provider's current state.
    3. `aplicar_estado` marks each signer. On completion it checks RF-39
       (reported original hash, the original as an exact prefix, the
       downloaded hash), then `guardar_firmado`, the same end state as the
       upload.
    4. A decline, expiry or cancellation moves the case to falta información.
    5. `sincronizar_solicitudes_abiertas` (beat, 15 min) and the backoffice
       documents GET are the fallback when a webhook is lost.
  - **Backoffice actions:** `…/firma/reenviar|cancelar|reintentar/`
    (`documentos.gestionar_firma`). The upload answers 409 `firma_avanzada`
    for `avanzada` types.
  - **Audit.** HU-30 is not merged: `TODO(RF-15)` marks the request sent, the
    webhook received and the signed PDF stored.
- **Payment.** The company has **not decided** the provider yet. Options
  mentioned were Transbank and Mercado Pago. Two adapters exist, both an
  assumption until Easy Office decides: `integrations/payment/klap.py` (Klap
  Checkout Flex, modal) and `integrations/payment/flow.py` (Flow, redirect).
  `PAYMENT_PROVIDERS` lists what the client may choose; each `OrdenPago`
  stores its provider and `registry.get_payment_provider(nombre)` builds it.
  Flow's notification is an unsigned token: `parse_webhook` verifies it by
  calling `payment/getStatus`, so `webhook_needs_lookup` providers are handled
  in the `procesar_notificacion` Celery task. Browsers come back through
  `/api/pagos/retorno/<orden>/` (Flow returns with a POST). Klap requires public HTTPS webhook URLs
  and calls the validation webhook while it creates the order. Locally, the
  `tunnel` service in `docker-compose.local.yml` (cloudflared quick tunnel,
  wrapped by `compose/local/tunnel/start-tunnel.sh`, which exits when the
  tunnel dies so Docker restarts it with a new one) provides one; `registry.webhook_base_url` reads its random URL from
  `PAYMENT_TUNNEL_METRICS_URL` unless `PAYMENT_WEBHOOK_BASE_URL` is set.
  The validation call cannot be signature-checked (Klap signs it with an
  order_id it has not sent yet), so it is answered from our data only.
  `httpx` is the HTTP client, used only inside `integrations/`.

Never import a provider SDK outside `integrations/`.

**PDF.** Generated contracts are converted from Word to PDF by Gotenberg
(LibreOffice, `gotenberg/gotenberg:8.37.0-libreoffice`), a compose service
reached only by the Celery worker, behind `integrations/pdf/`
(`PdfConverter`; `PDF_CONVERTER=gotenberg|simulated`, `GOTENBERG_URL`).
Tests use the simulated converter.

---

## Authentication and roles

- **Session auth** (AD-03): `/api/auth/csrf/`, `login/`, `logout/`, `me/` in
  `users/api/auth_views.py`. httpOnly cookies, CSRF-protected login, one generic
  error for any failed login. Idle timeout from
  `DJANGO_SESSION_INACTIVITY_SECONDS` (assumption, 1800 s).
- **The Django admin has its own session cookie** (`<SESSION_COOKIE_NAME>_admin`,
  path `/<ADMIN_URL>`), set by `core.middleware.AdminSessionMiddleware`, so
  signing in to the admin never replaces the web app's session or the reverse.
  Tests reach the admin through the `admin_client` fixture in
  `crm_easyoffice/conftest.py`, which sets both cookies. With
  `DJANGO_ADMIN_FORCE_ALLAUTH` the admin login happens under `/accounts/`, on
  the web cookie, so the admin would not see it: keep it off.
- **Roles are `auth.Group`** (MOD-001 `ROL`). At most one per user, enforced in
  `UserAdminChangeForm`. Do not add a parallel role model; new roles are data.
- `core/migrations/0002_seed_roles.py` seeds Administrador (RN-31) and Ejecutivo
  (RN-32). Ejecutivo never gets `delete_*` (RF-04).
  `core/0003_dashboard_ejecutivo` grants `core.view_dashboard` to Ejecutivo
  (ACTA-002 D2-06, RN-32); its reverse removes it. When a new app adds
  models, grant its permissions to these roles in that app's own data
  migration.
- Feature permissions that guard no model live on the table-less
  `core.PermisoSistema` (today: `core.view_dashboard`, RF-14).
- `me` returns `rol` and `permisos`; clients authorise on permissions, not on
  the role name.
- Logins are not audited yet: `TODO(RF-15)` in `LoginView`.
- `/api/auth-token/` and `TokenAuthentication` come from cookiecutter and
  conflict with AD-03. Removal is pending a team decision.
- **Client portal accounts** (HU-03): `clientes.CuentaCliente` links a `User`
  to a `Cliente`. Clients register at `POST /api/portal/registro/`
  (`clientes.services.registrar_cuenta_cliente`) and then log in through the
  same `/api/auth/*` endpoints. A client user has no group, so staff
  permissions never apply; portal views use `clientes.api.permissions.EsCliente`.
  `me` adds `tipo` (`cliente` | `staff`) and `cliente`.

---

## Clients and dashboard

- **Clients API** (`clientes/api/`): `/api/clientes/` supports list, record,
  create and PATCH; there is no DELETE (RF-04). Writes nest the client's
  `persona` or `empresa`.
  - RUTs are normalised with `core.validators.normalize_rut` before validation.
  - A RUT that is already a client is rejected (HU-52). A Persona or Empresa on
    record that is not yet a client is linked instead.
  - `Cliente.codigo` (`CLI-000001`) is an internal id assigned in `save()`.
    It was `folio` until the folio moved to the contract (RN-38). Client
    payloads (`/api/clientes/`, `me`, `/api/ventas/`) still carry `folio` as
    a deprecated alias of `codigo` for one release; drop it once the frontend
    reads `codigo`.
  - `Persona` carries the optional contract data (`nacionalidad`,
    `estado_civil` from the `EstadoCivil` choices, `profesion`, `domicilio`,
    `comuna`, `region`); `RepresentanteLegal` carries the personería
    (`fecha_instrumento`, `sitio_o_notaria`).
  - The final client fields (MD-01) are still pending; `seed_demo_clientes`
    loads fictitious data meanwhile.
- **Properties** (`inmuebles/`, HU-66): `Oficina` is any property, `tipo`
  `oficina` or `bodega`. Branch offices carry `codigo_sucursal` (LF, VL, SA,
  seeded with placeholder address and rol; fill them in the admin), which
  heads the contract folio. `Autorizante` is the owner who authorises a
  property's use (RN-43): a `Persona`, or an `Empresa` with its
  `RepresentanteLegal`, for a period.
  - The identity card is sensitive: `core.storage.PrivateFileSystemStorage`
    keeps it under `PRIVATE_MEDIA_ROOT` (`DJANGO_PRIVATE_MEDIA_ROOT`), outside
    `MEDIA_ROOT` and in a production volume nginx does not mount. It has no
    URL; `GET /api/inmuebles/autorizantes/{id}/documento-identidad/` serves it
    as a no-store attachment to holders of
    `inmuebles.descargar_documento_identidad` (Administrador only). The
    codename deliberately avoids `view_`, which the core role seed grants
    Ejecutivo wholesale. Uploads go through
    `inmuebles.services.guardar_documento_identidad` (JPG/PNG/PDF checked by
    content, 5 MB).
    Both sides are stored (`documento_identidad`, `documento_identidad_reverso`;
    download with `?lado=reverso`): PLT-01 prints both.
  - A branch is offered for the online domicile only when
    `inmuebles.services.problemas_para_domicilio(oficina, fecha)` is empty:
    real address and rol, SII unit and municipality (OB-02), a current
    authoriser that is a company with a representative holding every field the
    contract prints, and both card sides as JPG/PNG. The admin shows the list
    per branch. `manage.py seed_demo_domicilio` (DEBUG only) fills the seeded
    branches and Easy Office's representative with fictitious data.
  - Who is domiciled where comes from contracts:
    `contratos.services.ocupantes(inmueble, fecha)`. `AsignacionDomicilio` was
    removed (HU-60).
  - Requirement profiles (`inmuebles.services.REQUISITOS`) say what a
    template prints about a property:
    - `domicilio` (PLT-01, above).
    - `ubicacion` (PLT-02's branch: address, comuna and region only).
    - `bodega` (PLT-02's warehouse: address, rol, and a current owner who is
      a **natural person** with RUT, nationality, civil status, profession
      and both card sides as JPG/PNG).

    Roles map to querysets (`ROLES`: `sucursal`, `bodega`).
    `inmuebles_para(rol, fecha, requisito)` lists the eligible properties,
    prefetching their authorisers (fixed query count). The admin shows "lista
    para bodega (PLT-02)" and what is missing.
  - `manage.py seed_demo_bodega` (DEBUG only) runs `seed_demo_domicilio`,
    then adds two fictitious warehouses with person owners.
- **Issuer configuration** (`configuracion/`, HU-65): `ConfigEmpresa` (one
  row, enforced by a constraint), `Marca` (EASY OFFICE, INOFFICE) and
  `CuentaPago` (`texto_contrato` is what the contract prints). Seeded with
  fictitious values and no RUT; the real data is entered in the admin and
  never committed. Nothing is deleted, only deactivated. Read it through
  `configuracion.services` (`obtener_config_empresa`, `marcas_activas`,
  `cuenta_pago_para`; `problemas_para_contrato` lists what a contract needs
  and is missing). That both brands are one company is an assumption.
- **Contracts** (`contratos/`, HU-60): `Contrato` is one row of Easy Office's
  spreadsheet: folio, brand, client, signer, payment account, term and
  notice contact, grouping `ServicioContratado` lines (name, description,
  price and VAT flag copied, cycle, optional property; no fixed limit,
  TA-12). Create them only through `contratos.services.crear_contrato`.
  - Folio (RN-38): `{branch}-{correlative}-{year}`, e.g. `LF-0007-2026`. The
    branch comes from the first located service, or is given explicitly when
    none gives one. The correlative is shared by branches and brands and
    restarts yearly; `contratos.folio` takes it from the year's
    `CorrelativoFolio` row under `select_for_update`, inside the contract's
    transaction (gapless, never repeated; a unique constraint backs it up).
    Width is `CONTRATO_FOLIO_ANCHO` (4) because of the 2-digit historical
    folios (TA-03).
  - Expiry is start + duration − 1 day (RN-37), computed; durations come from
    `DuracionContrato` (1, 3, 4, 6, 12).
  - States: `borrador` (a portal request: it has its folio but occupies no
    domicile), `vigente`, `terminado`, `anulado`. A draft changes only through
    `actualizar_borrador` (folio and branch fixed), enters into force with
    `activar_contrato` once signed, or is annulled keeping its folio. A line
    may name a `PlanServicio`, which sets its price, cycle and the duration.
  - API: `/api/contratos/` list, record and create (`contratos.add_contrato`;
    no PATCH or DELETE), filters `buscar`, `estado`, `marca`, `sucursal`,
    `anio`; `GET /api/contratos/opciones/` lists brands, accounts, terms,
    cycles, branches and services for the form. Nobody holds
    `delete_contrato`.
  - Tests that need committed rows (the folio concurrency tests) keep the
    plain `django_db` marker and commit from another connection, cleaning up
    their own rows: a transactional test flushes the seeded catalogue, and
    with `--reuse-db` every later run would start without it.
- **Dashboard** (`panel/`, HU-41, RF-14): `GET /api/panel/indicadores/` and
  `.../exportar/` (`.xlsx` via openpyxl), both requiring `core.view_dashboard`,
  held by Administrador and Ejecutivo. `panel/ejemplo.py` is gone: every figure
  is real. `panel` reads other apps only through their service functions and
  imports no model (only `Venta` for a type hint, under `TYPE_CHECKING`).
  - `calcular_indicadores(desde, hasta, *, hoy=None)`: clients and sales cover
    the period (inclusive, local time); point-in-time figures are read at
    `fecha_referencia = min(hasta, hoy)` (`hoy` defaults to today, and lets
    tests fix it). `DIAS_AVISO = 30`. Sales without an executive are grouped
    last as "En línea (sin ejecutivo)" (`EN_LINEA`).
  - Service functions it uses:
    - `clientes.services.contar_clientes(desde, hasta)`: clients registered up
      to `hasta`, and those registered in the period.
    - `contratos.services.resumen_vencimientos(fecha, dias_aviso)`: counts
      contracts, not lines. `activos` = `contratos_vigentes(fecha)`;
      `por_vencer` = active, expiring within `dias_aviso` days (both ends
      inclusive), no renewal; `vencidos` = `vigente`, started, no automatic
      renewal, past expiry, not terminated (`terminado_en` empty), not
      renewed. A contract is renewed when a non-void contract points to it
      through `contrato_anterior`. Drafts, terminated and void contracts never
      count.
    - `ventas.services.ventas_pagadas(desde, hasta)`: sales `pagada` with
      `pagada_en` in the period, inclusive, local time (refunded, void and
      unpaid excluded); `total_vendido(ventas)`: their total;
      `ventas_por_servicio(ventas)`: amount per catalogue service, where
      `cantidad` is the number of sales that include the service.
    - `tramites.services.ventas_por_ejecutivo(ventas)`: per executive through
      the sale's first case: the contract's `ejecutivo_responsable`, else
      `creado_por` if staff (no `CuentaCliente`), else `None`.
    - `tramites.services.pendientes_por_motivo(fecha)`: cases pending at the
      end of `fecha`, per reason; `en_firma(fecha)`: cases waiting for a
      signature then. Both rebuild the state at that date from the latest
      `EventoTramite` on or before it.
    - `documentos.services.contar_pendientes_de_firma(fecha)`: the latest
      version generated by `fecha` of each case in `en_firma(fecha)`.
  - API: new keys `fecha_referencia` (`AAAA-MM-DD`) and
    `tramites_pendientes_por_motivo` (`[{motivo, nombre, cantidad}]`);
    `tramites_pendientes` is their sum. `datos_de_ejemplo` is always `[]`:
    deprecated, removed next release. The Excel keeps its sheets and columns,
    has no "Valor de ejemplo", and its Detalle column says "Al dd-mm-aaaa" for
    point-in-time figures and "Pagadas en línea, en el período" for sales.
  - Assumptions, pending validation with Easy Office: contracts are counted,
    not services; an auto-renewing contract stays active after its first term
    and never reappears as `por_vencer` (RN-10, TA-17); the 30-day window
    (HU-42); who the executive of an online sale is (these four carry
    `ASSUMPTION` in code); and backoffice contracts without an online payment
    have no `Venta`, so they do not count as sales (a gap of the data model,
    stated in the API docs and the UI, not marked in code).
  - Pending: remove `datos_de_ejemplo`; assign an executive to portal
    contracts (today every sale lands in "En línea (sin ejecutivo)"); the
    rolling term of auto-renewing contracts.
  - Tests: `panel/tests/test_api.py` and each app's own tests. Helpers build
    dated rows directly: `tramites.tests.factories.tramite_con_historia`
    (a case and its dated history), `ventas.tests.factories.venta_pagada`
    and `documentos.tests.factories.documento_generado` (a row on the seeded
    PLT-01 v1, no file rendered). A query-count test keeps the dashboard at
    a fixed number of queries. The whole suite has 684 tests (firma_sandbox/ has its own 62).

- **Sales** (`ventas/`): `Servicio` (admin-edited, example prices with
  `precio_confirmado=False`), `CicloPago` (único … anual, HU-23), `Venta`,
  `ItemVenta` (price copied, RN-08),
  `OrdenPago` (one per attempt, RN-28), `Pago` and the append-only
  `EventoPago`. State changes go through `ventas.services` only; the order's
  transition table is `TRANSICIONES` there. Orders are created at the provider
  by the `crear_orden_en_proveedor` Celery task, and `sincronizar_orden` polls
  the provider as a fallback to webhooks (RF-23).
  - Portal: `/api/portal/servicios/`, `/api/portal/ventas/` (+ `pagar/`),
    `/api/portal/ordenes/{id}/`. Webhooks: `/api/pagos/webhooks/<provider>/<event>/`.
    Backoffice: read-only `/api/ventas/` with `ventas.view_venta`.
  - The catalogue comes from Easy Office's contract form
    (`0007_seed_catalogo_formulario`, descriptions verbatim): domicilio
    tributario, creación de empresas, web mail + dominio, and contabilidad
    (inactive, no price, until Easy Office provides one). Two independent
    portal flags: `se_vende_en_portal` (bookable online; a constraint stops
    it without a price) and `visible_en_portal` (a card on the landing).
    `/api/portal/servicios/` lists active services that are either, with
    both flags, ordered by `orden`. Purchases accept only bookable ones.
    Firma electrónica avanzada is bookable but hidden (an add-on charged in
    the domicile flow); `0010_seed_servicios_visibles` adds bodega, arriendo
    de vehículo, arriendo de estacionamiento, acuerdo de accionistas and
    poder simple as visible, not bookable, with no price (assumption; their
    descriptions are ours and edited in the admin); `0013_seed_planes_bodega`
    then makes the bodega bookable by plan (see the warehouse case below).
    `precio_incluye_iva` records
    how each price reads while the VAT question is open (RN-44 vs the
    template's "más I.V.A."); every price stays unconfirmed until then.
  - Plans (`PlanServicio`, HU-24): the portal sells domicilio tributario as
    plan anual (12 months, 59.990, signature included) or semestral (6 months,
    39.990, the firma service charged on top, 5.000), from Easy Office's
    website, unconfirmed. `lineas_de_plan` builds the sale's lines;
    `anular_venta` cancels a pending sale; `venta_pagada` (signal, on commit)
    announces a paid one.
  - Not built yet: a refund endpoint (refund policy undefined).
- **Cases** (`tramites/`, HU-24): `TipoTramite` (configuration JSONB:
  `servicio`, `marca`, `plantilla`, `requiere_pago`, `requiere_firma`,
  `inicio_max_dias`, `planes`, `duracion_por_defecto`, `canales`,
  `tipos_cliente`, `lineas[{servicio, inmueble, requisitos,
  inmueble_exclusivo, incluido_en_plan}]`; `requiere_pago` may list the
  channels that pay online; documented on the model; the two seeded types are
  compared in `docs/variation-points.md`), `MotivoPendiente` (TA-13 open), `Tramite` and its
  append-only `EventoTramite` history. States follow RN-42: iniciado →
  pendiente (reason) → completado; moves go only through `tramites.services`
  against its `TRANSICIONES` table. A case links its draft contract and its
  sale (MD-10).
  - Domicile flow: the company client files the form (`iniciar_domicilio`:
    `clientes.services.guardar_datos_contratante`, which never edits a person
    who does not already represent that company, then a draft contract) →
    the `documento_requerido` signal → document generated →
    pendiente(revision_borrador) → `confirmar_borrador` creates the plan's
    sale → pendiente(pago) → `venta_pagada` → pendiente(firma) → signed upload
    → completado and the contract in force. A start date that has passed at
    confirmation, payment or signing asks the client for a new one
    (`cambiar_fecha_inicio`): contracts are never backdated. The start date is
    today … +30 days (assumption).
  - The request functions are generic over the type and never compare its
    name:
    - `iniciar_tramite(tipo, cliente, datos, canal=…, usuario=…)`;
    - `actualizar_tramite`, `cambiar_fecha_inicio`, `confirmar_borrador`;
    - `formulario_tramite(tipo, cliente, canal)` (staff `problemas`) and
      `formulario_portal(tipo, cliente)` (the client's plain reason and the
      type's `nombre`).

    `iniciar_domicilio`, `actualizar_domicilio` and `formulario_domicilio`
    are the domicile's portal wrappers. Each side acts only on its own channel's
    cases (`_exigir_canal`).
  - **Warehouse case (PLT-02, tramites 0004 and 0005)**, type `bodega`
    ("Bodega virtual"), `canales: ["portal", "backoffice"]`:
    - Sold by plan (ventas 0013): anual 12, semestral 6 and trimestral 3
      months, each 59.990 with the signature included. ASSUMPTION (TA-15):
      the website's annual price as a placeholder; plans and the service's
      list price are admin data, `precio_confirmado` false.
    - Always two lines: the domicile at a branch (it heads the folio) and the
      warehouse. The plan prices the warehouse line and pays the domicile
      line too (`incluido_en_plan`: copied at $0 with the plan's cycle,
      `contratos.LineaContrato.incluido_en`). The plan sets the term and the
      expiry.
    - Portal (company clients): request → draft → the client confirms → the
      plan's sale (59.990) → payment → signed upload → in force.
    - Backoffice: an executive with `tramites.iniciar_tramite`
      (Administrador and Ejecutivo) picks the same plans; ASSUMPTION: no
      online sale (`requiere_pago: ["portal"]`), the executive confirms the
      draft (RN-13) and uploads the signed PDF.
    - The warehouse is shared; `inmueble_exclusivo` switches on
      `contratos.services.inmuebles_ocupados` (drafts hold it).
    - The client sees a backoffice case read-only in the portal.
    - Assumptions are listed in `docs/variation-points.md`.
  - Portal API for types sold by plan: `GET /api/portal/tramites/formulario/?tipo=`
    (`nombre`, plans, properties per role, pre-fill, plain reason),
    `POST /api/portal/tramites/` (`tipo`, section A, `plan`, `sucursal`,
    `bodega`, `fecha_inicio`) and `PUT /api/portal/tramites/{id}/`; confirm,
    new date and payment use the existing case and sale endpoints.
  - Backoffice API for it:
    - `GET /api/tramites/tipos/?canal=backoffice`;
    - `GET /api/tramites/formulario/?tipo=&cliente=` (`iniciar_tramite`;
      `problemas` for staff);
    - `POST /api/tramites/` (`iniciar_tramite`; a property per role at the
      top level, `sucursal`/`bodega`, and `plan`, or `duracion_meses` and
      `lineas` for a type without plans);
    - `PUT /api/tramites/{id}/`, `POST …/{id}/confirmar/` and
      `POST …/{id}/fecha-inicio/` (`gestionar_tramite`).

    Serializers add `tipo_codigo` and `contrato.servicios` (every line).
  - Portal: `/api/portal/tramites/domicilio/formulario/` (availability,
    plans, ready branches, pre-fill from the client's own records),
    `POST /api/portal/tramites/domicilio/`, `/api/portal/tramites/` and
    detail, `PUT …/{id}/domicilio/`, `POST …/{id}/fecha-inicio/`,
    `POST …/{id}/confirmar/`. Internal notes never reach the portal.
    Backoffice: read-only `/api/tramites/` (`tramites.view_tramite`) and
    `POST /api/tramites/{id}/regenerar/` (`tramites.gestionar_tramite`).
- **Documents** (`documentos/`, HU-19..21): `PlantillaDocumento`,
  `VersionPlantilla` (immutable once used), `Documento` (one version per
  generation: Word and PDF with their SHA-256, the frozen snapshot of every
  printed value and its source ids, the template version) and `Firmante`.
  - PLT-01 and PLT-02 are converted once (`manage.py convertir_plantilla
    PLT-0N`; `convertir_plt01` stays as an alias) from the anonymised
    templates (`plantillas_semilla/`) into docxtpl templates; migrations 0002
    and 0003 load them as v1. The shared steps are in `conversion/comun.py`
    and the shared context in `documentos/comun.py` (`DatosIncompletosError`
    lives there); PLT-02 adds OB-05: the term in words, the warehouse's
    address, comuna, rol and region, and a person owner.
    `documentos.plt01.contexto` / `plt02.contexto` give every field one source;
    the `generar_documento` Celery task renders it with docxtpl and converts
    it to PDF. Missing data or a failed conversion leaves no document: the
    case waits for information with the reason for the executive.
  - Files are private: `/api/portal/tramites/{id}/documentos/` and
    `…/documentos/{doc}/{pdf|docx|firmado}/` for the owner;
    `/api/tramites/{id}/documentos/…` for `documentos.view_documento`. The
    executive uploads the signed PDF (assisted signature) at
    `POST /api/tramites/{id}/documentos/{doc}/firmado/subir/`
    (`documentos.subir_documento_firmado`; PDF by content, 10 MB).

---

## MVP scope

**In scope**

Backoffice (users, roles, clients, companies, cases, states, audit) · PostgreSQL
with Excel migration · configurable engine · `domicilio tributario` end to end ·
three or four more documents added by configuration · client portal for the
priority flow · signature and payment behind decoupled interfaces · deployment to
a production environment with backups and an operations manual.

**Out of scope**

The full 25–40 document catalogue · company incorporation (the counterpart
confirmed it needs human judgement every time) · notary integration (manual, over
WhatsApp, stays that way) · replacing their existing website · SII integration ·
mobile app · operation and support after handover.

---

## Data privacy — non-negotiable

The repository is **public**.

- No real personal data is ever committed. Not in fixtures, not in tests, not in
  migrations, not in comments.
- The Excel file the company will provide contains real client data. It gets
  anonymised before entering any environment.
- Secrets live in environment variables. Never in code, never in the repo.
- Chile's Ley 21.719 on personal data protection comes into force on 1 December
  2026. The counterpart raised data protection as a reason for this project.
  Design for access control, minimisation and traceability accordingly.

---

## Language conventions

- **Domain model names in Spanish**: `Tramite`, `TipoTramite`, `Documento`,
  `PlantillaDocumento`, `Empresa`, `RepresentanteLegal`, `Oficina`. The domain is
  Chilean legal and administrative; translating it loses precision and makes
  conversations with the counterpart harder.
- **Technical and infrastructure code in English**: services, settings, celery
  tasks, test names, docstrings.
- Comments and docstrings in English.
- Commit messages in English.

---

## Working conventions

- Branch per user story: `feature/HU-14-tipo-tramite-configurable`
- Every commit references its GitHub issue: `refs #42`
- Nothing reaches `main` without a Pull Request reviewed by another team member
- When a task changes code, models, migrations, the API, settings, dependencies
  or tests, finish it with the `exportar-cambios` skill (`.claude/skills/`) and
  show its prompt, so the documentation chat can be updated
- Traceability chain the project is graded on:
  `requirement → user story → issue → commit/PR → test → evidence`

**Definition of Done**

- [ ] Acceptance criteria met
- [ ] PR reviewed by another member
- [ ] Unit tests for new business logic passing
- [ ] Documentation updated
- [ ] `docker-compose up` brings the system up from scratch
- [ ] No real personal data, no secrets committed

---

## Current status (Sprint 2 · 6 – 17 Oct 2026)

Done:
- the `clientes` / `inmuebles` model, staff session login, and the
  Administrador and Ejecutivo roles;
- the clients API: create, edit, record, search and folio (HU-06, HU-07,
  HU-47, HU-49, HU-51, HU-52);
- the dashboard indicators endpoint with its Excel export;
- client portal registration and login (HU-03);
- sales and online payment with Klap Checkout Flex in its sandbox (HU-38,
  HU-39, HU-40, HU-57);
- domicilio tributario end to end on the real PLT-01: plans, draft contract,
  case states, document generation with docxtpl and Gotenberg, assisted
  signature upload (HU-19..21, HU-24, HU-26..29, HU-61);
- the warehouse contract (PLT-02) as the second case, started in the
  backoffice, with the variation points for the engine in
  `docs/variation-points.md`;
- the advanced signature through an HTTP provider, end to end against the
  test PSC (`firma_sandbox/`, IN-01), `asistida` by default.

Still to build: user management (HU-02) and the audit log (HU-30, RF-15). Until
the audit log exists, client changes carry `TODO(RF-15)`.

**Still unknown — do not invent answers:**

- Structure and quality of the Excel file
- Whether the generated document must reproduce the templates' layout
  exactly. The templates are known: Word files with `MERGEFIELD`s, anonymized
  as `PLT-01..05` in the evidence repository (`13_plantillas`). The generation
  library is docxtpl (spike, issue #49); PDFs come from LibreOffice
  (Gotenberg), whose fonts differ slightly from Word's Times New Roman.
- Exact case states and valid transitions
- Roles beyond Administrador and Ejecutivo (a "supervisor" appears in HU-05
  and HU-41 but is not confirmed) and the session inactivity timeout
- Signature provider (tufirma.digital) API details and credentials; who signs
  through it and in what order; link and code durations
- Payment provider (Klap is implemented as an assumption), prices, and the
  refund policy
- Production hosting

If a task depends on one of these, say so rather than assuming. Mark assumptions
explicitly in code comments as `# ASSUMPTION: pending validation with Easy Office`.

---

## Things not to do

- Don't add dependencies without asking. Every package has to be justifiable in
  an oral defence.
- Don't build the abstraction before the second concrete case exists.
- Don't put document generation or external HTTP calls inside a request cycle —
  that's what Celery is for.
- Don't store uploaded files inside the container.
- Don't write `if tipo_tramite.nombre == "domicilio tributario"`. If a behaviour
  varies by case type, it belongs in the configuration.
- Don't soften the audit log into something editable.
- Don't promise a measured time reduction anywhere in docs or comments. The
  three-to-four-hours-to-minutes figure is the client's expectation, to be
  measured, not a result.

---

## Reference documents

Project documentation lives outside the code repositories (the team's
documentation folder, `docs/`; not yet published to the evidence repository):
requirements matrix (`MRQ-001`), business rules (`RN-001`), MVP scope
(`ALC-001`), product vision (`PV-001`), backlog (`BKL-001`), risk register
(`RSK-001`), traceability matrix (`TRZ-001`). Ask for them if a decision seems to
depend on one.
