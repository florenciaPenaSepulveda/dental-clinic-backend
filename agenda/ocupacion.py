import datetime
import math

from django.core.exceptions import ValidationError

from .models import Reserva, SlotAgenda

PASO = datetime.timedelta(minutes=30)
MINUTOS_POR_BLOQUE = 30


def bloques_de(servicio):
    minutos = servicio.duracion_min if servicio is not None else MINUTOS_POR_BLOQUE
    return max(1, math.ceil(minutos / MINUTOS_POR_BLOQUE))


def _horas_siguientes(fecha, hora, bloques):
    inicio = datetime.datetime.combine(fecha, hora)
    return [(inicio + PASO * k).time() for k in range(1, bloques)]


def horas_bloqueadas(reservas):
    bloqueadas = set()
    for reserva in reservas:
        slot = reserva.slot
        for hora in _horas_siguientes(slot.fecha, slot.hora, bloques_de(reserva.servicio)):
            bloqueadas.add((slot.dentista_id, slot.fecha, hora))
    return bloqueadas


def _reservas_principales(dentistas, fechas):
    return Reserva.objects.filter(slot__dentista_id__in=dentistas, slot__fecha__in=fechas, sobrecupo=False).select_related('slot', 'servicio')


def bloqueos_de(slots):
    dentistas = {slot.dentista_id for slot in slots}
    fechas = {slot.fecha for slot in slots}
    if not slots:
        return set()
    return horas_bloqueadas(_reservas_principales(dentistas, fechas))


def disponibilidad(slots, servicio=None):
    bloqueadas = bloqueos_de(slots)
    ocupados = {(slot.dentista_id, slot.fecha, slot.hora): getattr(slot, 'reservas_count', None) for slot in slots}
    bloques = bloques_de(servicio)
    resultado = {}
    for slot in slots:
        clave = (slot.dentista_id, slot.fecha, slot.hora)
        bloqueado = clave in bloqueadas
        cabe = not bloqueado
        if cabe:
            for hora in _horas_siguientes(slot.fecha, slot.hora, bloques):
                siguiente = (slot.dentista_id, slot.fecha, hora)
                if siguiente not in ocupados or siguiente in bloqueadas or ocupados[siguiente]:
                    cabe = False
                    break
        resultado[slot.id] = {'bloqueado': bloqueado, 'cabe': cabe}
    return resultado


def validar_espacio(slot, servicio, excluir=None):
    reservas = _reservas_principales([slot.dentista_id], [slot.fecha])
    if excluir is not None:
        reservas = reservas.exclude(pk=excluir.pk)
    bloqueadas = horas_bloqueadas(reservas)
    if (slot.dentista_id, slot.fecha, slot.hora) in bloqueadas:
        raise ValidationError('Ese horario está ocupado por la duración de la cita anterior.')
    horas = _horas_siguientes(slot.fecha, slot.hora, bloques_de(servicio))
    if not horas:
        return
    siguientes = {
        s.hora: s
        for s in SlotAgenda.objects.filter(dentista_id=slot.dentista_id, fecha=slot.fecha, hora__in=horas).prefetch_related('reservas')
    }
    for hora in horas:
        siguiente = siguientes.get(hora)
        ocupado = siguiente is not None and any(r.pk != getattr(excluir, 'pk', None) for r in siguiente.reservas.all())
        if siguiente is None or ocupado or (slot.dentista_id, slot.fecha, hora) in bloqueadas:
            raise ValidationError(
                f'El servicio dura {servicio.duracion_min} minutos y no hay horarios libres seguidos suficientes desde las {slot.hora:%H:%M}. Elige otro horario.'
            )
