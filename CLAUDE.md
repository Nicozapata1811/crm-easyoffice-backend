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
inmuebles/      oficinas, rol de avalúo, domicile assignments
tramites/       tipo de trámite (configuration), trámite, state machine
documentos/     plantillas (versioned), documento generation, hashing
integrations/   SignatureService, PaymentService + implementations
migracion/      Excel → PostgreSQL import pipeline
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
  yet** and are being requested by the company. Build against a simulated
  implementation that satisfies the same contract; the real one drops in via an
  environment variable.
- **Payment.** The company has **not decided** the provider yet. Options
  mentioned were Transbank and Mercado Pago. Transbank in its integration
  environment is our reference implementation.

Never import a provider SDK outside `integrations/`.

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

## Current status (week 5 of 18)

Requirements gathered, scope drafted, prototypes built but **not yet validated**
with the counterpart. Validation meeting is week 6.

**Still unknown — do not invent answers:**

- Structure and quality of the Excel file
- Real document templates and their format (Word? PDF? must the layout be
  reproduced exactly? — this determines the document generation library)
- Exact case states and valid transitions
- Exact roles and their permissions
- Signature provider API details and credentials
- Payment provider
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

Project documentation lives in the team's evidence repository under `docs/`:
requirements matrix (`MRQ-001`), business rules (`RN-001`), MVP scope
(`ALC-001`), product vision (`PV-001`), backlog (`BKL-001`), risk register
(`RSK-001`), traceability matrix (`TRZ-001`). Ask for them if a decision seems to
depend on one.
