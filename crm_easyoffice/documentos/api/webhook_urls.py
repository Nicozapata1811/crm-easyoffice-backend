from django.urls import path

from .webhook_views import FirmaWebhookView

app_name = "firma"
urlpatterns = [
    path("webhooks/<slug:proveedor>/", FirmaWebhookView.as_view(), name="webhook"),
]
