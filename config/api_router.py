from django.conf import settings
from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from crm_easyoffice.prospectos.api.views import ProspectoWebhookView
from crm_easyoffice.tramites.api.views import CatalogoView
from crm_easyoffice.users.api.views import UserViewSet

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)


app_name = "api"
urlpatterns = [
    *router.urls,
    path("catalogo/", CatalogoView.as_view(), name="catalogo"),
    path(
        "integraciones/sitio/prospectos/",
        ProspectoWebhookView.as_view(),
        name="webhook-sitio-prospectos",
    ),
]
