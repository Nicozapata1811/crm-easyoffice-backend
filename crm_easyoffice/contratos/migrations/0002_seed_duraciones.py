from django.db import migrations

# Terms offered by Easy Office's contract form, in months.
DURACIONES = [1, 3, 4, 6, 12]


def seed(apps, schema_editor):
    DuracionContrato = apps.get_model("contratos", "DuracionContrato")
    for meses in DURACIONES:
        DuracionContrato.objects.get_or_create(meses=meses)


class Migration(migrations.Migration):
    dependencies = [("contratos", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
