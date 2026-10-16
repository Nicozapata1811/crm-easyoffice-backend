from django.urls import path

from .views import DescargaPortalView
from .views import DocumentosPortalView

urlpatterns = [
    path(
        "tramites/<int:tramite_id>/documentos/",
        DocumentosPortalView.as_view(),
        name="tramite-documentos",
    ),
    path(
        "tramites/<int:tramite_id>/documentos/<int:pk>/<str:tipo>/",
        DescargaPortalView.as_view(),
        name="tramite-documento-archivo",
    ),
]
