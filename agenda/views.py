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
from .sobrecupos import MAX_SOBRECUPOS_DIA, con_sobrecupo_disponible, puede_gestionar, resumen_semana, usados
from .models import SobrecupoDia
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
    contexto = {'disponibilidad': disponibilidad(lista, servicio), 'con_sobrecupo': con_sobrecupo_disponible(lista)}
    return Response(SlotDisponibilidadSerializer(lista, many=True, context=contexto).data)


def _dentista_del_pedido(request, dato):
    perfil = perfil_dentista(request.user)
    if perfil is not None:
        if dato not in (None, '', perfil.id, str(perfil.id)):
            return None, Response({'detail': 'Solo puedes gestionar tus propios sobrecupos.'}, status=status.HTTP_403_FORBIDDEN)
        return perfil, None
    if dato is None or not str(dato).isdigit():
        return None, _error('Elige un dentista.')
    dentista = Dentista.objects.filter(pk=dato).first()
    if dentista is None:
        return None, Response({'detail': 'Dentista no encontrado.'}, status=status.HTTP_404_NOT_FOUND)
    return dentista, None


@api_view(['GET', 'PUT'])
@permission_classes([EsPersonal])
def sobrecupos(request):
    if request.method == 'GET':
        dentista, error = _dentista_del_pedido(request, request.query_params.get('dentista'))
        if error:
            return error
        desde = parse_date(request.query_params.get('desde', ''))
        if desde is None:
            return _error('Indica la fecha de inicio (desde=AAAA-MM-DD).')
        return Response(resumen_semana(dentista, desde))

    dentista, error = _dentista_del_pedido(request, request.data.get('dentista'))
    if error:
        return error
    if not puede_gestionar(request.user, dentista.id):
        return Response({'detail': 'No puedes gestionar los sobrecupos de este dentista.'}, status=status.HTTP_403_FORBIDDEN)
    cupos = request.data.get('cupos')
    fecha_texto = request.data.get('fecha')
    fecha = parse_date(str(fecha_texto)) if fecha_texto else None
    if fecha_texto and fecha is None:
        return _error('Formato de fecha inválido. Use YYYY-MM-DD.')
    if cupos is None and fecha is None:
        return _error('Indica la cantidad de sobrecupos.')
    if cupos is not None:
        try:
            cupos = int(cupos)
        except (TypeError, ValueError):
            return _error('Los sobrecupos deben ser un número entero.')
        if not 0 <= cupos <= MAX_SOBRECUPOS_DIA:
            return _error(f'Los sobrecupos deben estar entre 0 y {MAX_SOBRECUPOS_DIA}.')

    if fecha is None:
        dentista.max_overbook_day = cupos
        dentista.save(update_fields=['max_overbook_day'])
        return Response({'por_defecto': cupos})

    if fecha < timezone.localdate():
        return _error('No se pueden cambiar los sobrecupos de una fecha pasada.')
    if cupos is None:
        SobrecupoDia.objects.filter(dentista=dentista, fecha=fecha).delete()
        return Response({'fecha': fecha, 'cupos': dentista.max_overbook_day, 'personalizado': False})
    agendados = usados(dentista.id, fecha)
    if cupos < agendados:
        return _error(f'Ya hay {agendados} sobrecupo{"s" if agendados != 1 else ""} agendado{"s" if agendados != 1 else ""} ese día: cancélalos o muévelos antes de reducir el límite.')
    SobrecupoDia.objects.update_or_create(dentista=dentista, fecha=fecha, defaults={'cupos': cupos})
    return Response({'fecha': fecha, 'cupos': cupos, 'personalizado': True})
