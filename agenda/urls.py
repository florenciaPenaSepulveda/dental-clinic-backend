from django.urls import path, include
from .views import SlotsDisponiblesList, CrearReserva, generar_slots, sobrecupos
from .views import slots_por_fecha
from . import auth_views, views_clinica
from rest_framework.routers import DefaultRouter
from .viewsets import DentistaViewSet, ServicioViewSet, PacienteViewSet, RegionViewSet, ReservaViewSet

router = DefaultRouter()
router.register(r'regiones', RegionViewSet, basename='region')
router.register(r'dentistas', DentistaViewSet, basename='dentista')
router.register(r'servicios', ServicioViewSet, basename='servicio')
router.register(r'pacientes', PacienteViewSet, basename='paciente')
router.register(r'reservas', ReservaViewSet, basename='reserva')

urlpatterns = [
    path('slots/', SlotsDisponiblesList.as_view(), name='slots-disponibles'),
    path('reservas/', CrearReserva.as_view(), name='crear-reserva'),
    path('dentistas/<int:dentista_id>/generar_slots/', generar_slots, name='generar-slots'),
    path('slots_por_fecha/', slots_por_fecha, name='slots-por-fecha'),
    path('semana/', views_clinica.semana, name='semana'),
    path('sobrecupos/', sobrecupos, name='sobrecupos'),
    path('mi/historial/', views_clinica.mi_historial, name='mi-historial'),
    path('archivos/<int:archivo_id>/', views_clinica.archivo, name='archivo'),
    path('auth/login/', auth_views.login, name='auth-login'),
    path('auth/activar-cuenta/', auth_views.activar_cuenta, name='auth-activar-cuenta'),
    path('auth/cambiar-clave/', auth_views.cambiar_clave, name='auth-cambiar-clave'),
    path('auth/logout/', auth_views.logout, name='auth-logout'),
    path('auth/me/', auth_views.me, name='auth-me'),
    path('api/', include(router.urls)),
]
