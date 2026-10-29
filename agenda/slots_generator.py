import datetime
from .models import SlotAgenda

PASO = datetime.timedelta(minutes=30)


def _parse_time(t):
    if isinstance(t, datetime.time):
        return t
    return datetime.datetime.strptime(t, '%H:%M').time()


def blocks_per_day(desde='08:00', hasta='18:00'):
    inicio = datetime.datetime.combine(datetime.date.min, _parse_time(desde))
    fin = datetime.datetime.combine(datetime.date.min, _parse_time(hasta))
    return max(0, int((fin - inicio) / PASO))


def generate_slots_for_day(dentista, fecha, desde='08:00', hasta='18:00', capacidad_default=1):
    current = datetime.datetime.combine(fecha, _parse_time(desde))
    end = datetime.datetime.combine(fecha, _parse_time(hasta))
    created = 0
    while current + PASO <= end:
        _, nuevo = SlotAgenda.objects.get_or_create(
            dentista=dentista,
            fecha=fecha,
            hora=current.time(),
            defaults={'capacidad': capacidad_default}
        )
        created += int(nuevo)
        current += PASO
    return created


def generate_slots_range(dentista, start_date, end_date, desde='08:00', hasta='18:00', capacidad_default=1):
    total = 0
    day = start_date
    while day <= end_date:
        total += generate_slots_for_day(dentista, day, desde=desde, hasta=hasta, capacidad_default=capacidad_default)
        day += datetime.timedelta(days=1)
    return total
