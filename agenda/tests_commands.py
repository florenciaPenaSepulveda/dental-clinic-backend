import datetime
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .management.commands.seed_data import rut_con_dv
from .models import Dentista, Paciente, Servicio, SlotAgenda

FECHA = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


class SeedDataTests(TestCase):
    def ejecutar(self, *args):
        salida = StringIO()
        call_command("seed_data", *args, stdout=salida)
        return salida.getvalue()

    def test_siembra_datos_y_es_idempotente(self):
        texto = self.ejecutar("--dentistas", "2", "--servicios", "3", "--pacientes", "4")
        self.assertIn("Seed finished", texto)
        self.assertEqual(
            (Dentista.objects.count(), Servicio.objects.count(), Paciente.objects.count()), (2, 3, 4)
        )
        self.ejecutar("--dentistas", "2", "--servicios", "3", "--pacientes", "4")
        self.assertEqual(Paciente.objects.count(), 4)

    def test_los_pacientes_tienen_rut_unico_y_valido(self):
        self.ejecutar("--pacientes", "3")
        ruts = list(Paciente.objects.values_list("rut", flat=True))
        self.assertEqual(len(set(ruts)), 3)
        self.assertIn(rut_con_dv(15000001), ruts)
        self.assertEqual(rut_con_dv(12345678), "12.345.678-5")

    def test_genera_slots_para_los_dias_pedidos(self):
        texto = self.ejecutar("--dentistas", "1", "--pacientes", "1", "--generate-slots", "2", "--desde", "08:00", "--hasta", "09:00")
        self.assertIn("Slots creados", texto)
        self.assertEqual(SlotAgenda.objects.count(), 4)


class GenerateSlotsCommandTests(TestCase):
    def setUp(self):
        self.dentista = Dentista.objects.create(nombre="Ana", apellido="Pérez")

    def test_genera_un_dia(self):
        call_command("generate_slots", dentista=self.dentista.id, fecha=FECHA, desde="08:00", hasta="09:00", stdout=StringIO())
        self.assertEqual(SlotAgenda.objects.count(), 2)

    def test_genera_varios_dias(self):
        call_command("generate_slots", dentista=self.dentista.id, fecha=FECHA, dias=2, desde="08:00", hasta="08:30", stdout=StringIO())
        self.assertEqual(SlotAgenda.objects.count(), 2)

    def test_valida_los_argumentos(self):
        with self.assertRaises(CommandError):
            call_command("generate_slots", dentista=999, fecha=FECHA)
        with self.assertRaises(CommandError):
            call_command("generate_slots", dentista=self.dentista.id, fecha="mañana")
        with self.assertRaises(CommandError):
            call_command("generate_slots", dentista=self.dentista.id, fecha=FECHA, dias=0)
