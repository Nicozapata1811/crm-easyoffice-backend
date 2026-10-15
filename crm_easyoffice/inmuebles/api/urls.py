from django.urls import path

from .views import DocumentoIdentidadView

app_name = "inmuebles"
urlpatterns = [
    path(
        "autorizantes/<int:pk>/documento-identidad/",
        DocumentoIdentidadView.as_view(),
        name="documento-identidad",
    ),
]
