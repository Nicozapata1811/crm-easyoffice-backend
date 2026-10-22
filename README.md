# CRM Easy Office — Backend

Plataforma web de gestión de clientes, trámites y documentos para Easy Office.
Este repositorio contiene el backend: API REST y panel de administración. El
frontend vive en un repositorio separado,
[crm-easyoffice-frontend](https://github.com/Nicozapata1811/crm-easyoffice-frontend).

Proyecto de Capstone, Duoc UC, Ingeniería en Informática (PTY4614).

---

## Qué hace y qué problema resuelve

Easy Office presta servicios de formalización a emprendedores y pequeñas
empresas: domicilio tributario, documentos, asesorías. Hoy el proceso es
manual: los clientes envían sus datos por WhatsApp, un ejecutivo los transcribe
en una plantilla, genera el documento, lo devuelve como borrador, espera la
confirmación y luego firma en lotes. Cada servicio toma entre tres y cuatro
horas, la mayor parte de ellas en espera, y la información de los clientes vive
en planillas Excel sin control de acceso ni registro de quién modificó qué.

Esta plataforma reemplaza ese flujo. Centraliza clientes y trámites en una base
de datos relacional, registra cada acción y automatiza la generación y firma de
los documentos estandarizables.

**Dentro del alcance del MVP:** backoffice (usuarios, roles, clientes,
empresas, trámites, estados, auditoría) · migración desde Excel a PostgreSQL ·
motor configurable de tipos de trámite · domicilio tributario de extremo a
extremo · tres o cuatro documentos más agregados por configuración · portal de
cliente para el flujo prioritario · firma y pago detrás de interfaces
desacopladas · despliegue con respaldos y manual de operación.

**Fuera del alcance:** el catálogo completo de 25 a 40 documentos ·
constitución de empresas, que la contraparte confirmó que requiere criterio
humano · integración con notaría · reemplazo del sitio web actual · integración
con el SII · aplicación móvil · operación y soporte posteriores a la entrega.

---

## Tecnologías

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.14 |
| Framework | Django 6.0 |
| API | Django REST Framework, con esquema OpenAPI vía drf-spectacular |
| Base de datos | PostgreSQL 17 |
| Trabajo asíncrono | Celery con Redis |
| Contenedores | Docker y docker compose |
| Autenticación | django-allauth, con MFA |
| Calidad | pytest, ruff, mypy, pre-commit |
| CI | GitHub Actions |

El proyecto se generó con `cookiecutter-django`.

---

## Instalación local

Requisitos: Docker y Docker Compose.

```bash
git clone git@github.com:Nicozapata1811/crm-easyoffice-backend.git
cd crm-easyoffice-backend
cp -R .envs.example .envs
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml up -d
```

El paso `cp -R .envs.example .envs` no es opcional: `.envs/` no se versiona, y
sin él PostgreSQL no arranca. Los valores de `.envs.example/.local/` sirven tal
cual para desarrollo y no son secretos, porque los servicios que alcanzan son
contenedores de esta máquina. Los de `.production/` son plantillas: cada
`CHANGEME` se reemplaza por un valor generado para ese ambiente.

Esto levanta siete servicios: `django`, `postgres`, `redis`, `celeryworker`,
`celerybeat`, `flower` y `mailpit`. Las migraciones se aplican al iniciar.

Crear un superusuario:

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py createsuperuser
```

Cargar clientes ficticios para desarrollo (solo con `DEBUG` activo; volver a
ejecutarlo no duplica datos):

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py seed_demo_clientes
```

Completar las sucursales y agregar bodegas ficticias, listas para generar
`PLT-01` y `PLT-02` (solo con `DEBUG` activo; no sobrescribe lo ingresado en
el panel de administración):

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py seed_demo_bodega
```

Ejecutar las pruebas:

```bash
docker compose -f docker-compose.local.yml run --rm django pytest
```

La suite tiene 637 pruebas.

| Servicio | URL |
|---|---|
| Aplicación | http://localhost:8000 |
| Panel de administración | http://localhost:8000/admin/ |
| Documentación de la API | http://localhost:8000/api/docs/ |
| Correo de prueba (Mailpit) | http://localhost:8025 |
| Monitor de Celery (Flower) | http://localhost:5555 |

La documentación de la API requiere una sesión de administrador.

### Variables de entorno

`DJANGO_SESSION_INACTIVITY_SECONDS` fija los segundos de inactividad tras los
que expira la sesión. Las variables de pago se describen en
[Pago con Klap en local](#pago-con-klap-en-local).

Las credenciales viven en `.envs/`, que **no** se versiona. Los archivos se
generan al crear el proyecto y no deben commitearse nunca: este repositorio es
público. Ningún dato personal real entra en fixtures, pruebas, migraciones ni
comentarios.

---

## Integrantes y roles

| Integrante | Rol principal |
|---|---|
| Fernando Esteban Cartagena Acuña | Coordinación del proyecto, ingeniería de requisitos, arquitectura e integraciones |
| Nicolás Eduardo Zapata Trujillo | Base de datos y desarrollo backend |
| Marcos José Álvarez Muñoz | Desarrollo frontend y UX/UI |

Los roles indican responsabilidades principales, no funciones exclusivas.

---

## Metodología de trabajo

Enfoque ágil basado en **Scrum**, adaptado a un equipo de tres integrantes y a
un semestre académico. El trabajo se organiza con Product Backlog, historias de
usuario, Sprint Backlog, tablero Kanban, desarrollo iterativo, pruebas,
revisiones y retrospectivas, con retroalimentación de la contraparte.

Convenciones del repositorio:

- Una rama por historia de usuario: `feature/HU-14-tipo-tramite-configurable`
- Cada commit referencia su issue: `refs #42`
- Nada llega a `main` sin un Pull Request revisado por otro integrante

Cadena de trazabilidad sobre la que se evalúa el proyecto:
`requerimiento → historia de usuario → issue → commit/PR → prueba → evidencia`

**Definition of Done:** criterios de aceptación cumplidos · PR revisado por otro
integrante · pruebas unitarias de la lógica nueva pasando · documentación
actualizada · `docker compose up` levanta el sistema desde cero · sin datos
personales reales ni secretos.

---

## Arquitectura de la solución

**Monolito modular.** Un proyecto Django, una base de datos, un despliegue,
dividido internamente en aplicaciones con límites explícitos. No son
microservicios: tres desarrolladores, un producto, un semestre.

```
core/           usuarios, roles, permisos, log de auditoría
clientes/       persona, empresa, representante legal
inmuebles/      oficinas, rol de avalúo, asignación de domicilios
tramites/       tipo de trámite (configuración), trámite, máquina de estados
documentos/     plantillas versionadas, generación de documentos, hashing
integrations/   SignatureProvider, PaymentProvider e implementaciones
migracion/      pipeline de importación Excel → PostgreSQL
panel/          indicadores del panel operativo y su exportación a Excel
ventas/         servicios con precio, ventas, órdenes de pago, pagos y webhooks
```

Las aplicaciones se comunican mediante funciones de servicio, no importando los
modelos unas de otras. `core` no depende de nada; `documentos` puede depender de
`tramites`, nunca al revés.

**Decisiones de modelo de dominio:** plantillas versionadas e inmutables, de modo
que corregir una cláusula no altere documentos ya emitidos · copia congelada de
los datos usados en cada documento · hash SHA-256 del archivo generado y del
firmado · log de auditoría append-only · persona, empresa y representante legal
como entidades distintas, con vigencia en la representación · múltiples firmantes
por documento · máquina de estados como tabla de transiciones permitidas ·
eventos externos idempotentes, porque los webhooks llegan duplicados y
desordenados.

**Integraciones externas.** Firma electrónica avanzada y pago viven detrás de
interfaces propias en `integrations/`. Las credenciales del proveedor de firma
aún no están disponibles, por lo que existe una implementación simulada que
satisface el mismo contrato. Para el pago hay una implementación simulada y un
adaptador de Klap Checkout Flex, elegidos con `PAYMENT_PROVIDER`; Easy Office
aún no define el proveedor, así que Klap es una suposición pendiente de validar.
Ningún SDK ni cliente HTTP de proveedor se usa fuera de esa aplicación.

---

## Autenticación y roles

**Sesión con cookies `httpOnly`** (decisión AD-03), no JWT en el almacenamiento
del navegador. El login está protegido con el token CSRF de Django y las
credenciales inválidas responden siempre lo mismo, exista o no el usuario. La
sesión expira tras `DJANGO_SESSION_INACTIVITY_SECONDS` segundos sin actividad
(1800 por defecto; valor pendiente de validar con Easy Office). Los endpoints
viven en `crm_easyoffice/users/api/auth_views.py`. En desarrollo,
`config/settings/local.py` confía en el origen del servidor de Vite
(`http://localhost:5173`) para el chequeo CSRF, porque el frontend llega a la
API a través de su proxy.

**Roles = grupos de Django.** La tabla `ROL` de MOD-001 se implementa con
`django.contrib.auth.models.Group`: nombre y permisos. Un usuario tiene a lo más
un rol, y los roles nuevos se crean como datos desde el panel de administración,
sin código (RN-33). La migración `core/0002_seed_roles` siembra los dos roles
confirmados:

| Rol | Permisos |
|---|---|
| Administrador (RN-31) | Todos sobre clientes, inmuebles, usuarios y roles, más `core.view_dashboard` |
| Ejecutivo (RN-32) | Crear, modificar y consultar clientes; consultar inmuebles; `core.view_dashboard`. **Sin permisos de eliminación** (RF-04) |

Ambos roles ven el panel operativo (`core.view_dashboard`): el Ejecutivo lo
recibe en `core/0003_dashboard_ejecutivo` (ACTA-002, D2-06).
Cada aplicación nueva asigna sus permisos a estos roles en su propia
migración de datos.

Cada ingreso, cierre de sesión e intento fallido queda en el registro de
auditoría (criterio de HU-01; ver «Registro de auditoría»). Solo el
Administrador tiene `core.consultar_auditoria` (`core/0006_permiso_auditoria`).

---

## API

Contrato compartido con el frontend. Todas las rutas usan la sesión y, en
métodos no seguros, la cabecera `X-CSRFToken`.

| Método y ruta | Acceso | Respuesta |
|---|---|---|
| `GET /api/auth/csrf/` | Público | `{"csrfToken": "..."}` y deja la cookie CSRF |
| `POST /api/auth/login/` | Público, con CSRF | Cuerpo `{"email", "password"}`. `200` con el usuario de sesión; `400` con un mensaje único si falla |
| `POST /api/auth/logout/` | Sesión activa | `204` |
| `GET /api/auth/me/` | Sesión activa (`403` sin sesión) | Usuario de sesión |

Usuario de sesión:

```json
{
  "id": 1,
  "email": "usuario@example.com",
  "name": "Nombre Apellido",
  "tipo": "staff",
  "cliente": null,
  "rol": "Administrador",
  "permisos": ["clientes.add_cliente", "core.view_dashboard"]
}
```

`rol` es `null` si el usuario no tiene rol. El frontend decide qué mostrar según
`permisos`, no según el nombre del rol. `tipo` es `"cliente"` para una cuenta del
portal, y entonces `cliente` trae `{"id", "folio", "nombre"}`.

### Cuentas de cliente del portal (HU-03)

Los clientes inician sesión con las mismas rutas `/api/auth/*`. Una cuenta de
cliente no tiene rol ni permisos, así que no puede usar las rutas del personal.

| Método y ruta | Acceso | Respuesta |
|---|---|---|
| `POST /api/portal/registro/` | Público, con CSRF; máximo `DJANGO_THROTTLE_REGISTRO` (10/hora por defecto) | `201` con el usuario de sesión, ya autenticado |

Cuerpo: `tipo` (`persona` o `empresa`), `rut`, `email`, `password` y, según el
tipo, `nombres`, `apellido_paterno`, `apellido_materno` (opcional) o
`razon_social`.

- Un RUT nuevo crea la persona o empresa y el cliente.
- Un RUT ya registrado se vincula solo si su email coincide con el informado y
  el cliente aún no tiene cuenta. Es una suposición pendiente de validar con
  Easy Office.
- Cualquier otro rechazo responde `400` con un único `detail`, para no revelar
  qué RUT o emails existen. Una contraseña débil responde `400` en `password`.
- No se verifica el email todavía.

### Clientes (HU-06, HU-07, HU-47, HU-49, HU-51, HU-52)

Requieren `clientes.view_cliente` para leer, `add_cliente` para crear y
`change_cliente` para editar. Ambos roles los tienen. No hay eliminación
(RF-04): un cliente se desactiva con `activo`.

| Método y ruta | Respuesta |
|---|---|
| `GET /api/clientes/?buscar=&tipo=&activo=&page=` | Lista paginada (25 por página), del más reciente al más antiguo |
| `POST /api/clientes/` | `201` con la ficha |
| `GET /api/clientes/{id}/` | Ficha |
| `PATCH /api/clientes/{id}/` | Ficha actualizada |

- `buscar` separa palabras y exige que cada una aparezca en el RUT (con o sin
  puntos), nombres, apellidos, razón social, nombre de fantasía, correo,
  teléfono o folio.
- `tipo` es `persona` o `empresa`; `activo` es `true` o `false`.

Elemento de la lista:

```json
{
  "id": 7, "folio": "CLI-000007", "tipo": "persona", "rut": "12345678-5",
  "nombre": "Nombre Apellido", "email": "persona@example.com",
  "telefono": "+56 9 0000 0000", "activo": true,
  "created_at": "2026-10-07T12:00:00-03:00"
}
```

Ficha. Exactamente uno de `persona` o `empresa` viene con datos; el otro es
`null`. `representantes` solo tiene filas para empresas y es de solo lectura.

```json
{
  "id": 7, "folio": "CLI-000007", "tipo": "empresa", "activo": true,
  "created_at": "…", "updated_at": "…",
  "persona": null,
  "empresa": {
    "rut": "76543210-3", "razon_social": "Empresa SpA", "nombre_fantasia": "",
    "giro": "", "email": "", "telefono": ""
  },
  "representantes": [
    {"id": 1, "rut": "12345678-5", "nombre": "Nombre Apellido",
     "vigente_desde": "2026-01-01", "vigente_hasta": null, "activo": true}
  ]
}
```

Para crear se envía `tipo` y el objeto de ese tipo, con los campos de la ficha
(`persona`: `rut`, `nombres`, `apellido_paterno`, `apellido_materno`, `email`,
`telefono`). Para editar se envían solo los campos que cambian, y `tipo` no
puede cambiar.

- El RUT se acepta con o sin puntos y se guarda normalizado (`12345678-K`).
- Un RUT que ya es cliente responde `400` en `persona.rut` o `empresa.rut`
  (HU-52).
- Si el RUT pertenece a una persona registrada que aún no es cliente (por
  ejemplo, un representante legal), se reutiliza ese registro.
- El folio (`CLI-` y seis dígitos) se asigna al crear. Su formato es una
  suposición pendiente de validar con Easy Office.

Los campos definitivos de la ficha (MD-01) siguen pendientes. Mientras tanto,
`seed_demo_clientes` carga datos ficticios.

### Ventas y pago en línea (HU-38, HU-39, HU-40, HU-57)

Una **venta** guarda lo que el cliente compra, con el precio de lista copiado al
momento de la compra (RN-08). Cada intento de cobro es una **orden de pago**
(RN-28); el proveedor confirma la transacción como un **pago**, y cada webhook
recibido queda en un registro de **eventos** que solo admite inserciones.

Portal (solo cuentas de cliente, y solo sus propios registros; `404` para los
de otro cliente):

| Método y ruta | Respuesta |
|---|---|
| `GET /api/portal/servicios/` | Servicios activos (público), con `precio_confirmado` |
| `GET /api/portal/medios-pago/` | Medios de pago habilitados (público): `codigo`, `nombre`, `descripcion` y `checkout` (`{"tipo": "modal" \| "redireccion", "script_url"}`) |
| `POST /api/portal/ventas/` | Cuerpo `{"items": [{"servicio": "<código>", "cantidad": 1}]}`. `201` con la venta |
| `GET /api/portal/ventas/`, `GET /api/portal/ventas/{id}/` | Ventas del cliente, con su última orden |
| `POST /api/portal/ventas/{id}/pagar/` | Cuerpo `{"proveedor": "klap" \| "flow"}` (sin él, el primero habilitado). `202` con la orden; `400` si el medio no está habilitado; `409` si la venta no está pendiente de pago |
| `GET /api/portal/ordenes/{id}/` | Estado de la orden, `proveedor`, `id_externo`, `checkout`, `checkout_script_url` y `redirect_url` |

**Medios de pago.** `PAYMENT_PROVIDERS` lista los proveedores entre los que
elige el cliente, en orden (`klap`, `flow`; `simulated` solo para pruebas). Cada
orden guarda su proveedor. Si el cliente cambia de medio, la orden abierta del
otro proveedor queda `cancelada`; un pago que aun así llegue se registra igual.
Easy Office no ha elegido proveedor: ambos son una suposición pendiente de
validar.

Al pagar se crea la orden en estado `creando` y una tarea de Celery la crea en
el proveedor. El portal consulta `GET /api/portal/ordenes/{id}/` hasta que la
orden queda `pendiente` con `id_externo`, y abre el pago: el modal de Klap, o
una redirección a la página de Flow (`redirect_url`). Si una orden sigue
`pendiente` más de 10 segundos, la misma consulta pide su estado al proveedor
(RF-23), por si una notificación no llegó.

**Vuelta al portal.** Ambos proveedores devuelven el navegador a
`/api/pagos/retorno/{orden}/` (Flow lo hace con un POST, que el portal no puede
recibir). Ese endpoint no cambia nada: pide una consulta del estado y redirige
con `303` a `PORTAL_BASE_URL/pagos/{orden}/resultado`, o a `/cancelado` si
llega con `?cancelado=1`.

Notificaciones de Flow: `POST /api/pagos/webhooks/flow/confirmacion/`, sin
sesión. Flow solo envía un `token`, sin firma; el endpoint responde `200` al
tiro y una tarea de Celery consulta `payment/getStatus` con ese token (firmado
con la secret key), que es lo que autentica el aviso, y aplica el resultado. Un
token que Flow no reconoce queda registrado como `firma_invalida`.

Webhooks de Klap: `POST /api/pagos/webhooks/klap/{validacion|confirmacion|rechazo}/`,
sin sesión.
- En confirmación y rechazo se verifica la cabecera `Apikey`
  (`sha256(reference_id + order_id + api key)`); si no coincide, `401`.
- La validación llega mientras Klap crea la orden, firmada con un `order_id`
  que aún no conocemos, así que no se puede verificar. No cambia nada: responde
  `200` solo si la referencia es de una orden abierta y el monto coincide, y
  `400` en otro caso (Klap no crea la orden).
- Un webhook repetido no se vuelve a procesar y recibe la misma respuesta que
  la primera vez.
- Una orden ya pagada no retrocede por un rechazo tardío.
- Si el monto de una confirmación no coincide con el de la orden, la orden
  queda en `error` en vez de marcar la venta como pagada.
- Si Klap reversa un cobro antes de que lo registremos (consulta con estado
  `refund`), la orden queda `rechazada`.
- El código de transacción (`mc_code`) no es único: el sandbox de Klap repite
  el mismo en todos los pagos.

Backoffice: `GET /api/ventas/?buscar=&estado=&page=` y `GET /api/ventas/{id}/`,
con `ventas.view_venta` (Administrador y Ejecutivo). El detalle trae ítems,
órdenes y pagos. Las ventas no se editan por la API.

Los precios de `Servicio` se editan en el panel de administración; los cargados
por la migración son valores de ejemplo, con `precio_confirmado` en falso. No
hay endpoint de reembolso: Easy Office aún no define cuándo se devuelve un pago.

### Trámite de bodega (PLT-02)

Segundo caso real antes del motor configurable. Se vende por plan, en el portal
y en el backoffice: anual (12 meses), semestral (6) y trimestral (3), cada uno a
$59.990 con la firma electrónica avanzada incluida. Es un valor provisorio,
el precio anual del sitio web de Easy Office `[SUPUESTO – VALIDAR CON EASY
OFFICE]` (TA-15). Los planes y el precio de lista se editan en el panel de
administración, sin desplegar.

El contrato siempre lleva dos servicios: el domicilio tributario en una
sucursal, que encabeza el folio, y la bodega. El plan cobra la bodega y paga
también el domicilio, que el contrato imprime en $0 con el ciclo del plan. La
duración y el vencimiento salen del plan, y la autorización los imprime en
palabras ("TRES (3) MESES").

- **En el portal** (solo empresas): el cliente elige la sucursal, la bodega, el
  plan y la fecha; revisa el borrador, lo confirma, paga la venta del plan y
  el ejecutivo sube el PDF firmado.
- **En el backoffice**: un ejecutivo elige los mismos planes para el cliente.
  `[SUPUESTO – VALIDAR CON EASY OFFICE]` Ese trámite no se paga en línea: el
  ejecutivo registra que el cliente confirmó el borrador, sube el PDF firmado
  y el contrato entra en vigencia. El cliente lo ve en el portal, sin
  acciones.

| Método y ruta | Permiso | Uso |
|---|---|---|
| `GET /api/tramites/tipos/?canal=backoffice` | `tramites.view_tramite` | Tipos de trámite que se inician en el backoffice |
| `GET /api/tramites/formulario/?tipo=bodega&cliente={id}` | `tramites.iniciar_tramite` | Planes, sucursales y bodegas disponibles, servicios y datos precargados; `problemas` dice qué falta |
| `POST /api/tramites/` | `tramites.iniciar_tramite` | `{tipo, cliente, empresa, representante, personeria, email_aviso, movil_aviso, fecha_inicio, plan, sucursal, bodega}` → `201` |
| `PUT /api/tramites/{id}/` | `tramites.gestionar_tramite` | Edita la solicitud antes de la firma; el documento se genera de nuevo |
| `POST /api/tramites/{id}/confirmar/` | `tramites.gestionar_tramite` | El cliente confirmó el borrador (RN-13) |
| `POST /api/tramites/{id}/fecha-inicio/` | `tramites.gestionar_tramite` | Nueva fecha de inicio cuando la elegida ya pasó |
| `GET /api/portal/tramites/formulario/?tipo=bodega` | Cliente del portal | Nombre del trámite, planes, sucursales y bodegas, datos precargados y, si no está disponible, un motivo para el cliente |
| `POST /api/portal/tramites/` | Cliente del portal | `{tipo, empresa, representante, personeria, email_aviso, movil_aviso, fecha_inicio, plan, sucursal, bodega}` → `201` |
| `PUT /api/portal/tramites/{id}/` | Cliente del portal | Edita la solicitud antes del pago |

`iniciar_tramite` lo tienen el Administrador y el Ejecutivo. Una bodega se
ofrece solo si tiene dirección, comuna, región, rol y un autorizante vigente
persona natural con nacionalidad, estado civil, profesión y ambos lados de la
cédula en JPG o PNG. Las diferencias con el domicilio, y lo que sugieren para
el motor configurable, están en
[`docs/variation-points.md`](docs/variation-points.md).

### Panel operativo (RF-14, HU-41)

Ambas rutas requieren `core.view_dashboard`, que tienen el Administrador y el
Ejecutivo (el Ejecutivo lo recibe en `core/0003_dashboard_ejecutivo`,
ACTA-002 D2-06). Un cliente del portal o un usuario anónimo recibe `403`. Los
dos parámetros son obligatorios, y `desde` no puede ser posterior a `hasta` (si
no, `400`).

| Método y ruta | Respuesta |
|---|---|
| `GET /api/panel/indicadores/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Indicadores en JSON |
| `GET /api/panel/indicadores/exportar/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Archivo `.xlsx` (`panel-operativo_<desde>_<hasta>.xlsx`) con las hojas Resumen, Ventas por servicio y Ventas por ejecutivo |

```json
{
  "periodo": {"desde": "2026-09-01", "hasta": "2026-09-30"},
  "fecha_referencia": "2026-09-30",
  "clientes": {"total": 0, "nuevos": 0},
  "servicios": {"activos": 0, "por_vencer": 0, "vencidos": 0, "dias_aviso": 30},
  "ventas": {
    "moneda": "CLP",
    "total": 0,
    "por_servicio": [{"servicio": "Domicilio tributario", "monto": 0, "cantidad": 0}],
    "por_ejecutivo": [{"ejecutivo": "En línea (sin ejecutivo)", "monto": 0, "cantidad": 0}]
  },
  "tramites_pendientes": 0,
  "tramites_pendientes_por_motivo": [{"motivo": "firma", "nombre": "Firma", "cantidad": 0}],
  "documentos_pendientes_firma": 0,
  "datos_de_ejemplo": []
}
```

Todas las cifras son reales (ya no existe `panel/ejemplo.py`); cada aplicación
entrega las suyas por sus servicios. Claves nuevas: `fecha_referencia` y
`tramites_pendientes_por_motivo` (`[{motivo, nombre, cantidad}]`).
`tramites_pendientes` es la suma del desglose.

- **Período** (`desde` … `hasta`, ambos inclusive en hora de Chile): `clientes`
  (`total` hasta `hasta`, `nuevos` en el período) y `ventas`.
- **A una fecha** (`fecha_referencia`, que es `hasta` o hoy si `hasta` es
  posterior): `servicios`, `tramites_pendientes` y `documentos_pendientes_firma`.
- `servicios` cuenta **contratos** (un folio, un vencimiento), no sus líneas.
  `activos` son los vigentes a la fecha (`contratos.services.contratos_vigentes`);
  `por_vencer`, los que vencen dentro de `dias_aviso` días (ambos extremos
  incluidos) y no tienen renovación; `vencidos`, los vencidos sin renovación
  automática que nadie terminó ni renovó. Borradores, terminados y anulados no
  cuentan. Un contrato con renovación automática sigue activo tras su primer
  término y no vuelve a aparecer por vencer (RN-10, TA-17 abiertos).
- `ventas` suma las ventas **pagadas** en el período por `pagada_en`;
  reembolsadas y anuladas no cuentan. `por_servicio` agrupa por servicio del
  catálogo (`cantidad` = ventas que lo incluyen). `por_ejecutivo` usa el
  ejecutivo responsable del contrato del trámite de la venta, si no quien abrió
  el trámite (si es personal); el resto va a "En línea (sin ejecutivo)". Los
  contratos registrados en el backoffice sin pago en línea no tienen venta y no
  aparecen.
- `tramites_pendientes` y su desglose por motivo (RF-47) se leen del historial
  de estados (`EventoTramite`), así que un período pasado muestra lo que estaba
  pendiente entonces.
- `documentos_pendientes_firma` cuenta la última versión de cada trámite que
  espera firma a la fecha.
- `datos_de_ejemplo` queda vacío y se elimina en la próxima versión.

El Excel tiene las mismas hojas y columnas y no rotula nada como "Valor de
ejemplo". La columna Detalle dice "Al dd-mm-aaaa" en las cifras a una fecha y
"Pagadas en línea, en el período" en las ventas.

`dias_aviso` es la ventana de "por vencer"; 30 días es una suposición pendiente
de validar (HU-42 propone 60, 30, 15 y 7).

### Registro de auditoría (HU-30, HU-31 · RF-15, RF-16, RF-17, RS-04)

**Qué se registra.** Disparadores de PostgreSQL (AD-08) escriben en
`core_registroauditoria` cada inserción, modificación y eliminación de las
tablas auditadas, también las hechas con `queryset.update()`, en lote, desde el
panel de administración o con SQL directo. Una inserción guarda la fila nueva;
una eliminación, la anterior; una modificación, solo los campos que cambiaron,
antes y después (una modificación que no cambia nada no deja registro). La
lista de tablas auditadas, las excluidas y los campos que nunca se guardan
viven en un solo lugar, `crm_easyoffice/core/auditoria/registro.py`: nunca se
guardan `last_login`, `Pago.respuesta`, `OrdenPago.redirect_url` ni
`Documento.datos_snapshot`; la contraseña aparece como `***`, nunca su hash; los
archivos, solo por su nombre. Los roles y permisos se registran por nombre
(`{"rol": "Ejecutivo"}`). Además, `core.auditoria.registrar_evento` registra lo
que no cambia filas: ingreso, cierre de sesión e intento fallido (personal,
portal, panel de administración), descarga de un documento del trámite y acceso
a la cédula del autorizante.

**Quién, desde dónde y por qué canal.** Cada fila lleva `usuario`,
`direccion_ip` y `origen` (`api`, `portal`, `admin` o `sistema`). Las tareas de
Celery, los webhooks de pago y los comandos quedan como `sistema`, sin usuario.
Los disparadores leen el contexto de `set_config(..., true)` (equivalente a
`SET LOCAL`), que se fija antes de la primera escritura de cada transacción y
termina con ella: nunca pasa a la petición siguiente. Una escritura fuera de
transacción queda sin usuario, nunca con el de otro.

**Protección.** La base de datos rechaza `UPDATE`, `DELETE` y `TRUNCATE` sobre
el registro, también para el usuario de la aplicación; el modelo rechaza
`save()` sobre una fila existente y `delete()`, y el panel de administración es
de solo lectura incluso para un superusuario. El dueño de la base de datos
puede, en todo caso, eliminar los disparadores: separar ese rol del de la
aplicación es una tarea del despliegue (TA-09). `manage.py flush` falla; para
reiniciar la base local, `docker compose down -v`.

**Consulta.** Solo con `core.consultar_auditoria` (Administrador). El Ejecutivo,
un cliente del portal y un usuario anónimo reciben `403`. No hay método de
escritura.

| Método y ruta | Respuesta |
|---|---|
| `GET /api/auditoria/` | Registro paginado (25), del más reciente al más antiguo. Filtros: `entidad` (por ejemplo `clientes.cliente`) y `registro_id`, `usuario`, `accion`, `origen`, `desde` y `hasta` (`AAAA-MM-DD`, inclusive, hora de Chile) |
| `GET /api/auditoria/historial/?entidad=&registro_id=` | Historial de un registro junto con los que le pertenecen: el de un cliente incluye su persona o empresa, sus representantes y su cuenta del portal; el de un trámite, su contrato y sus líneas, su venta, órdenes y pagos, y sus documentos y firmantes. Incluye las filas ya eliminadas |

Cada fila trae `fecha_hora`, `usuario` y `usuario_nombre` (`null` cuando actuó
el sistema), `origen`, `accion` (`crear`, `modificar`, `eliminar`,
`inicio_sesion`, `cierre_sesion`, `inicio_sesion_fallido`,
`descarga_documento`, `acceso_documento_identidad`), `entidad` y
`entidad_nombre`, `registro_id` y `registro_nombre`, `valor_anterior`,
`valor_nuevo` y `direccion_ip`.

Suposiciones pendientes de validar con Easy Office: que los intentos fallidos
se conserven con el correo escrito; el plazo de conservación del registro (hoy
indefinido); que el historial de un cliente no incluya sus contratos ni
trámites; y qué encabezado de proxy da la IP del cliente en producción.

### Pago con Flow en local

Flow no publica credenciales compartidas: cada desarrollador crea una cuenta en
[sandbox.flow.cl](https://sandbox.flow.cl) y copia `apiKey` y `secretKey` desde
"Mis datos".

1. En `.envs/.local/.django` define `PAYMENT_PROVIDERS=klap,flow`,
   `FLOW_API_KEY` y `FLOW_SECRET_KEY`. Usa el mismo túnel que Klap
   (`PAYMENT_TUNNEL_METRICS_URL`); no requiere configuración adicional.
2. Reinicia `django` y `celeryworker`.
3. Elige Flow en "Confirma y paga". Tarjeta de prueba en
   [Credenciales de prueba](https://developers.flow.cl/docs/credentials); si el
   banco simulado lo pide, RUT `11111111-1` y clave `123`.

`FLOW_PAYMENT_METHOD` (por defecto `9`) elige el medio dentro de Flow: `9`
muestra todos los que tenga habilitados la cuenta.

### Pago con Klap en local

Klap exige URLs de webhook públicas en HTTPS y llama al webhook de validación
mientras crea la orden. Por eso `docker-compose.local.yml` levanta junto al
resto el servicio `tunnel`: un túnel rápido de Cloudflare (`cloudflared`, sin
cuenta) hacia Django. Su URL (`https://<palabras>.trycloudflare.com`) cambia en
cada arranque, y el backend la lee de `http://tunnel:2000/quicktunnel` cada vez
que crea una orden, así que no hay que copiarla a ninguna parte. En producción
no hace falta: el backend tiene su propio dominio público.

1. En `.envs/.local/.django` define:
   - `PAYMENT_PROVIDER=klap`;
   - `KLAP_API_KEY` con la API key de prueba publicada en
     [Datos de prueba](https://developers.klap.cl/datos-de-prueba);
   - `PAYMENT_TUNNEL_METRICS_URL=http://tunnel:2000/quicktunnel`;
   - `PORTAL_BASE_URL` con la dirección donde abres el portal (por ejemplo
     `http://localhost:5173`), porque Klap vuelve ahí después de pagar
     (`/pagos/{orden}/resultado`, o `/cancelado` si el cliente cancela).
2. `docker compose -f docker-compose.local.yml up -d`.
3. Paga desde el portal con las tarjetas de prueba de esa misma página.

Mientras el proyecto corre, la API local es alcanzable desde internet en esa URL
aleatoria. Usa solo datos ficticios en local.

**El túnel se renueva solo.** Cloudflare descarta los túneles rápidos tras uno o
dos días, y `cloudflared` seguiría reintentando el caído para siempre. Por eso el
servicio `tunnel` corre con un pequeño script (`compose/local/tunnel/`) que
revisa la conexión cada 10 segundos y, si pasan alrededor de 80 sin conexión, se
detiene: `restart: unless-stopped` lo levanta con un túnel nuevo, y el backend lee
su URL nueva en la siguiente orden. No hace falta ningún acceso especial a
Docker. Una orden creada justo mientras el túnel está caído termina en `error` y
se reintenta pagando de nuevo.

Si el pago sigue fallando con "No pudimos iniciar el pago" y el detalle de la
orden habla del túnel, fuerza uno nuevo:

```bash
docker compose -f docker-compose.local.yml restart tunnel
```

Si `PAYMENT_WEBHOOK_BASE_URL` tiene valor, se usa esa URL en vez del túnel (su
host va en `DJANGO_EXTRA_ALLOWED_HOSTS`). Con `PAYMENT_PROVIDER=simulated` (el
valor por defecto) no se contacta a ningún proveedor; sirve para las pruebas
automáticas.

---

## Estado actual

Sprint 2 (6 – 17 de octubre de 2026). Ya están:

- el modelo de clientes e inmuebles;
- la autenticación del personal interno y los roles Administrador y Ejecutivo;
- el registro y el ingreso de clientes al portal (HU-03);
- las ventas y el pago en línea con Klap Checkout Flex en su ambiente de
  pruebas (HU-38, HU-39, HU-40, HU-57);
- la API de clientes (registro, edición, ficha, búsqueda y folio);
- los indicadores del panel operativo, exportables a Excel;
- el domicilio tributario de punta a punta (PLT-01) y el contrato de bodega
  (PLT-02), iniciado desde el backoffice;
- el registro de auditoría con disparadores de base de datos, protegido contra
  modificación, y su consulta para el Administrador (HU-30, HU-31).

Siguen pendientes los campos definitivos del cliente, los estados de los
trámites, las plantillas reales, el proveedor de firma, la confirmación del
proveedor de pago y de los precios, y la política de reembolsos.

---

## Protección de datos

El repositorio es público. Los secretos viven en variables de entorno. El
archivo Excel que entregará la empresa contiene datos reales de clientes y se
anonimiza antes de entrar a cualquier ambiente. La Ley 21.719 sobre protección
de datos personales entra en vigencia el 1 de diciembre de 2026, y la contraparte
planteó la protección de datos como una de las razones de este proyecto.
