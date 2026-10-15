import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations
from django.db.models import Q

seed = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")


def grant(apps, schema_editor):
    app_config = apps.get_app_config("contratos")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    def de(modelo):
        return Q(content_type__app_label="contratos", content_type__model=modelo)

    editables = de("contrato") | de("serviciocontratado") | de("duracioncontrato")
    trabajo = Q(codename__regex=r"^(add|change|view)_")
    # Nothing here is deleted, by anyone: durations are deactivated. The folio
    # counter is only read.
    Group.objects.get(name=seed.ADMINISTRADOR).permissions.add(
        *Permission.objects.filter(
            (editables & trabajo)
            | (de("correlativofolio") & Q(codename__startswith="view_")),
        ),
    )
    contrato = de("contrato") | de("serviciocontratado")
    Group.objects.get(name=seed.EJECUTIVO).permissions.add(
        *Permission.objects.filter(
            (contrato & trabajo)
            | (de("duracioncontrato") & Q(codename__startswith="view_")),
        ),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("contratos", "0002_seed_duraciones"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
