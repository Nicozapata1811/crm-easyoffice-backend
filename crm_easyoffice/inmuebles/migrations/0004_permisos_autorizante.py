import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations
from django.db.models import Q

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def grant(apps, schema_editor):
    app_config = apps.get_app_config("inmuebles")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    autorizante = Q(
        content_type__app_label="inmuebles",
        content_type__model="autorizante",
    )
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.add(
        *Permission.objects.filter(autorizante),
    )
    # ASSUMPTION: pending validation with Easy Office. An Ejecutivo sees who
    # authorises each property but not the identity card.
    Group.objects.get(name=seed.EJECUTIVO).permissions.add(
        *Permission.objects.filter(autorizante, codename="view_autorizante"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inmuebles", "0003_seed_sucursales"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
