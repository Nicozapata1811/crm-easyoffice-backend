from django.urls import path

from .views import DescargaBackofficeView
from .views import DocumentosBackofficeView
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
        "tramites/<int:tramite_id>/documentos/<int:pk>/<str:tipo>/",
        DescargaBackofficeView.as_view(),
        name="tramite-documento-archivo",
    ),
]
