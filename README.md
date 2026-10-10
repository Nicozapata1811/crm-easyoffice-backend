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

Ejecutar las pruebas:

```bash
docker compose -f docker-compose.local.yml run --rm django pytest
```

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
que expira la sesión.

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
aún no están disponibles y el proveedor de pago no ha sido definido, por lo que
existen implementaciones simuladas que satisfacen el mismo contrato. Ningún SDK
de proveedor se importa fuera de esa aplicación.

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
| Ejecutivo (RN-32) | Crear, modificar y consultar clientes; consultar inmuebles. **Sin permisos de eliminación** (RF-04) |

Si el Ejecutivo puede ver el panel operativo no está definido; por ahora no
puede. Cada aplicación nueva asigna sus permisos a estos roles en su propia
migración de datos.

El registro de cada ingreso en auditoría (criterio de HU-01) queda pendiente del
módulo de auditoría (RF-15, HU-30).

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
  "rol": "Administrador",
  "permisos": ["clientes.add_cliente", "core.view_dashboard"]
}
```

`rol` es `null` si el usuario no tiene rol. El frontend decide qué mostrar según
`permisos`, no según el nombre del rol.

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

### Panel operativo (RF-14, HU-41)

Ambas rutas requieren `core.view_dashboard`. Los dos parámetros son
obligatorios, y `desde` no puede ser posterior a `hasta` (si no, `400`).

| Método y ruta | Respuesta |
|---|---|
| `GET /api/panel/indicadores/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Indicadores en JSON |
| `GET /api/panel/indicadores/exportar/?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Archivo `.xlsx` (`panel-operativo_<desde>_<hasta>.xlsx`) con las hojas Resumen, Ventas por servicio y Ventas por ejecutivo |

```json
{
  "periodo": {"desde": "2026-09-01", "hasta": "2026-09-30"},
  "clientes": {"total": 0, "nuevos": 0},
  "servicios": {"activos": 0, "por_vencer": 0, "vencidos": 0, "dias_aviso": 30},
  "ventas": {
    "moneda": "CLP",
    "total": 0,
    "por_servicio": [{"servicio": "Domicilio tributario", "monto": 0, "cantidad": 0}],
    "por_ejecutivo": [{"ejecutivo": "Nombre", "monto": 0, "cantidad": 0}]
  },
  "tramites_pendientes": 0,
  "documentos_pendientes_firma": 0,
  "datos_de_ejemplo": ["servicios", "ventas", "tramites_pendientes", "documentos_pendientes_firma"]
}
```

- `clientes` es real: `total` cuenta los clientes registrados hasta `hasta`, y
  `nuevos` los registrados en el período.
- Las claves de `datos_de_ejemplo` traen valores de ejemplo hasta que existan los
  servicios contratados y los pagos (HU-10, HU-48). El Excel los rotula igual.

`dias_aviso` es la ventana de "por vencer"; 30 días es una suposición pendiente
de validar (HU-42 propone 60, 30, 15 y 7).

---

## Estado actual

Sprint 2 (6 – 17 de octubre de 2026). Ya están:

- el modelo de clientes e inmuebles;
- la autenticación del personal interno y los roles Administrador y Ejecutivo;
- la API de clientes (registro, edición, ficha, búsqueda y folio);
- los indicadores del panel operativo, exportables a Excel.

Siguen pendientes los campos definitivos del cliente, los estados de los
trámites, las plantillas reales, el proveedor de firma y el de pago.

---

## Protección de datos

El repositorio es público. Los secretos viven en variables de entorno. El
archivo Excel que entregará la empresa contiene datos reales de clientes y se
anonimiza antes de entrar a cualquier ambiente. La Ley 21.719 sobre protección
de datos personales entra en vigencia el 1 de diciembre de 2026, y la contraparte
planteó la protección de datos como una de las razones de este proyecto.
