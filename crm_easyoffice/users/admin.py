from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from crm_easyoffice.core.throttling import IngresoThrottle

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import User

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


def _con_limite_de_intentos(login):
    """Limit the admin's sign-in attempts, sharing the API login's rate."""

    def vista(request, extra_context=None):
        limite = IngresoThrottle()
        if request.method == "POST" and not limite.allow_request(request, None):
            return HttpResponse(
                _("Demasiados intentos de ingreso. Espera un momento."),
                status=429,
                headers={"Retry-After": str(int(limite.wait() or 0))},
            )
        return login(request, extra_context)

    return vista


admin.site.login = _con_limite_de_intentos(admin.site.login)  # type: ignore[method-assign]


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name",)}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    list_display = ["email", "name", "is_superuser"]
    search_fields = ["name"]
    ordering = ["id"]
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )
