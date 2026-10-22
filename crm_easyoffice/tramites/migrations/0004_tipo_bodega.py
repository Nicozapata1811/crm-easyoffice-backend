import importlib

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed_roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

# The keys PLT-02 made explicit, for the domicile as it already behaves.
DOMICILIO = {
    "planes": True,
    "canal": "portal",
    "tipos_cliente": ["empresa"],
    "lineas": [
        {
            "servicio": "domicilio-tributario",
            "inmueble": "sucursal",
            "requisitos": "domicilio",
            "inmueble_exclusivo": False,
        },
    ],
}

# The second case type (build order step 2): the warehouse contract, PLT-02.
# ASSUMPTION: pending validation with Easy Office. Every PLT-02 carries the
# domicile at a branch and the warehouse (the 2026 sample does); the
# warehouse is shared like a domicile; it is started in the backoffice with
# no online payment; brand EASY OFFICE; 12 months unless chosen otherwise;
# companies only; start date at most 30 days ahead.
BODEGA = {
    "codigo": "bodega",
    "nombre": "Bodega virtual",
    "configuracion": {
        "servicio": "bodega",
        "marca": "EASY OFFICE",
        "plantilla": "PLT-02",
        "requiere_pago": False,
        "requiere_firma": True,
        "inicio_max_dias": 30,
        "planes": False,
        "duracion_por_defecto": 12,
        "canal": "backoffice",
        "tipos_cliente": ["empresa"],
        "lineas": [
            {
                "servicio": "domicilio-tributario",
                "inmueble": "sucursal",
                "requisitos": "ubicacion",
                "inmueble_exclusivo": False,
            },
            {
                "servicio": "bodega",
                "inmueble": "bodega",
                "requisitos": "bodega",
                "inmueble_exclusivo": False,
            },
        ],
    },
}


def seed(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")

    # Values edited in the admin are kept: only missing keys are added.
    for tipo in TipoTramite.objects.filter(codigo="domicilio-tributario"):
        for clave, valor in DOMICILIO.items():
            tipo.configuracion.setdefault(clave, valor)
        tipo.save(update_fields=["configuracion"])
    datos = dict(BODEGA)
    TipoTramite.objects.get_or_create(codigo=datos.pop("codigo"), defaults=datos)
    _grant(apps)


def unseed(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    TipoTramite.objects.filter(codigo="bodega", tramites__isnull=True).delete()


def _grant(apps):
    app_config = apps.get_app_config("tramites")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    iniciar = Permission.objects.get(
        content_type__app_label="tramites",
        codename="iniciar_tramite",
    )
    for rol in (seed_roles.ADMINISTRADOR, seed_roles.EJECUTIVO):
        Group.objects.get(name=rol).permissions.add(iniciar)


class Migration(migrations.Migration):
    dependencies = [
        ("tramites", "0003_permiso_gestionar_tramite"),
        ("ventas", "0010_seed_servicios_visibles"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="tramite",
            options={
                "ordering": ["-created_at", "-pk"],
                "permissions": [
                    ("gestionar_tramite", "Can act on a case (retry its document)"),
                    ("iniciar_tramite", "Can start a case for a client"),
                ],
                "verbose_name": "trámite",
                "verbose_name_plural": "trámites",
            },
        ),
        migrations.RunPython(seed, unseed),
    ]
