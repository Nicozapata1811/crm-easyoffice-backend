from decimal import Decimal

from django.db import migrations

# ASSUMPTION: pending validation with Easy Office. Example prices from the
# prototype (06_ux_mockups); none is confirmed.
SERVICIOS = [
    ("domicilio-tributario", "Domicilio tributario", Decimal(14900)),
    ("firma-electronica-avanzada", "Firma electrónica avanzada", Decimal(3500)),
]


def seed_servicios(apps, schema_editor):
    Servicio = apps.get_model("ventas", "Servicio")
    for codigo, nombre, precio in SERVICIOS:
        Servicio.objects.get_or_create(
            codigo=codigo,
            defaults={"nombre": nombre, "precio_base": precio},
        )


class Migration(migrations.Migration):
    dependencies = [("ventas", "0001_initial")]

    operations = [migrations.RunPython(seed_servicios, migrations.RunPython.noop)]
