import hashlib

from django.core.files.base import ContentFile
from django.db import migrations
from django.db import models
from django.utils import timezone

from crm_easyoffice.documentos.semillas import PLANTILLA_PLT03


def seed(apps, schema_editor):
    """Load PLT-03 v1, the converted anonymised template, into private storage."""
    PlantillaDocumento = apps.get_model("documentos", "PlantillaDocumento")
    VersionPlantilla = apps.get_model("documentos", "VersionPlantilla")

    plantilla, _ = PlantillaDocumento.objects.get_or_create(
        codigo="PLT-03",
        defaults={"nombre": "Contrato de arrendamiento de vehículo"},
    )
    if not VersionPlantilla.objects.filter(plantilla=plantilla).exists():
        contenido = PLANTILLA_PLT03.read_bytes()
        version = VersionPlantilla(
            plantilla=plantilla,
            numero=1,
            sha256=hashlib.sha256(contenido).hexdigest(),
            notas="Plantilla anonimizada de 13_plantillas, convertida con "
            "manage.py convertir_plantilla PLT-03.",
            vigente_desde=timezone.now(),
        )
        version.archivo.save("PLT-03_v1.docx", ContentFile(contenido), save=False)
        version.save()


class Migration(migrations.Migration):
    dependencies = [
        ("documentos", "0005_permisos_firma_avanzada"),
    ]

    operations = [
        # The parties of the documents Easy Office is not a party to.
        migrations.AlterField(
            model_name="firmante",
            name="rol",
            field=models.CharField(
                choices=[
                    ("cliente_representante", "representante del cliente"),
                    ("representante_emisor", "representante de Easy Office"),
                    ("autorizante", "autorizante del domicilio"),
                    ("arrendador", "arrendador"),
                    ("arrendatario", "arrendatario"),
                    ("accionista", "accionista"),
                ],
                max_length=30,
                verbose_name="rol",
            ),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
