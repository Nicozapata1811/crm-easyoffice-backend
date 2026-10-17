from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import FormularioDomicilioView
from .views import TramitePortalViewSet

router = SimpleRouter()
router.register("tramites", TramitePortalViewSet, basename="tramite")

urlpatterns = [
    path(
        "tramites/domicilio/formulario/",
        FormularioDomicilioView.as_view(),
        name="tramite-formulario-domicilio",
    ),
    *router.urls,
]
