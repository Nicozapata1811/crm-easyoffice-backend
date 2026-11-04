"""Install the audit triggers on the audited tables (RF-15, MD-16, AD-08).

A frozen copy of ``core.auditoria.registro``: a later change to that module
needs a migration of its own. ``core/tests/test_auditoria_registro.py``
checks that the triggers in the database match the module.
"""

from django.db import migrations

from crm_easyoffice.core.auditoria import sql

MASCARAS = ("password",)

AUDITADAS = (
    ("clientes_persona", "clientes.persona", ("last_login",)),
    ("clientes_empresa", "clientes.empresa", ("last_login",)),
    ("clientes_cliente", "clientes.cliente", ("last_login",)),
    ("clientes_representantelegal", "clientes.representantelegal", ("last_login",)),
    ("clientes_cuentacliente", "clientes.cuentacliente", ("last_login",)),
    ("configuracion_configempresa", "configuracion.configempresa", ("last_login",)),
    ("configuracion_cuentapago", "configuracion.cuentapago", ("last_login",)),
    ("configuracion_marca", "configuracion.marca", ("last_login",)),
    ("inmuebles_oficina", "inmuebles.oficina", ("last_login",)),
    ("inmuebles_autorizante", "inmuebles.autorizante", ("last_login",)),
    ("contratos_duracioncontrato", "contratos.duracioncontrato", ("last_login",)),
    ("contratos_contrato", "contratos.contrato", ("last_login",)),
    ("contratos_serviciocontratado", "contratos.serviciocontratado", ("last_login",)),
    ("tramites_tipotramite", "tramites.tipotramite", ("last_login",)),
    ("tramites_motivopendiente", "tramites.motivopendiente", ("last_login",)),
    ("tramites_tramite", "tramites.tramite", ("last_login",)),
    ("documentos_plantilladocumento", "documentos.plantilladocumento", ("last_login",)),
    ("documentos_versionplantilla", "documentos.versionplantilla", ("last_login",)),
    ("documentos_documento", "documentos.documento", ("last_login", "datos_snapshot")),
    ("documentos_firmante", "documentos.firmante", ("last_login",)),
    ("ventas_ciclopago", "ventas.ciclopago", ("last_login",)),
    ("ventas_servicio", "ventas.servicio", ("last_login",)),
    ("ventas_planservicio", "ventas.planservicio", ("last_login",)),
    ("ventas_venta", "ventas.venta", ("last_login",)),
    ("ventas_itemventa", "ventas.itemventa", ("last_login",)),
    ("ventas_ordenpago", "ventas.ordenpago", ("last_login", "redirect_url")),
    ("ventas_pago", "ventas.pago", ("last_login", "respuesta")),
    ("users_user", "users.user", ("last_login",)),
    ("auth_group", "auth.group", ("last_login",)),
)

RELACIONES = (
    ("users_user_groups", "users.user", "user_id", "rol"),
    ("users_user_user_permissions", "users.user", "user_id", "permiso"),
    ("auth_group_permissions", "auth.group", "group_id", "permiso"),
)

TABLAS = [tabla for tabla, *_ in AUDITADAS] + [tabla for tabla, *_ in RELACIONES]

CREAR = [sql.crear_trigger(t, e, x, MASCARAS) for t, e, x in AUDITADAS] + [
    sql.crear_trigger_relacion(*relacion) for relacion in RELACIONES
]
ELIMINAR = [sql.eliminar_trigger(tabla) for tabla in TABLAS]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_registro_auditoria"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("users", "0001_initial"),
        ("clientes", "0006_rename_folio_codigo"),
        ("configuracion", "0003_permisos_roles"),
        ("inmuebles", "0006_autorizante_documento_reverso"),
        ("contratos", "0004_contrato_borrador"),
        ("tramites", "0005_bodega_en_portal"),
        ("documentos", "0003_seed_plt02"),
        ("ventas", "0013_seed_planes_bodega"),
    ]

    operations = [migrations.RunSQL(CREAR, ELIMINAR)]
