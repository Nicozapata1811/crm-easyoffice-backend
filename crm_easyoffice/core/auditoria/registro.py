"""What the audit log records, and what it never stores (RF-15, MD-16).

This module is the one place that decides it. Tables are named by string, so
``core`` imports no other app. ``core/migrations/0005_triggers_auditoria``
installs the triggers from a frozen copy of these lists; a test compares the
triggers in the database with this module, and another one fails when a
model is in neither list, so a new model forces a decision.

To change it: edit the lists here, then add a migration that drops and
recreates the affected triggers with ``core.auditoria.sql``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Never stored, on any table. ``last_login`` changes on every sign-in; the
# sign-in itself is an event.
EXCLUIDOS_GLOBAL = ("last_login",)

# Stored as "***" when set or changed, never the value: a password change is
# worth recording, its hash is not.
ENMASCARADOS = ("password",)


@dataclass(frozen=True)
class Auditada:
    """A table whose row changes are recorded under ``entidad``."""

    tabla: str
    entidad: str
    excluir: tuple[str, ...] = ()

    @property
    def excluidos(self) -> tuple[str, ...]:
        return (*EXCLUIDOS_GLOBAL, *self.excluir)


@dataclass(frozen=True)
class Relacion:
    """A many-to-many row recorded as a change of its owner.

    Adding or removing the row records ``{clave: name}`` on ``entidad``
    (the owner's id in ``columna``), so the history reads "rol: Ejecutivo"
    instead of a row of ids.
    """

    tabla: str
    entidad: str
    columna: str
    clave: str  # "rol" or "permiso"


AUDITADAS = (
    Auditada("clientes_persona", "clientes.persona"),
    Auditada("clientes_empresa", "clientes.empresa"),
    Auditada("clientes_cliente", "clientes.cliente"),
    Auditada("clientes_representantelegal", "clientes.representantelegal"),
    Auditada("clientes_cuentacliente", "clientes.cuentacliente"),
    Auditada("configuracion_configempresa", "configuracion.configempresa"),
    Auditada("configuracion_cuentapago", "configuracion.cuentapago"),
    Auditada("configuracion_marca", "configuracion.marca"),
    # File fields hold the stored name only; the content never reaches here.
    Auditada("inmuebles_oficina", "inmuebles.oficina"),
    Auditada("inmuebles_autorizante", "inmuebles.autorizante"),
    Auditada("contratos_duracioncontrato", "contratos.duracioncontrato"),
    Auditada("contratos_contrato", "contratos.contrato"),
    Auditada("contratos_serviciocontratado", "contratos.serviciocontratado"),
    Auditada("tramites_tipotramite", "tramites.tipotramite"),
    Auditada("tramites_motivopendiente", "tramites.motivopendiente"),
    Auditada("tramites_tramite", "tramites.tramite"),
    Auditada("documentos_plantilladocumento", "documentos.plantilladocumento"),
    Auditada("documentos_versionplantilla", "documentos.versionplantilla"),
    # The snapshot is a frozen copy of personal data that the document row
    # already keeps and never changes: copying it again adds nothing.
    Auditada("documentos_documento", "documentos.documento", ("datos_snapshot",)),
    Auditada("documentos_firmante", "documentos.firmante"),
    Auditada("ventas_ciclopago", "ventas.ciclopago"),
    Auditada("ventas_servicio", "ventas.servicio"),
    Auditada("ventas_planservicio", "ventas.planservicio"),
    Auditada("ventas_venta", "ventas.venta"),
    Auditada("ventas_itemventa", "ventas.itemventa"),
    # The checkout URL carries the provider's payment token.
    Auditada("ventas_ordenpago", "ventas.ordenpago", ("redirect_url",)),
    # The provider's raw answer stays in its own table.
    Auditada("ventas_pago", "ventas.pago", ("respuesta",)),
    Auditada("users_user", "users.user"),
    Auditada("auth_group", "auth.group"),
)

RELACIONES = (
    Relacion("users_user_groups", "users.user", "user_id", "rol"),
    Relacion("users_user_user_permissions", "users.user", "user_id", "permiso"),
    Relacion("auth_group_permissions", "auth.group", "group_id", "permiso"),
)

# Tables deliberately left out: logs of their own, counters, framework
# state, or secrets.
NO_AUDITADAS = (
    "core_registroauditoria",  # the log itself
    "tramites_eventotramite",  # append-only history of its own
    "ventas_eventopago",  # webhook log with the raw payloads
    "contratos_correlativofolio",  # folio counter, changes on every contract
    "auth_permission",
    "django_content_type",
    "django_session",
    "django_site",
    "django_admin_log",
    "account_emailaddress",
    "account_emailconfirmation",
    "mfa_authenticator",  # MFA secrets
    "authtoken_token",  # API tokens
    "django_celery_beat_solarschedule",
    "django_celery_beat_intervalschedule",
    "django_celery_beat_clockedschedule",
    "django_celery_beat_crontabschedule",
    "django_celery_beat_periodictasks",
    "django_celery_beat_periodictask",
)

# The field that names a record in the consultation API (one query per
# entity on a page); any other entity shows "#id".
ETIQUETAS = {
    "clientes.persona": "rut",
    "clientes.empresa": "razon_social",
    "clientes.cliente": "codigo",
    "configuracion.configempresa": "razon_social",
    "configuracion.marca": "nombre",
    "inmuebles.oficina": "nombre",
    "contratos.contrato": "folio",
    "contratos.serviciocontratado": "nombre",
    "tramites.tipotramite": "nombre",
    "tramites.motivopendiente": "nombre",
    "tramites.tramite": "folio",
    "documentos.plantilladocumento": "codigo",
    "ventas.ciclopago": "nombre",
    "ventas.servicio": "nombre",
    "ventas.planservicio": "nombre",
    "ventas.venta": "folio",
    "ventas.itemventa": "nombre",
    "ventas.ordenpago": "referencia",
    "users.user": "email",
    "auth.group": "name",
}


@dataclass(frozen=True)
class Vinculo:
    """A record whose history belongs to another's.

    ``hija``: rows of ``entidad`` whose ``columna`` points at the record (its
    lines, its documents). ``padre``: the record of ``entidad`` that the
    record's own ``columna`` points at (a client's persona).
    """

    entidad: str
    columna: str
    hija: bool


# The history of a record also shows these related records, followed
# recursively. ASSUMPTION: pending validation with Easy Office. A client's
# history covers its own data (persona or empresa, representatives, portal
# account), not its contracts or cases, which have a history of their own.
HISTORIAL = {
    "clientes.cliente": (
        Vinculo("clientes.persona", "persona_id", hija=False),
        Vinculo("clientes.empresa", "empresa_id", hija=False),
        Vinculo("clientes.cuentacliente", "cliente_id", hija=True),
    ),
    "clientes.empresa": (
        Vinculo("clientes.representantelegal", "empresa_id", hija=True),
    ),
    "clientes.representantelegal": (
        Vinculo("clientes.persona", "persona_id", hija=False),
    ),
    "tramites.tramite": (
        Vinculo("contratos.contrato", "contrato_id", hija=False),
        Vinculo("ventas.venta", "venta_id", hija=False),
        Vinculo("documentos.documento", "tramite_id", hija=True),
    ),
    "contratos.contrato": (
        Vinculo("contratos.serviciocontratado", "contrato_id", hija=True),
    ),
    "documentos.documento": (
        Vinculo("documentos.firmante", "documento_id", hija=True),
    ),
    "ventas.venta": (
        Vinculo("ventas.itemventa", "venta_id", hija=True),
        Vinculo("ventas.ordenpago", "venta_id", hija=True),
    ),
    "ventas.ordenpago": (Vinculo("ventas.pago", "orden_id", hija=True),),
}
