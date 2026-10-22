# Variation points: PLT-01 domicile vs PLT-02 warehouse

This file is the input for the configurable engine plan (OE-3, RF-33 to
RF-37, RF-41). It was built from the only two cases that run end to end, so it
records what really differs between them, not what might differ in a third.

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

## The two cases

| Aspect | PLT-01 domicile | PLT-02 warehouse | Where it lives now | Engine parameter it suggests |
|---|---|---|---|---|
| **Form fields and validation** | Section A + plan + branch + start date. | Section A + branch + warehouse + duration + each line's cycle, and the agreed price for a line with no list price + start date. | Section A is shared: `clientes.services.guardar_datos_contratante` and frontend `features/tramites/formulario/`. The rest: `tramites/api/serializers.py` (`DomicilioSerializer`, `EdicionBackofficeSerializer`) and `tramites.services._validar_eleccion`. | `formulario.campos`: a list of typed fields (choice from a queryset, date in a window, money, enum), each naming its validation. Section A becomes one reusable block. |
| **Client types** | Company only: the template prints razón social, giro and personería. | Company only, for the same reasons; the template has no natural-person variant. | Config `tipos_cliente: ["empresa"]`, read by `cliente_admitido`. | `tipos_cliente` as is. A natural-person type would also need a different section A and template text. |
| **Property type and its selection rule** | One line located at a branch (role `sucursal`). Profile `domicilio`: address, rol, SII unit, municipality, and a current company owner with its representative and both card sides. | Two lines. The domicile at a branch (role `sucursal`, profile `ubicacion`: address, comuna and region only) and the warehouse (role `bodega`, profile `bodega`: address, rol, and a current natural-person owner with civil data and both card sides). ASSUMPTION: the warehouse is shared (`inmueble_exclusivo: false`); the exclusive rule is built and tested behind the flag. | Config `lineas[]` names `{servicio, inmueble, requisitos, inmueble_exclusivo}` per line. Roles and profiles: `inmuebles.services.ROLES` and `REQUISITOS`. Occupancy: `contratos.services.inmuebles_ocupados`. | `lineas[]` as is. Profiles should be derived from the template's printed fields instead of hand-written: today each profile exists in config and is checked again in the template's `contexto`. |
| **Template and converter** | `conversion/plt01.py`: OB-01, plus OB-02 (SII unit and municipality per branch), company-owner markers. | `conversion/plt02.py`: OB-01, plus OB-05 (term in words, warehouse region, «BODEGA_*» markers), person-owner markers. | Shared steps: `conversion/comun.py` (tracked changes, service rows, PRIMERO, fields, markers, images). One command, `manage.py convertir_plantilla PLT-0N`. | The field → path and marker → path maps (`CAMPOS`, `MARCADORES`) as data on the template version. Text surgery (OB-02, OB-05) stays code. |
| **Context sources** | Contract, client company, representative, notice contact, services, Easy Office, branch (with rol and SII unit), company owner and its representative's card. | Same shared parts, plus the branch (location only), the warehouse (location and rol), the person owner and their card. The term is printed twice: in figures and in words. | `documentos/comun.py` (shared builders and their source ids), `documentos/plt01.py`, `documentos/plt02.py`; `documentos.services.CONTEXTOS` by template code. | A dotted path → source map (`sucursal.direccion` ← property of role `sucursal`). The record ids in `fuentes` come from the same map. |
| **States and pending reasons** | iniciado → revision_borrador → pago → firma → completado; falta_informacion for missing data or a passed date. | iniciado → revision_borrador → firma → completado; never `pago`. | One shared `tramites.services.TRANSICIONES`; `requiere_pago` decides the step after review. | Per-type transitions (MD-17) only if a third case needs a state the table lacks; two cases did not. |
| **Payment and signature** | Online sale of the chosen plan (`requiere_pago: true`), then an assisted signature: the executive uploads the signed PDF. | No sale and no `Venta` (`requiere_pago: false`), so the dashboard counts no sale. ASSUMPTION: the executive confirms the draft on the client's behalf (RN-13) and uploads the signed PDF. | `requiere_pago` / `requiere_firma`; `confirmar_borrador(canal=…)`. | `requiere_pago`, `requiere_firma`, plus **price source**: plan, list price, or agreed. |
| **Start date and duration** | Today … +30 days (`inicio_max_dias`). The duration is the plan's (6 or 12). | Today … +30 days. The duration is chosen from `DuracionContrato`, default 12 (ASSUMPTION). Printed as "DOCE (12) MESES" and "(12 MESES)". | `inicio_max_dias`, `planes`, `duracion_por_defecto`; `documentos.formato.duracion` / `duracion_en_letras`. | `duracion: {origen: plan \| elegida, por_defecto, opciones}`. |
| **Channel** | Portal: the client files it. | Backoffice only: the bodega has no price, is not bookable, and starts with `tramites.iniciar_tramite`. The client follows it read-only in the portal. | Config `canal`, `Tramite.canal`; `_exigir_canal` keeps each side to its own cases. | `canal` as is; a type sold in both channels would need the pair (who files, who confirms). |
| **Folio and brand** | `{branch}-{n}-{year}`, branch of the first located line; brand EASY OFFICE. | Same. The domicile line goes first, so the branch heads the folio (`LF-0150-2026` in the sample). Brand EASY OFFICE (the heading). | `contratos.folio`, `contratos.services._codigo_sucursal`; config `marca`. | None new. Line order in `lineas[]` already decides the folio. |
| **Signers** | The client's representative and the owner company's representative. | The client's representative and the warehouse owner (person). | Each template's `contexto().firmantes`. | `firmantes`: a list of roles → people from the same source map. |
| **Client-facing copy** | Portal copy names the domicile (`SOLO_EMPRESAS`, `NO_DISPONIBLE`). | None (backoffice). Staff see the detailed `problemas`. | Constants in `tramites/services.py`; the frontend's copy. | Per-type copy, or generic copy built from `nombre`. |

Shared and **not** forked:
- the parties clause and Easy Office's representative;
- the complementary-services annex: OB-04, whose "desde" prices differ
  between templates (contabilidad 15.900 vs 19.900);
- "MÁS I.V.A." (OB-09);
- the authoriser's domicile and the signing city (OB-10, TA-22).

All of them stay fixed template text in both conversions.

## What still needs code even with an engine

The third case (PLT-03 vehicle lease, or PLT-04 parking lease) will test these:

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
7. **Online prices that do not come from a plan**, such as the agreed price
   of a backoffice line (online, RN-44 forbids per-client prices).
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
- What are the price, cycle and plans of the bodega virtual? Does the domicile
  keep its list price when bundled?
- The catalogue says "Bodega" (our name) while the contract prints "BODEGA
  VIRTUAL". The description is ours too: it ends with a period, and the
  template adds another one in Anexo 1.
- Does the authorisation's region always come from the warehouse? Is it dated
  at the branch's comuna or at the warehouse's?
- Which durations apply to a warehouse? Does the renewal keep the same
  period?
- Since this change, a one-month contract prints "(1 MES)" instead of "(1
  MESES)", in both templates.
