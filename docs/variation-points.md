# Variation points: the documents implemented so far

This file records what really differs between the documents that run end to
end. It was started as the input for the configurable engine plan (OE-3, RF-33
to RF-37, RF-41), from the first two cases.

**The configurable engine is out of the MVP** (team decision, 05-11-2026).
Each document is implemented directly, as PLT-01 and PLT-02 were: no
configuration screens (HU-14, HU-16, HU-17, HU-18) and no generic form or
field engine. What already exists and fits is kept: `TipoTramite.configuracion`,
the generic request functions, the shared conversion steps and context
builders, the signature flow and the transition table. The table gains one
column per document; the "engine parameter" column stays as a record of what
an engine would need.

**Evidence.**
- Both anonymised templates (`13_plantillas`).
- The field dictionary and observations OB-01 to OB-10.
- RN-37, RN-38, RN-43 and RN-44.
- The seeded catalogue.
- From Easy Office's 2026 PLT-02 sample, only these non-personal field
  results:
  - folio `LF-0150-2026`;
  - lines `DOMICILIO TRIBUTARIO` at the La Florida branch, then
    `BODEGA VIRTUAL`.

Every `ASSUMPTION` below is marked in the code as
`ASSUMPTION: pending validation with Easy Office`.

## The cases

| Aspect | PLT-01 domicile | PLT-02 warehouse | PLT-03 vehicle lease | Where it lives now | Engine parameter it suggests |
|---|---|---|---|---| | ---
| **Form fields and validation** | Section A + plan + branch + start date. | Section A + plan + branch + warehouse + start date, in the portal and in the backoffice. (Before it was sold online: duration + each line's cycle and agreed price.) | Backoffice only. Section A (company, signer, personería), the owner as a person block, the company's address, comuna, document date, the vehicle (plate and VIN/chassis validated), term, start date, rent, payment day and method. Its own serializer: `tramites/formularios/plt03.py`. | Section A is shared: `clientes.services.guardar_datos_contratante` and frontend `features/tramites/formulario/`. The rest: `tramites/api/serializers.py` (`DomicilioSerializer`, `EdicionBackofficeSerializer`) and `tramites.services._validar_eleccion`. | `formulario.campos`: a list of typed fields (choice from a queryset, date in a window, money, enum), each naming its validation. Section A becomes one reusable block. |
| **Client types** | Company only: the template prints razón social, giro and personería. | Company only, for the same reasons; the template has no natural-person variant. | Company only: the lessee is the client company. | Config `tipos_cliente: ["empresa"]`, read by `cliente_admitido`. | `tipos_cliente` as is. A natural-person type would also need a different section A and template text. |
| **Property type and its selection rule** | One line located at a branch (role `sucursal`). Profile `domicilio`: address, rol, SII unit, municipality, and a current company owner with its representative and both card sides. | Two lines. The domicile at a branch (role `sucursal`, profile `ubicacion`: address, comuna and region only) and the warehouse (role `bodega`, profile `bodega`: address, rol, and a current natural-person owner with civil data and both card sides). ASSUMPTION: the warehouse is shared (`inmueble_exclusivo: false`); the exclusive rule is built and tested behind the flag. | None. No property and no lines: the vehicle is case data (`Tramite.datos`), not a model. | Config `lineas[]` names `{servicio, inmueble, requisitos, inmueble_exclusivo}` per line. Roles and profiles: `inmuebles.services.ROLES` and `REQUISITOS`. Occupancy: `contratos.services.inmuebles_ocupados`. | `lineas[]` as is. Profiles should be derived from the template's printed fields instead of hand-written: today each profile exists in config and is checked again in the template's `contexto`. |
| **Template and converter** | `conversion/plt01.py`: OB-01, plus OB-02 (SII unit and municipality per branch), company-owner markers. | `conversion/plt02.py`: OB-01, plus OB-05 (term in words, warehouse region, «BODEGA_*» markers), person-owner markers. | `conversion/plt03.py`: no merge fields; `[MARKERS]` (`corchetes`) and the signature table's `Label: ____` blanks (`rotulos`). No tracked changes, service rows or images. | Shared steps: `conversion/comun.py` (tracked changes, service rows, PRIMERO, fields, markers, images). One command, `manage.py convertir_plantilla PLT-0N`. | The field → path and marker → path maps (`CAMPOS`, `MARCADORES`) as data on the template version. Text surgery (OB-02, OB-05) stays code. |
| **Context sources** | Contract, client company, representative, notice contact, services, Easy Office, branch (with rol and SII unit), company owner and its representative's card. | Same shared parts, plus the branch (location only), the warehouse (location and rol), the person owner and their card. The term is printed twice: in figures and in words. | The case's data, the client company, its representative and the owner (`Persona`). No contract, no Easy Office, no folio. | `documentos/comun.py` (shared builders and their source ids), `documentos/plt01.py`, `documentos/plt02.py`; `documentos.services.CONTEXTOS` by template code. | A dotted path → source map (`sucursal.direccion` ← property of role `sucursal`). The record ids in `fuentes` come from the same map. |
| **States and pending reasons** | iniciado → revision_borrador → pago → firma → completado; falta_informacion for missing data or a passed date. | Portal: the same path as the domicile. Backoffice: iniciado → revision_borrador → firma → completado, never `pago`. | iniciado → revision_borrador → pago → firma → completado, from the backoffice. No "start date passed" rule: there is no contract to backdate (ASSUMPTION). | One shared `tramites.services.TRANSICIONES`; `requiere_pago` (per channel) decides the step after review. | Per-type transitions (MD-17) only if a third case needs a state the table lacks; two cases did not. |
| **Payment and signature** | Online sale of the chosen plan (`requiere_pago: true`), then an assisted signature: the executive uploads the signed PDF. | Portal: the plan's sale (59.990, signature included), checkout, then the assisted signature. Backoffice: no sale and no `Venta`, so the dashboard counts none; ASSUMPTION: paid outside the platform, and the executive confirms the draft for the client (RN-13). | Online after the draft, from a backoffice case (`requiere_pago: ["backoffice"]`): the catalogue service once, at list price plus VAT (`precio: "lista"`; fictitious 30.000 net). The client pays in the portal. Only the parties sign. | `requiere_pago: ["portal"]` (a list of channels) / `requiere_firma`; `confirmar_borrador(canal=…)`. | `requiere_pago` per channel, `requiere_firma`, plus **price source**: plan, list price, or agreed. |
| **Start date and duration** | Today … +30 days (`inicio_max_dias`). The duration is the plan's (6 or 12). | Today … +30 days. The duration is the plan's (3, 6 or 12), in both channels; expiry is start + duration − 1 day (RN-37). | The parties' dates, no window; the term is typed (1 to 99 months); end = start + term − 1 day (ASSUMPTION, as RN-37). | `inicio_max_dias`, `planes`; `contratos.services.calcular_vencimiento`. `duracion_por_defecto` stays for a type without plans. | `duracion: {origen: plan \| elegida, por_defecto, opciones}`. |
| **Channel** | Portal only: the client files it. | Both. The client buys it in the portal by plan; an executive starts it in the backoffice with the same plans (`tramites.iniciar_tramite`). Each side moves only its own cases; the client follows a backoffice case read-only. | Backoffice only; the client follows it in the portal and pays there (ASSUMPTION). | Config `canales` (a list), `Tramite.canal`; `_exigir_canal`; portal endpoints `/api/portal/tramites/formulario/?tipo=`, `POST /api/portal/tramites/`, `PUT …/{id}/`; the domicile keeps its own URLs. | `canales` as is, with **per-channel step settings** (`requiere_pago: ["portal"]`); who confirms the draft follows the channel. |
| **Plans** | Two plans (anual 12 months 59.990 with the signature; semestral 6 months 39.990, signature charged on top, 5.000). The plan sets price, cycle and term of the only line. | Three plans (anual, semestral, trimestral), each 59.990 with the signature included (ASSUMPTION, TA-15: the annual website price as a placeholder). The plan prices the bodega line and also pays the domicile line, copied at $0 with the plan's cycle (`incluido_en_plan`). | None: one list price. | `ventas.PlanServicio` rows (migrations 0012, 0013), edited in the admin; config `planes`, `servicio`, `lineas[].incluido_en_plan`; `contratos.LineaContrato.incluido_en`. | `planes: {servicio, lineas_incluidas}`; plan prices stay data. |
| **Duration printed in the document** | Figures only: `«DURACIÓN»` → "(12 MESES)". | Words and figures from the plan: "TRES (3) MESES" in the authorisation, "(3 MESES)" in the renewal (OB-05), and the expiry date. | Words and figures ("DOCE (12) MESES"), start and end dates, and the rent in figures and words (`formato.monto_en_letras`). | `documentos.formato.duracion` / `duracion_en_letras`; `conversion/plt02.py` (`_autorizacion_bodega`, `_renovacion`). | A value format per field (`duracion`, `duracion_letras`); the formats themselves stay code. |
| **Folio and brand** | `{branch}-{n}-{year}`, branch of the first located line; brand EASY OFFICE. | Same. The domicile line goes first, so the branch heads the folio (`LF-0150-2026` in the sample). Brand EASY OFFICE (the heading). | Neither. `contrato: false`: no `Contrato`; files are named by the case number. | `contratos.folio`, `contratos.services._codigo_sucursal`; config `marca`. | None new. Line order in `lineas[]` already decides the folio. |
| **Signers** | The client's representative and the owner company's representative. | The client's representative and the warehouse owner (person). | The owner (`arrendador`), then the client's representative. Easy Office never signs. The same person may hold both roles. | Each template's `contexto().firmantes`. | `firmantes`: a list of roles → people from the same source map. |
| **Client-facing copy** | Portal copy, now built from the type's `nombre` (`SOLO_EMPRESAS`, `NO_DISPONIBLE`). | The same generic copy; the form's title is the type's `nombre`; signer and summary labels follow the contract's property ("Propietario de la bodega"). Staff see the detailed `problemas`. | The case screens show `resumen`, label/value lines built by the form module. | Constants in `tramites/services.py`; frontend `features/tramites/formulario/roles.ts` and `features/tramites/contrato.ts`. | Per-type copy, or generic copy built from `nombre`. |

Shared and **not** forked:
- the parties clause and Easy Office's representative;
- the complementary-services annex: OB-04, whose "desde" prices differ
  between templates (contabilidad 15.900 vs 19.900);
- "MÁS I.V.A." (OB-09);
- the authoriser's domicile and the signing city (OB-10, TA-22).

All of them stay fixed template text in both conversions.

## What still needs code even with an engine

The third case (PLT-03, the vehicle lease) tested these. What it needed, per
point: 1 a new converter with two new shared steps; 2 no model (the vehicle is
case data, the owner a `Persona`); 4 amounts in words; 7 a list price charged
once (`precio: "lista"`); 8 a plate field. It also needed what this list did
not foresee: a case **without a contract** (`contrato: false`), VAT added to
a net price (`ventas.montos`), and signers that are only the parties.

1. **Template text surgery.** Typed values (OB-02, OB-05) and drift checks
   are specific to each Word file. Every new template version needs its
   converter checked.
2. **New source entities.** PLT-03's vehicle and its owner (Easy Office is not
   a party, OB-06) and PLT-04's Conservador de Bienes Raíces data and the
   lessor's bank account (OB-07) have no model yet.
3. **New requirement profiles.** What a property (or vehicle) must have
   before it is offered, until profiles are derived from the template.
4. **New value formats.** Amounts in words, a different date wording, a
   singular or plural agreement beyond months.
5. **Optional clauses.** PLT-05's articles vary per case (OB-08).
6. **Transitions outside the shared table**, if a case needs a state RN-42
   does not have.
7. **Prices that do not come from a plan**: the agreed price of a backoffice
   line (online, RN-44 forbids per-client prices), and bundles beyond "this
   line is included in that plan" (PLT-02's domicile at $0).
8. **New form widgets**, for example a vehicle plate or a CBR inscription.
9. **OB-10**: if TA-22 moves the signing city and the authoriser's domicile to
   configuration, both converters change.
10. **Property requirements written twice.** The config profile and each
    `contexto` both check them. Tests keep them in sync until the engine
    derives one from the other.

## Open questions for Easy Office (from PLT-02)

- Is a bodega unit exclusive or shared? Is there a capacity per unit (MD-04)?
- Is the warehouse ever contracted without the domicile, or at a branch other
  than the one that issues the folio?
- The bodega's plans (anual, semestral, trimestral) all cost 59.990 with the
  signature included: a placeholder from the website's annual price (TA-15).
  What are the real prices, and does the plan really include the domicile
  (printed at $0)?
- Is a bodega started by an executive paid outside the platform, as today's
  backoffice contracts are, or should it also go through the online sale?
- The catalogue says "Bodega" (our name) while the contract prints "BODEGA
  VIRTUAL". The description is ours too: it ends with a period, and the
  template adds another one in Anexo 1.
- Does the authorisation's region always come from the warehouse? Is it dated
  at the branch's comuna or at the warehouse's?
- Which durations apply to a warehouse? Does the renewal keep the same
  period?
- Since this change, a one-month contract prints "(1 MES)" instead of "(1
  MESES)", in both templates.

## Open questions for Easy Office (from PLT-03)

- The prices are fictitious (30.000 net, plus VAT) until the price list arrives.
- Is the lease always started by an executive, and paid by the client in the
  portal?
- The company's address is typed per case: our records hold none (OB-17).
- `[COMUNA]` is one value for the heading and the domicile clause.
- When the owner is also the company's representative, they sign twice, once
  per role.
- May the lease's dates be in the past? Is its end start + term − 1 day?
- Should a lease's end date raise an expiry alert, as contracts do? Not built.
- Upper case for names, addresses and dates, as in the service contracts?
