from django.core.management.base import BaseCommand
from django.db import transaction
from agenda.models import Dentista, Servicio, Paciente
from agenda.slots_generator import generate_slots_range
import datetime


class Command(BaseCommand):
    help = 'Siembra datos de ejemplo: dentistas, servicios y pacientes. Opcionalmente genera slots para N días.'

    def add_arguments(self, parser):
        parser.add_argument('--dentistas', type=int, default=2, help='Número de dentistas a crear')
        parser.add_argument('--servicios', type=int, default=3, help='Número de servicios a crear')
        parser.add_argument('--pacientes', type=int, default=10, help='Número de pacientes a crear')
        parser.add_argument('--generate-slots', type=int, default=0, help='Generar slots para los N días siguientes (0 = none)')
        parser.add_argument('--desde', type=str, default='08:00', help='Hora desde para generar slots')
        parser.add_argument('--hasta', type=str, default='16:00', help='Hora hasta para generar slots')
        parser.add_argument('--capacidad', type=int, default=1, help='Capacidad por slot (default 1)')

    def handle(self, *args, **options):
        nd = options.get('dentistas')
        ns = options.get('servicios')
        npat = options.get('pacientes')
        gen_days = options.get('generate_slots')
        desde = options.get('desde')
        hasta = options.get('hasta')
        capacidad = options.get('capacidad')

        created = {'dentistas': 0, 'servicios': 0, 'pacientes': 0, 'slots': 0}

        with transaction.atomic():
            # Dentistas
            for i in range(1, nd + 1):
                nombre = f'Dentista{i}'
                apellido = f'Ejemplo {i}'
                dentista, d_created = Dentista.objects.get_or_create(
                    nombre=nombre,
                    apellido=apellido,
                    defaults={'max_overbook_day': 2}
                )
                if d_created:
                    created['dentistas'] += 1

            # Servicios (duraciones comunes)
            default_durations = [30, 45, 60]
            for i in range(1, ns + 1):
                svc_name = f'Servicio Ejemplo {i}'
                duration = default_durations[(i - 1) % len(default_durations)]
                precio = 50.00 + (i - 1) * 10
                servicio, s_created = Servicio.objects.get_or_create(
                    nombre=svc_name,
                    defaults={'duracion_min': duration, 'precio': precio}
                )
                if s_created:
                    created['servicios'] += 1

            # Pacientes
            for i in range(1, npat + 1):
                nombre = f'Paciente{i}'
                apellido = f'Ejemplo {i}'
                paciente, p_created = Paciente.objects.get_or_create(
                    nombre=nombre,
                    apellido=apellido,
                    defaults={'telefono': f'+000000000{i:02d}', 'email': f'paciente{i}@example.com'}
                )
                if p_created:
                    created['pacientes'] += 1

        # Generar slots si se solicita
        if gen_days and gen_days > 0:
            start_date = datetime.date.today()
            end_date = start_date + datetime.timedelta(days=gen_days - 1)
            total_slots = 0
            dentists = Dentista.objects.all()
            for d in dentists:
                total_slots += generate_slots_range(d, start_date, end_date, desde=desde, hasta=hasta, capacidad_default=capacidad)
            created['slots'] = total_slots

        # Resumen
        self.stdout.write(self.style.SUCCESS('Seed completed:'))
        self.stdout.write(f"  Dentistas creados: {created['dentistas']}")
        self.stdout.write(f"  Servicios creados: {created['servicios']}")
        self.stdout.write(f"  Pacientes creados: {created['pacientes']}")
        if created['slots']:
            self.stdout.write(f"  Slots creados/validados: {created['slots']}")
        self.stdout.write(self.style.SUCCESS('Seed finished.'))
