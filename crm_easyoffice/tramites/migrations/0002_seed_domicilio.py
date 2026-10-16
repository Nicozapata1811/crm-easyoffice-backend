import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed_roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

# The pilot case type (build order step 1). Its configuration is edited in
# the admin.
# ASSUMPTION: pending validation with Easy Office. Brand EASY OFFICE, and a
# start date at most 30 days ahead.
DOMICILIO = {
    "codigo": "domicilio-tributario",
    "nombre": "Domicilio tributario",
    "configuracion": {
        "servicio": "domicilio-tributario",
        "marca": "EASY OFFICE",
        "plantilla": "PLT-01",
        "requiere_pago": True,
        "requiere_firma": True,
        "inicio_max_dias": 30,
    },
}

# ASSUMPTION: pending validation with Easy Office. TA-13 (the closed list of
# reasons) is open; these are RN-42's examples.
MOTIVOS = [
    (
        "falta_informacion",
        "Falta información",
        "Estamos revisando tu trámite. Te avisaremos si necesitamos algo.",
    ),
    (
        "revision_borrador",
        "Revisión del borrador",
        "Revisa el borrador del contrato y confírmalo para continuar.",
    ),
    ("pago", "Pago", "Falta el pago para continuar."),
    (
        "firma",
        "Firma",
        "Estamos gestionando la firma del contrato.",
    ),
]


def seed(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    MotivoPendiente = apps.get_model("tramites", "MotivoPendiente")

    datos = dict(DOMICILIO)
    TipoTramite.objects.get_or_create(codigo=datos.pop("codigo"), defaults=datos)
    for codigo, nombre, texto in MOTIVOS:
        MotivoPendiente.objects.get_or_create(
            codigo=codigo,
            defaults={"nombre": nombre, "texto_cliente": texto},
        )
    _grant(apps)


def _grant(apps):
    app_config = apps.get_app_config("tramites")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    propios = Permission.objects.filter(content_type__app_label="tramites")
    # Cases move only through the services: nobody edits one in the admin.
    lectura = propios.filter(codename__startswith="view_")
    configuracion = propios.filter(
        content_type__model__in=["tipotramite", "motivopendiente"],
        codename__regex=r"^(add|change)_",
    )
    Group.objects.get(name=seed_roles.ADMINISTRADOR).permissions.add(
        *lectura,
        *configuracion,
    )
    Group.objects.get(name=seed_roles.EJECUTIVO).permissions.add(*lectura)


class Migration(migrations.Migration):
    dependencies = [
        ("tramites", "0001_initial"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
