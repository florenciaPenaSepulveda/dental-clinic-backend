import datetime

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import ArchivoReserva, Reserva, SlotAgenda
from .permissions import EsPaciente, EsPersonal, EsUsuarioConRol, PACIENTE, perfil_dentista, puede_ver_reserva, rol_de
from .ocupacion import bloqueos_de
from .serializers import HistorialSerializer, PacienteSerializer, SlotSemanaSerializer


@api_view(['GET'])
@permission_classes([EsPersonal])
def semana(request):
    desde = parse_date(request.query_params.get('desde', ''))
    if desde is None:
        return Response({'detail': 'Indica la fecha de inicio (desde=AAAA-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)
    perfil = perfil_dentista(request.user)
    pedido = request.query_params.get('dentista')
    if perfil is not None:
        if pedido and pedido != str(perfil.id):
            return Response({'detail': 'Solo puedes ver tu propia agenda.'}, status=status.HTTP_403_FORBIDDEN)
        dentista_id = perfil.id
    elif pedido and pedido.isdigit():
        dentista_id = int(pedido)
    else:
        return Response({'detail': 'Elige un dentista.'}, status=status.HTTP_400_BAD_REQUEST)
    slots = (
        SlotAgenda.objects.filter(dentista_id=dentista_id, fecha__range=(desde, desde + datetime.timedelta(days=6)))
        .prefetch_related('reservas__paciente', 'reservas__servicio', 'reservas__archivos')
        .select_related('dentista')
        .order_by('fecha', 'hora')
    )
    lista = list(slots)
    return Response(SlotSemanaSerializer(lista, many=True, context={'bloqueados': bloqueos_de(lista)}).data)


@api_view(['GET'])
@permission_classes([EsPaciente])
def mi_historial(request):
    paciente = request.user.paciente_perfil
    reservas = list(
        Reserva.objects.filter(paciente=paciente)
        .select_related('slot__dentista', 'servicio', 'atencion')
        .prefetch_related('archivos')
        .order_by('-slot__fecha', '-slot__hora')
    )
    hoy = timezone.localdate()
    proximas = [r for r in reservas if r.estado == 'pendiente' and r.slot.fecha >= hoy]
    ids = {r.id for r in proximas}
    historial = [r for r in reservas if r.id not in ids]
    return Response(
        {
            'paciente': PacienteSerializer(paciente).data,
            'proximas': HistorialSerializer(reversed(proximas), many=True).data,
            'historial': HistorialSerializer(historial, many=True).data,
        }
    )


@api_view(['GET', 'DELETE'])
@permission_classes([EsUsuarioConRol])
def archivo(request, archivo_id):
    adjunto = get_object_or_404(ArchivoReserva.objects.select_related('reserva__slot'), pk=archivo_id)
    if not puede_ver_reserva(request.user, adjunto.reserva):
        raise Http404
    if request.method == 'DELETE':
        if rol_de(request.user) == PACIENTE:
            return Response({'detail': 'No tienes permiso para eliminar archivos.'}, status=status.HTTP_403_FORBIDDEN)
        adjunto.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    respuesta = FileResponse(adjunto.archivo.open('rb'), as_attachment=True, filename=adjunto.nombre, content_type=adjunto.tipo)
    respuesta['X-Content-Type-Options'] = 'nosniff'
    return respuesta
