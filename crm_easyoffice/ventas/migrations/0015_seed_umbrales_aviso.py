from django.db import migrations

# ASSUMPTION: pending validation with Easy Office. HU-42's initial values, the
# same for every service until Easy Office says otherwise. Edited in the admin.
UMBRALES = [60, 30, 15, 7]


def seed(apps, schema_editor):
    apps.get_model("ventas", "Servicio").objects.update(umbrales_aviso_dias=UMBRALES)


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0014_servicio_umbrales_aviso"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
