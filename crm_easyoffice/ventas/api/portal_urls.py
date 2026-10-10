from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import MedioPagoPortalView
from .views import OrdenPortalView
from .views import ServicioPortalView
from .views import VentaPortalViewSet

router = SimpleRouter()
router.register("ventas", VentaPortalViewSet, basename="venta")

urlpatterns = [
    path("servicios/", ServicioPortalView.as_view(), name="servicio-list"),
    path("medios-pago/", MedioPagoPortalView.as_view(), name="medio-pago-list"),
    path("ordenes/<int:pk>/", OrdenPortalView.as_view(), name="orden-detail"),
    *router.urls,
]
