from django.db import migrations

# The three branches of Easy Office's form, by folio code. Address and rol de
# avalúo are placeholders: the real ones are entered in the admin and never
# committed.
#
# ASSUMPTION: pending validation with Easy Office. The San Antonio branch is
# physically in Algarrobo, and the form gives no region for it; Algarrobo is
# in the Valparaíso region.
SUCURSALES = [
    ("LF", "La Florida", "La Florida", "Región Metropolitana de Santiago"),
    ("VL", "Valparaíso", "Valparaíso", "Región de Valparaíso"),
    ("SA", "San Antonio", "Algarrobo", "Región de Valparaíso"),
]


def seed_sucursales(apps, schema_editor):
    Oficina = apps.get_model("inmuebles", "Oficina")
    for codigo, nombre, comuna, region in SUCURSALES:
        Oficina.objects.get_or_create(
            codigo_sucursal=codigo,
            defaults={
                "tipo": "oficina",
                "nombre": nombre,
                "calle": "Por completar",
                "numero": "S/N",
                "comuna": comuna,
                "region": region,
                "rol_avaluo": f"PENDIENTE-{codigo}",
            },
        )


def unseed_sucursales(apps, schema_editor):
    # Only placeholders nobody has completed or linked to an authoriser.
    Oficina = apps.get_model("inmuebles", "Oficina")
    Oficina.objects.filter(
        codigo_sucursal__in=[codigo for codigo, *_ in SUCURSALES],
        calle="Por completar",
        rol_avaluo__startswith="PENDIENTE-",
        autorizaciones__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("inmuebles", "0002_inmueble_autorizante")]

    operations = [migrations.RunPython(seed_sucursales, unseed_sucursales)]
