"""Audit second factors and API tokens, without their secrets (RF-15, RS-04).

A frozen copy of the ``mfa_authenticator`` and ``authtoken_token`` entries of
``core.auditoria.registro``.
"""

from django.db import migrations

from crm_easyoffice.core.auditoria import sql


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_acciones_firma"),
        ("mfa", "0003_authenticator_type_uniq"),
        ("authtoken", "0004_alter_tokenproxy_options"),
    ]

    operations = [
        migrations.RunSQL(
            sql.crear_trigger(
                "mfa_authenticator",
                "mfa.authenticator",
                ("last_login", "data", "last_used_at"),
                ("password",),
            ),
            sql.eliminar_trigger("mfa_authenticator"),
        ),
        migrations.RunSQL(
            sql.crear_trigger(
                "authtoken_token",
                "authtoken.token",
                ("last_login", "key"),
                ("password",),
            ),
            sql.eliminar_trigger("authtoken_token"),
        ),
    ]
