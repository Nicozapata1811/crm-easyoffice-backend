from django.urls import path

from .views import PagoRetornoView
from .views import PagoWebhookView

app_name = "pagos"
urlpatterns = [
    path("retorno/<int:orden_id>/", PagoRetornoView.as_view(), name="retorno"),
    path(
        "webhooks/<slug:proveedor>/<slug:evento>/",
        PagoWebhookView.as_view(),
        name="webhook",
    ),
]
