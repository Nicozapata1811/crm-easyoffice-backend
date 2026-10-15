from django.db import migrations, models


class Migration(migrations.Migration):
    """Rename Cliente.folio to codigo: the folio now belongs to the contract.

    Existing values are kept; reversing restores the old column name.
    """

    dependencies = [
        ("clientes", "0005_persona_datos_civiles_personeria"),
    ]

    operations = [
        migrations.RenameField(
            model_name="cliente",
            old_name="folio",
            new_name="codigo",
        ),
        migrations.AlterField(
            model_name="cliente",
            name="codigo",
            field=models.CharField(
                editable=False,
                help_text="Internal client code, assigned on creation from the primary key.",
                max_length=12,
                null=True,
                unique=True,
                verbose_name="código",
            ),
        ),
    ]
