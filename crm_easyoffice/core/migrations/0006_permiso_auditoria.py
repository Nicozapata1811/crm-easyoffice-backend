import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def _permiso_auditoria(apps):
    app_config = apps.get_app_config("core")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None
    Permission = apps.get_model("auth", "Permission")
    return Permission.objects.get(
        content_type__app_label="core",
        codename="consultar_auditoria",
    )


def grant(apps, schema_editor):
    # Only the Administrador consults the audit log (RN-31, RF-17); the
    # Ejecutivo does not (PLA-001 §3.4).
    Group = apps.get_model("auth", "Group")
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.add(_permiso_auditoria(apps))


def revoke(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.remove(
        _permiso_auditoria(apps),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_triggers_auditoria"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
