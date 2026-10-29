import datetime
from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Dentista, Paciente, Region, Reserva, Servicio, SlotAgenda
from .slots_generator import generate_slots_for_day, generate_slots_range

BASE = "/agenda"
MANANA = timezone.localdate() + datetime.timedelta(days=1)


def autenticar_personal(cliente):
    usuario = get_user_model().objects.create_user("personal", password="clave-segura-123", is_staff=True)
    cliente.force_authenticate(usuario)
    return usuario


def crear_dentista(**extra):
    datos = {"nombre": "Ana", "apellido": "Pérez", "especialidad": "Ortodoncia", "max_overbook_day": 1}
    datos.update(extra)
    return Dentista.objects.create(**datos)


def crear_paciente(rut="12.345.678-5", **extra):
    datos = {"rut": rut, "nombre": "Juan", "apellido": "Soto"}
    datos.update(extra)
    return Paciente.objects.create(**datos)


def crear_slot(dentista, hora=datetime.time(10, 0), fecha=MANANA, **extra):
    return SlotAgenda.objects.create(dentista=dentista, fecha=fecha, hora=hora, **extra)


class ModelosTests(TestCase):
    def test_representaciones_en_texto(self):
        region = Region.objects.create(nombre="Biobío", codigo="08")
        dentista = crear_dentista(region=region)
        paciente = crear_paciente()
        servicio = Servicio.objects.create(nombre="Limpieza", duracion_min=30, precio=15000)
        slot = crear_slot(dentista, servicio=servicio)
        reserva = Reserva.objects.create(slot=slot, paciente=paciente, sobrecupo=True)
        self.assertEqual(str(region), "Biobío")
        self.assertIn("Ana Pérez", str(dentista))
        self.assertEqual(str(paciente), "Juan Soto")
        self.assertEqual(str(servicio), "Limpieza")
        self.assertIn("Ana Pérez", str(slot))
        self.assertIn("(Sobrecupo)", str(reserva))

    def test_el_slot_valida_horario_y_bloques(self):
        dentista = crear_dentista()
        with self.assertRaises(ValidationError):
            crear_slot(dentista, hora=datetime.time(7, 30))
        with self.assertRaises(ValidationError):
            crear_slot(dentista, hora=datetime.time(18, 30))
        with self.assertRaises(ValidationError):
            crear_slot(dentista, hora=datetime.time(10, 15))

    def test_no_permite_slots_duplicados(self):
        dentista = crear_dentista()
        crear_slot(dentista)
        with self.assertRaises(ValidationError):
            crear_slot(dentista)

    def test_el_rut_es_unico(self):
        crear_paciente()
        with self.assertRaises(Exception):
            crear_paciente()


class GeneradorDeSlotsTests(TestCase):
    def test_genera_bloques_de_30_minutos_sin_duplicar(self):
        dentista = crear_dentista()
        creados = generate_slots_for_day(dentista, MANANA, desde="08:00", hasta="10:00")
        self.assertEqual(creados, 4)
        self.assertEqual(generate_slots_for_day(dentista, MANANA, desde="08:00", hasta="10:00"), 0)
        self.assertEqual(SlotAgenda.objects.filter(dentista=dentista).count(), 4)

    def test_genera_un_rango_de_dias(self):
        dentista = crear_dentista()
        total = generate_slots_range(dentista, MANANA, MANANA + datetime.timedelta(days=2), desde="08:00", hasta="09:00")
        self.assertEqual(total, 6)

    def test_acepta_objetos_time(self):
        dentista = crear_dentista()
        creados = generate_slots_for_day(dentista, MANANA, desde=datetime.time(8, 0), hasta=datetime.time(8, 30))
        self.assertEqual(creados, 1)


class CatalogosApiTests(APITestCase):
    def setUp(self):
        autenticar_personal(self.client)

    def test_crud_de_regiones_servicios_y_pacientes(self):
        region = self.client.post(f"{BASE}/api/regiones/", {"nombre": "Ñuble", "codigo": "16"}, format="json")
        self.assertEqual(region.status_code, 201)
        servicio = self.client.post(
            f"{BASE}/api/servicios/", {"nombre": "Extracción", "duracion_min": 60, "precio": "30000.00"}, format="json"
        )
        self.assertEqual(servicio.status_code, 201)
        paciente = self.client.post(
            f"{BASE}/api/pacientes/", {"rut": "11.111.111-1", "nombre": "Ana", "apellido": "Ríos"}, format="json"
        )
        self.assertEqual(paciente.status_code, 201)

        listado = self.client.get(f"{BASE}/api/pacientes/")
        self.assertEqual(listado.status_code, 200)
        self.assertEqual(listado.json()["count"], 1)

        actualizado = self.client.patch(f"{BASE}/api/pacientes/{paciente.json()['id']}/", {"telefono": "+56 9 1234 5678"}, format="json")
        self.assertEqual(actualizado.json()["telefono"], "+56 9 1234 5678")
        eliminado = self.client.delete(f"{BASE}/api/pacientes/{paciente.json()['id']}/")
        self.assertEqual(eliminado.status_code, 204)

    def test_rechaza_un_rut_repetido(self):
        crear_paciente()
        respuesta = self.client.post(
            f"{BASE}/api/pacientes/", {"rut": "12.345.678-5", "nombre": "Otra", "apellido": "Persona"}, format="json"
        )
        self.assertEqual(respuesta.status_code, 400)

    def test_filtra_dentistas_por_region(self):
        sur = Region.objects.create(nombre="Sur", codigo="S")
        norte = Region.objects.create(nombre="Norte", codigo="N")
        crear_dentista(nombre="Sur", region=sur)
        crear_dentista(nombre="Norte", region=norte)
        todos = self.client.get(f"{BASE}/api/dentistas/").json()
        filtrados = self.client.get(f"{BASE}/api/dentistas/?region={sur.id}").json()
        self.assertEqual(len(todos), 2)
        self.assertEqual([d["nombre"] for d in filtrados], ["Sur"])
        self.assertEqual(filtrados[0]["region"]["codigo"], "S")


class SlotsApiTests(APITestCase):
    def setUp(self):
        autenticar_personal(self.client)
        self.dentista = crear_dentista()

    def test_lista_solo_slots_desde_hoy(self):
        crear_slot(self.dentista, fecha=timezone.localdate() - datetime.timedelta(days=2))
        crear_slot(self.dentista, fecha=MANANA)
        respuesta = self.client.get(f"{BASE}/slots/")
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        resultados = datos["results"] if isinstance(datos, dict) else datos
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["fecha"], MANANA.isoformat())

    def test_filtra_por_fecha_y_dentista(self):
        otro = crear_dentista(nombre="Luis")
        crear_slot(self.dentista, hora=datetime.time(9, 0))
        crear_slot(otro, hora=datetime.time(9, 30))
        por_fecha = self.client.get(f"{BASE}/slots_por_fecha/", {"fecha": MANANA.isoformat()}).json()
        por_dentista = self.client.get(
            f"{BASE}/slots_por_fecha/", {"fecha": MANANA.isoformat(), "dentista_id": otro.id}
        ).json()
        self.assertEqual(len(por_fecha), 2)
        self.assertEqual(len(por_dentista), 1)
        self.assertEqual(self.client.get(f"{BASE}/slots_por_fecha/").status_code, 200)

    def test_fecha_invalida_en_el_filtro(self):
        respuesta = self.client.get(f"{BASE}/slots_por_fecha/", {"fecha": "24-10-2026"})
        self.assertEqual(respuesta.status_code, 400)

    def test_genera_slots_de_un_dia_y_de_varios(self):
        url = f"{BASE}/dentistas/{self.dentista.id}/generar_slots/"
        uno = self.client.post(url, {"fecha": MANANA.isoformat(), "desde": "08:00", "hasta": "09:00"}, format="json")
        self.assertEqual(uno.status_code, 201)
        self.assertEqual(uno.json()["created"], 2)
        varios = self.client.post(
            url, {"fecha": (MANANA + datetime.timedelta(days=5)).isoformat(), "desde": "08:00", "hasta": "08:30", "dias": 2}, format="json"
        )
        self.assertEqual(varios.json()["created"], 2)

    def test_generar_slots_valida_los_datos(self):
        url = f"{BASE}/dentistas/{self.dentista.id}/generar_slots/"
        self.assertEqual(self.client.post(f"{BASE}/dentistas/999/generar_slots/", {"fecha": MANANA.isoformat()}, format="json").status_code, 404)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"fecha": "no-es-fecha"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"fecha": MANANA.isoformat(), "dias": "abc"}, format="json").status_code, 400)


class ReservasApiTests(APITestCase):
    def setUp(self):
        self.dentista = crear_dentista(max_overbook_day=1)
        self.paciente = crear_paciente()
        self.otro = crear_paciente(rut="22.222.222-2", nombre="Marta")
        self.tercero = crear_paciente(rut="33.333.333-3", nombre="Pedro")
        self.servicio = Servicio.objects.create(nombre="Limpieza", duracion_min=30, precio=15000)
        self.slot = crear_slot(self.dentista, capacidad=1, max_overbook=1)

    def reservar(self, paciente, **extra):
        datos = {"slot": self.slot.id, "paciente": paciente.id}
        datos.update(extra)
        return self.client.post(f"{BASE}/reservas/", datos, format="json")

    def test_crea_una_reserva_normal(self):
        respuesta = self.reservar(self.paciente, servicio=self.servicio.id)
        self.assertEqual(respuesta.status_code, 201)
        self.assertFalse(respuesta.json()["sobrecupo"])

    def test_repetir_la_reserva_devuelve_la_existente(self):
        primera = self.reservar(self.paciente).json()["id"]
        segunda = self.reservar(self.paciente).json()["id"]
        self.assertEqual(primera, segunda)
        self.assertEqual(Reserva.objects.count(), 1)

    def test_sobrecupo_hasta_el_limite_del_slot(self):
        self.reservar(self.paciente)
        con_sobrecupo = self.reservar(self.otro)
        self.assertTrue(con_sobrecupo.json()["sobrecupo"])
        lleno = self.reservar(self.tercero)
        self.assertEqual(lleno.status_code, 400)

    def test_sobrecupo_respeta_el_limite_diario_del_dentista(self):
        self.dentista.max_overbook_day = 0
        self.dentista.save()
        self.reservar(self.paciente)
        self.assertEqual(self.reservar(self.otro).status_code, 400)

    def test_reserva_buscando_el_horario_por_dentista_fecha_y_hora(self):
        crear_slot(self.dentista, hora=datetime.time(11, 0))
        datos = {"paciente": self.paciente.id, "dentista": self.dentista.id, "fecha": MANANA.isoformat(), "hora_inicio": "11:00"}
        self.assertEqual(self.client.post(f"{BASE}/reservas/", datos, format="json").status_code, 201)

    def test_no_crea_horarios_inexistentes_desde_el_publico(self):
        datos = {"paciente": self.paciente.id, "dentista": self.dentista.id, "fecha": MANANA.isoformat(), "hora_inicio": "11:30"}
        self.assertEqual(self.client.post(f"{BASE}/reservas/", datos, format="json").status_code, 400)
        self.assertFalse(SlotAgenda.objects.filter(hora=datetime.time(11, 30)).exists())

    def test_rechaza_horarios_que_ya_pasaron(self):
        ayer = crear_slot(self.dentista, hora=datetime.time(12, 0), fecha=timezone.localdate() - datetime.timedelta(days=1))
        respuesta = self.reservar(self.paciente, slot=ayer.id)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("ya pasó", str(respuesta.json()))
        self.assertEqual(Reserva.objects.count(), 0)

    def test_valida_los_datos_de_entrada(self):
        sin_slot = self.client.post(f"{BASE}/reservas/", {"paciente": self.paciente.id}, format="json")
        self.assertEqual(sin_slot.status_code, 400)
        sin_paciente = self.client.post(f"{BASE}/reservas/", {"slot": self.slot.id, "paciente": 9999}, format="json")
        self.assertEqual(sin_paciente.status_code, 400)
        sin_servicio = self.reservar(self.paciente, servicio=9999)
        self.assertEqual(sin_servicio.status_code, 400)
        sin_dentista = self.client.post(
            f"{BASE}/reservas/",
            {"paciente": self.paciente.id, "dentista": 9999, "fecha": MANANA.isoformat(), "hora_inicio": "12:00"},
            format="json",
        )
        self.assertEqual(sin_dentista.status_code, 400)

    def test_viewset_crea_lista_y_filtra(self):
        autenticar_personal(self.client)
        creada = self.client.post(f"{BASE}/api/reservas/", {"slot": self.slot.id, "paciente": self.paciente.id}, format="json")
        self.assertEqual(creada.status_code, 201)
        self.assertTrue(creada.json()["created"])

        todas = self.client.get(f"{BASE}/api/reservas/")
        self.assertEqual(todas.status_code, 200)
        self.assertEqual(todas.json()["count"], 1)
        por_dentista = self.client.get(f"{BASE}/api/reservas/", {"dentista": self.dentista.id}).json()["results"]
        por_fecha = self.client.get(f"{BASE}/api/reservas/", {"fecha": MANANA.isoformat()}).json()["results"]
        fuera = self.client.get(f"{BASE}/api/reservas/", {"fecha": "2000-01-01"}).json()["results"]
        self.assertEqual((len(por_dentista), len(por_fecha), len(fuera)), (1, 1, 0))

        detalle = self.client.get(f"{BASE}/api/reservas/{creada.json()['id']}/")
        self.assertEqual(detalle.status_code, 200)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="clinica@test.cl")
class CorreoDeConfirmacionTests(APITestCase):
    def setUp(self):
        self.slot = crear_slot(crear_dentista())

    def test_envia_el_correo_cuando_el_paciente_tiene_email(self):
        paciente = crear_paciente(email="juan@test.cl")
        self.client.post(f"{BASE}/reservas/", {"slot": self.slot.id, "paciente": paciente.id}, format="json")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["juan@test.cl"])
        self.assertIn("Confirmación", mail.outbox[0].subject)

    def test_omite_el_correo_sin_email(self):
        paciente = crear_paciente()
        respuesta = self.client.post(f"{BASE}/reservas/", {"slot": self.slot.id, "paciente": paciente.id}, format="json")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)

    def test_un_fallo_de_correo_no_bloquea_la_reserva(self):
        paciente = crear_paciente(email="juan@test.cl")
        with mock.patch("agenda.serializers.send_mail", side_effect=OSError("sin red")):
            respuesta = self.client.post(f"{BASE}/reservas/", {"slot": self.slot.id, "paciente": paciente.id}, format="json")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(Reserva.objects.count(), 1)
