import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .archivos import guardar_reserva, validar_archivos
from .models import Dentista, Servicio, SlotAgenda
from .permissions import EsPersonal, perfil_dentista
from .ocupacion import disponibilidad
from .serializers import ReservaCreateSerializer, SlotAgendaSerializer, SlotDisponibilidadSerializer
from .slots_generator import blocks_per_day, generate_slots_range
from .throttles import ReservaThrottle

MAX_DIAS_A_GENERAR = 62


class SlotsDisponiblesList(generics.ListAPIView):
    serializer_class = SlotAgendaSerializer

    def get_queryset(self):
        return SlotAgenda.objects.filter(fecha__gte=timezone.localdate()).order_by('fecha', 'hora')


class CrearReserva(generics.CreateAPIView):
    serializer_class = ReservaCreateSerializer
    throttle_classes = [ReservaThrottle]

    def create(self, request, *args, **kwargs):
        archivos = request.FILES.getlist('archivos')
        validar_archivos(archivos)
        datos = request.data.copy()
        perfil = getattr(request.user, 'paciente_perfil', None)
        if perfil is not None:
            datos['paciente'] = perfil.id
        serializer = self.get_serializer(data=datos)
        serializer.is_valid(raise_exception=True)
        reserva = guardar_reserva(serializer, archivos)
        return Response({'id': reserva.id, 'sobrecupo': reserva.sobrecupo}, status=status.HTTP_201_CREATED)


def _error(texto):
    return Response({'detail': texto}, status=status.HTTP_400_BAD_REQUEST)


def _hora(valor):
    return datetime.datetime.strptime(str(valor), '%H:%M').time()


@api_view(['POST'])
@permission_classes([EsPersonal])
def generar_slots(request, dentista_id):
    dentista = Dentista.objects.filter(pk=dentista_id).first()
    if dentista is None:
        return Response({'detail': 'Dentista no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
    perfil = perfil_dentista(request.user)
    if perfil is not None and perfil.id != dentista.id:
        return Response({'detail': 'Solo puedes generar horarios de tu propia agenda.'}, status=status.HTTP_403_FORBIDDEN)

    texto_fecha = request.data.get('fecha')
    if not texto_fecha:
        return _error('Se requiere campo fecha (YYYY-MM-DD).')
    fecha = parse_date(str(texto_fecha))
    if fecha is None:
        return _error('Formato de fecha inválido. Use YYYY-MM-DD.')
    crudo = request.data.get('dias')
    try:
        dias = 1 if crudo in (None, '') else int(crudo)
    except (TypeError, ValueError):
        return _error('El campo dias debe ser un entero.')
    if not 1 <= dias <= MAX_DIAS_A_GENERAR:
        return _error(f'El campo dias debe estar entre 1 y {MAX_DIAS_A_GENERAR}.')
    try:
        desde = _hora(request.data.get('desde', '08:00'))
        hasta = _hora(request.data.get('hasta', '16:00'))
    except ValueError:
        return _error('Las horas deben tener el formato HH:MM.')

    if hasta <= desde:
        return _error('La hora final debe ser posterior a la hora inicial.')

    try:
        with transaction.atomic():
            creados = generate_slots_range(dentista, fecha, fecha + datetime.timedelta(days=dias - 1), desde=desde, hasta=hasta)
    except ValidationError as error:
        return _error(' '.join(error.messages))
    existentes = blocks_per_day(desde, hasta) * dias - creados
    return Response({'created': creados, 'existing': existentes}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def slots_por_fecha(request):
    dentista_id = request.GET.get('dentista_id')
    slots = SlotAgenda.objects.annotate(
        reservas_count=Count('reservas'),
        sobrecupos_count=Count('reservas', filter=Q(reservas__sobrecupo=True)),
    )
    if request.GET.get('fecha'):
        fecha = parse_date(request.GET['fecha'])
        if fecha is None:
            return _error('Formato de fecha inválido. Use YYYY-MM-DD.')
        slots = slots.filter(fecha=fecha)
    else:
        slots = slots.filter(fecha__gte=timezone.localdate())
    if dentista_id:
        if not dentista_id.isdigit():
            return _error('El identificador del dentista debe ser numérico.')
        slots = slots.filter(dentista_id=dentista_id)
    servicio = None
    if request.GET.get('servicio_id'):
        if not request.GET['servicio_id'].isdigit():
            return _error('El identificador del servicio debe ser numérico.')
        servicio = Servicio.objects.filter(pk=request.GET['servicio_id']).first()
    lista = list(slots.order_by('fecha', 'hora'))
    contexto = {'disponibilidad': disponibilidad(lista, servicio)}
    return Response(SlotDisponibilidadSerializer(lista, many=True, context=contexto).data)
