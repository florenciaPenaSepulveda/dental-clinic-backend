import datetime
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from .demo_data import cargar_demo
from .models import Dentista, Paciente, Reserva, SlotAgenda
from .utils import es_correo_de_ejemplo, rut_con_dv

LUNES = datetime.date(2026, 11, 2)


class DatosDeDemostracionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.resumen = cargar_demo(hoy=LUNES)

    def test_carga_los_catalogos_completos(self):
        self.assertEqual(self.resumen["regiones"], 3)
        self.assertEqual(self.resumen["dentistas"], 5)
        self.assertEqual(self.resumen["servicios"], 7)
        self.assertEqual(self.resumen["pacientes"], 24)
        self.assertGreater(self.resumen["slots"], 500)
        self.assertGreater(self.resumen["reservas"], 30)

    def test_crea_un_usuario_de_personal_una_sola_vez(self):
        cargar_demo(hoy=LUNES)
        usuarios = get_user_model().objects.filter(username="recepcion")
        self.assertEqual(usuarios.count(), 1)
        self.assertTrue(usuarios.get().is_staff)
        self.assertTrue(usuarios.get().check_password("recepcion123"))

    def test_es_idempotente(self):
        reservas = Reserva.objects.count()
        slots = SlotAgenda.objects.count()
        segunda = cargar_demo(hoy=LUNES)
        self.assertEqual(segunda["reservas"], 0)
        self.assertEqual(Reserva.objects.count(), reservas)
        self.assertEqual(SlotAgenda.objects.count(), slots)
        self.assertEqual(Paciente.objects.count(), 24)

    def test_la_agenda_solo_tiene_dias_habiles_en_horario_de_atencion(self):
        self.assertFalse(any(slot.fecha.weekday() >= 5 for slot in SlotAgenda.objects.all()))
        horas = {slot.hora for slot in SlotAgenda.objects.all()}
        self.assertGreaterEqual(min(horas), datetime.time(9, 0))
        self.assertLessEqual(max(horas), datetime.time(17, 30))
        self.assertTrue(all(hora.minute in (0, 30) for hora in horas))

    def test_las_reservas_respetan_los_cupos_y_sobrecupos(self):
        for slot in SlotAgenda.objects.all():
            reservas = list(slot.reservas.all())
            sobrecupos = [reserva for reserva in reservas if reserva.sobrecupo]
            self.assertLessEqual(len(reservas) - len(sobrecupos), slot.capacidad)
            self.assertLessEqual(len(sobrecupos), slot.max_overbook)
        for dentista in Dentista.objects.all():
            fechas = set(Reserva.objects.filter(slot__dentista=dentista, sobrecupo=True).values_list("slot__fecha", flat=True))
            for fecha in fechas:
                cantidad = Reserva.objects.filter(slot__dentista=dentista, slot__fecha=fecha, sobrecupo=True).count()
                self.assertLessEqual(cantidad, dentista.max_overbook_day)

    def test_incluye_al_menos_un_sobrecupo(self):
        self.assertTrue(Reserva.objects.filter(sobrecupo=True).exists())

    def test_los_pacientes_tienen_rut_valido_y_unico(self):
        ruts = list(Paciente.objects.values_list("rut", flat=True))
        self.assertEqual(len(ruts), len(set(ruts)))
        self.assertIn(rut_con_dv(14000000), ruts)

    def test_el_comando_informa_el_resumen(self):
        salida = StringIO()
        call_command("seed_data", "--demo", stdout=salida)
        texto = salida.getvalue()
        self.assertIn("Datos de demostración cargados", texto)
        self.assertIn("Dentistas: 5", texto)


class CorreosDeEjemploTests(APITestCase):
    def test_reconoce_dominios_reservados(self):
        self.assertTrue(es_correo_de_ejemplo("ana@example.com"))
        self.assertTrue(es_correo_de_ejemplo("ana@EXAMPLE.org"))
        self.assertTrue(es_correo_de_ejemplo("ana@correo.test"))
        self.assertFalse(es_correo_de_ejemplo("ana@gmail.com"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_no_envia_confirmaciones_a_correos_de_ejemplo(self):
        cargar_demo(hoy=LUNES)
        slot = SlotAgenda.objects.filter(reservas__isnull=True).first()
        paciente = Paciente.objects.filter(email__endswith="@example.com").first()
        respuesta = self.client.post("/agenda/reservas/", {"slot": slot.id, "paciente": paciente.id}, format="json")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)
