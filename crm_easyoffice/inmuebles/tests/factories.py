"""Factories for properties. Every value they produce is synthetic."""

from __future__ import annotations

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
