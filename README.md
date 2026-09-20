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
docker compose -f docker-compose.local.yml build
docker compose -f docker-compose.local.yml up -d
```

Esto levanta siete servicios: `django`, `postgres`, `redis`, `celeryworker`,
`celerybeat`, `flower` y `mailpit`. Las migraciones se aplican al iniciar.

Crear un superusuario:

```bash
docker compose -f docker-compose.local.yml run --rm django python manage.py createsuperuser
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

## Protección de datos

El repositorio es público. Los secretos viven en variables de entorno. El
archivo Excel que entregará la empresa contiene datos reales de clientes y se
anonimiza antes de entrar a cualquier ambiente. La Ley 21.719 sobre protección
de datos personales entra en vigencia el 1 de diciembre de 2026, y la contraparte
planteó la protección de datos como una de las razones de este proyecto.
