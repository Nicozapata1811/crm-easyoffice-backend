from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ventas', '0008_permisos_ciclopago'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='servicio',
            options={'ordering': ['orden', 'nombre'], 'verbose_name': 'servicio', 'verbose_name_plural': 'servicios'},
        ),
        migrations.AlterField(
            model_name='servicio',
            name='se_vende_en_portal',
            field=models.BooleanField(default=True, help_text='Can be bought online. Requires a price.', verbose_name='se vende en el portal'),
        ),
        migrations.AddField(
            model_name='servicio',
            name='visible_en_portal',
            field=models.BooleanField(default=False, help_text='Shown as a card on the portal landing, bookable or not.', verbose_name='visible en el portal'),
        ),
        migrations.AddField(
            model_name='servicio',
            name='orden',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='orden'),
        ),
    ]
