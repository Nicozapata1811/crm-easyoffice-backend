import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def grant(apps, schema_editor):
    app_config = apps.get_app_config("ventas")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ciclo = Permission.objects.filter(
        content_type__app_label="ventas",
        content_type__model="ciclopago",
    )
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.add(
        *ciclo.filter(codename__regex=r"^(add|change|view)_"),
    )
    Group.objects.get(name=seed.EJECUTIVO).permissions.add(
        *ciclo.filter(codename="view_ciclopago"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0007_seed_catalogo_formulario"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
