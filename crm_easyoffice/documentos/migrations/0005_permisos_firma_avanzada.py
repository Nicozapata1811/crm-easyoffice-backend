import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed_roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

PERMISOS = ("gestionar_firma", "view_solicitudfirma", "view_eventofirma")


def grant(apps, schema_editor):
    app_config = apps.get_app_config("documentos")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permisos = Permission.objects.filter(
        content_type__app_label="documentos",
        codename__in=PERMISOS,
    )
    for rol in (seed_roles.ADMINISTRADOR, seed_roles.EJECUTIVO):
        Group.objects.get(name=rol).permissions.add(*permisos)


def revoke(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for rol in (seed_roles.ADMINISTRADOR, seed_roles.EJECUTIVO):
        grupo = Group.objects.get(name=rol)
        grupo.permissions.remove(
            *grupo.permissions.filter(
                content_type__app_label="documentos",
                codename__in=PERMISOS,
            ),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("documentos", "0004_firma_avanzada"),
        ("core", "0002_seed_roles"),
    ]

    operations = [
        migrations.RunPython(grant, revoke),
    ]
