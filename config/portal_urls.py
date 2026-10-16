from django.urls import include
from django.urls import path

app_name = "portal"
urlpatterns = [
    path("", include("crm_easyoffice.clientes.api.portal_urls")),
    path("", include("crm_easyoffice.ventas.api.portal_urls")),
    path("", include("crm_easyoffice.tramites.api.portal_urls")),
]
