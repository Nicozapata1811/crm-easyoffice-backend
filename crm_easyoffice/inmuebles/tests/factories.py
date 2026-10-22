"""Factories for properties. Every value they produce is synthetic."""

from __future__ import annotations

import struct
import zlib
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.clientes.tests.factories import EmpresaFactory
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.inmuebles.models import Autorizante
from crm_easyoffice.inmuebles.models import Oficina
from crm_easyoffice.inmuebles.models import TipoInmueble
from crm_easyoffice.inmuebles.services import guardar_documento_identidad

# The smallest content each validator accepts; not real images.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PDF = b"%PDF-1.4\n%synthetic\n"


def archivo(nombre: str = "cedula.jpg", contenido: bytes = JPEG) -> SimpleUploadedFile:
    return SimpleUploadedFile(nombre, contenido)


def representacion(empresa: Empresa | None = None) -> RepresentanteLegal:
    """A synthetic person representing ``empresa`` (a new one by default)."""
    return RepresentanteLegal.objects.create(
        persona=PersonaFactory.create(),
        empresa=empresa or EmpresaFactory.create(),
        vigente_desde=date(2026, 1, 1),
    )


class OficinaFactory(DjangoModelFactory[Oficina]):
    """A property without a branch code: the migrations seed LF, VL and SA."""

    tipo = TipoInmueble.OFICINA
    codigo_sucursal = None
    rol_avaluo = Sequence(lambda n: f"EJ-{n:05d}")
    nombre = Sequence(lambda n: f"Inmueble de Ejemplo {n}")
    calle = "Calle de Ejemplo"
    numero = Sequence(str)
    comuna = "Comuna de Ejemplo"
    region = "Región de Ejemplo"

    class Meta:
        model = Oficina


class AutorizanteFactory(DjangoModelFactory[Autorizante]):
    """A natural-person owner; pass empresa and representante for a company."""

    inmueble = SubFactory(OficinaFactory)
    persona = SubFactory(PersonaFactory)
    empresa = None
    representante = None
    vigente_desde = date(2026, 1, 1)

    class Meta:
        model = Autorizante


def png_sintetico(ancho: int = 64, alto: int = 40, tono: int = 200) -> bytes:
    """A real, valid grey PNG (not a card): documents can embed and size it."""
    fila = b"\x00" + bytes([tono]) * ancho
    crudo = fila * alto

    def bloque(tipo: bytes, datos: bytes) -> bytes:
        cuerpo = tipo + datos
        return (
            struct.pack(">I", len(datos))
            + cuerpo
            + struct.pack(">I", zlib.crc32(cuerpo))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + bloque(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 0, 0, 0, 0))
        + bloque(b"IDAT", zlib.compress(crudo))
        + bloque(b"IEND", b"")
    )


def preparar_bodega(desde: date = date(2026, 1, 1), **campos) -> Autorizante:
    """A warehouse ready for PLT-02, with its natural-person owner.

    A fictitious address and rol, and an owner with every field the
    authorisation prints and both sides of a synthetic card.
    """
    bodega = OficinaFactory.create(
        tipo=TipoInmueble.BODEGA,
        nombre="Bodega de Ejemplo",
        calle="Camino de Ejemplo",
        numero="500",
        unidad="Bodega 7",
        comuna="Quilicura",
        region="Región Metropolitana de Santiago",
        **campos,
    )
    autorizante = Autorizante.objects.create(
        inmueble=bodega,
        persona=PersonaFactory.create(con_datos_civiles=True),
        vigente_desde=desde,
    )
    guardar_documento_identidad(
        autorizante,
        archivo("anverso.png", png_sintetico(tono=170)),
    )
    guardar_documento_identidad(
        autorizante,
        archivo("reverso.png", png_sintetico(tono=210)),
        reverso=True,
    )
    return autorizante


def preparar_sucursal_domicilio(
    codigo: str = "LF",
    desde: date = date(2026, 1, 1),
) -> Autorizante:
    """Complete a seeded branch so PLT-01 can be issued for it.

    A fictitious address, rol and SII unit, and a fictitious owner company
    whose representative has every field the contract prints and both sides
    of a synthetic card.
    """
    oficina = Oficina.objects.get(codigo_sucursal=codigo)
    oficina.calle = "Avenida de Ejemplo"
    oficina.numero = "100"
    oficina.unidad = "Oficina 1"
    oficina.rol_avaluo = f"0000-{codigo}"
    oficina.unidad_sii = f"UNIDAD DE EJEMPLO {codigo}"
    oficina.municipalidad = oficina.comuna
    oficina.save()

    empresa = EmpresaFactory.create(razon_social="Inmobiliaria de Ejemplo Ltda.")
    representante = RepresentanteLegal.objects.create(
        persona=PersonaFactory.create(con_datos_civiles=True),
        empresa=empresa,
        vigente_desde=desde,
    )
    autorizante = Autorizante.objects.create(
        inmueble=oficina,
        empresa=empresa,
        representante=representante,
        vigente_desde=desde,
    )
    guardar_documento_identidad(
        autorizante,
        archivo("anverso.png", png_sintetico(tono=180)),
    )
    guardar_documento_identidad(
        autorizante,
        archivo("reverso.png", png_sintetico(tono=220)),
        reverso=True,
    )
    return autorizante
