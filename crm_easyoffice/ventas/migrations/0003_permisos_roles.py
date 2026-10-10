import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations
from django.db.models import Q

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def grant(apps, schema_editor):
    app_config = apps.get_app_config("ventas")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ver = Q(content_type__app_label="ventas", codename__startswith="view_")
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.add(
        *Permission.objects.filter(
            ver | Q(codename__in=["add_servicio", "change_servicio"]),
        ),
    )
    Group.objects.get(name=seed.EJECUTIVO).permissions.add(
        *Permission.objects.filter(ver),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0002_seed_servicios"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
