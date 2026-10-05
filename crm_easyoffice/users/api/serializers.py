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


class SessionUserSerializer(serializers.ModelSerializer[User]):
    rol = serializers.SerializerMethodField()
    permisos = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "rol", "permisos"]

    def get_rol(self, user: User) -> str | None:
        return user.groups.order_by("name").values_list("name", flat=True).first()

    def get_permisos(self, user: User) -> list[str]:
        return sorted(user.get_all_permissions())
