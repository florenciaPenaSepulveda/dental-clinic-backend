import datetime
from collections import Counter

from django.core.exceptions import ValidationError

from .models import Dentista, Reserva, SobrecupoDia
from .permissions import RECEPCION, perfil_dentista, rol_de

MAX_SOBRECUPOS_DIA = 10
SOBRECUPOS_POR_HORARIO = 1


def puede_gestionar(user, dentista_id):
    rol = rol_de(user)
    if rol == RECEPCION:
        return True
    perfil = perfil_dentista(user)
    return perfil is not None and perfil.id == dentista_id


def permitidos(dentista, fecha):
    cupos = SobrecupoDia.objects.filter(dentista=dentista, fecha=fecha).values_list('cupos', flat=True).first()
    return dentista.max_overbook_day if cupos is None else cupos


def usados(dentista_id, fecha, excluir=None):
    reservas = Reserva.objects.filter(slot__dentista_id=dentista_id, slot__fecha=fecha, sobrecupo=True)
    if excluir is not None:
        reservas = reservas.exclude(pk=excluir.pk)
    return reservas.count()


def resumen_semana(dentista, desde):
    fechas = [desde + datetime.timedelta(days=k) for k in range(7)]
    personalizados = dict(SobrecupoDia.objects.filter(dentista=dentista, fecha__in=fechas).values_list('fecha', 'cupos'))
    en_uso = Counter(
        Reserva.objects.filter(slot__dentista=dentista, slot__fecha__in=fechas, sobrecupo=True).values_list('slot__fecha', flat=True)
    )
    return {
        'por_defecto': dentista.max_overbook_day,
        'dias': [
            {
                'fecha': fecha,
                'permitidos': personalizados.get(fecha, dentista.max_overbook_day),
                'usados': en_uso.get(fecha, 0),
                'personalizado': fecha in personalizados,
            }
            for fecha in fechas
        ],
    }


def validar_sobrecupo(slot, excluir=None):
    en_el_horario = slot.reservas.filter(sobrecupo=True)
    if excluir is not None:
        en_el_horario = en_el_horario.exclude(pk=excluir.pk)
    if en_el_horario.count() >= SOBRECUPOS_POR_HORARIO:
        raise ValidationError('Ese horario ya tiene un sobrecupo.')
    limite = permitidos(slot.dentista, slot.fecha)
    if limite == 0:
        raise ValidationError('El dentista no admite sobrecupos ese día.')
    if usados(slot.dentista_id, slot.fecha, excluir) >= limite:
        raise ValidationError(f'Se alcanzó el límite de {limite} sobrecupo{"s" if limite != 1 else ""} de ese día.')


def con_sobrecupo_disponible(slots):
    if not slots:
        return set()
    dentistas = {slot.dentista_id for slot in slots}
    fechas = {slot.fecha for slot in slots}
    por_defecto = dict(Dentista.objects.filter(pk__in=dentistas).values_list('pk', 'max_overbook_day'))
    personalizados = {
        (d, f): c for d, f, c in SobrecupoDia.objects.filter(dentista_id__in=dentistas, fecha__in=fechas).values_list('dentista_id', 'fecha', 'cupos')
    }
    en_uso = Counter(
        Reserva.objects.filter(slot__dentista_id__in=dentistas, slot__fecha__in=fechas, sobrecupo=True).values_list('slot__dentista_id', 'slot__fecha')
    )
    disponibles = set()
    for slot in slots:
        principales = getattr(slot, 'reservas_count', 0) - getattr(slot, 'sobrecupos_count', 0)
        if principales < slot.capacidad or getattr(slot, 'sobrecupos_count', 0) >= SOBRECUPOS_POR_HORARIO:
            continue
        limite = personalizados.get((slot.dentista_id, slot.fecha), por_defecto.get(slot.dentista_id, 0))
        if en_uso.get((slot.dentista_id, slot.fecha), 0) < limite:
            disponibles.add(slot.id)
    return disponibles
