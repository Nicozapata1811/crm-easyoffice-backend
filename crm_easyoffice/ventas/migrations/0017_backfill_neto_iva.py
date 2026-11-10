"""Net and VAT of the sales made before the split was stored.

Every price sold so far reads VAT included (``precio_incluye_iva`` true), so
what was charged does not change: the net is the amount / 1,19, rounded half
up, and the VAT is the rest. The arithmetic is written here, frozen, rather
than imported from ventas.montos.
"""

from decimal import ROUND_HALF_UP
from decimal import Decimal

from django.db import migrations

DIVISOR = Decimal("1.19")


def _neto(total):
    return (total / DIVISOR).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def backfill(apps, schema_editor):
    Venta = apps.get_model("ventas", "Venta")
    ItemVenta = apps.get_model("ventas", "ItemVenta")
    for item in ItemVenta.objects.filter(neto=0, iva=0).exclude(subtotal=0):
        neto = _neto(item.subtotal)
        ItemVenta.objects.filter(pk=item.pk).update(neto=neto, iva=item.subtotal - neto)
    for venta in Venta.objects.filter(neto=0, iva=0).exclude(total=0):
        neto = _neto(venta.total)
        Venta.objects.filter(pk=venta.pk).update(neto=neto, iva=venta.total - neto)


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0016_venta_neto_iva"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
