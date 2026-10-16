import importlib
from decimal import Decimal

from django.contrib.auth.management import create_permissions
from django.db import migrations

seed_roles = importlib.import_module("crm_easyoffice.core.migrations.0002_seed_roles")

DOMICILIO = "domicilio-tributario"
FIRMA = "firma-electronica-avanzada"

# ASSUMPTION: pending validation with Easy Office. The two plans and their
# prices come from Easy Office's public website (seen 15-10-2026). They stay
# unconfirmed, and whether they include VAT is open (RN-44 vs OB-09).
PLANES = [
    {
        "codigo": "anual",
        "nombre": "Plan anual",
        "duracion_meses": 12,
        "ciclo": "anual",
        "precio": Decimal(59990),
        "firma_incluida": True,
        "orden": 10,
    },
    {
        "codigo": "semestral",
        "nombre": "Plan semestral",
        "duracion_meses": 6,
        "ciclo": "semestral",
        "precio": Decimal(39990),
        "firma_incluida": False,
        "orden": 20,
    },
]

# ASSUMPTION: pending validation with Easy Office. The website charges the
# signature of the half-yearly plan at 5.000; the seed had 3.500 (prototype)
# and the PLT-01 annex prints 5.900.
PRECIO_FIRMA = Decimal(5000)
PRECIO_FIRMA_ANTERIOR = Decimal(3500)


def seed(apps, schema_editor):
    Servicio = apps.get_model("ventas", "Servicio")
    CicloPago = apps.get_model("ventas", "CicloPago")
    PlanServicio = apps.get_model("ventas", "PlanServicio")

    domicilio = Servicio.objects.filter(codigo=DOMICILIO).first()
    if domicilio is not None:
        for datos in PLANES:
            datos = dict(datos)
            codigo = datos.pop("codigo")
            ciclo = CicloPago.objects.get(codigo=datos.pop("ciclo"))
            # An existing plan keeps whatever was edited in the admin.
            PlanServicio.objects.get_or_create(
                servicio=domicilio,
                codigo=codigo,
                defaults={
                    **datos,
                    "ciclo_pago": ciclo,
                    "precio_incluye_iva": True,
                    "precio_confirmado": False,
                    "se_vende_en_portal": True,
                    "activo": True,
                },
            )
    # Only the untouched seed price moves; an admin edit is kept.
    Servicio.objects.filter(codigo=FIRMA, precio_base=PRECIO_FIRMA_ANTERIOR).update(
        precio_base=PRECIO_FIRMA,
    )

    _grant(apps)


def _grant(apps):
    app_config = apps.get_app_config("ventas")
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)
    app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    planes = Permission.objects.filter(
        content_type__app_label="ventas",
        content_type__model="planservicio",
    )
    Group.objects.get(name=seed_roles.ADMINISTRADOR).permissions.add(
        *planes.filter(codename__regex=r"^(add|change|view)_"),
    )
    Group.objects.get(name=seed_roles.EJECUTIVO).permissions.add(
        *planes.filter(codename="view_planservicio"),
    )


def unseed(apps, schema_editor):
    PlanServicio = apps.get_model("ventas", "PlanServicio")
    Servicio = apps.get_model("ventas", "Servicio")
    PlanServicio.objects.filter(
        servicio__codigo=DOMICILIO,
        codigo__in=[plan["codigo"] for plan in PLANES],
    ).delete()
    Servicio.objects.filter(codigo=FIRMA, precio_base=PRECIO_FIRMA).update(
        precio_base=PRECIO_FIRMA_ANTERIOR,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0011_plan_servicio"),
        ("core", "0002_seed_roles"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
