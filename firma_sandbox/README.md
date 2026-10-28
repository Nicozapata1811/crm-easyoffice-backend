# PSC de pruebas · API de firma electrónica avanzada

> **Sin validez legal.** Este servicio es un
> prestador de servicios de certificación **ficticio**, hecho para desarrollo,
> pruebas y demostraciones de CRM Easy Office. Una firma electrónica avanzada
> solo tiene validez legal si la certifica un prestador acreditado (Ley
> 19.799). Nada de lo que firma este servicio la tiene. Nunca se despliega en
> producción: se niega a iniciar fuera de desarrollo, y la configuración de
> producción del CRM rechaza su dirección.

No imita a ningún proveedor real: su nombre, su API y sus formatos son
propios.

## Qué hace

1. **Tiene su propia infraestructura de pruebas**, generada en la máquina que
   lo ejecuta y nunca commiteada:
   - una CA raíz y una CA emisora, ambas «de PRUEBAS»;
   - una autoridad de sellado de tiempo (RFC 3161);
   - una CRL por CA y un respondedor OCSP.
2. **Verifica la identidad** de cada firmante: RUT y número de serie de la
   cédula, contra un registro civil ficticio.
3. **Emite un certificado de un solo uso por firmante**, con su nombre y su
   RUT. La clave privada la genera y la guarda el servicio, cifrada en reposo.
   Se usa una sola vez, después de un código enviado al correo del firmante, y
   luego se borra.
4. **Firma en PAdES** con el certificado del firmante, en orden, una revisión
   incremental por firma:
   - cada firma es **PAdES B-LT**: sello de tiempo, y la cadena, las CRL y la
     respuesta OCSP embebidas;
   - la última firma agrega un sello de tiempo de documento, lo que da
     **PAdES B-LTA**;
   - el PDF final valida sin conexión contra la raíz de pruebas, y las
     firmas anteriores siguen validando después de las siguientes.
5. **Agrega una hoja de firmas** con un sello visible por firmante: nombre,
   RUT, fecha, «Firma electrónica avanzada» y un código de verificación.
6. **Avisa por webhooks firmados**, con reintentos.

## Levantarlo en local

```bash
cp .envs.example/.local/.firma .envs/.local/.firma
```

Reemplaza cada `CHANGEME` de ese archivo por un valor propio, por ejemplo con
`python -c "import secrets; print(secrets.token_urlsafe(32))"`. Luego:

```bash
docker compose -f docker-compose.local.yml up -d
```

Al iniciar, el servicio:

- aplica sus migraciones;
- genera la PKI de pruebas si falta (`firma_sandbox/.pki/`, ignorada por git);
- registra al CRM como cliente de la API, con las credenciales de `.firma`;
- carga el registro civil ficticio (`fixtures/identidades_demo.json`).

| Qué | Dónde |
|---|---|
| Páginas de firma, descarga de la PKI | `http://localhost:8100` (solo desde esta máquina) |
| API | `http://firma-sandbox:8100/api/v1/`, solo dentro de la red de compose |
| Correos (enlaces y códigos) | Mailpit, `http://localhost:8025` |

Comandos (`docker compose -f docker-compose.local.yml run --rm firma-sandbox python manage.py …`):

| Comando | Para qué |
|---|---|
| `generar_pki [--si-falta]` | Crea la CA raíz, la emisora y la TSA de pruebas |
| `rotar_pki [--raiz]` | Reemplaza la emisora y la TSA (y la raíz con `--raiz`); reinicia el servicio después |
| `crear_cliente_api [--desde-env]` | Da de alta un cliente de la API; sin `--desde-env` muestra su clave una sola vez |
| `seed_identidades_demo` | Carga el registro civil ficticio |
| `registrar_identidad --rut --serie --nombre` | Agrega una persona ficticia al registro. Nunca datos reales |
| `despachar [--una-vez]` | Entrega webhooks pendientes y vence solicitudes (lo corre `firma-sandbox-worker`) |

Pruebas del servicio: `just firma-pytest`.

## Autenticación

Cada sistema cliente tiene una API key, que se envía en cada llamada:

```http
Authorization: Bearer <api key>
```

El servicio guarda solo su SHA-256. Una clave inválida responde `401`.

## Endpoints

Base: `http://firma-sandbox:8100/api/v1/`. El esquema OpenAPI está en
`GET /api/v1/schema`.

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `solicitudes` | Crea una solicitud de firma |
| `GET` | `solicitudes/{id}` | Estado de la solicitud y de cada firmante |
| `GET` | `solicitudes/{id}/documento` | PDF firmado; `409` mientras no esté completada |
| `POST` | `solicitudes/{id}/cancelar` | Cancela una solicitud abierta y revoca sus certificados |
| `POST` | `solicitudes/{id}/firmantes/{firmante}/reenviar` | Envía un enlace nuevo; el anterior deja de servir |
| `POST` | `validaciones` | Valida un PDF firmado contra la raíz de pruebas |

### Crear una solicitud

`multipart/form-data` con dos partes:

- `documento`: el PDF, de hasta 10 MB;
- `datos`: un JSON como este.

```json
{
  "nombre_documento": "Contrato LF-0007-2026",
  "referencia_externa": "42",
  "url_notificacion": "http://django:8000/api/firma/webhooks/http/",
  "expira_en": "2026-11-02T23:59:59-03:00",
  "firmantes": [
    {"orden": 1, "nombre": "Representante Demo Uno", "rut": "90000301-3",
     "email": "uno@example.test", "rol": "cliente_representante", "referencia": "101"},
    {"orden": 2, "nombre": "Rodrigo Andrés Ejemplo Ficticio", "rut": "90000001-4",
     "email": "dos@example.test", "rol": "representante_emisor", "referencia": "102"}
  ]
}
```

- El orden va de 1 en adelante, sin saltos. Cada firmante firma solo cuando
  firmó el anterior.
- `expira_en` es opcional: 7 días por defecto, 30 como máximo.
- `referencia` es el id del firmante en el sistema cliente; el servicio lo
  devuelve en cada estado.

Responde `201` con el estado de la solicitud y `url_firma`, el enlace del
primer firmante. Cada firmante recibe su enlace por correo cuando le toca.

### Estado

```json
{
  "id": "8f0e2c1a-…",
  "estado": "pendiente",
  "ambiente": "pruebas",
  "nombre_documento": "Contrato LF-0007-2026",
  "referencia_externa": "42",
  "creada_en": "…", "expira_en": "…", "terminada_en": null,
  "sha256_original": "…",
  "sha256_firmado": null,
  "firmantes": [
    {"id": "…", "orden": 1, "nombre": "…", "rol": "…", "referencia": "101",
     "estado": "firmado", "firmado_en": "…", "rechazado_en": null, "motivo_rechazo": ""}
  ]
}
```

- **Estados de la solicitud:** `pendiente`, `completada`, `rechazada`,
  `expirada`, `cancelada`.
- **Estados de un firmante:** `pendiente`, `firmado`, `rechazado`.
- `ambiente` es siempre `pruebas`.
- `sha256_original` es el hash del PDF recibido. El firmado lo contiene byte a
  byte como prefijo, porque cada firma es una actualización incremental.
- El estado no expone el RUT ni el correo de los firmantes.

### Validar

`POST validaciones` (multipart, `documento`). La respuesta trae:

- `valido`;
- `documento_sin_cambios`;
- `sello_documento`;
- por firma: firmante, RUT, hora del sello, si está intacta, si su cadena
  llega a la raíz de pruebas (`confiable`), y si tiene sello de tiempo y
  revocación embebida.

La validación usa solo lo que trae el PDF, con revocación estricta.

## Webhooks

Cada evento se envía con `POST` a la `url_notificacion` de la solicitud.

| Evento | Cuándo |
|---|---|
| `firmante.firmo` | Un firmante firmó |
| `firmante.rechazo` | Un firmante rechazó, con su motivo; la solicitud queda `rechazada` |
| `solicitud.completada` | Firmaron todos; el PDF firmado está disponible |
| `solicitud.expirada` | Venció sin todas las firmas |

El cuerpo es JSON:

```json
{"id_evento": "uuid", "tipo": "firmante.firmo", "creado_en": "…", "solicitud": { /* el estado */ }}
```

Cada envío trae tres encabezados:

| Encabezado | Contenido |
|---|---|
| `X-PSC-Evento` | El id del evento, igual en cada reintento: con él se descartan duplicados |
| `X-PSC-Timestamp` | Segundos Unix del intento |
| `X-PSC-Firma` | `v1=` y el HMAC-SHA256, en hexadecimal, de `"{timestamp}.{cuerpo}"` con el secreto de webhook del cliente |

Para verificar un webhook:

1. calcula el HMAC sobre los bytes exactos recibidos;
2. compáralo en tiempo constante;
3. rechaza un timestamp con más de 5 minutos de diferencia.

```python
import hashlib, hmac, time


def es_valido(secreto: str, timestamp: str, cuerpo: bytes, firma: str) -> bool:
    esperada = (
        "v1="
        + hmac.new(
            secreto.encode(), f"{timestamp}.".encode() + cuerpo, hashlib.sha256
        ).hexdigest()
    )
    return (
        hmac.compare_digest(esperada, firma)
        and abs(time.time() - int(timestamp)) <= 300
    )
```

- **Respuesta:** contesta `2xx` para confirmar la entrega.
- **Reintentos:** cualquier otra respuesta, o ningún contacto, se reintenta a
  los 30 s, 2 min, 10 min, 1 h y luego cada 6 h, hasta 8 intentos.
- **Orden:** los eventos pueden llegar repetidos o desordenados. Ante la duda,
  consulta `GET solicitudes/{id}`.

## Páginas de firma

El firmante abre su enlace (`/firmar/<token>/`). La página muestra el PDF y lo
lleva por estos pasos:

1. **Verifica su identidad** con su RUT y el número de serie de su cédula. Tiene
   3 intentos; luego necesita un enlace nuevo.
2. **Recibe un código** de 6 dígitos por correo. Vence en 10 minutos y admite 5
   intentos.
3. **Consiente y firma**, o rechaza con un motivo.

`/verificar/<código>/` muestra la firma que corresponde al código impreso en
un sello.

En el registro ficticio, el número de serie de cada persona demo es «A»
seguido del número del RUT: por ejemplo, `A90000301` para `90000301-3`.

### Personas de demostración

Todas son ficticias y están en `fixtures/identidades_demo.json`.

| Quién firma | Nombre | RUT | N° de documento (serie) |
|---|---|---|---|
| Representante de Easy Office | Rodrigo Andrés Ejemplo Ficticio | `90000001-4` | `A90000001` |
| Autorizante, sucursal La Florida | María José Propietaria Ejemplo 1 | `90000101-0` | `A90000101` |
| Autorizante, sucursal Valparaíso | María José Propietaria Ejemplo 2 | `90000102-9` | `A90000102` |
| Autorizante, sucursal San Antonio | María José Propietaria Ejemplo 3 | `90000103-7` | `A90000103` |
| Dueña de la Bodega de Ejemplo Norte | Carolina Andrea Bodeguera Ejemplo | `90000201-7` | `A90000201` |
| Dueño de la Bodega de Ejemplo Costa | Pedro Pablo Almacén Ficticio | `90000202-5` | `A90000202` |
| Representante del cliente | Representante Demo 1 (lo usa la prueba e2e) | `90000301-3` | `A90000301` |
| Representante del cliente | Representante Demo 2 | `90000302-1` | `A90000302` |
| Representante del cliente | Representante Demo 3 | `90000303-K` | `A90000303` |
| Representante del cliente | Representante Demo 4 | `90000304-8` | `A90000304` |
| Representante del cliente | Representante Demo 5 | `90000305-6` | `A90000305` |

Cada RUT de representante del cliente sirve para una sola empresa.

## PKI pública

| Ruta | Contenido |
|---|---|
| `GET /pki/raiz.crt`, `/pki/emisora.crt`, `/pki/tsa.crt` | Certificados (DER) |
| `GET /pki/raiz.crl`, `/pki/emisora.crl` | Listas de revocación |
| `POST /pki/ocsp` | OCSP (RFC 6960) |
| `POST /pki/tsa` | Sellado de tiempo (RFC 3161) |

Para validar fuera del servicio, confía en `raiz.crt`, por ejemplo con pyHanko:

```bash
pyhanko sign validate --trust raiz.crt --pretty-print firmado.pdf
```
