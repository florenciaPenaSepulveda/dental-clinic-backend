from rest_framework import routers
from .views import PacienteViewSet, CitaViewSet, DentistaViewSet, AgendaViewSet

router = routers.DefaultRouter()
router.register(r'pacientes', PacienteViewSet)
router.register(r'citas', CitaViewSet)
router.register(r'dentistas', DentistaViewSet)
router.register(r'agendas', AgendaViewSet)

urlpatterns = router.urls
