from django.core.management.base import BaseCommand, CommandError
from agenda.models import Dentista
from agenda.slots_generator import generate_slots_for_day, generate_slots_range
import datetime


class Command(BaseCommand):
    help = 'Genera slots para dentistas. Uso: generate_slots --dentista <id> --fecha YYYY-MM-DD [--dias N] [--desde HH:MM] [--hasta HH:MM]'

    def add_arguments(self, parser):
        parser.add_argument('--dentista', type=int, required=True, help='ID del dentista')
        parser.add_argument('--fecha', type=str, required=True, help='Fecha inicial YYYY-MM-DD')
        parser.add_argument('--dias', type=int, default=1, help='Número de días a generar (inclusive)')
        parser.add_argument('--desde', type=str, default='08:00', help='Hora desde HH:MM')
        parser.add_argument('--hasta', type=str, default='16:00', help='Hora hasta HH:MM')

    def handle(self, *args, **options):
        dentista_id = options['dentista']
        fecha = options['fecha']
        dias = options['dias']
        desde = options['desde']
        hasta = options['hasta']

        try:
            dentista = Dentista.objects.get(pk=dentista_id)
        except Dentista.DoesNotExist:
            raise CommandError('Dentista no encontrado')

        try:
            fecha_obj = datetime.datetime.strptime(fecha, '%Y-%m-%d').date()
        except Exception:
            raise CommandError('Formato de fecha inválido. Use YYYY-MM-DD')

        if dias <= 0:
            raise CommandError('dias debe ser mayor que 0')

        if dias == 1:
            created = generate_slots_for_day(dentista, fecha_obj, desde=desde, hasta=hasta)
        else:
            end_date = fecha_obj + datetime.timedelta(days=dias - 1)
            created = generate_slots_range(dentista, fecha_obj, end_date, desde=desde, hasta=hasta)

        self.stdout.write(self.style.SUCCESS(f'Se crearon/validaron {created} slots para el dentista {dentista}'))
