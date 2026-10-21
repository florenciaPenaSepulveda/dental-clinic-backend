"""Generación de slots: implementa la práctica común de clínicas:

- Slots de 30 minutos
- Horario por defecto 08:00-18:00 (extendido para mayor flexibilidad)
- Evita duplicados usando get_or_create
"""
import datetime
from .models import SlotAgenda


def _parse_time(t):
    if isinstance(t, datetime.time):
        return t
    return datetime.datetime.strptime(t, '%H:%M').time()


def generate_slots_for_day(dentista, fecha, desde='08:00', hasta='18:00', capacidad_default=1):
    t_desde = _parse_time(desde)
    t_hasta = _parse_time(hasta)
    current = datetime.datetime.combine(fecha, t_desde)
    end = datetime.datetime.combine(fecha, t_hasta)
    created = 0
    # crear slots en bloques de 30 minutos (excluye el instante final si es igual a end)
    while current <= end:
        hora = current.time()
        SlotAgenda.objects.get_or_create(
            dentista=dentista,
            fecha=fecha,
            hora=hora,
            defaults={'capacidad': capacidad_default}
        )
        created += 1
        current += datetime.timedelta(minutes=30)
    return created


def generate_slots_range(dentista, start_date, end_date, desde='08:00', hasta='18:00', capacidad_default=1):
    total = 0
    day = start_date
    while day <= end_date:
        total += generate_slots_for_day(dentista, day, desde=desde, hasta=hasta, capacidad_default=capacidad_default)
        day += datetime.timedelta(days=1)
    return total
