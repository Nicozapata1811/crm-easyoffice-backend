from django.db import migrations, models


def assign_folios(apps, schema_editor):
    Cliente = apps.get_model("clientes", "Cliente")
    for cliente in Cliente.objects.filter(folio__isnull=True).only("pk"):
        cliente.folio = f"CLI-{cliente.pk:06d}"
        cliente.save(update_fields=["folio"])


class Migration(migrations.Migration):

    dependencies = [
        ("clientes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cliente",
            name="folio",
            field=models.CharField(
                editable=False,
                help_text="Assigned on creation from the primary key.",
                max_length=12,
                null=True,
                unique=True,
                verbose_name="folio",
            ),
        ),
        migrations.RunPython(assign_folios, migrations.RunPython.noop),
    ]
