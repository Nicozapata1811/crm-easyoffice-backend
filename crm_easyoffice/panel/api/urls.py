from django.urls import path

from .views import ExportarIndicadoresView
from .views import IndicadoresView

app_name = "panel"
urlpatterns = [
    path("indicadores/", IndicadoresView.as_view(), name="indicadores"),
    path(
        "indicadores/exportar/",
        ExportarIndicadoresView.as_view(),
        name="exportar",
    ),
]
