"""Every existing case type keeps today's assisted signature (IN-01).

``firma.nivel`` is ``asistida`` (an executive uploads the signed PDF) or
``avanzada`` (an external provider). ``setdefault`` keeps a value already
edited in the admin.
"""

from django.db import migrations


def asistida(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    for tipo in TipoTramite.objects.all():
        tipo.configuracion.setdefault("firma", {"nivel": "asistida"})
        tipo.save(update_fields=["configuracion"])


def quitar(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    for tipo in TipoTramite.objects.all():
        tipo.configuracion.pop("firma", None)
        tipo.save(update_fields=["configuracion"])


class Migration(migrations.Migration):
    dependencies = [
        ("tramites", "0005_bodega_en_portal"),
    ]

    operations = [
        migrations.RunPython(asistida, quitar),
    ]
