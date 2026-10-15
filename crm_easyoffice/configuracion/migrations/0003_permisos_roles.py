import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations
from django.db.models import Q

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def grant(apps, schema_editor):
    app_config = apps.get_app_config("configuracion")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    app = Q(content_type__app_label="configuracion")
    # Nobody deletes configuration: contracts point at it.
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.add(
        *Permission.objects.filter(app, codename__regex=r"^(add|change|view)_"),
    )
    # An Ejecutivo picks the brand and account of a contract but edits neither.
    Group.objects.get(name=seed.EJECUTIVO).permissions.add(
        *Permission.objects.filter(app, codename__startswith="view_"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("configuracion", "0002_seed"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
