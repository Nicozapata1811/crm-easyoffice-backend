"""Audit the advanced-signature requests (IN-01, RF-15).

A frozen copy of the ``documentos_solicitudfirma`` entry of
``core.auditoria.registro``. ``EventoFirma`` is the provider's webhook log and
stays out, like ``EventoPago``.
"""

from django.db import migrations

from crm_easyoffice.core.auditoria import sql

TABLA = "documentos_solicitudfirma"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_permiso_auditoria"),
        ("documentos", "0005_permisos_firma_avanzada"),
    ]

    operations = [
        migrations.RunSQL(
            sql.crear_trigger(
                TABLA,
                "documentos.solicitudfirma",
                ("last_login",),
                ("password",),
            ),
            sql.eliminar_trigger(TABLA),
        ),
    ]
