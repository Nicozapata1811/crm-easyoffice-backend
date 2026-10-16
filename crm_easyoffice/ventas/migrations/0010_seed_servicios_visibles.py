from django.db import migrations

# The landing shows Domicilio tributario first; the documents Easy Office
# delivered (PLT-02..05) and the poder simple follow as "Próximamente".
DOMICILIO = "domicilio-tributario"
ORDEN_DOMICILIO = 10

# ASSUMPTION: pending validation with Easy Office. How each of these is sold,
# its price and its payment cycle are unconfirmed, so none is bookable online
# and none has a price. Names and descriptions are ours, not contract text,
# and are edited in the admin.
VISIBLES = [
    {
        "codigo": "bodega",
        "nombre": "Bodega",
        "descripcion": "Contrato para usar una bodega como espacio de almacenamiento.",
        "orden": 20,
    },
    {
        "codigo": "arriendo-vehiculo",
        "nombre": "Arriendo de vehículo",
        "descripcion": "Contrato de arriendo de un vehículo entre su dueño y tu empresa.",
        "orden": 30,
    },
    {
        "codigo": "arriendo-estacionamiento",
        "nombre": "Arriendo de estacionamiento",
        "descripcion": "Contrato de arriendo de un estacionamiento.",
        "orden": 40,
    },
    {
        "codigo": "acuerdo-accionistas",
        "nombre": "Acuerdo de accionistas",
        "descripcion": (
            "Acuerdo de los accionistas de una SpA para modificar sus estatutos."
        ),
        "orden": 50,
    },
    {
        "codigo": "poder-simple",
        "nombre": "Poder simple",
        "descripcion": "Documento para autorizar a otra persona a actuar en tu nombre.",
        "orden": 60,
    },
]

NUEVOS = [datos["codigo"] for datos in VISIBLES]


def seed(apps, schema_editor):
    Servicio = apps.get_model("ventas", "Servicio")

    Servicio.objects.filter(codigo=DOMICILIO).update(
        visible_en_portal=True,
        orden=ORDEN_DOMICILIO,
    )
    for datos in VISIBLES:
        datos = dict(datos)
        # An existing row keeps whatever was edited in the admin.
        Servicio.objects.get_or_create(
            codigo=datos.pop("codigo"),
            defaults={
                **datos,
                "precio_base": None,
                "precio_incluye_iva": True,
                "precio_confirmado": False,
                "ciclo_pago_default": None,
                "se_vende_en_portal": False,
                "visible_en_portal": True,
                "activo": True,
            },
        )


def unseed(apps, schema_editor):
    # Remove the added services unless something was sold or contracted.
    Servicio = apps.get_model("ventas", "Servicio")
    Servicio.objects.filter(
        codigo__in=NUEVOS,
        items_vendidos__isnull=True,
        contrataciones__isnull=True,
    ).delete()
    Servicio.objects.filter(codigo=DOMICILIO).update(visible_en_portal=False, orden=0)


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0009_servicio_visible_en_portal_orden"),
        # ServicioContratado.servicio, read by the reverse.
        ("contratos", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
