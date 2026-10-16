import hashlib
import importlib

from django.contrib.auth.management import create_permissions
from django.core.files.base import ContentFile
from django.db import migrations
from django.utils import timezone

from crm_easyoffice.documentos.semillas import PLANTILLA_PLT01

seed_roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def seed(apps, schema_editor):
    """Load PLT-01 v1, the converted anonymised template, into private storage."""
    PlantillaDocumento = apps.get_model("documentos", "PlantillaDocumento")
    VersionPlantilla = apps.get_model("documentos", "VersionPlantilla")

    plantilla, _ = PlantillaDocumento.objects.get_or_create(
        codigo="PLT-01",
        defaults={"nombre": "Contrato de servicios con autorización de domicilio"},
    )
    if not VersionPlantilla.objects.filter(plantilla=plantilla).exists():
        contenido = PLANTILLA_PLT01.read_bytes()
        version = VersionPlantilla(
            plantilla=plantilla,
            numero=1,
            sha256=hashlib.sha256(contenido).hexdigest(),
            notas="Plantilla anonimizada de 13_plantillas, convertida con "
            "manage.py convertir_plt01.",
            vigente_desde=timezone.now(),
        )
        version.archivo.save("PLT-01_v1.docx", ContentFile(contenido), save=False)
        version.save()
    _grant(apps)


def _grant(apps):
    app_config = apps.get_app_config("documentos")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    propios = Permission.objects.filter(content_type__app_label="documentos")
    # Documents and templates are written only by the services.
    permisos = [
        *propios.filter(codename__startswith="view_"),
        *propios.filter(codename="subir_documento_firmado"),
    ]
    for rol in (seed_roles.ADMINISTRADOR, seed_roles.EJECUTIVO):
        Group.objects.get(name=rol).permissions.add(*permisos)


class Migration(migrations.Migration):
    dependencies = [
        ("documentos", "0001_initial"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
