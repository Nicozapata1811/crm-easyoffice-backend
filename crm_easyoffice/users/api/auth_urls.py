from django.urls import path

from .auth_views import CsrfView
from .auth_views import LoginView
from .auth_views import LogoutView
from .auth_views import MeView

app_name = "auth"
urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="csrf"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
]
