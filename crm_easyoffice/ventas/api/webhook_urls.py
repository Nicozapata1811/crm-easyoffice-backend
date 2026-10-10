from django.urls import path

from .views import PagoWebhookView

app_name = "pagos"
urlpatterns = [
    path(
        "webhooks/<slug:proveedor>/<slug:evento>/",
        PagoWebhookView.as_view(),
        name="webhook",
    ),
]
