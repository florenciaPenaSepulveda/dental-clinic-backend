from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from .models import Paciente
from .utils import normalizar_rut

BASE = "/agenda/api/pacientes"


class NormalizarRutTests(SimpleTestCase):
    def test_acepta_distintos_formatos_y_devuelve_el_canonico(self):
        for valor in ("12.345.678-5", "12345678-5", "123456785", " 12.345.678 - 5 ", "12345.678-5"):
            self.assertEqual(normalizar_rut(valor), "12.345.678-5", valor)

    def test_acepta_digito_verificador_k_en_minuscula(self):
        self.assertEqual(normalizar_rut("1.000.005-k"), "1.000.005-K")

    def test_acepta_ruts_de_siete_digitos(self):
        self.assertEqual(normalizar_rut("1.000.005-K"), "1.000.005-K")

    def test_rechaza_digito_verificador_incorrecto(self):
        self.assertIsNone(normalizar_rut("12.345.678-9"))

    def test_rechaza_formatos_invalidos(self):
        for valor in (None, "", "   ", "abc", "12.345.678-", "12.34.5678-5", "12.345.678-55", "1234567", "K2345678-5",
                      "12.345.678-5; DROP", "12,345,678-5", "012345678-5"):
            self.assertIsNone(normalizar_rut(valor), valor)

    def test_rechaza_cuerpos_demasiado_chicos_o_grandes(self):
        for valor in ("0-0", "999.999-9", "00000000-0", "123.456.789-0"):
            self.assertIsNone(normalizar_rut(valor), valor)


class PacienteRutApiTests(APITestCase):
    def setUp(self):
        self.paciente = Paciente.objects.create(rut="12.345.678-5", nombre="Juan", apellido="Soto", email="j@test.cl")

    def test_crear_guarda_el_rut_normalizado(self):
        respuesta = self.client.post(BASE + "/", {"rut": "11111111-1", "nombre": "Ana", "apellido": "Ríos"}, format="json")
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json()["rut"], "11.111.111-1")

    def test_crear_rechaza_rut_invalido(self):
        respuesta = self.client.post(BASE + "/", {"rut": "11.111.111-2", "nombre": "Ana", "apellido": "Ríos"}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("rut", respuesta.json())

    def test_crear_rechaza_rut_repetido_aunque_cambie_el_formato(self):
        respuesta = self.client.post(BASE + "/", {"rut": "123456785", "nombre": "Otra", "apellido": "Persona"}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(Paciente.objects.count(), 1)

    def test_editar_el_propio_rut_no_cuenta_como_repetido(self):
        respuesta = self.client.patch(f"{BASE}/{self.paciente.id}/", {"rut": "12345678-5", "telefono": "999"}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["telefono"], "999")

    def test_buscar_devuelve_solo_al_paciente_del_rut(self):
        Paciente.objects.create(rut="11.111.111-1", nombre="Ana", apellido="Ríos")
        respuesta = self.client.get(BASE + "/buscar/", {"rut": "12345678-5"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["id"], self.paciente.id)
        self.assertEqual(respuesta.json()["nombre"], "Juan")

    def test_buscar_responde_404_si_el_rut_no_existe(self):
        respuesta = self.client.get(BASE + "/buscar/", {"rut": "11.111.111-1"})
        self.assertEqual(respuesta.status_code, 404)

    def test_buscar_responde_400_si_el_rut_es_invalido_o_falta(self):
        self.assertEqual(self.client.get(BASE + "/buscar/", {"rut": "12.345.678-9"}).status_code, 400)
        self.assertEqual(self.client.get(BASE + "/buscar/").status_code, 400)
