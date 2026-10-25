import datetime

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Dentista, Paciente, Reserva, SlotAgenda

BASE = "/agenda"
MANANA = timezone.localdate() + datetime.timedelta(days=1)
CLAVE = "clave-segura-123"


class AutenticacionTests(APITestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.personal = User.objects.create_user("recepcion", password=CLAVE, is_staff=True)
        self.cliente = User.objects.create_user("cliente", password=CLAVE)

    def login(self, usuario="recepcion", clave=CLAVE):
        return self.client.post(f"{BASE}/auth/login/", {"username": usuario, "password": clave}, format="json")

    def test_el_personal_inicia_sesion_y_recibe_un_token(self):
        respuesta = self.login()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["username"], "recepcion")
        self.assertEqual(respuesta.json()["token"], Token.objects.get(user=self.personal).key)

    def test_rechaza_credenciales_incorrectas(self):
        self.assertEqual(self.login(clave="otra").status_code, 400)
        self.assertEqual(self.login(usuario="nadie").status_code, 400)
        self.assertEqual(self.client.post(f"{BASE}/auth/login/", {}, format="json").status_code, 400)

    def test_un_usuario_sin_permiso_de_personal_no_puede_entrar(self):
        self.assertEqual(self.login(usuario="cliente").status_code, 400)
        self.assertFalse(Token.objects.filter(user=self.cliente).exists())

    def test_el_token_da_acceso_y_cerrar_sesion_lo_invalida(self):
        token = self.login().json()["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.get(f"{BASE}/auth/me/").json()["rol"], "recepcion")
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/").status_code, 200)
        self.assertEqual(self.client.post(f"{BASE}/auth/logout/").status_code, 204)
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/").status_code, 401)

    def test_limita_los_intentos_de_inicio_de_sesion(self):
        estados = [self.login(clave="mala").status_code for _ in range(25)]
        self.assertEqual(estados[0], 400)
        self.assertEqual(estados[-1], 429)


class AccesoPublicoTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.dentista = Dentista.objects.create(nombre="Ana", apellido="Pérez", max_overbook_day=1)
        self.paciente = Paciente.objects.create(rut="12.345.678-5", nombre="Juan", apellido="Soto", email="j@test.cl")
        self.slot = SlotAgenda.objects.create(dentista=self.dentista, fecha=MANANA, hora=datetime.time(10, 0), capacidad=1, max_overbook=1)

    def test_los_catalogos_son_publicos_pero_no_se_pueden_modificar(self):
        for recurso in ("dentistas", "servicios", "regiones"):
            self.assertEqual(self.client.get(f"{BASE}/api/{recurso}/").status_code, 200)
            self.assertEqual(self.client.post(f"{BASE}/api/{recurso}/", {}, format="json").status_code, 401)
        self.assertEqual(self.client.delete(f"{BASE}/api/dentistas/{self.dentista.id}/").status_code, 401)

    def test_no_se_puede_listar_ni_modificar_pacientes_sin_sesion(self):
        url = f"{BASE}/api/pacientes/"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(f"{url}{self.paciente.id}/").status_code, 401)
        self.assertEqual(self.client.patch(f"{url}{self.paciente.id}/", {"nombre": "X"}, format="json").status_code, 401)
        self.assertEqual(self.client.delete(f"{url}{self.paciente.id}/").status_code, 401)
        self.paciente.refresh_from_db()
        self.assertEqual(self.paciente.nombre, "Juan")

    def test_se_puede_buscar_y_registrar_pacientes_sin_sesion(self):
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/buscar/", {"rut": "12.345.678-5"}).status_code, 200)
        creado = self.client.post(f"{BASE}/api/pacientes/", {"rut": "11.111.111-1", "nombre": "Ana", "apellido": "Ríos"}, format="json")
        self.assertEqual(creado.status_code, 201)

    def test_limita_las_busquedas_por_rut(self):
        estados = [self.client.get(f"{BASE}/api/pacientes/buscar/", {"rut": "12.345.678-5"}).status_code for _ in range(65)]
        self.assertEqual(estados[0], 200)
        self.assertEqual(estados[-1], 429)

    def test_las_reservas_solo_se_crean_sin_sesion(self):
        creada = self.client.post(f"{BASE}/reservas/", {"slot": self.slot.id, "paciente": self.paciente.id}, format="json")
        self.assertEqual(creada.status_code, 201)
        self.assertEqual(self.client.get(f"{BASE}/api/reservas/").status_code, 401)
        reserva = Reserva.objects.get()
        self.assertEqual(self.client.delete(f"{BASE}/api/reservas/{reserva.id}/").status_code, 401)

    def test_generar_horarios_requiere_sesion(self):
        respuesta = self.client.post(f"{BASE}/dentistas/{self.dentista.id}/generar_slots/", {"fecha": MANANA.isoformat()}, format="json")
        self.assertEqual(respuesta.status_code, 401)

    def test_la_disponibilidad_es_publica_y_no_expone_pacientes(self):
        Reserva.objects.create(slot=self.slot, paciente=self.paciente)
        otro = Paciente.objects.create(rut="11.111.111-1", nombre="Ana", apellido="Ríos")
        Reserva.objects.create(slot=self.slot, paciente=otro, sobrecupo=True)
        respuesta = self.client.get(f"{BASE}/slots_por_fecha/", {"fecha": MANANA.isoformat(), "dentista_id": self.dentista.id})
        self.assertEqual(respuesta.status_code, 200)
        slot = respuesta.json()[0]
        self.assertEqual(slot["reservas_count"], 2)
        self.assertEqual(slot["sobrecupos_count"], 1)
        self.assertNotIn("Soto", respuesta.content.decode())
        self.assertNotIn("12.345.678-5", respuesta.content.decode())

    def test_un_token_de_usuario_sin_permiso_de_personal_no_sirve(self):
        usuario = get_user_model().objects.create_user("cliente", password=CLAVE)
        token = Token.objects.create(user=usuario)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/").status_code, 403)
