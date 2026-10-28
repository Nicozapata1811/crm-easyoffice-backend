"""The audit triggers record row changes and the log cannot be altered (RF-15, RF-16).

Every name, RUT and value here is synthetic.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.db import DatabaseError
from django.db import connection
from django.db import transaction
from django.utils import timezone

from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.tests.factories import PersonaFactory
from crm_easyoffice.core.models import RegistroAuditoria
from crm_easyoffice.core.models import RegistroAuditoriaError
from crm_easyoffice.tramites.tests.factories import cuenta_empresa
from crm_easyoffice.users.tests.factories import UserFactory
from crm_easyoffice.ventas.models import OrdenPago
from crm_easyoffice.ventas.models import Pago
from crm_easyoffice.ventas.models import Venta

from .auditoria import entradas
from .auditoria import roles
from .auditoria import ultima

pytestmark = pytest.mark.django_db

Accion = RegistroAuditoria.Accion


class TestCambiosDeFilas:
    def test_insert_records_the_new_row(self):
        persona = PersonaFactory.create(nombres="Persona Sintética")

        entrada = ultima("clientes.persona", persona.pk)
        assert entrada.accion == Accion.CREAR
        assert entrada.valor_anterior is None
        assert entrada.valor_nuevo["nombres"] == "Persona Sintética"
        assert entrada.valor_nuevo["rut"] == persona.rut

    def test_update_records_only_what_changed(self):
        persona = PersonaFactory.create(telefono="+56 9 0000 0001")
        persona.telefono = "+56 9 0000 0002"
        persona.save()

        entrada = ultima("clientes.persona", persona.pk)
        assert entrada.accion == Accion.MODIFICAR
        assert entrada.valor_anterior == {"telefono": "+56 9 0000 0001"}
        assert entrada.valor_nuevo == {"telefono": "+56 9 0000 0002"}

    def test_queryset_update_is_recorded(self):
        persona = PersonaFactory.create(profesion="Ingeniera")
        Persona.objects.filter(pk=persona.pk).update(profesion="Diseñadora")

        assert ultima("clientes.persona", persona.pk).valor_nuevo == {
            "profesion": "Diseñadora",
        }

    def test_raw_sql_is_recorded(self):
        persona = PersonaFactory.create(comuna="Ñuñoa")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE clientes_persona SET comuna = %s WHERE id = %s",
                ["Providencia", persona.pk],
            )

        assert ultima("clientes.persona", persona.pk).valor_nuevo == {
            "comuna": "Providencia",
        }

    def test_delete_records_the_old_row(self):
        persona = PersonaFactory.create()
        pk, rut = persona.pk, persona.rut
        persona.delete()

        entrada = ultima("clientes.persona", pk)
        assert entrada.accion == Accion.ELIMINAR
        assert entrada.valor_anterior["rut"] == rut
        assert entrada.valor_nuevo is None

    def test_an_update_without_real_changes_records_nothing(self):
        persona = PersonaFactory.create()
        antes = entradas("clientes.persona", persona.pk).count()

        persona.save()  # only updated_at changes
        Persona.objects.filter(pk=persona.pk).update(nombres=persona.nombres)

        assert entradas("clientes.persona", persona.pk).count() == antes

    def test_without_context_the_change_is_the_systems(self):
        persona = PersonaFactory.create()

        entrada = ultima("clientes.persona", persona.pk)
        assert entrada.origen == RegistroAuditoria.Origen.SISTEMA
        assert entrada.usuario is None
        assert entrada.direccion_ip is None


class TestNuncaSeGuardan:
    def test_the_password_hash_is_never_stored(self):
        usuario = UserFactory.create(password="synthetic-Pass-123")  # noqa: S106
        usuario.set_password("otra-Clave-456")
        usuario.save()

        filas = entradas("users.user", usuario.pk)
        creacion, cambio = filas.first(), filas.last()
        assert creacion.valor_nuevo["password"] == "***"  # noqa: S105
        assert cambio.valor_anterior == {"password": "***"}
        assert cambio.valor_nuevo == {"password": "***"}
        for entrada in filas:
            texto = str(entrada.valor_anterior) + str(entrada.valor_nuevo)
            assert usuario.password not in texto
            assert "argon2" not in texto
            assert "pbkdf2" not in texto

    def test_last_login_is_never_stored(self):
        usuario = UserFactory.create()
        antes = entradas("users.user", usuario.pk).count()

        usuario.last_login = usuario.date_joined
        usuario.save(update_fields=["last_login"])

        assert entradas("users.user", usuario.pk).count() == antes
        assert all(
            "last_login" not in (e.valor_nuevo or {}) for e in entradas("users.user")
        )

    def test_payment_secrets_are_never_stored(self):
        cliente = cuenta_empresa().cliente
        venta = Venta.objects.create(cliente=cliente, total=1000)
        orden = OrdenPago.objects.create(
            venta=venta,
            proveedor="simulated",
            monto=1000,
            redirect_url="https://pago.example.test/?token=sintetico",
        )
        Pago.objects.create(
            orden=orden,
            monto=1000,
            pagado_en=timezone.now(),
            respuesta={"token": "sintetico"},
        )

        assert "redirect_url" not in ultima("ventas.ordenpago", orden.pk).valor_nuevo
        assert "respuesta" not in ultima("ventas.pago").valor_nuevo


class TestRoles:
    def test_role_membership_is_recorded_by_name(self):
        usuario = UserFactory.create()
        ejecutivo = Group.objects.get(name=roles.EJECUTIVO)
        administrador = Group.objects.get(name=roles.ADMINISTRADOR)

        usuario.groups.add(ejecutivo)
        usuario.groups.remove(ejecutivo)
        usuario.groups.add(administrador)

        cambios = [
            (e.valor_anterior, e.valor_nuevo)
            for e in entradas("users.user", usuario.pk).filter(accion=Accion.MODIFICAR)
            if "rol" in (e.valor_anterior or e.valor_nuevo)
        ]
        assert cambios == [
            (None, {"rol": roles.EJECUTIVO}),
            ({"rol": roles.EJECUTIVO}, None),
            (None, {"rol": roles.ADMINISTRADOR}),
        ]

    def test_group_permissions_are_recorded(self):
        grupo = Group.objects.create(name="Rol sintético")
        permiso = Permission.objects.get(codename="view_cliente")
        grupo.permissions.add(permiso)

        entrada = ultima("auth.group", grupo.pk)
        assert entrada.valor_nuevo == {"permiso": "clientes.view_cliente"}


def ejecutar(sentencia: str) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        # Deferred foreign key checks would block TRUNCATE first.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(sentencia)


class TestProteccion:
    @pytest.mark.parametrize(
        "sentencia",
        [
            "UPDATE core_registroauditoria SET entidad = 'alterada'",
            "DELETE FROM core_registroauditoria",
            "TRUNCATE core_registroauditoria",
            "TRUNCATE core_registroauditoria CASCADE",
        ],
    )
    def test_raw_sql_cannot_alter_the_log(self, sentencia):
        PersonaFactory.create()
        assert RegistroAuditoria.objects.exists()

        with pytest.raises(DatabaseError, match="no se puede modificar"):
            ejecutar(sentencia)

    def test_the_orm_cannot_alter_the_log(self):
        PersonaFactory.create()
        with pytest.raises(DatabaseError), transaction.atomic():
            RegistroAuditoria.objects.update(entidad="alterada")
        with pytest.raises(DatabaseError), transaction.atomic():
            RegistroAuditoria.objects.all().delete()

    def test_the_model_refuses_to_change_or_delete_an_entry(self):
        PersonaFactory.create()
        entrada = RegistroAuditoria.objects.first()

        entrada.entidad = "alterada"
        with pytest.raises(RegistroAuditoriaError):
            entrada.save()
        with pytest.raises(RegistroAuditoriaError):
            entrada.delete()
