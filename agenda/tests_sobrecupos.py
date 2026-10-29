import datetime

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase

from .models import Dentista, Reserva, SobrecupoDia
from .tests_api import BASE, MANANA, crear_dentista, crear_paciente, crear_slot

User = get_user_model()


def pasado_manana():
    return MANANA + datetime.timedelta(days=1)


class SobrecuposBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.recepcion = User.objects.create_user("recepcion", password="clave-segura-123", is_staff=True)
        self.dentista = crear_dentista(max_overbook_day=2)
        self.dentista.usuario = User.objects.create_user("dr.perez", password="clave-segura-123")
        self.dentista.save()
        self.otro_dentista = crear_dentista(nombre="Luis", apellido="Rojas", max_overbook_day=1)
        self.otro_dentista.usuario = User.objects.create_user("dr.rojas", password="clave-segura-123")
        self.otro_dentista.save()
        self.pacientes = [crear_paciente(rut=rut, nombre=f"P{i}") for i, rut in enumerate(["11.111.111-1", "22.222.222-2", "33.333.333-3", "44.444.444-4"])]
        self.slot = crear_slot(self.dentista, hora=datetime.time(10, 0))
        self.slot2 = crear_slot(self.dentista, hora=datetime.time(11, 0))
        self.slot3 = crear_slot(self.dentista, hora=datetime.time(12, 0))
        self.client.force_authenticate(self.recepcion)

    def reservar(self, paciente, slot=None, **extra):
        datos = {"slot": (slot or self.slot).id, "paciente": paciente.id, **extra}
        return self.client.post(f"{BASE}/reservas/", datos, format="json")

    def llenar(self, slot=None):
        self.assertEqual(self.reservar(self.pacientes[0], slot).status_code, 201)


class AgendarSobrecuposTests(SobrecuposBase):
    def test_recepcion_agenda_un_sobrecupo_en_un_horario_completo(self):
        self.llenar()
        respuesta = self.reservar(self.pacientes[1], sobrecupo=True)
        self.assertEqual(respuesta.status_code, 201)
        self.assertTrue(respuesta.json()["sobrecupo"])

    def test_el_dentista_agenda_sobrecupos_en_su_propia_agenda(self):
        self.llenar()
        self.client.force_authenticate(self.dentista.usuario)
        self.assertEqual(self.reservar(self.pacientes[1], sobrecupo=True).status_code, 201)

    def test_un_dentista_no_agenda_sobrecupos_en_la_agenda_de_otro(self):
        self.llenar()
        self.client.force_authenticate(self.otro_dentista.usuario)
        rechazo = self.reservar(self.pacientes[1], sobrecupo=True)
        self.assertEqual(rechazo.status_code, 400)
        self.assertIn("propio dentista", rechazo.json()["detail"])

    def test_el_publico_nunca_agenda_sobrecupos(self):
        self.llenar()
        self.client.force_authenticate(None)
        self.assertEqual(self.reservar(self.pacientes[1], sobrecupo=True).status_code, 400)
        self.assertEqual(self.reservar(self.pacientes[1]).status_code, 400)

    def test_un_horario_completo_sugiere_el_sobrecupo_solo_al_personal(self):
        self.llenar()
        self.assertIn("sobrecupo", self.reservar(self.pacientes[1]).json()["detail"])
        self.client.force_authenticate(None)
        self.assertNotIn("sobrecupo", self.reservar(self.pacientes[1]).json()["detail"])

    def test_no_se_agenda_como_sobrecupo_un_horario_con_espacio(self):
        rechazo = self.reservar(self.pacientes[0], sobrecupo=True)
        self.assertEqual(rechazo.status_code, 400)
        self.assertIn("aún tiene espacio", rechazo.json()["detail"])

    def test_solo_un_sobrecupo_por_horario(self):
        self.llenar()
        self.reservar(self.pacientes[1], sobrecupo=True)
        rechazo = self.reservar(self.pacientes[2], sobrecupo=True)
        self.assertEqual(rechazo.status_code, 400)
        self.assertIn("ya tiene un sobrecupo", rechazo.json()["detail"])

    def test_respeta_el_limite_de_sobrecupos_del_dia(self):
        for slot, indice in ((self.slot, 0), (self.slot2, 1), (self.slot3, 2)):
            self.reservar(self.pacientes[indice], slot)
        self.assertEqual(self.reservar(self.pacientes[3], self.slot, sobrecupo=True).status_code, 201)
        self.assertEqual(self.reservar(self.pacientes[3], self.slot2, sobrecupo=True).status_code, 201)
        rechazo = self.reservar(self.pacientes[3], self.slot3, sobrecupo=True)
        self.assertEqual(rechazo.status_code, 400)
        self.assertIn("límite de 2 sobrecupos", rechazo.json()["detail"])

    def test_un_dentista_sin_sobrecupos_los_rechaza(self):
        Dentista.objects.filter(pk=self.dentista.pk).update(max_overbook_day=0)
        self.llenar()
        rechazo = self.reservar(self.pacientes[1], sobrecupo=True)
        self.assertEqual(rechazo.status_code, 400)
        self.assertIn("no admite sobrecupos", rechazo.json()["detail"])

    def test_el_limite_de_una_fecha_reemplaza_al_valor_por_defecto(self):
        Dentista.objects.filter(pk=self.dentista.pk).update(max_overbook_day=0)
        SobrecupoDia.objects.create(dentista=self.dentista, fecha=MANANA, cupos=1)
        self.llenar()
        self.assertEqual(self.reservar(self.pacientes[1], sobrecupo=True).status_code, 201)

    def test_un_sobrecupo_no_bloquea_los_horarios_siguientes(self):
        self.llenar()
        self.reservar(self.pacientes[1], sobrecupo=True)
        filas = {f["hora"][:5]: f for f in self.client.get(f"{BASE}/slots_por_fecha/", {"fecha": MANANA.isoformat(), "dentista_id": self.dentista.id}).json()}
        self.assertFalse(filas["11:00"]["bloqueado"])


class DisponibilidadDeSobrecuposTests(SobrecuposBase):
    def disponibilidad(self):
        filas = self.client.get(f"{BASE}/slots_por_fecha/", {"fecha": MANANA.isoformat(), "dentista_id": self.dentista.id}).json()
        return {fila["hora"][:5]: fila["sobrecupo_disponible"] for fila in filas}

    def test_solo_los_horarios_completos_con_cupo_ofrecen_sobrecupo(self):
        self.llenar()
        self.assertEqual(self.disponibilidad(), {"10:00": True, "11:00": False, "12:00": False})

    def test_deja_de_ofrecerse_cuando_el_horario_ya_tiene_su_sobrecupo(self):
        self.llenar()
        self.reservar(self.pacientes[1], sobrecupo=True)
        self.assertFalse(self.disponibilidad()["10:00"])

    def test_deja_de_ofrecerse_cuando_se_agota_el_limite_del_dia(self):
        Dentista.objects.filter(pk=self.dentista.pk).update(max_overbook_day=1)
        self.llenar(self.slot)
        self.llenar(self.slot2)
        self.reservar(self.pacientes[1], self.slot, sobrecupo=True)
        self.assertEqual(self.disponibilidad(), {"10:00": False, "11:00": False, "12:00": False})

    def test_no_se_ofrece_si_el_dentista_no_admite_sobrecupos(self):
        Dentista.objects.filter(pk=self.dentista.pk).update(max_overbook_day=0)
        self.llenar()
        self.assertFalse(self.disponibilidad()["10:00"])


class GestionDeSobrecuposTests(SobrecuposBase):
    url = f"{BASE}/sobrecupos/"

    def resumen(self, **extra):
        return self.client.get(self.url, {"dentista": self.dentista.id, "desde": MANANA.isoformat(), **extra})

    def fijar(self, **datos):
        return self.client.put(self.url, {"dentista": self.dentista.id, **datos}, format="json")

    def test_resume_la_semana_con_lo_permitido_y_lo_usado(self):
        self.llenar()
        self.reservar(self.pacientes[1], sobrecupo=True)
        SobrecupoDia.objects.create(dentista=self.dentista, fecha=pasado_manana(), cupos=4)
        datos = self.resumen().json()
        self.assertEqual(datos["por_defecto"], 2)
        self.assertEqual(len(datos["dias"]), 7)
        primero, segundo = datos["dias"][0], datos["dias"][1]
        self.assertEqual((primero["fecha"], primero["permitidos"], primero["usados"], primero["personalizado"]), (MANANA.isoformat(), 2, 1, False))
        self.assertEqual((segundo["permitidos"], segundo["usados"], segundo["personalizado"]), (4, 0, True))

    def test_recepcion_cambia_el_valor_por_defecto_de_cualquier_dentista(self):
        self.assertEqual(self.fijar(cupos=5).json(), {"por_defecto": 5})
        self.dentista.refresh_from_db()
        self.assertEqual(self.dentista.max_overbook_day, 5)

    def test_el_dentista_gestiona_sus_propios_sobrecupos(self):
        self.client.force_authenticate(self.dentista.usuario)
        self.assertEqual(self.client.get(self.url, {"desde": MANANA.isoformat()}).status_code, 200)
        respuesta = self.client.put(self.url, {"fecha": MANANA.isoformat(), "cupos": 3}, format="json")
        self.assertEqual(respuesta.json(), {"fecha": MANANA.isoformat(), "cupos": 3, "personalizado": True})
        self.assertEqual(SobrecupoDia.objects.get(dentista=self.dentista, fecha=MANANA).cupos, 3)

    def test_un_dentista_no_gestiona_los_de_otro(self):
        self.client.force_authenticate(self.otro_dentista.usuario)
        self.assertEqual(self.resumen().status_code, 403)
        self.assertEqual(self.fijar(cupos=3).status_code, 403)

    def test_el_publico_y_los_pacientes_no_gestionan_sobrecupos(self):
        self.client.force_authenticate(None)
        self.assertIn(self.resumen().status_code, (401, 403))
        self.assertIn(self.fijar(cupos=3).status_code, (401, 403))

    def test_define_y_quita_el_limite_de_una_fecha(self):
        self.assertEqual(self.fijar(fecha=MANANA.isoformat(), cupos=0).json()["cupos"], 0)
        self.assertEqual(SobrecupoDia.objects.count(), 1)
        quitado = self.fijar(fecha=MANANA.isoformat(), cupos=None).json()
        self.assertEqual((quitado["cupos"], quitado["personalizado"]), (2, False))
        self.assertFalse(SobrecupoDia.objects.exists())

    def test_no_permite_bajar_el_limite_por_debajo_de_los_sobrecupos_ya_agendados(self):
        self.llenar()
        self.reservar(self.pacientes[1], sobrecupo=True)
        rechazo = self.fijar(fecha=MANANA.isoformat(), cupos=0)
        self.assertEqual(rechazo.status_code, 400)
        self.assertIn("Ya hay 1 sobrecupo agendado", rechazo.json()["detail"])
        self.assertEqual(self.fijar(fecha=MANANA.isoformat(), cupos=1).status_code, 200)

    def test_valida_los_datos(self):
        self.assertEqual(self.fijar().status_code, 400)
        self.assertEqual(self.fijar(cupos=11).status_code, 400)
        self.assertEqual(self.fijar(cupos=-1).status_code, 400)
        self.assertEqual(self.fijar(cupos="muchos").status_code, 400)
        self.assertEqual(self.fijar(fecha="no-es-fecha", cupos=1).status_code, 400)
        ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.assertEqual(self.fijar(fecha=ayer, cupos=1).status_code, 400)
        self.assertEqual(self.client.put(self.url, {"cupos": 1}, format="json").status_code, 400)
        self.assertEqual(self.client.put(self.url, {"dentista": 999, "cupos": 1}, format="json").status_code, 404)
        self.assertEqual(self.client.get(self.url, {"dentista": self.dentista.id}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"desde": MANANA.isoformat()}).status_code, 400)

    def test_el_valor_por_defecto_del_dentista_tiene_un_maximo(self):
        respuesta = self.client.patch(f"{BASE}/api/dentistas/{self.dentista.id}/", {"max_overbook_day": 50}, format="json")
        self.assertEqual(respuesta.status_code, 400)


class MoverConSobrecupoTests(SobrecuposBase):
    def test_mover_a_un_horario_completo_lo_convierte_en_sobrecupo_y_viceversa(self):
        self.llenar(self.slot)
        reserva = Reserva.objects.get(pk=self.reservar(self.pacientes[1], self.slot2).json()["id"])
        enviar = lambda slot: self.client.patch(f"{BASE}/api/reservas/{reserva.id}/", {"slot": slot.id}, format="json")
        self.assertEqual(enviar(self.slot).status_code, 200)
        reserva.refresh_from_db()
        self.assertTrue(reserva.sobrecupo)
        self.assertEqual(enviar(self.slot3).status_code, 200)
        reserva.refresh_from_db()
        self.assertFalse(reserva.sobrecupo)

    def test_no_se_mueve_a_un_horario_que_ya_tiene_su_sobrecupo(self):
        self.llenar(self.slot)
        self.reservar(self.pacientes[1], self.slot, sobrecupo=True)
        reserva = Reserva.objects.get(pk=self.reservar(self.pacientes[2], self.slot2).json()["id"])
        rechazo = self.client.patch(f"{BASE}/api/reservas/{reserva.id}/", {"slot": self.slot.id}, format="json")
        self.assertEqual(rechazo.status_code, 400)
