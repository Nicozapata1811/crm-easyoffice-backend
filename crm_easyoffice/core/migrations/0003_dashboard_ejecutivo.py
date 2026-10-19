import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def _permiso_panel(apps):
    app_config = apps.get_app_config("core")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None
    Permission = apps.get_model("auth", "Permission")
    return Permission.objects.get(
        content_type__app_label="core",
        codename="view_dashboard",
    )


def grant(apps, schema_editor):
    # The dashboard is for the Administrador and the Ejecutivo: confirmed by
    # Easy Office on 08-10-2026 (ACTA-002, D2-06; RN-32, RF-14).
    Group = apps.get_model("auth", "Group")
    Group.objects.get(name=seed.EJECUTIVO).permissions.add(_permiso_panel(apps))


def revoke(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get(name=seed.EJECUTIVO).permissions.remove(_permiso_panel(apps))


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
