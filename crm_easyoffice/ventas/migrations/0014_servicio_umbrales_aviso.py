"""Notice thresholds per catalogue service (HU-42, RF-13).

The column starts empty so that ``0015`` seeds it with a recorded update; the
second operation only changes the default that new services get.
"""

import django.contrib.postgres.fields
import django.core.validators
from django.db import migrations
from django.db import models

import crm_easyoffice.ventas.models


def _umbrales(default):
    return django.contrib.postgres.fields.ArrayField(
        base_field=models.PositiveSmallIntegerField(
            validators=[django.core.validators.MinValueValidator(1)],
        ),
        blank=True,
        default=default,
        help_text=(
            "Days before a contract's expiry to alert, separated by commas. "
            "Empty: this service does not alert."
        ),
        size=None,
        validators=[crm_easyoffice.ventas.models.validar_umbrales_distintos],
        verbose_name="umbrales de aviso (días)",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ventas", "0013_seed_planes_bodega"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicio",
            name="umbrales_aviso_dias",
            field=_umbrales(list),
        ),
        migrations.AlterField(
            model_name="servicio",
            name="umbrales_aviso_dias",
            field=_umbrales(crm_easyoffice.ventas.models.umbrales_por_defecto),
        ),
    ]
