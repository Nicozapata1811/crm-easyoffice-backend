"""Audit the contract expiry alerts (HU-42, RF-15).

A frozen copy of the ``contratos_alertavencimiento`` entry of
``core.auditoria.registro``.
"""

from django.db import migrations

from crm_easyoffice.core.auditoria import sql

TABLA = "contratos_alertavencimiento"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_auditoria_mfa_tokens"),
        ("contratos", "0005_alertas_vencimiento"),
    ]

    operations = [
        migrations.RunSQL(
            sql.crear_trigger(
                TABLA,
                "contratos.alertavencimiento",
                ("last_login",),
                ("password",),
            ),
            sql.eliminar_trigger(TABLA),
        ),
    ]
