from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from crm_easyoffice.clientes.models import Cliente
from crm_easyoffice.clientes.models import Empresa
from crm_easyoffice.clientes.models import Persona
from crm_easyoffice.clientes.models import RepresentanteLegal
from crm_easyoffice.clientes.models import TipoCliente
from crm_easyoffice.clientes.services import guardar_parte
from crm_easyoffice.core.validators import normalize_rut
from crm_easyoffice.core.validators import validate_rut

RUT_YA_REGISTRADO = _("A client with this RUT already exists.")
RUT_DE_OTRA_PARTE = _("This RUT belongs to another person or company on record.")


class FolioObsoletoField(serializers.CharField):
    """The client's codigo under its old name, kept for one release.

    Cliente.folio became codigo when the folio moved to the contract. Remove
    this field once the frontend reads codigo.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(source="codigo", read_only=True, **kwargs)


class RutField(serializers.CharField):
    """Accepts a RUT as typed and stores it normalised."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 12)
        super().__init__(validators=[validate_rut], **kwargs)

    def to_internal_value(self, data: Any) -> str:
        return normalize_rut(super().to_internal_value(data))


class PersonaSerializer(serializers.ModelSerializer[Persona]):
    rut = RutField()

    class Meta:
        model = Persona
        fields = [
            "rut",
            "nombres",
            "apellido_paterno",
            "apellido_materno",
            "nacionalidad",
            "estado_civil",
            "profesion",
            "domicilio",
            "comuna",
            "region",
            "email",
            "telefono",
        ]


class EmpresaSerializer(serializers.ModelSerializer[Empresa]):
    rut = RutField()

    class Meta:
        model = Empresa
        fields = ["rut", "razon_social", "nombre_fantasia", "giro", "email", "telefono"]


class RepresentanteSerializer(serializers.ModelSerializer[RepresentanteLegal]):
    rut = serializers.CharField(source="persona.rut")
    nombre = serializers.CharField(source="persona.nombre_completo")

    class Meta:
        model = RepresentanteLegal
        fields = [
            "id",
            "rut",
            "nombre",
            "vigente_desde",
            "vigente_hasta",
            "fecha_instrumento",
            "sitio_o_notaria",
            "activo",
        ]
        read_only_fields = fields


@extend_schema_serializer(deprecate_fields=["folio"])
class ClienteResumenSerializer(serializers.ModelSerializer[Cliente]):
    folio = FolioObsoletoField()
    tipo = serializers.ChoiceField(choices=TipoCliente.choices)
    rut = serializers.CharField(source="parte.rut")
    nombre = serializers.CharField()
    email = serializers.CharField(source="parte.email")
    telefono = serializers.CharField(source="parte.telefono")

    class Meta:
        model = Cliente
        fields = [
            "id",
            "codigo",
            "folio",
            "tipo",
            "rut",
            "nombre",
            "email",
            "telefono",
            "activo",
            "created_at",
        ]
        read_only_fields = fields


@extend_schema_serializer(deprecate_fields=["folio"])
class ClienteSerializer(serializers.ModelSerializer[Cliente]):
    """A client record. Writes carry the nested data of its persona or empresa."""

    folio = FolioObsoletoField()
    tipo = serializers.ChoiceField(choices=TipoCliente.choices)
    persona = PersonaSerializer(required=False)
    empresa = EmpresaSerializer(required=False)
    representantes = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = [
            "id",
            "codigo",
            "folio",
            "tipo",
            "activo",
            "created_at",
            "updated_at",
            "persona",
            "empresa",
            "representantes",
        ]
        read_only_fields = ["id", "codigo", "created_at", "updated_at"]

    @extend_schema_field(RepresentanteSerializer(many=True))
    def get_representantes(self, cliente: Cliente) -> list[Any]:
        if cliente.empresa is None:
            return []
        representantes = cliente.empresa.representantes.select_related("persona")
        return list(RepresentanteSerializer(representantes, many=True).data)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        tipo: str = attrs.get("tipo") or (self.instance.tipo if self.instance else "")
        if self.instance is not None and tipo != self.instance.tipo:
            raise serializers.ValidationError(
                {"tipo": _("The client type cannot change.")},
            )

        otro = (
            TipoCliente.EMPRESA if tipo == TipoCliente.PERSONA else TipoCliente.PERSONA
        )
        if otro in attrs:
            raise serializers.ValidationError(
                {otro: _("Does not match the client type.")},
            )

        datos = attrs.get(tipo)
        if self.instance is None and datos is None:
            raise serializers.ValidationError({tipo: _("This field is required.")})
        if datos and "rut" in datos:
            self._validate_rut_available(tipo, datos["rut"])
        return attrs

    def _validate_rut_available(self, tipo: str, rut: str) -> None:
        """Reject a RUT held by another client (HU-52, RN-04).

        A Persona or Empresa on record that is not a client yet, such as a
        legal representative, is linked on create instead of rejected.
        """
        modelo = Persona if tipo == TipoCliente.PERSONA else Empresa
        existente = modelo.objects.filter(rut=rut).first()
        if existente is None:
            return
        if self.instance is not None:
            if existente.pk == getattr(self.instance, f"{tipo}_id"):
                return
            raise serializers.ValidationError({tipo: {"rut": [RUT_DE_OTRA_PARTE]}})
        if Cliente.objects.filter(**{tipo: existente}).exists():
            raise serializers.ValidationError({tipo: {"rut": [RUT_YA_REGISTRADO]}})

    def create(self, validated_data: dict[str, Any]) -> Cliente:
        tipo = validated_data.pop("tipo")
        datos = validated_data.pop(tipo)
        with transaction.atomic():
            parte = guardar_parte(tipo, datos)
            return Cliente.objects.create(**{tipo: parte}, **validated_data)

    def update(self, instance: Cliente, validated_data: dict[str, Any]) -> Cliente:
        validated_data.pop("tipo", None)
        datos = validated_data.pop(instance.tipo, None)
        with transaction.atomic():
            if datos:
                parte = instance.parte
                for campo, valor in datos.items():
                    setattr(parte, campo, valor)
                parte.save()
            return super().update(instance, validated_data)
