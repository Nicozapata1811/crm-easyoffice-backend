import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed_roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def grant(apps, schema_editor):
    app_config = apps.get_app_config("tramites")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    gestionar = Permission.objects.get(
        content_type__app_label="tramites",
        codename="gestionar_tramite",
    )
    for rol in (seed_roles.ADMINISTRADOR, seed_roles.EJECUTIVO):
        Group.objects.get(name=rol).permissions.add(gestionar)


class Migration(migrations.Migration):
    dependencies = [
        ("tramites", "0002_seed_domicilio"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="tramite",
            options={
                "ordering": ["-created_at", "-pk"],
                "permissions": [
                    ("gestionar_tramite", "Can act on a case (retry its document)"),
                ],
                "verbose_name": "trámite",
                "verbose_name_plural": "trámites",
            },
        ),
        migrations.RunPython(grant, migrations.RunPython.noop),
    ]
