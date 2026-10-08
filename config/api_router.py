from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from crm_easyoffice.clientes.api.views import ClienteViewSet
from crm_easyoffice.users.api.views import UserViewSet

router = DefaultRouter() if settings.DEBUG else SimpleRouter()

router.register("users", UserViewSet)
router.register("clientes", ClienteViewSet)


app_name = "api"
urlpatterns = router.urls
