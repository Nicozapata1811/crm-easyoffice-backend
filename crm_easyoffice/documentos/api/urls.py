from django.urls import path

from .views import CancelarFirmaView
from .views import DescargaBackofficeView
from .views import DocumentosBackofficeView
from .views import ReenviarFirmaView
from .views import ReintentarFirmaView
from .views import SubirFirmadoView

app_name = "documentos"
urlpatterns = [
    path(
        "tramites/<int:tramite_id>/documentos/",
        DocumentosBackofficeView.as_view(),
        name="tramite-documentos",
    ),
    path(
        "tramites/<int:tramite_id>/documentos/<int:pk>/firmado/subir/",
        SubirFirmadoView.as_view(),
        name="tramite-documento-subir-firmado",
    ),
    path(
        "tramites/<int:tramite_id>/documentos/<int:pk>/firma/reenviar/",
        ReenviarFirmaView.as_view(),
        name="tramite-documento-firma-reenviar",
    ),
    path(
        "tramites/<int:tramite_id>/documentos/<int:pk>/firma/cancelar/",
        CancelarFirmaView.as_view(),
        name="tramite-documento-firma-cancelar",
    ),
    path(
        "tramites/<int:tramite_id>/documentos/<int:pk>/firma/reintentar/",
        ReintentarFirmaView.as_view(),
        name="tramite-documento-firma-reintentar",
    ),
    path(
        "tramites/<int:tramite_id>/documentos/<int:pk>/<str:tipo>/",
        DescargaBackofficeView.as_view(),
        name="tramite-documento-archivo",
    ),
]
