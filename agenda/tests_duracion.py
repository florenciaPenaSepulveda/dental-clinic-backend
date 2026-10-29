import datetime

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import Reserva, Servicio
from .tests_api import BASE, MANANA, crear_dentista, crear_paciente, crear_slot


def hora(h, m=0):
    return datetime.time(h, m)


class DuracionBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.dentista = crear_dentista(max_overbook_day=0)
        self.paciente = crear_paciente()
        self.otro = crear_paciente(rut="22.222.222-2", nombre="Marta")
        self.s30 = Servicio.objects.create(nombre="Limpieza", duracion_min=30, precio=10000)
        self.s45 = Servicio.objects.create(nombre="Extracción", duracion_min=45, precio=20000)
        self.s60 = Servicio.objects.create(nombre="Conducto", duracion_min=60, precio=30000)
        self.s90 = Servicio.objects.create(nombre="Blanqueamiento", duracion_min=90, precio=40000)
        self.slots = {h: crear_slot(self.dentista, hora=hora(*h)) for h in [(15, 0), (15, 30), (16, 0), (16, 30), (17, 0), (17, 30)]}

    def reservar(self, slot, servicio, paciente=None):
        datos = {"slot": slot.id, "paciente": (paciente or self.paciente).id, "servicio": servicio.id}
        return self.client.post(f"{BASE}/reservas/", datos, format="json")

    def disponibilidad(self, servicio=None):
        parametros = {"fecha": MANANA.isoformat(), "dentista_id": self.dentista.id}
        if servicio:
            parametros["servicio_id"] = servicio.id
        return {fila["hora"][:5]: fila for fila in self.client.get(f"{BASE}/slots_por_fecha/", parametros).json()}


class BloqueoPorDuracionTests(DuracionBase):
    def test_un_servicio_de_30_minutos_no_bloquea_nada(self):
        self.assertEqual(self.reservar(self.slots[(17, 0)], self.s30).status_code, 201)
        self.assertFalse(self.disponibilidad()["17:30"]["bloqueado"])
        self.assertEqual(self.reservar(self.slots[(17, 30)], self.s30, self.otro).status_code, 201)

    def test_un_servicio_de_60_minutos_bloquea_el_horario_siguiente(self):
        self.assertEqual(self.reservar(self.slots[(16, 0)], self.s60).status_code, 201)
        filas = self.disponibilidad()
        self.assertTrue(filas["16:30"]["bloqueado"])
        self.assertFalse(filas["17:00"]["bloqueado"])
        rechazo = self.reservar(self.slots[(16, 30)], self.s30, self.otro)
        self.assertEqual(rechazo.status_code, 400)
        self.assertIn("ocupado", rechazo.json()["detail"])

    def test_un_servicio_de_45_minutos_tambien_bloquea_el_siguiente(self):
        self.reservar(self.slots[(16, 0)], self.s45)
        self.assertTrue(self.disponibilidad()["16:30"]["bloqueado"])

    def test_un_servicio_de_90_minutos_bloquea_dos_horarios(self):
        self.assertEqual(self.reservar(self.slots[(15, 0)], self.s90).status_code, 201)
        filas = self.disponibilidad()
        self.assertTrue(filas["15:30"]["bloqueado"])
        self.assertTrue(filas["16:00"]["bloqueado"])
        self.assertFalse(filas["16:30"]["bloqueado"])

    def test_rechaza_un_servicio_que_no_cabe_antes_del_cierre(self):
        respuesta = self.reservar(self.slots[(17, 30)], self.s60)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("60 minutos", respuesta.json()["detail"])
        self.assertFalse(Reserva.objects.exists())

    def test_rechaza_un_servicio_cuando_el_siguiente_horario_ya_esta_reservado(self):
        self.reservar(self.slots[(17, 30)], self.s30, self.otro)
        self.assertEqual(self.reservar(self.slots[(17, 0)], self.s60).status_code, 400)
        self.assertEqual(self.reservar(self.slots[(17, 0)], self.s30).status_code, 201)

    def test_la_disponibilidad_indica_si_el_servicio_cabe(self):
        filas = self.disponibilidad(self.s60)
        self.assertTrue(filas["17:00"]["cabe"])
        self.assertFalse(filas["17:30"]["cabe"])
        self.assertTrue(self.disponibilidad(self.s30)["17:30"]["cabe"])
        self.reservar(self.slots[(17, 30)], self.s30, self.otro)
        self.assertFalse(self.disponibilidad(self.s60)["17:00"]["cabe"])

    def test_sin_servicio_ocupa_un_solo_horario(self):
        datos = {"slot": self.slots[(17, 0)].id, "paciente": self.paciente.id}
        self.assertEqual(self.client.post(f"{BASE}/reservas/", datos, format="json").status_code, 201)
        self.assertFalse(self.disponibilidad()["17:30"]["bloqueado"])

    def test_la_agenda_semanal_marca_los_horarios_bloqueados(self):
        self.reservar(self.slots[(16, 0)], self.s60)
        usuario = get_user_model().objects.create_user("personal", password="clave-segura-123", is_staff=True)
        self.client.force_authenticate(usuario)
        filas = self.client.get(f"{BASE}/semana/", {"desde": MANANA.isoformat(), "dentista": self.dentista.id}).json()
        bloqueados = {fila["hora"][:5] for fila in filas if fila["bloqueado"]}
        self.assertEqual(bloqueados, {"16:30"})

    def test_rechaza_un_identificador_de_servicio_invalido(self):
        respuesta = self.client.get(f"{BASE}/slots_por_fecha/", {"servicio_id": "abc"})
        self.assertEqual(respuesta.status_code, 400)


class CambioDeReservaTests(DuracionBase):
    def setUp(self):
        super().setUp()
        usuario = get_user_model().objects.create_user("personal", password="clave-segura-123", is_staff=True)
        self.client.force_authenticate(usuario)

    def actualizar(self, reserva, **datos):
        return self.client.patch(f"{BASE}/api/reservas/{reserva.id}/", datos, format="json")

    def test_no_permite_alargar_el_servicio_si_el_siguiente_horario_esta_ocupado(self):
        self.reservar(self.slots[(17, 30)], self.s30, self.otro)
        creada = self.reservar(self.slots[(17, 0)], self.s30)
        reserva = Reserva.objects.get(pk=creada.json()["id"])
        self.assertEqual(self.actualizar(reserva, servicio=self.s60.id).status_code, 400)
        self.assertEqual(self.actualizar(reserva, servicio=self.s30.id).status_code, 200)

    def test_permite_alargar_el_servicio_si_hay_espacio(self):
        reserva = Reserva.objects.get(pk=self.reservar(self.slots[(16, 0)], self.s30).json()["id"])
        self.assertEqual(self.actualizar(reserva, servicio=self.s60.id).status_code, 200)
        self.assertTrue(self.disponibilidad()["16:30"]["bloqueado"])

    def test_no_permite_mover_a_un_horario_bloqueado(self):
        self.reservar(self.slots[(16, 0)], self.s60)
        reserva = Reserva.objects.get(pk=self.reservar(self.slots[(17, 0)], self.s30, self.otro).json()["id"])
        self.assertEqual(self.actualizar(reserva, slot=self.slots[(16, 30)].id).status_code, 400)

    def test_cambiar_solo_el_estado_no_revalida_el_espacio(self):
        reserva = Reserva.objects.get(pk=self.reservar(self.slots[(16, 0)], self.s60).json()["id"])
        self.assertEqual(self.actualizar(reserva, estado="atendida").status_code, 200)


class ServiciosApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.recepcion = get_user_model().objects.create_user("recepcion", password="clave-segura-123", is_staff=True)

    def test_recepcion_crea_y_edita_servicios(self):
        self.client.force_authenticate(self.recepcion)
        creado = self.client.post(f"{BASE}/api/servicios/", {"nombre": "  Endodoncia ", "duracion_min": 90, "precio": "120000"}, format="json")
        self.assertEqual(creado.status_code, 201)
        self.assertEqual(creado.json()["nombre"], "Endodoncia")
        editado = self.client.patch(f"{BASE}/api/servicios/{creado.json()['id']}/", {"duracion_min": 60}, format="json")
        self.assertEqual(editado.json()["duracion_min"], 60)

    def test_valida_duracion_nombre_y_precio(self):
        self.client.force_authenticate(self.recepcion)
        url = f"{BASE}/api/servicios/"
        base = {"nombre": "Limpieza", "duracion_min": 30, "precio": "1000"}
        for cambio in ({"duracion_min": 10}, {"duracion_min": 50}, {"duracion_min": 300}, {"nombre": "   "}, {"precio": "-5"}):
            self.assertEqual(self.client.post(url, {**base, **cambio}, format="json").status_code, 400, cambio)
        self.assertEqual(self.client.post(url, {**base, "duracion_min": 45}, format="json").status_code, 201)

    def test_el_publico_solo_puede_leer(self):
        servicio = Servicio.objects.create(nombre="Limpieza", duracion_min=30, precio=1000)
        self.assertEqual(self.client.get(f"{BASE}/api/servicios/").status_code, 200)
        self.assertIn(self.client.post(f"{BASE}/api/servicios/", {"nombre": "X", "duracion_min": 30, "precio": "1"}, format="json").status_code, (401, 403))
        self.assertIn(self.client.patch(f"{BASE}/api/servicios/{servicio.id}/", {"nombre": "Y"}, format="json").status_code, (401, 403))
