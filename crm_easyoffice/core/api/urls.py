from django.urls import path

from .views import HistorialView
from .views import RegistroAuditoriaListView

app_name = "auditoria"
urlpatterns = [
    path("", RegistroAuditoriaListView.as_view(), name="lista"),
    path("historial/", HistorialView.as_view(), name="historial"),
]
