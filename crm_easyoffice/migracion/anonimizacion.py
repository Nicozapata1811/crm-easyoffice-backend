"""Anonymize a throwaway copy of the database before it leaves the machine.

Every value that identifies someone becomes a generated one, and every private
file a placeholder. ``verificar`` then searches every table for the original
values, so a field nobody classified fails the copy instead of reaching the
server. Rows change through ``update`` and ``bulk_update`` because the
append-only models raise in ``save()``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import field
from io import BytesIO
from typing import TYPE_CHECKING
from typing import Any

from django.apps import apps
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.db import connection
from django.db import transaction
from django.utils import timezone
from docx import Document as WordDocument

from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.configuracion.models import ConfigEmpresa
from crm_easyoffice.configuracion.models import CuentaPago
from crm_easyoffice.contratos.models import AlertaVencimiento
from crm_easyoffice.contratos.models import Contrato
from crm_easyoffice.core.validators import compute_rut_check_digit
from crm_easyoffice.core.validators import normalize_rut
from crm_easyoffice.documentos import formato
from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.models import EventoFirma
from crm_easyoffice.documentos.models import Firmante
from crm_easyoffice.documentos.models import SolicitudFirma
from crm_easyoffice.documentos.models import VersionPlantilla
from crm_easyoffice.inmuebles.management.commands.seed_demo_domicilio import tarjeta_png
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.services import CALLE_PENDIENTE
from crm_easyoffice.inmuebles.services import ROL_PENDIENTE
from crm_easyoffice.tramites.formularios import formulario_de
from crm_easyoffice.tramites.models import EventoTramite
from crm_easyoffice.tramites.models import Tramite
from crm_easyoffice.users.models import User
from crm_easyoffice.ventas.models import EventoPago
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Pago

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    from django.db.models import Model

NOMBRE_BD_COPIA = "crm_copia"
TEXTO_FIJO = "Detalle no disponible en la copia de staging."
TEXTO_PLACEHOLDER = "Documento no disponible en la copia de staging"
# Generated values use no word that is also a name ("Calle", "Bodega" and "Giro"
# are surnames), or verificar would match them. RUTs start above the test PSC's
# demo ones (90.000.xxx).
PRIMER_RUT = 91_000_000
LARGO_MINIMO_TEXTO = 3
LARGO_MINIMO_DIGITOS = 7

ANONIMIZADOS = {
    "users.User": {"password", "name", "email"},
    "account.EmailAddress": {"email"},
    "clientes.Persona": {
        "rut",
        "nombres",
        "apellido_paterno",
        "apellido_materno",
        "domicilio",
        "comuna",
        "region",
        "email",
        "telefono",
    },
    "clientes.Empresa": {
        "rut",
        "razon_social",
        "nombre_fantasia",
        "giro",
        "email",
        "telefono",
    },
    "clientes.RepresentanteLegal": {"sitio_o_notaria"},
    "inmuebles.Oficina": {"rol_avaluo", "calle", "numero", "unidad"},
    "inmuebles.Autorizante": {"documento_identidad", "documento_identidad_reverso"},
    "configuracion.ConfigEmpresa": {
        "razon_social",
        "rut",
        "direccion",
        "email_contacto",
        "email_pagos",
        "telefono",
    },
    "configuracion.CuentaPago": {"numero", "titular", "texto_contrato"},
    "tramites.Tramite": {"detalle_pendiente"},
    "tramites.EventoTramite": {"detalle"},
    "documentos.Documento": {
        "archivo_docx",
        "sha256_docx",
        "archivo_pdf",
        "sha256_pdf",
        "datos_snapshot",
        "archivo_firmado",
        "sha256_firmado",
    },
    "documentos.Firmante": {"motivo_rechazo"},
    "documentos.SolicitudFirma": {"detalle_error"},
    "documentos.EventoFirma": {"payload"},
    "ventas.OrdenPago": {"detalle_error"},
    "ventas.Pago": {"ultimos_digitos", "respuesta"},
    "ventas.EventoPago": {"payload"},
    "contratos.Contrato": {"email_aviso", "movil_aviso"},
    # Free text an executive writes; it may name someone.
    "contratos.AlertaVencimiento": {"nota"},
}

# Not identifying, so ``verificar`` skips them: a person's comuna may equal a
# branch's, and a catalogue name may equal an old printed value.
CONSERVADOS = {
    "clientes.Persona": {"nacionalidad", "estado_civil", "profesion"},
    "clientes.Cliente": {"codigo"},
    "inmuebles.Oficina": {
        "tipo",
        "codigo_sucursal",
        "nombre",
        "comuna",
        "region",
        "unidad_sii",
        "municipalidad",
    },
    "configuracion.ConfigEmpresa": {"comuna", "region", "registro_personeria"},
    "configuracion.CuentaPago": {"banco", "tipo_cuenta"},
    "configuracion.Marca": {"nombre"},
    "tramites.TipoTramite": {"codigo", "nombre", "configuracion"},
    "tramites.MotivoPendiente": {"codigo", "nombre", "texto_cliente"},
    "tramites.Tramite": {"folio", "estado", "canal"},
    "tramites.EventoTramite": {
        "estado_anterior",
        "motivo_anterior",
        "estado_nuevo",
        "motivo_nuevo",
    },
    "documentos.PlantillaDocumento": {"codigo", "nombre"},
    "documentos.VersionPlantilla": {"archivo", "sha256", "notas"},
    "documentos.Documento": {"estado"},
    "documentos.Firmante": {"rol", "estado", "id_externo"},
    "documentos.SolicitudFirma": {"proveedor", "id_externo", "estado"},
    "documentos.EventoFirma": {
        "proveedor",
        "id_evento",
        "tipo",
        "clave_dedup",
        "resultado",
    },
    "ventas.CicloPago": {"codigo", "nombre"},
    "ventas.Servicio": {"codigo", "nombre", "descripcion"},
    "ventas.PlanServicio": {"codigo", "nombre"},
    "ventas.Venta": {"folio", "estado"},
    "ventas.ItemVenta": {"nombre"},
    "ventas.OrdenPago": {"proveedor", "id_externo", "estado", "redirect_url"},
    "ventas.Pago": {
        "tipo",
        "id_externo",
        "medio",
        "marca",
        "tipo_tarjeta",
        "billetera",
    },
    "ventas.EventoPago": {"proveedor", "evento", "clave_dedup", "resultado"},
    "contratos.Contrato": {"folio", "codigo_sucursal", "estado"},
    "contratos.ServicioContratado": {"nombre", "descripcion"},
    "contratos.AlertaVencimiento": {"estado"},
}

# The contract types keep only the client's choices (plan, branch, date). A
# type with its own form (PLT-03 …) also keeps what identifies a vehicle or a
# place: its form module lists those paths (CLAVES_SENSIBLES) and
# _datos_de_tramites replaces them. The column is still searched afterwards.
REVISADOS = {"tramites.Tramite": {"datos"}}

# How each kind of sensitive case value is replaced; the case id keeps them
# distinct. The plate and the VIN keep a valid shape.
DATOS_GENERADOS = {
    "direccion": lambda pk: f"Calle Anonima {pk:04d}",
    "patente": lambda pk: f"ZZ{pk % 10000:04d}",
    "vin": lambda pk: f"ANON{pk:013d}",
    "texto": lambda pk: TEXTO_FIJO,
}

VACIADOS = (
    "authtoken.Token",
    "mfa.Authenticator",
    "sessions.Session",
    "admin.LogEntry",
    "account.EmailConfirmation",
)

# Framework catalogues: no row comes from a person, and "America/Santiago" in a
# schedule would match a comuna.
TABLAS_SIN_DATOS = re.compile(
    r"^(django_migrations|django_content_type|django_site|auth_permission|auth_group"
    r"|django_celery_beat_.*)$",
)

# The audit log holds original values in its JSON, and the triggers add more as
# this module overwrites rows. Its rows never leave the machine: the bundle is
# dumped with --exclude-table-data (scripts/staging/copy_local_db.sh), and the
# copy is destroyed with them. So staging starts with no history and the log
# keeps its protection everywhere. Not searched, since it is known to match.
FUERA_DE_LA_COPIA = {
    "core.RegistroAuditoria": {
        "origen",
        "accion",
        "entidad",
        "valor_anterior",
        "valor_nuevo",
    },
}
TABLA_AUDITORIA = "core_registroauditoria"

SNAPSHOT_CONSERVADO = {"folio", "fecha_inicio", "duracion", "vencimiento", "servicios"}
COLUMNA_SNAPSHOT = ("documentos_documento", "datos_snapshot")


class CopiaRechazadaError(Exception):
    """The command must not run here, or the copy still holds original values."""


def exigir_copia(*, es_copia: bool) -> None:
    """Refuse anything but an explicit run on the throwaway copy.

    Raises:
        CopiaRechazadaError: The flag is missing, the settings are production's
            or staging's, or the database is not the copy.
    """
    if not es_copia:
        msg = "This overwrites the database. Pass --es-copia, on a copy only."
        raise CopiaRechazadaError(msg)
    modulo = settings.SETTINGS_MODULE or ""
    if "production" in modulo or "staging" in modulo:
        msg = f"Refusing to anonymize with {modulo}."
        raise CopiaRechazadaError(msg)
    nombre = connection.settings_dict["NAME"]
    if nombre != NOMBRE_BD_COPIA:
        msg = f"Refusing to anonymize database {nombre!r}: not {NOMBRE_BD_COPIA!r}."
        raise CopiaRechazadaError(msg)


@dataclass
class Resumen:
    personas: int
    empresas: int
    usuarios: int
    documentos: int
    valores_buscados: int
    tablas_eliminadas: list[str]
    identidades: list[dict[str, str]]


@dataclass
class _Copia:
    originales: set[str] = field(default_factory=set)
    reemplazos: dict[str, str] = field(default_factory=dict)
    ruts: dict[str, str] = field(default_factory=dict)
    ruts_ocupados: set[int] = field(default_factory=set)
    siguiente_rut: int = PRIMER_RUT

    def registrar(self, original: str, nuevo: str) -> str:
        if original:
            self.originales.add(original)
            self.reemplazos[original.casefold()] = nuevo
        return nuevo

    def rut(self, original: str) -> str:
        """The generated RUT for ``original``, the same one in every table."""
        original = normalize_rut(original)
        if original in self.ruts:
            return self.ruts[original]
        while self.siguiente_rut in self.ruts_ocupados:
            self.siguiente_rut += 1
        numero = str(self.siguiente_rut)
        self.siguiente_rut += 1
        nuevo = f"{numero}-{compute_rut_check_digit(numero)}"
        self.ruts[original] = nuevo
        for antes, despues in _formas_de_rut(original, nuevo):
            self.registrar(antes, despues)
        return nuevo


def _formas_de_rut(original: str, nuevo: str) -> Iterator[tuple[str, str]]:
    yield original, nuevo
    yield original.replace("-", ""), nuevo.replace("-", "")
    cuerpo = original.partition("-")[0]
    if cuerpo.isdigit():
        yield formato.rut(original), formato.rut(nuevo)
        yield cuerpo, nuevo.partition("-")[0]


def _anonimizar_filas(
    copia: _Copia,
    modelo: type[Model],
    generar: Callable[[Any], dict[str, str]],
) -> int:
    """Replace each row's values with generated ones; a blank value stays blank."""
    filas = list(modelo.objects.order_by("pk"))
    campos: set[str] = set()
    for fila in filas:
        for campo, nuevo in generar(fila).items():
            original = getattr(fila, campo)
            if original:
                setattr(fila, campo, copia.registrar(original, nuevo))
                campos.add(campo)
    if campos:
        modelo.objects.bulk_update(filas, campos, batch_size=500)
    return len(filas)


def _persona(copia: _Copia, persona: Persona) -> dict[str, str]:
    n = f"{persona.pk:04d}"
    apellido_materno = f"Materno {n}" if persona.apellido_materno else ""
    completo = " ".join(
        parte for parte in [f"Nombre {n}", f"Paterno {n}", apellido_materno] if parte
    )
    copia.registrar(persona.nombre_completo, completo)
    copia.registrar(
        f"{persona.nombres} {persona.apellido_paterno}",
        f"Nombre {n} Paterno {n}",
    )
    return {
        "rut": copia.rut(persona.rut),
        "nombres": f"Nombre {n}",
        "apellido_paterno": f"Paterno {n}",
        "apellido_materno": apellido_materno,
        "domicilio": f"Direccion Anonima {n}",
        "comuna": f"Comuna Anonima {n}",
        "region": f"Region Anonima {n}",
        "email": f"persona{n}@example.test",
        "telefono": f"+5690{persona.pk:07d}",
    }


def _empresa(copia: _Copia, empresa: Empresa) -> dict[str, str]:
    n = f"{empresa.pk:04d}"
    return {
        "rut": copia.rut(empresa.rut),
        "razon_social": f"Empresa Anonima {n} SpA",
        "nombre_fantasia": f"Fantasia Anonima {n}",
        "giro": f"Actividad Anonima {n}",
        "email": f"empresa{n}@example.test",
        "telefono": f"+5691{empresa.pk:07d}",
    }


def _usuarios(copia: _Copia) -> int:
    total = _anonimizar_filas(
        copia,
        User,
        lambda usuario: {
            "email": f"usuario{usuario.pk:04d}@example.test",
            "name": f"Usuario Anonimo {usuario.pk:04d}",
        },
    )
    usuarios = list(User.objects.all())
    for usuario in usuarios:
        usuario.password = make_password(None)
    User.objects.bulk_update(usuarios, ["password"], batch_size=500)

    correos = apps.get_model("account", "EmailAddress")
    _anonimizar_filas(
        copia,
        correos,
        lambda correo: {
            "email": (
                correo.user.email
                if correo.primary
                else f"direccion{correo.pk:04d}@example.test"
            ),
        },
    )
    return total


def _oficina(copia: _Copia, oficina: Oficina) -> dict[str, str]:
    """A property's address; a row still holding a placeholder keeps it.

    A warehouse's name may describe its owner, so it changes too. A branch's is
    only the place, which the portal shows.
    """
    n = f"{oficina.pk:04d}"
    generados = {"unidad": f"Unidad {n}"}
    if oficina.calle != CALLE_PENDIENTE:
        copia.registrar(
            f"{oficina.calle} {oficina.numero}",
            f"Direccion Anonima Inmueble {n} {oficina.pk}",
        )
        generados["calle"] = f"Direccion Anonima Inmueble {n}"
        generados["numero"] = str(oficina.pk)
    if not oficina.rol_avaluo.startswith(ROL_PENDIENTE):
        generados["rol_avaluo"] = f"ANON-{n}"
    if oficina.tipo == TipoInmueble.BODEGA:
        generados["nombre"] = f"Inmueble Anonimo {n}"
    return generados


def _config(copia: _Copia, config: ConfigEmpresa) -> dict[str, str]:
    generados = {
        "razon_social": "Emisora Anonima SpA",
        "direccion": "Direccion Anonima Emisora 1",
        "email_contacto": "contacto@example.test",
        "email_pagos": "pagos@example.test",
        "telefono": "+56900000001",
    }
    if config.rut:
        generados["rut"] = copia.rut(config.rut)
    return generados


def _texto_fijo(copia: _Copia, modelo: type[Model], campo: str) -> None:
    filas = modelo.objects.exclude(**{campo: ""})
    copia.originales.update(filas.values_list(campo, flat=True).distinct())
    filas.update(**{campo: TEXTO_FIJO})


def _pdf_placeholder() -> bytes:
    contenido = f"BT /F1 14 Tf 60 720 Td ({TEXTO_PLACEHOLDER}) Tj ET".encode()
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(contenido), contenido),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    salida = bytearray(b"%PDF-1.4\n")
    posiciones = []
    for numero, objeto in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += b"%d 0 obj\n%s\nendobj\n" % (numero, objeto)
    inicio_xref = len(salida)
    salida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for posicion in posiciones:
        salida += b"%010d 00000 n \n" % posicion
    salida += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objetos) + 1)
    salida += b"startxref\n%d\n%%%%EOF\n" % inicio_xref
    return bytes(salida)


def _docx_placeholder() -> bytes:
    documento = WordDocument()
    documento.add_paragraph(TEXTO_PLACEHOLDER)
    salida = BytesIO()
    documento.save(salida)
    return salida.getvalue()


def _sha256(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def _autorizantes(anverso: bytes, reverso: bytes) -> None:
    for autorizante in Autorizante.objects.order_by("pk"):
        cambios = {}
        for campo, contenido, nombre in (
            ("documento_identidad", anverso, "anverso.png"),
            ("documento_identidad_reverso", reverso, "reverso.png"),
        ):
            archivo = getattr(autorizante, campo)
            if archivo:
                archivo.save(nombre, ContentFile(contenido), save=False)
                cambios[campo] = archivo.name
        if cambios:
            Autorizante.objects.filter(pk=autorizante.pk).update(**cambios)


def _hoja_ficticia(copia: _Copia, clave: str, valor: Any) -> Any:
    """Replace everything under a snapshot key that is not explicitly kept.

    A snapshot can print values no record holds any more, so an unknown value
    is generated from its key, never left as it was.
    """
    if isinstance(valor, dict):
        return {k: _hoja_ficticia(copia, k, v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_hoja_ficticia(copia, clave, v) for v in valor]
    if not isinstance(valor, str) or not valor:
        return valor

    copia.originales.add(valor)
    conocido = copia.reemplazos.get(valor.casefold())
    if conocido is not None:
        return conocido.upper() if valor.isupper() else conocido
    if "rut" in clave.lower():
        nuevo = copia.rut(valor)
        return formato.rut(nuevo) if "." in valor else nuevo
    return _generado_por_clave(clave.lower())


def _generado_por_clave(clave: str) -> str:
    if "mail" in clave:
        return "snapshot@example.test"
    if "celular" in clave or "telefono" in clave:
        return "+56900000000"
    return "DATO ANONIMO"


def _snapshot(
    copia: _Copia,
    snapshot: dict[str, Any],
    imagenes: dict[str, str],
) -> dict[str, Any]:
    if not snapshot:
        return snapshot
    resultado = dict(snapshot)
    valores = {}
    for clave, valor in snapshot.get("valores", {}).items():
        valores[clave] = (
            valor
            if clave in SNAPSHOT_CONSERVADO
            else _hoja_ficticia(copia, clave, valor)
        )
    resultado["valores"] = valores
    if "imagenes" in snapshot:
        resultado["imagenes"] = {
            nombre: imagenes.get(nombre, imagenes["cedula_anverso"])
            for nombre in snapshot["imagenes"]
        }
    return resultado


def _documentos(copia: _Copia, imagenes: dict[str, str]) -> int:
    docx = _docx_placeholder()
    pdf = _pdf_placeholder()
    documentos = list(Documento.objects.order_by("pk"))
    for documento in documentos:
        cambios: dict[str, Any] = {
            "datos_snapshot": _snapshot(copia, documento.datos_snapshot, imagenes),
        }
        for campo, campo_hash, nombre, contenido in (
            ("archivo_docx", "sha256_docx", "copia.docx", docx),
            ("archivo_pdf", "sha256_pdf", "copia.pdf", pdf),
            ("archivo_firmado", "sha256_firmado", "copia.pdf", pdf),
        ):
            archivo = getattr(documento, campo)
            if archivo:
                archivo.save(nombre, ContentFile(contenido), save=False)
                cambios[campo] = archivo.name
                cambios[campo_hash] = _sha256(contenido)
        Documento.objects.filter(pk=documento.pk).update(**cambios)
    return len(documentos)


def _datos_de_tramites(copia: _Copia) -> None:
    """Replace what a case's own data says about a vehicle, a place or in free text.

    People are not in ``datos``: a case names them by id.
    """
    for tramite in Tramite.objects.select_related("tipo").order_by("pk"):
        formulario = formulario_de(tramite.tipo)
        if formulario is None:
            continue
        datos = copy.deepcopy(tramite.datos)
        for ruta, clase in formulario.CLAVES_SENSIBLES.items():
            *padres, hoja = ruta.split(".")
            nodo = datos
            for padre in padres:
                nodo = nodo.get(padre) or {}
            if nodo.get(hoja):
                nodo[hoja] = copia.registrar(
                    str(nodo[hoja]),
                    DATOS_GENERADOS[clase](tramite.pk),
                )
        Tramite.objects.filter(pk=tramite.pk).update(datos=datos)


def _cerrar_abiertos() -> None:
    """Open requests and orders point at a provider that has never heard of them."""
    SolicitudFirma.objects.filter(estado__in=SolicitudFirma.ABIERTAS).update(
        estado=SolicitudFirma.Estado.CANCELADA,
        terminada_en=timezone.now(),
    )
    OrdenPago.objects.filter(estado__in=OrdenPago.ABIERTAS).update(
        estado=OrdenPago.Estado.CANCELADA,
    )


def _columnas(clasificacion: dict[str, set[str]]) -> set[tuple[str, str]]:
    columnas = set()
    for etiqueta, campos in clasificacion.items():
        opciones = apps.get_model(etiqueta)._meta  # noqa: SLF001
        columnas |= {
            (opciones.db_table, opciones.get_field(campo).column) for campo in campos
        }
    return columnas


def _eliminar_tablas_desconocidas() -> list[str]:
    """Drop what no model knows, such as a table left by another branch.

    Staging's schema does not need them, and they may hold anything.
    """
    conocidas = set(connection.introspection.django_table_names()) | {
        "django_migrations",
    }
    with connection.cursor() as cursor:
        desconocidas = sorted(
            set(connection.introspection.table_names(cursor)) - conocidas,
        )
        for tabla in desconocidas:
            nombre = connection.ops.quote_name(tabla)
            cursor.execute(f"DROP TABLE {nombre} CASCADE")
    return desconocidas


def _patron(valores: set[str]) -> re.Pattern[str] | None:
    def buscable(valor: str) -> bool:
        digitos = valor.lstrip("+").replace("-", "")
        minimo = LARGO_MINIMO_DIGITOS if digitos.isdigit() else LARGO_MINIMO_TEXTO
        return len(valor) >= minimo

    buscados = sorted(filter(buscable, valores), key=len, reverse=True)
    if not buscados:
        return None
    alternativas = "|".join(re.escape(valor) for valor in buscados)
    return re.compile(rf"(?<!\w)(?:{alternativas})(?!\w)", re.IGNORECASE)


def _hojas(valor: Any) -> Iterator[str]:
    """Every value inside a cell; JSON keys are field names, like "giro"."""
    if isinstance(valor, dict):
        for hijo in valor.values():
            yield from _hojas(hijo)
    elif isinstance(valor, list):
        for hijo in valor:
            yield from _hojas(hijo)
    elif valor is not None:
        yield str(valor)


def _buscable_en_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The part of a snapshot to search: "15 DE JULIO" must not match a Julio."""
    valores = snapshot.get("valores", {})
    return {k: v for k, v in valores.items() if k not in SNAPSHOT_CONSERVADO}


def verificar(originales: set[str]) -> list[str]:
    """Search every table for ``originales``; return the columns that hold any.

    It reads whole rows, so a column no model knows about is searched too. A
    column this module overwrites holds only generated values, so it must not
    equal an original; comparing by substring there would make someone typed as
    "test" match every ``@example.test``. Any other column is searched by
    substring. The result names columns, never values.
    """
    patron = _patron(originales)
    if patron is None:
        return []
    exactos = {valor.casefold() for valor in originales}
    saltadas = _columnas(CONSERVADOS)
    generadas = _columnas(ANONIMIZADOS)
    culpables = set()
    with connection.cursor() as cursor:
        for tabla in connection.introspection.table_names(cursor):
            if TABLAS_SIN_DATOS.match(tabla) or tabla == TABLA_AUDITORIA:
                continue
            nombre = connection.ops.quote_name(tabla)
            cursor.execute(f"SELECT to_jsonb(t)::text FROM {nombre} t")  # noqa: S608
            for (fila,) in cursor.fetchall():
                for columna, valor in json.loads(fila).items():
                    if (tabla, columna) in saltadas:
                        continue
                    if (tabla, columna) == COLUMNA_SNAPSHOT:
                        valor = _buscable_en_snapshot(valor)  # noqa: PLW2901
                    if (tabla, columna) in generadas:
                        encontrado = any(
                            hoja.casefold() in exactos for hoja in _hojas(valor)
                        )
                    else:
                        encontrado = any(patron.search(hoja) for hoja in _hojas(valor))
                    if encontrado:
                        culpables.add(f"{tabla}.{columna}")
    return sorted(culpables)


def plantillas_faltantes() -> list[str]:
    """Template files the copy's rows point at and its storage lacks."""
    return [
        version.archivo.name
        for version in VersionPlantilla.objects.all()
        if not version.archivo.storage.exists(version.archivo.name)
    ]


@transaction.atomic
def anonimizar() -> Resumen:
    """Anonymize the database in one transaction, and verify it before committing.

    Raises:
        CopiaRechazadaError: An original value survived. Nothing is committed.
    """
    tablas_eliminadas = _eliminar_tablas_desconocidas()
    copia = _Copia()
    copia.ruts_ocupados = {
        int(numero)
        for numero in (
            normalize_rut(rut).partition("-")[0]
            for modelo in (Persona, Empresa, ConfigEmpresa)
            for rut in modelo.objects.values_list("rut", flat=True)
        )
        if numero.isdigit()
    }

    personas = _anonimizar_filas(copia, Persona, lambda p: _persona(copia, p))
    empresas = _anonimizar_filas(copia, Empresa, lambda e: _empresa(copia, e))
    _anonimizar_filas(
        copia,
        RepresentanteLegal,
        lambda r: {"sitio_o_notaria": f"Notaria Anonima {r.pk:04d}"},
    )
    usuarios = _usuarios(copia)
    _anonimizar_filas(copia, Oficina, lambda o: _oficina(copia, o))
    _anonimizar_filas(copia, ConfigEmpresa, lambda c: _config(copia, c))
    _anonimizar_filas(
        copia,
        CuentaPago,
        lambda c: {
            "numero": f"{c.pk:010d}",
            "titular": f"Titular Anonimo {c.pk:04d}",
            "texto_contrato": f"Cuenta Anonima {c.pk:04d}",
        },
    )
    _anonimizar_filas(
        copia,
        Contrato,
        lambda c: {
            "email_aviso": f"aviso{c.pk:04d}@example.test",
            "movil_aviso": f"+5692{c.pk:07d}",
        },
    )

    _datos_de_tramites(copia)

    anverso = tarjeta_png(200)
    reverso = tarjeta_png(225)
    _autorizantes(anverso, reverso)
    documentos = _documentos(
        copia,
        {"cedula_anverso": _sha256(anverso), "cedula_reverso": _sha256(reverso)},
    )

    for modelo, campo in (
        (Tramite, "detalle_pendiente"),
        (EventoTramite, "detalle"),
        (Firmante, "motivo_rechazo"),
        (SolicitudFirma, "detalle_error"),
        (OrdenPago, "detalle_error"),
        (AlertaVencimiento, "nota"),
    ):
        _texto_fijo(copia, modelo, campo)
    Pago.objects.exclude(ultimos_digitos="").update(ultimos_digitos="0000")
    Pago.objects.update(respuesta={})
    EventoPago.objects.update(payload={})
    EventoFirma.objects.update(payload={})
    _cerrar_abiertos()
    for etiqueta in VACIADOS:
        apps.get_model(etiqueta).objects.all().delete()

    culpables = verificar(copia.originales)
    if culpables:
        msg = f"Original values remain in: {', '.join(culpables)}."
        raise CopiaRechazadaError(msg)

    return Resumen(
        personas=personas,
        empresas=empresas,
        usuarios=usuarios,
        documentos=documentos,
        valores_buscados=len(copia.originales),
        tablas_eliminadas=tablas_eliminadas,
        identidades=[
            {
                "rut": persona.rut,
                "numero_serie": f"A{persona.rut.partition('-')[0]}",
                "nombre": persona.nombre_completo,
            }
            for persona in Persona.objects.order_by("pk")
        ],
    )
