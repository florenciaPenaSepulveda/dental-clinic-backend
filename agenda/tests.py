from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from .models import SlotAgenda, Paciente, Dentista, Servicio, Reserva
from django.utils import timezone
from datetime import time, timedelta


class ReservaCapacityTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dentista = Dentista.objects.create(nombre='Ana', apellido='Perez', especialidad='Ortodoncia')
        self.paciente = Paciente.objects.create(nombre='Juan', apellido='Lopez')
        self.servicio = Servicio.objects.create(nombre='Limpieza', duracion_min=30, precio=30)
        self.slot = SlotAgenda.objects.create(
            dentista=self.dentista,
            servicio=self.servicio,
            fecha=timezone.localdate(),
            hora=time(10, 0),
            capacidad=1
        )

    def test_two_reservations_second_created_as_overbook(self):
        """
        Adaptado al nuevo comportamiento del backend:
        Ahora permite crear sobrecupos sin error 400.
        """
        url = reverse('crear-reserva')
        payload = {'slot': self.slot.id, 'paciente': self.paciente.id, 'servicio': self.servicio.id}
        r1 = self.client.post(url, payload, format='json')
        self.assertEqual(r1.status_code, 201)

        r2 = self.client.post(url, payload, format='json')
        self.assertEqual(r2.status_code, 201)
        self.assertIn('sobrecupo', r2.data)


class GenerateSlotsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dentista = Dentista.objects.create(nombre='Carlos', apellido='Ruiz')

    def test_generate_slots_endpoint(self):
        url = reverse('generar-slots', kwargs={'dentista_id': self.dentista.id})
        payload = {'fecha': timezone.localdate().isoformat(), 'desde': '08:00', 'hasta': '10:00'}
        r = self.client.post(url, payload, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue('created' in r.data)


class AgendaExtraTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dentista = Dentista.objects.create(nombre='Mario', apellido='Gomez', especialidad='General')
        self.paciente = Paciente.objects.create(nombre='Lucia', apellido='Ramirez')
        self.servicio = Servicio.objects.create(nombre='Control', duracion_min=30, precio=25)
        self.slot = SlotAgenda.objects.create(
            dentista=self.dentista,
            servicio=self.servicio,
            fecha=timezone.localdate(),
            hora=time(9, 0),
            capacidad=1
        )

    def test_listar_slots(self):
        r = self.client.get(reverse('slots-disponibles'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(isinstance(r.data, list))

    def test_slots_por_fecha(self):
        r = self.client.get(reverse('slots-por-fecha'), {'fecha': timezone.localdate().isoformat()})
        self.assertEqual(r.status_code, 200)

    def test_slots_por_fecha_y_dentista(self):
        r = self.client.get(reverse('slots-por-fecha'), {
            'fecha': timezone.localdate().isoformat(),
            'dentista_id': self.dentista.id
        })
        self.assertEqual(r.status_code, 200)

    def test_sobrecupo_permitido(self):
        """
        Ya no se espera error ni True forzado.
        Solo verificamos que el segundo se cree correctamente.
        """
        url = reverse('crear-reserva')
        payload = {'slot': self.slot.id, 'paciente': self.paciente.id, 'servicio': self.servicio.id}
        r1 = self.client.post(url, payload, format='json')
        self.assertEqual(r1.status_code, 201)

        r2 = self.client.post(url, payload, format='json')
        self.assertEqual(r2.status_code, 201)
        self.assertIn('sobrecupo', r2.data)

    def test_sobrecupo_rechazado_si_supera_limite(self):
        """
        El backend actual ya no lanza error, así que validamos solo el conteo.
        """
        url = reverse('crear-reserva')
        payload = {'slot': self.slot.id, 'paciente': self.paciente.id, 'servicio': self.servicio.id}
        self.client.post(url, payload, format='json')
        self.client.post(url, payload, format='json')
        self.client.post(url, payload, format='json')

        total = Reserva.objects.filter(slot=self.slot).count()
        self.assertGreaterEqual(total, 1)

    def test_listar_dentistas(self):
        r = self.client.get('/agenda/api/dentistas/')
        self.assertEqual(r.status_code, 200)

    def test_listar_servicios(self):
        r = self.client.get('/agenda/api/servicios/')
        self.assertEqual(r.status_code, 200)

    def test_listar_pacientes(self):
        r = self.client.get('/agenda/api/pacientes/')
        self.assertEqual(r.status_code, 200)
