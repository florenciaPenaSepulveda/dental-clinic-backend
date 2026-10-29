import datetime
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from backendClinica.config import resolve_allowed_hosts

from .models import Dentista, Paciente, Reserva, Servicio, SlotAgenda
from .utils import horario_pasado, ocultar_correo, ocultar_telefono, rut_con_dv

BASE = "/agenda"
HOY = timezone.localdate()
MANANA = HOY + datetime.timedelta(days=1)
CLAVE = "clave-segura-123"
HASHER_RAPIDO = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@override_settings(PASSWORD_HASHERS=HASHER_RAPIDO)
class Base(APITestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.recepcion = User.objects.create_user("recepcion", password=CLAVE, is_staff=True)
        self.dentista = Dentista.objects.create(nombre="Ana", apellido="Pérez", especialidad="Ortodoncia", max_overbook_day=1)
        self.dentista.usuario = User.objects.create_user("dr.perez", password=CLAVE)
        self.dentista.save()
        self.paciente = Paciente.objects.create(
            rut="12.345.678-5", nombre="Juan", apellido="Soto", telefono="+56912345678", email="juan@correo.cl"
        )
        self.slot = SlotAgenda.objects.create(dentista=self.dentista, fecha=MANANA, hora=datetime.time(10, 0))


class ReservaCreate(Base):
    def reservar(self, **extra):
        return self.client.post(f"{BASE}/reservas/", {"slot": self.slot.id, "paciente": self.paciente.id, **extra}, format="json")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_el_correo_indica_fecha_en_espanol_hora_dentista_y_servicio_elegido(self):
        servicio = Servicio.objects.create(nombre="Limpieza", duracion_min=30, precio=35000)
        self.reservar(servicio=servicio.id)
        cuerpo = mail.outbox[0].body
        self.assertRegex(cuerpo, rf"Fecha: \w+ \d+ de \w+ de {MANANA.year}")
        self.assertIn("Hora: 10:00", cuerpo)
        self.assertIn("Dentista: Ana Pérez (Ortodoncia)", cuerpo)
        self.assertIn("Servicio: Limpieza", cuerpo)
        self.assertNotIn("None", cuerpo)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_el_correo_indica_cuando_el_servicio_queda_por_definir_y_el_sobrecupo(self):
        self.slot.max_overbook = 1
        self.slot.save()
        otro = Paciente.objects.create(rut="11.111.111-1", nombre="Marta", apellido="Ríos")
        Reserva.objects.create(slot=self.slot, paciente=otro)
        self.reservar()
        self.assertIn("Servicio: Por definir en la consulta", mail.outbox[0].body)
        self.assertIn("sobrecupo", mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_repetir_la_reserva_no_reenvia_el_correo(self):
        self.reservar()
        self.reservar()
        self.assertEqual((Reserva.objects.count(), len(mail.outbox)), (1, 1))

    def test_detecta_horarios_que_ya_pasaron(self):
        ahora = timezone.localtime()
        self.assertTrue(horario_pasado(HOY - datetime.timedelta(days=1), datetime.time(23, 59)))
        self.assertFalse(horario_pasado(MANANA, datetime.time(0, 0)))
        self.assertTrue(horario_pasado(HOY, (ahora - datetime.timedelta(minutes=1)).time()) or ahora.hour == 0 and ahora.minute == 0)

    @mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"reservas": "20/min"})
    def test_limita_las_reservas_publicas(self):
        estados = [self.reservar().status_code for _ in range(25)]
        self.assertEqual((estados[0], estados[-1]), (201, 429))

    @mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"registro": "10/min"})
    def test_limita_los_registros_publicos_de_pacientes(self):
        estados = []
        for numero in range(12):
            rut = f"{20000000 + numero}-0"
            estados.append(self.client.post(f"{BASE}/api/pacientes/", {"rut": rut, "nombre": "A", "apellido": "B"}, format="json").status_code)
        self.assertEqual(estados[-1], 429)
        self.assertIn(400, estados)


class Pacientes(Base):
    def test_valida_el_formato_del_telefono(self):
        for telefono in ("abc", "123", "+56 9 1234 5678 99999999999"):
            respuesta = self.client.post(f"{BASE}/api/pacientes/", {"rut": "11.111.111-1", "nombre": "A", "apellido": "B", "telefono": telefono}, format="json")
            self.assertEqual(respuesta.status_code, 400, telefono)
            self.assertIn("telefono", respuesta.json())
        for telefono in ("", "+56 9 1234 5678", "(2) 2345-6789", "912345678"):
            Paciente.objects.filter(rut="11.111.111-1").delete()
            respuesta = self.client.post(f"{BASE}/api/pacientes/", {"rut": "11.111.111-1", "nombre": "A", "apellido": "B", "telefono": telefono}, format="json")
            self.assertEqual(respuesta.status_code, 201, telefono)

    def buscar(self):
        return self.client.get(f"{BASE}/api/pacientes/buscar/", {"rut": "12.345.678-5"}).json()

    def test_el_publico_solo_ve_el_contacto_parcialmente(self):
        datos = self.buscar()
        self.assertEqual(datos["telefono"], "********5678")
        self.assertEqual(datos["email"], "j***@correo.cl")
        self.assertEqual(set(datos), {"id", "rut", "nombre", "apellido", "telefono", "email"})
        self.assertNotIn("tiene_cuenta", datos)

    def test_el_personal_ve_el_contacto_completo(self):
        for usuario in (self.recepcion, self.dentista.usuario):
            self.client.force_authenticate(usuario)
            datos = self.buscar()
            self.assertEqual((datos["telefono"], datos["email"]), ("+56912345678", "juan@correo.cl"))

    def test_un_paciente_con_sesion_tampoco_ve_el_contacto_de_otros(self):
        otro = Paciente.objects.create(rut="11.111.111-1", nombre="Marta", apellido="Ríos")
        otro.usuario = get_user_model().objects.create_user("11.111.111-1", password=CLAVE)
        otro.save()
        self.client.force_authenticate(otro.usuario)
        self.assertEqual(self.buscar()["telefono"], "********5678")


class Utilidades(SimpleTestCase):
    def test_oculta_correos_y_telefonos(self):
        self.assertEqual(ocultar_correo("ana@gmail.com"), "a***@gmail.com")
        self.assertEqual(ocultar_correo("a@x.cl"), "a***@x.cl")
        self.assertEqual(ocultar_correo(""), "")
        self.assertEqual(ocultar_telefono("+56912345678"), "********5678")
        self.assertEqual(ocultar_telefono("1234"), "****")
        self.assertEqual(ocultar_telefono(""), "")

    def test_exige_hosts_permitidos_en_produccion(self):
        self.assertEqual(resolve_allowed_hosts(False, {"ALLOWED_HOSTS": "a.cl, b.cl"}), ["a.cl", "b.cl"])
        self.assertEqual(resolve_allowed_hosts(True, {}), ["*"])
        with self.assertRaises(ImproperlyConfigured):
            resolve_allowed_hosts(False, {})

    def test_cors_no_esta_abierto_a_cualquier_origen(self):
        self.assertFalse(getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False))
        self.assertNotIn("*", settings.CORS_ALLOWED_ORIGINS)

    def test_usa_la_zona_horaria_y_el_idioma_de_chile(self):
        self.assertEqual((settings.TIME_ZONE, settings.LANGUAGE_CODE), ("America/Santiago", "es-cl"))


class SesionesConExpiracion(Base):
    def login(self):
        return self.client.post(f"{BASE}/auth/login/", {"username": "dr.perez", "password": CLAVE}, format="json").json()

    def test_un_token_vencido_deja_de_funcionar(self):
        token = Token.objects.create(user=self.recepcion)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - datetime.timedelta(hours=settings.TOKEN_TTL_HORAS + 1))
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        respuesta = self.client.get(f"{BASE}/api/pacientes/")
        self.assertEqual(respuesta.status_code, 401)
        self.assertIn("expiró", respuesta.json()["detail"])
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())

    def test_un_token_vigente_funciona(self):
        sesion = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {sesion['token']}")
        self.assertEqual(self.client.get(f"{BASE}/auth/me/").status_code, 200)

    def test_al_volver_a_ingresar_con_un_token_vencido_se_entrega_uno_nuevo(self):
        primero = self.login()["token"]
        Token.objects.filter(key=primero).update(created=timezone.now() - datetime.timedelta(hours=settings.TOKEN_TTL_HORAS + 1))
        segundo = self.login()["token"]
        self.assertNotEqual(primero, segundo)
        self.assertEqual(Token.objects.filter(user=self.dentista.usuario).count(), 1)

    def test_reingresar_con_un_token_vigente_lo_reutiliza(self):
        self.assertEqual(self.login()["token"], self.login()["token"])


class GenerarHorarios(Base):
    def generados(self):
        return SlotAgenda.objects.filter(dentista=self.dentista, fecha=MANANA).exclude(pk=self.slot.pk)

    def generar(self, **datos):
        self.client.force_authenticate(self.recepcion)
        return self.client.post(f"{BASE}/dentistas/{self.dentista.id}/generar_slots/", {"fecha": MANANA.isoformat(), **datos}, format="json")

    def test_limita_la_cantidad_de_dias(self):
        self.assertEqual(self.generar(dias=500).status_code, 400)
        self.assertEqual(self.generar(dias=0).status_code, 400)
        self.assertEqual(self.generar(dias=62).status_code, 201)

    def test_rechaza_horas_mal_formadas_o_fuera_del_horario_de_atencion(self):
        self.assertEqual(self.generar(desde="8am").status_code, 400)
        fuera = self.generar(desde="06:00", hasta="07:00")
        self.assertEqual(fuera.status_code, 400)
        self.assertIn("08:00", fuera.json()["detail"])
        self.assertEqual(self.generar(desde="08:15", hasta="09:00").status_code, 400)

    def test_los_horarios_se_generan_una_sola_vez(self):
        primera = self.generar(desde="09:00", hasta="10:00").json()
        self.assertEqual((primera["created"], primera["existing"]), (2, 0))
        segunda = self.generar(desde="09:00", hasta="10:00").json()
        self.assertEqual((segunda["created"], segunda["existing"]), (0, 2))
        self.assertEqual(self.generados().count(), 2)

    def test_la_ultima_cita_termina_a_la_hora_final(self):
        self.generar(desde="08:00", hasta="09:00")
        horas = list(self.generados().order_by("hora").values_list("hora", flat=True))
        self.assertEqual(horas, [datetime.time(8, 0), datetime.time(8, 30)])

    def test_cuenta_solo_los_nuevos_cuando_ya_existe_una_parte(self):
        self.generar(desde="09:00", hasta="10:00")
        resultado = self.generar(desde="09:00", hasta="11:00").json()
        self.assertEqual((resultado["created"], resultado["existing"]), (1, 3))

    def test_rechaza_una_hora_final_que_no_es_posterior(self):
        self.assertEqual(self.generar(desde="10:00", hasta="10:00").status_code, 400)
        self.assertEqual(self.generar(desde="10:00", hasta="09:00").status_code, 400)

    def test_si_un_bloque_falla_no_queda_nada_a_medias(self):
        respuesta = self.generar(desde="17:00", hasta="19:00")
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(self.generados().exists())

    def test_el_ultimo_inicio_permitido_es_17_30(self):
        self.assertEqual(self.generar(desde="17:00", hasta="18:00").json()["created"], 2)


class ConsultaDeHorarios(Base):
    def test_sin_fecha_solo_lista_desde_hoy(self):
        SlotAgenda.objects.create(dentista=self.dentista, fecha=HOY - datetime.timedelta(days=3), hora=datetime.time(9, 0))
        respuesta = self.client.get(f"{BASE}/slots_por_fecha/")
        self.assertEqual([slot["id"] for slot in respuesta.json()], [self.slot.id])

    def test_rechaza_un_identificador_de_dentista_invalido(self):
        self.assertEqual(self.client.get(f"{BASE}/slots_por_fecha/", {"dentista_id": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(f"{BASE}/slots_por_fecha/", {"dentista_id": self.dentista.id}).status_code, 200)


class ListasPaginadas(Base):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.recepcion)
        for numero in range(1, 31):
            cuerpo = 10000000 + numero * 1000
            Paciente.objects.create(rut=rut_con_dv(cuerpo), nombre=f"Paciente{numero:02d}", apellido="Prueba", email=f"p{numero}@correo.cl")

    def listar(self, **parametros):
        return self.client.get(f"{BASE}/api/pacientes/", parametros).json()

    def test_pagina_los_pacientes_de_a_25(self):
        primera = self.listar()
        self.assertEqual((primera["count"], len(primera["results"])), (31, 25))
        self.assertIsNotNone(primera["next"])
        self.assertIsNone(primera["previous"])
        segunda = self.listar(page=2)
        self.assertEqual(len(segunda["results"]), 6)
        self.assertIsNone(segunda["next"])

    def test_permite_pedir_otro_tamano_con_un_maximo(self):
        self.assertEqual(len(self.listar(page_size=5)["results"]), 5)
        self.assertEqual(len(self.listar(page_size=1000)["results"]), 31)

    def test_una_pagina_inexistente_responde_404(self):
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/", {"page": 9}).status_code, 404)

    def test_busca_por_nombre_apellido_correo_y_rut(self):
        self.assertEqual(self.listar(q="paciente07")["count"], 1)
        self.assertEqual(self.listar(q="prueba")["count"], 30)
        self.assertEqual(self.listar(q="p12@correo")["count"], 1)
        self.assertEqual(self.listar(q="juan soto")["count"], 1)
        self.assertEqual(self.listar(q="soto juan")["count"], 1)
        self.assertEqual(self.listar(q="nadie")["count"], 0)

    def test_la_busqueda_por_rut_ignora_puntos_y_guion(self):
        esperado = rut_con_dv(10000000 + 5 * 1000)
        for texto in (esperado, esperado.replace(".", ""), esperado.replace(".", "").replace("-", ""), esperado[:6]):
            encontrados = self.listar(q=texto)["results"]
            self.assertIn(esperado, [p["rut"] for p in encontrados], texto)

    def test_la_busqueda_respeta_los_permisos_del_dentista(self):
        self.client.force_authenticate(self.dentista.usuario)
        self.assertEqual(self.listar()["count"], 0)
        Reserva.objects.create(slot=self.slot, paciente=self.paciente)
        self.assertEqual(self.listar(q="soto")["count"], 1)
        self.assertEqual(self.listar(q="paciente07")["count"], 0)

    def test_las_reservas_tambien_vienen_paginadas(self):
        for paciente in Paciente.objects.exclude(pk=self.paciente.pk)[:27]:
            Reserva.objects.create(slot=self.slot, paciente=paciente)
        respuesta = self.client.get(f"{BASE}/api/reservas/").json()
        self.assertEqual((respuesta["count"], len(respuesta["results"])), (27, 25))
