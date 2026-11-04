import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations
from django.db.models import Q

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

# Viewing and handling alerts. Which alerts each one sees is the queryset's rule.
TRABAJO = ("view_alertavencimiento", "gestionar_alertavencimiento")
# Nobody adds, changes or deletes an alert by hand; only the Administrador sees
# them all and sets the responsible executive.
SOLO_ADMINISTRADOR = ("ver_todas_alertasvencimiento", "asignar_responsable_contrato")


def _permisos(Permission, codenames):
    return Permission.objects.filter(
        Q(content_type__app_label="contratos"),
        Q(codename__in=codenames),
    )


def grant(apps, schema_editor):
    app_config = apps.get_app_config("contratos")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.add(
        *_permisos(Permission, (*TRABAJO, *SOLO_ADMINISTRADOR)),
    )
    Group.objects.get(name=seed.EJECUTIVO).permissions.add(
        *_permisos(Permission, TRABAJO),
    )


def revoke(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    permisos = _permisos(Permission, (*TRABAJO, *SOLO_ADMINISTRADOR))
    for rol in (seed.ADMINISTRADOR, seed.EJECUTIVO):
        Group.objects.get(name=rol).permissions.remove(*permisos)


class Migration(migrations.Migration):
    dependencies = [
        ("contratos", "0005_alertas_vencimiento"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
