import hashlib

from django.core.files.base import ContentFile
from django.db import migrations
from django.utils import timezone

from crm_easyoffice.documentos.semillas import PLANTILLA_PLT02


def seed(apps, schema_editor):
    """Load PLT-02 v1, the converted anonymised template, into private storage."""
    PlantillaDocumento = apps.get_model("documentos", "PlantillaDocumento")
    VersionPlantilla = apps.get_model("documentos", "VersionPlantilla")

    plantilla, _ = PlantillaDocumento.objects.get_or_create(
        codigo="PLT-02",
        defaults={"nombre": "Contrato de servicios con autorización de uso de bodega"},
    )
    if not VersionPlantilla.objects.filter(plantilla=plantilla).exists():
        contenido = PLANTILLA_PLT02.read_bytes()
        version = VersionPlantilla(
            plantilla=plantilla,
            numero=1,
            sha256=hashlib.sha256(contenido).hexdigest(),
            notas="Plantilla anonimizada de 13_plantillas, convertida con "
            "manage.py convertir_plantilla PLT-02.",
            vigente_desde=timezone.now(),
        )
        version.archivo.save("PLT-02_v1.docx", ContentFile(contenido), save=False)
        version.save()


class Migration(migrations.Migration):
    dependencies = [
        ("documentos", "0002_seed_plt01"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
