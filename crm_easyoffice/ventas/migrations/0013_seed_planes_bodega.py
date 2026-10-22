from decimal import Decimal

from django.db import migrations

BODEGA = "bodega"

# ASSUMPTION: pending validation with Easy Office (TA-15). The bodega is sold
# online at the annual price on Easy Office's official website (59.990, with
# the advanced electronic signature included) as a placeholder until Easy
# Office confirms its prices; the list price only lets the portal sell it
# (servicio_portal_con_precio). Edited in the admin, never in code.
PRECIO_LISTA = Decimal(59990)

# ASSUMPTION: pending validation with Easy Office (TA-15). Price: the same
# placeholder 59.990 for every plan. Duration: 12, 6 and 3 months.
# Signature: included in all three. None is confirmed.
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
        "precio": Decimal(59990),
        "firma_incluida": True,
        "orden": 20,
    },
    {
        "codigo": "trimestral",
        "nombre": "Plan trimestral",
        "duracion_meses": 3,
        "ciclo": "trimestral",
        "precio": Decimal(59990),
        "firma_incluida": True,
        "orden": 30,
    },
]


def seed(apps, schema_editor):
    Servicio = apps.get_model("ventas", "Servicio")
    CicloPago = apps.get_model("ventas", "CicloPago")
    PlanServicio = apps.get_model("ventas", "PlanServicio")

    bodega = Servicio.objects.filter(codigo=BODEGA).first()
    if bodega is None:
        return
    # A price or cycle already entered in the admin is kept.
    if bodega.precio_base is None:
        bodega.precio_base = PRECIO_LISTA
        bodega.precio_confirmado = False
    if bodega.ciclo_pago_default_id is None:
        bodega.ciclo_pago_default = CicloPago.objects.get(codigo="anual")
    bodega.se_vende_en_portal = True
    bodega.save()

    for datos in PLANES:
        datos = dict(datos)
        codigo = datos.pop("codigo")
        ciclo = CicloPago.objects.get(codigo=datos.pop("ciclo"))
        # An existing plan keeps whatever was edited in the admin.
        PlanServicio.objects.get_or_create(
            servicio=bodega,
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


def unseed(apps, schema_editor):
    Servicio = apps.get_model("ventas", "Servicio")
    PlanServicio = apps.get_model("ventas", "PlanServicio")
    PlanServicio.objects.filter(
        servicio__codigo=BODEGA,
        codigo__in=[plan["codigo"] for plan in PLANES],
    ).delete()
    Servicio.objects.filter(codigo=BODEGA).update(se_vende_en_portal=False)
    Servicio.objects.filter(
        codigo=BODEGA,
        precio_base=PRECIO_LISTA,
        precio_confirmado=False,
        items_vendidos__isnull=True,
        contrataciones__isnull=True,
    ).update(precio_base=None, ciclo_pago_default=None)


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0012_seed_planes_domicilio"),
        ("ventas", "0010_seed_servicios_visibles"),
        ("contratos", "0004_contrato_borrador"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
