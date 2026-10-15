from drf_spectacular.utils import extend_schema_field
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from crm_easyoffice.users.models import User


class UserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["name", "url"]

        extra_kwargs = {
            "url": {"view_name": "api:user-detail", "lookup_field": "pk"},
        }


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)


@extend_schema_serializer(deprecate_fields=["folio"])
class ClienteSesionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    # Old name of codigo, kept for one release until the frontend reads codigo.
    folio = serializers.CharField(source="codigo", read_only=True)
    nombre = serializers.CharField()


class SessionUserSerializer(serializers.ModelSerializer[User]):
    tipo = serializers.SerializerMethodField()
    cliente = serializers.SerializerMethodField()
    rol = serializers.SerializerMethodField()
    permisos = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "tipo", "cliente", "rol", "permisos"]

    @staticmethod
    def _cuenta(user: User):
        return getattr(user, "cuenta_cliente", None)

    @extend_schema_field(serializers.ChoiceField(choices=["cliente", "staff"]))
    def get_tipo(self, user: User) -> str:
        return "cliente" if self._cuenta(user) else "staff"

    @extend_schema_field(ClienteSesionSerializer(allow_null=True))
    def get_cliente(self, user: User) -> dict | None:
        cuenta = self._cuenta(user)
        if cuenta is None:
            return None
        return ClienteSesionSerializer(cuenta.cliente).data

    def get_rol(self, user: User) -> str | None:
        return user.groups.order_by("name").values_list("name", flat=True).first()

    def get_permisos(self, user: User) -> list[str]:
        return sorted(user.get_all_permissions())
