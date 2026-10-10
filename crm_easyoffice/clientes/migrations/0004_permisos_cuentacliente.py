import importlib

from django.db import migrations

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


class Migration(migrations.Migration):
    dependencies = [
        ("clientes", "0003_cuentacliente"),
        ("core", "0002_seed_roles"),
    ]

    operations = [
        migrations.RunPython(seed.seed_roles, migrations.RunPython.noop),
    ]
