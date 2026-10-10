from django.urls import path

from .portal_views import RegistroView

urlpatterns = [
    path("registro/", RegistroView.as_view(), name="registro"),
]
