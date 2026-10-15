from django.db import migrations

# Obviously fictitious values: the real company data and bank accounts are
# entered in the admin and never committed. The RUT is left blank rather than
# invented, so it cannot collide with a real one.
RAZON_SOCIAL = "Easy Office SpA"
TEXTO_EJEMPLO = "DATOS DE PAGO DE EJEMPLO – REEMPLAZAR EN EL ADMIN"

# ASSUMPTION: pending validation with Easy Office. Both brands belong to one
# company (ACTA-002, D2-02); each has its own account in the form.
MARCAS = ["EASY OFFICE", "INOFFICE"]


def seed(apps, schema_editor):
    ConfigEmpresa = apps.get_model("configuracion", "ConfigEmpresa")
    CuentaPago = apps.get_model("configuracion", "CuentaPago")
    Marca = apps.get_model("configuracion", "Marca")

    if not ConfigEmpresa.objects.exists():
        ConfigEmpresa.objects.create(razon_social=RAZON_SOCIAL)

    for nombre in MARCAS:
        if Marca.objects.filter(nombre=nombre).exists():
            continue
        cuenta = CuentaPago.objects.create(
            banco="Banco de Ejemplo",
            tipo_cuenta="Cuenta corriente",
            numero="00-000-00000-0",
            titular="Titular de Ejemplo",
            texto_contrato=f"{TEXTO_EJEMPLO} ({nombre})",
        )
        Marca.objects.create(nombre=nombre, cuenta_pago_default=cuenta)


class Migration(migrations.Migration):
    dependencies = [("configuracion", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
