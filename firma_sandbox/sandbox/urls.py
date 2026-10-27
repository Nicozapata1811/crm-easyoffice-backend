from django.urls import include
from django.urls import path
from drf_spectacular.views import SpectacularAPIView

from psc import pki_views
from psc.api import views as api
from psc.paginas import views as paginas

api_v1 = [
    path("solicitudes", api.SolicitudesView.as_view(), name="solicitudes"),
    path("solicitudes/<uuid:pk>", api.SolicitudView.as_view(), name="solicitud"),
    path(
        "solicitudes/<uuid:pk>/documento",
        api.DocumentoView.as_view(),
        name="documento",
    ),
    path("solicitudes/<uuid:pk>/cancelar", api.CancelarView.as_view(), name="cancelar"),
    path(
        "solicitudes/<uuid:pk>/firmantes/<uuid:firmante>/reenviar",
        api.ReenviarView.as_view(),
        name="reenviar",
    ),
    path("validaciones", api.ValidacionesView.as_view(), name="validaciones"),
    path("schema", SpectacularAPIView.as_view(), name="schema"),
]

pki = [
    path("<str:nombre>.crt", pki_views.certificado, name="certificado"),
    path("<str:nombre>.crl", pki_views.crl, name="crl"),
    path("ocsp", pki_views.respondedor_ocsp, name="ocsp"),
    path("tsa", pki_views.tsa, name="tsa"),
]

paginas_urls = [
    path("firmar/<str:token>/", paginas.firmar, name="firmar"),
    path("firmar/<str:token>/documento.pdf", paginas.documento, name="documento"),
    path("verificar/<str:codigo>/", paginas.verificar, name="verificar"),
]

urlpatterns = [
    path("api/v1/", include((api_v1, "api"))),
    path("pki/", include((pki, "pki"))),
    path("", include((paginas_urls, "paginas"))),
]
