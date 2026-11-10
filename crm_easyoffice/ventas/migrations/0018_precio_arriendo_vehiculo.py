"""A list price for the vehicle lease (PLT-03), so its case can be charged."""

from decimal import Decimal

from django.db import migrations

SERVICIO = "arriendo-vehiculo"
# ASSUMPTION: fictitious price until Easy Office sends its price list. Net,
# "más IVA" (meeting of 05-11-2026); edited in the admin, without code.
PRECIO = Decimal(30000)


def poner_precio(apps, schema_editor):
    apps.get_model("ventas", "Servicio").objects.filter(
        codigo=SERVICIO,
        precio_base__isnull=True,
    ).update(precio_base=PRECIO, precio_incluye_iva=False, precio_confirmado=False)


def quitar_precio(apps, schema_editor):
    apps.get_model("ventas", "Servicio").objects.filter(
        codigo=SERVICIO,
        precio_base=PRECIO,
        precio_incluye_iva=False,
    ).update(precio_base=None, precio_incluye_iva=True)


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0017_backfill_neto_iva"),
    ]

    operations = [migrations.RunPython(poner_precio, quitar_precio)]
