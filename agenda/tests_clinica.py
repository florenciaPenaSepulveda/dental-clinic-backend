import datetime
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import ArchivoReserva, Atencion, Dentista, Paciente, Reserva, Servicio, SlotAgenda

BASE = "/agenda"
HOY = timezone.localdate()
MANANA = HOY + datetime.timedelta(days=1)
CLAVE = "clave-segura-123"
MEDIA = tempfile.mkdtemp()
PDF = b"%PDF-1.4\n%contenido de prueba"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def pdf(nombre="examen.pdf", contenido=PDF):
    return SimpleUploadedFile(nombre, contenido, content_type="application/pdf")


@override_settings(MEDIA_ROOT=MEDIA, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ClinicaBase(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.recepcion = User.objects.create_user("recepcion", password=CLAVE, is_staff=True)
        self.dentista = Dentista.objects.create(nombre="Ana", apellido="Pérez", especialidad="Ortodoncia", max_overbook_day=1)
        self.otro_dentista = Dentista.objects.create(nombre="Luis", apellido="Rojas", especialidad="Endodoncia")
        self.dentista.usuario = User.objects.create_user("dr.perez", password=CLAVE)
        self.dentista.save()
        self.otro_dentista.usuario = User.objects.create_user("dr.rojas", password=CLAVE)
        self.otro_dentista.save()
        self.paciente = Paciente.objects.create(rut="12.345.678-5", nombre="Juan", apellido="Soto", email="juan@test.cl")
        self.paciente.usuario = User.objects.create_user(self.paciente.rut, password=CLAVE)
        self.paciente.save()
        self.otro_paciente = Paciente.objects.create(rut="11.111.111-1", nombre="Marta", apellido="Ríos")
        self.otro_paciente.usuario = User.objects.create_user(self.otro_paciente.rut, password=CLAVE)
        self.otro_paciente.save()
        self.servicio = Servicio.objects.create(nombre="Limpieza", duracion_min=30, precio=35000)
        self.slot = SlotAgenda.objects.create(dentista=self.dentista, fecha=MANANA, hora=datetime.time(10, 0), capacidad=1, max_overbook=1)
        self.slot_libre = SlotAgenda.objects.create(dentista=self.dentista, fecha=MANANA, hora=datetime.time(11, 0))
        self.slot_ajeno = SlotAgenda.objects.create(dentista=self.otro_dentista, fecha=MANANA, hora=datetime.time(10, 0))
        self.reserva = Reserva.objects.create(slot=self.slot, paciente=self.paciente, servicio=self.servicio)
        self.reserva_ajena = Reserva.objects.create(slot=self.slot_ajeno, paciente=self.otro_paciente)

    def como(self, usuario):
        self.client.force_authenticate(usuario)

    @property
    def dr(self):
        return self.dentista.usuario

    @property
    def dr_ajeno(self):
        return self.otro_dentista.usuario


class RolesTests(ClinicaBase):
    def login(self, usuario, clave=CLAVE):
        return self.client.post(f"{BASE}/auth/login/", {"username": usuario, "password": clave}, format="json")

    def test_el_login_informa_el_rol_y_el_perfil(self):
        medico = self.login("dr.perez").json()
        self.assertEqual((medico["rol"], medico["dentista_id"], medico["nombre"]), ("dentista", self.dentista.id, "Ana Pérez"))
        paciente = self.login("12345678-5").json()
        self.assertEqual((paciente["rol"], paciente["paciente_id"]), ("paciente", self.paciente.id))
        self.assertEqual(self.login("recepcion").json()["rol"], "recepcion")

    def test_un_usuario_sin_rol_no_entra(self):
        get_user_model().objects.create_user("suelto", password=CLAVE)
        self.assertEqual(self.login("suelto").status_code, 400)

    def test_el_dentista_solo_ve_a_sus_pacientes(self):
        self.como(self.dr)
        lista = self.client.get(f"{BASE}/api/pacientes/").json()
        self.assertEqual([p["rut"] for p in lista], ["12.345.678-5"])
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/{self.paciente.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/{self.otro_paciente.id}/").status_code, 404)

    def test_recepcion_ve_a_todos_y_el_dentista_no_puede_modificar_pacientes(self):
        self.como(self.recepcion)
        self.assertEqual(len(self.client.get(f"{BASE}/api/pacientes/").json()), 2)
        self.como(self.dr)
        self.assertEqual(self.client.patch(f"{BASE}/api/pacientes/{self.paciente.id}/", {"nombre": "X"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"{BASE}/api/pacientes/{self.paciente.id}/").status_code, 403)

    def test_un_paciente_no_accede_a_los_endpoints_del_personal(self):
        self.como(self.paciente.usuario)
        for ruta in ("/api/pacientes/", "/api/reservas/", f"/api/pacientes/{self.paciente.id}/historial/", "/semana/?desde=2026-01-05"):
            self.assertEqual(self.client.get(f"{BASE}{ruta}").status_code, 403, ruta)

    def test_el_dentista_solo_ve_sus_reservas(self):
        self.como(self.dr)
        lista = self.client.get(f"{BASE}/api/reservas/").json()
        self.assertEqual([r["id"] for r in lista], [self.reserva.id])
        self.assertEqual(self.client.get(f"{BASE}/api/reservas/{self.reserva_ajena.id}/").status_code, 404)
        self.assertEqual(self.client.delete(f"{BASE}/api/reservas/{self.reserva_ajena.id}/").status_code, 404)

    def test_el_dentista_no_modifica_el_catalogo(self):
        self.como(self.dr)
        self.assertEqual(self.client.post(f"{BASE}/api/servicios/", {"nombre": "X", "duracion_min": 30, "precio": 1}, format="json").status_code, 403)

    def test_generar_horarios_solo_en_la_propia_agenda(self):
        self.como(self.dr)
        propio = self.client.post(f"{BASE}/dentistas/{self.dentista.id}/generar_slots/", {"fecha": (MANANA + datetime.timedelta(days=3)).isoformat()}, format="json")
        ajeno = self.client.post(f"{BASE}/dentistas/{self.otro_dentista.id}/generar_slots/", {"fecha": MANANA.isoformat()}, format="json")
        self.assertEqual((propio.status_code, ajeno.status_code), (201, 403))
        self.como(self.recepcion)
        self.assertEqual(self.client.post(f"{BASE}/dentistas/{self.otro_dentista.id}/generar_slots/", {"fecha": MANANA.isoformat()}, format="json").status_code, 201)


class SemanaTests(ClinicaBase):
    def pedir(self, **parametros):
        return self.client.get(f"{BASE}/semana/", {"desde": MANANA.isoformat(), **parametros})

    def test_recepcion_ve_la_semana_de_un_dentista_con_el_detalle_de_las_reservas(self):
        self.como(self.recepcion)
        respuesta = self.pedir(dentista=self.dentista.id)
        self.assertEqual(respuesta.status_code, 200)
        horas = [slot["hora"] for slot in respuesta.json()]
        self.assertEqual(horas, ["10:00:00", "11:00:00"])
        reservas = respuesta.json()[0]["reservas"]
        self.assertEqual(reservas[0]["paciente"]["nombre"], "Juan")
        self.assertEqual(reservas[0]["servicio"]["nombre"], "Limpieza")
        self.assertEqual(respuesta.json()[1]["reservas"], [])

    def test_recepcion_debe_elegir_un_dentista_y_una_fecha(self):
        self.como(self.recepcion)
        self.assertEqual(self.pedir().status_code, 400)
        self.assertEqual(self.client.get(f"{BASE}/semana/", {"dentista": self.dentista.id}).status_code, 400)

    def test_el_dentista_ve_solo_su_agenda(self):
        self.como(self.dr)
        self.assertEqual(len(self.pedir().json()), 2)
        self.assertEqual(self.pedir(dentista=self.dentista.id).status_code, 200)
        self.assertEqual(self.pedir(dentista=self.otro_dentista.id).status_code, 403)

    def test_limita_la_consulta_a_siete_dias(self):
        SlotAgenda.objects.create(dentista=self.dentista, fecha=MANANA + datetime.timedelta(days=7), hora=datetime.time(9, 0))
        self.como(self.recepcion)
        self.assertEqual(len(self.pedir(dentista=self.dentista.id).json()), 2)

    def test_requiere_sesion(self):
        self.assertEqual(self.pedir(dentista=self.dentista.id).status_code, 401)


class ActualizarReservaTests(ClinicaBase):
    def url(self, reserva=None):
        return f"{BASE}/api/reservas/{(reserva or self.reserva).id}/"

    def test_recepcion_deja_observaciones_y_cambia_el_estado(self):
        self.como(self.recepcion)
        respuesta = self.client.patch(self.url(), {"observaciones": "Llega con acompañante", "estado": "no_asistio"}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["observaciones"], "Llega con acompañante")
        self.assertEqual(respuesta.json()["estado"], "no_asistio")
        self.assertIn("archivos", respuesta.json())

    def test_cambia_el_servicio(self):
        otro = Servicio.objects.create(nombre="Control", duracion_min=30, precio=20000)
        self.como(self.dr)
        self.assertEqual(self.client.patch(self.url(), {"servicio": otro.id}, format="json").json()["servicio"]["nombre"], "Control")

    def test_reprograma_a_un_horario_libre(self):
        self.como(self.recepcion)
        respuesta = self.client.patch(self.url(), {"slot": self.slot_libre.id}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.reserva.refresh_from_db()
        self.assertEqual((self.reserva.slot_id, self.reserva.sobrecupo), (self.slot_libre.id, False))

    def test_reprograma_como_sobrecupo_cuando_el_horario_ya_tiene_un_paciente(self):
        Reserva.objects.create(slot=self.slot_libre, paciente=self.otro_paciente)
        self.slot_libre.max_overbook = 1
        self.slot_libre.save()
        self.como(self.recepcion)
        self.assertEqual(self.client.patch(self.url(), {"slot": self.slot_libre.id}, format="json").status_code, 200)
        self.reserva.refresh_from_db()
        self.assertTrue(self.reserva.sobrecupo)

    def test_rechaza_reprogramar_a_un_horario_lleno(self):
        Reserva.objects.create(slot=self.slot_libre, paciente=self.otro_paciente)
        self.como(self.recepcion)
        respuesta = self.client.patch(self.url(), {"slot": self.slot_libre.id}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("lleno", str(respuesta.json()))

    def test_rechaza_reprogramar_donde_el_paciente_ya_tiene_reserva(self):
        Reserva.objects.create(slot=self.slot_libre, paciente=self.paciente)
        self.como(self.recepcion)
        self.assertEqual(self.client.patch(self.url(), {"slot": self.slot_libre.id}, format="json").status_code, 400)

    def test_el_dentista_no_mueve_reservas_a_la_agenda_de_otro(self):
        libre_ajeno = SlotAgenda.objects.create(dentista=self.otro_dentista, fecha=MANANA, hora=datetime.time(12, 0))
        self.como(self.dr)
        self.assertEqual(self.client.patch(self.url(), {"slot": libre_ajeno.id}, format="json").status_code, 403)
        self.assertEqual(self.client.patch(self.url(self.reserva_ajena), {"observaciones": "x"}, format="json").status_code, 404)

    def test_cancelar_elimina_la_reserva(self):
        self.como(self.dr)
        self.assertEqual(self.client.delete(self.url()).status_code, 204)
        self.assertFalse(Reserva.objects.filter(id=self.reserva.id).exists())


class AtencionTests(ClinicaBase):
    def url(self, reserva=None):
        return f"{BASE}/api/reservas/{(reserva or self.reserva).id}/atencion/"

    def test_el_dentista_registra_la_atencion_y_la_reserva_queda_atendida(self):
        self.como(self.dr)
        respuesta = self.client.put(self.url(), {"diagnostico": "Caries", "procedimiento": "Restauración", "indicaciones": "Evitar duros"}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["estado"], "atendida")
        self.assertEqual(respuesta.json()["atencion"]["diagnostico"], "Caries")

    def test_actualiza_la_atencion_existente_sin_duplicarla(self):
        self.como(self.dr)
        self.client.put(self.url(), {"diagnostico": "Caries"}, format="json")
        self.client.put(self.url(), {"indicaciones": "Reposo"}, format="json")
        self.assertEqual(Atencion.objects.count(), 1)
        atencion = Atencion.objects.get()
        self.assertEqual((atencion.diagnostico, atencion.indicaciones), ("Caries", "Reposo"))

    def test_recepcion_puede_leerla_pero_no_escribirla(self):
        Atencion.objects.create(reserva=self.reserva, diagnostico="Caries")
        self.como(self.recepcion)
        self.assertEqual(self.client.put(self.url(), {"diagnostico": "Otro"}, format="json").status_code, 403)
        self.assertEqual(self.client.get(f"{BASE}/api/reservas/{self.reserva.id}/").json()["atencion"]["diagnostico"], "Caries")

    def test_un_dentista_no_registra_atenciones_de_otro(self):
        self.como(self.dr)
        self.assertEqual(self.client.put(self.url(self.reserva_ajena), {"diagnostico": "x"}, format="json").status_code, 404)

    def test_limita_el_largo_de_los_textos(self):
        self.como(self.dr)
        self.assertEqual(self.client.put(self.url(), {"diagnostico": "a" * 5001}, format="json").status_code, 400)


class ArchivosTests(ClinicaBase):
    def reservar(self, archivos, paciente=None, slot=None):
        datos = {"slot": (slot or self.slot_libre).id, "paciente": (paciente or self.paciente).id, "archivos": archivos}
        return self.client.post(f"{BASE}/reservas/", datos, format="multipart")

    def test_el_publico_adjunta_examenes_al_reservar(self):
        respuesta = self.reservar([pdf(), SimpleUploadedFile("radiografia.png", PNG, content_type="image/png")])
        self.assertEqual(respuesta.status_code, 201)
        reserva = Reserva.objects.get(id=respuesta.json()["id"])
        self.assertEqual(sorted(reserva.archivos.values_list("nombre", flat=True)), ["examen.pdf", "radiografia.png"])

    def test_guarda_el_motivo_de_la_consulta(self):
        datos = {"slot": self.slot_libre.id, "paciente": self.paciente.id, "motivo": "Dolor en una muela"}
        respuesta = self.client.post(f"{BASE}/reservas/", datos, format="json")
        self.assertEqual(Reserva.objects.get(id=respuesta.json()["id"]).motivo, "Dolor en una muela")

    def test_rechaza_tipos_de_archivo_no_permitidos(self):
        respuesta = self.reservar([SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")])
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(Reserva.objects.filter(slot=self.slot_libre).exists())

    def test_rechaza_archivos_cuyo_contenido_no_coincide_con_la_extension(self):
        self.assertEqual(self.reservar([pdf("falso.pdf", b"no es un pdf")]).status_code, 400)

    def test_rechaza_archivos_muy_grandes_y_demasiados_archivos(self):
        with mock.patch("agenda.archivos.MAX_BYTES", 10):
            self.assertEqual(self.reservar([pdf()]).status_code, 400)
        self.assertEqual(self.reservar([pdf(f"{i}.pdf") for i in range(6)]).status_code, 400)

    def test_no_adjunta_archivos_a_una_reserva_ya_existente(self):
        respuesta = self.reservar([pdf()], slot=self.slot)
        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(ArchivoReserva.objects.count(), 0)

    def descargar(self, usuario, archivo):
        self.como(usuario) if usuario else self.client.force_authenticate(None)
        return self.client.get(f"{BASE}/archivos/{archivo.id}/")

    def test_descarga_solo_quien_puede_ver_la_reserva(self):
        self.client.force_authenticate(None)
        self.reservar([pdf()], slot=self.slot_libre)
        archivo = ArchivoReserva.objects.get()
        propio = self.descargar(self.paciente.usuario, archivo)
        self.assertEqual(propio.status_code, 200)
        self.assertEqual(b"".join(propio.streaming_content), PDF)
        self.assertIn("attachment", propio["Content-Disposition"])
        self.assertEqual(propio["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.descargar(self.recepcion, archivo).status_code, 200)
        self.assertEqual(self.descargar(self.dr, archivo).status_code, 200)
        self.assertEqual(self.descargar(self.otro_paciente.usuario, archivo).status_code, 404)
        self.assertEqual(self.descargar(self.dr_ajeno, archivo).status_code, 404)
        self.assertEqual(self.descargar(None, archivo).status_code, 401)

    def test_personal_elimina_archivos_pero_el_paciente_no(self):
        self.reservar([pdf()])
        archivo = ArchivoReserva.objects.get()
        url = f"{BASE}/archivos/{archivo.id}/"
        self.como(self.paciente.usuario)
        self.assertEqual(self.client.delete(url).status_code, 403)
        self.como(self.dr)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(ArchivoReserva.objects.count(), 0)

    def test_al_eliminar_la_reserva_o_el_archivo_se_borra_el_archivo_del_disco(self):
        self.reservar([pdf("uno.pdf"), pdf("dos.pdf")])
        uno, dos = ArchivoReserva.objects.order_by("id")
        ruta_uno, ruta_dos = uno.archivo.path, dos.archivo.path
        self.assertTrue(os.path.exists(ruta_uno) and os.path.exists(ruta_dos))
        self.como(self.dr)
        self.client.delete(f"{BASE}/archivos/{uno.id}/")
        self.assertFalse(os.path.exists(ruta_uno))
        Reserva.objects.filter(id=dos.reserva_id).delete()
        self.assertFalse(os.path.exists(ruta_dos))

    def test_agrega_archivos_a_una_reserva_existente(self):
        url = f"{BASE}/api/reservas/{self.reserva.id}/archivos/"
        self.como(self.recepcion)
        self.assertEqual(self.client.post(url, {"archivos": [pdf()]}, format="multipart").status_code, 201)
        self.como(self.paciente.usuario)
        self.assertEqual(self.client.post(url, {"archivos": [pdf("otro.pdf")]}, format="multipart").status_code, 201)
        self.assertEqual(self.client.post(url, {}, format="multipart").status_code, 400)
        self.assertEqual(self.client.post(url, {"archivos": [pdf(f"{i}.pdf") for i in range(4)]}, format="multipart").status_code, 400)
        self.como(self.otro_paciente.usuario)
        self.assertEqual(self.client.post(url, {"archivos": [pdf()]}, format="multipart").status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(url, {"archivos": [pdf()]}, format="multipart").status_code, 401)


class HistorialTests(ClinicaBase):
    def setUp(self):
        super().setUp()
        ayer = HOY - datetime.timedelta(days=30)
        pasado = SlotAgenda.objects.create(dentista=self.dentista, fecha=ayer, hora=datetime.time(9, 0))
        pasado_ajeno = SlotAgenda.objects.create(dentista=self.otro_dentista, fecha=ayer - datetime.timedelta(days=5), hora=datetime.time(9, 0))
        self.atendida = Reserva.objects.create(slot=pasado, paciente=self.paciente, estado="atendida", observaciones="Nota interna")
        Atencion.objects.create(reserva=self.atendida, diagnostico="Caries", procedimiento="Resina", indicaciones="Reposo")
        self.atendida_ajena = Reserva.objects.create(slot=pasado_ajeno, paciente=self.paciente, estado="atendida")
        Atencion.objects.create(reserva=self.atendida_ajena, diagnostico="Pulpitis")

    def test_el_paciente_ve_su_historial_con_el_profesional_que_lo_atendio(self):
        self.como(self.paciente.usuario)
        datos = self.client.get(f"{BASE}/mi/historial/").json()
        self.assertEqual(datos["paciente"]["rut"], "12.345.678-5")
        self.assertEqual([r["id"] for r in datos["proximas"]], [self.reserva.id])
        self.assertEqual(len(datos["historial"]), 2)
        primero = datos["historial"][0]
        self.assertEqual(primero["dentista"]["nombre"], "Ana Pérez")
        self.assertEqual(primero["atencion"]["diagnostico"], "Caries")
        self.assertNotIn("observaciones", primero)
        self.assertEqual({r["dentista"]["nombre"] for r in datos["historial"]}, {"Ana Pérez", "Luis Rojas"})

    def test_el_paciente_no_ve_el_historial_de_otros(self):
        self.como(self.otro_paciente.usuario)
        datos = self.client.get(f"{BASE}/mi/historial/").json()
        self.assertEqual(datos["paciente"]["rut"], "11.111.111-1")
        self.assertEqual(len(datos["proximas"]) + len(datos["historial"]), 1)
        self.assertNotIn("Caries", str(datos))

    def test_solo_los_pacientes_usan_el_historial_personal(self):
        self.como(self.recepcion)
        self.assertEqual(self.client.get(f"{BASE}/mi/historial/").status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f"{BASE}/mi/historial/").status_code, 401)

    def test_el_dentista_ve_solo_sus_atenciones_del_paciente(self):
        self.como(self.dr)
        historial = self.client.get(f"{BASE}/api/pacientes/{self.paciente.id}/historial/").json()
        self.assertEqual({r["id"] for r in historial}, {self.atendida.id, self.reserva.id})
        self.assertNotIn("Pulpitis", str(historial))
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/{self.otro_paciente.id}/historial/").status_code, 404)

    def test_recepcion_ve_todo_el_historial_con_las_observaciones(self):
        self.como(self.recepcion)
        historial = self.client.get(f"{BASE}/api/pacientes/{self.paciente.id}/historial/").json()
        self.assertEqual(len(historial), 3)
        self.assertIn("Nota interna", str(historial))
        self.assertIn("Pulpitis", str(historial))


class ActivarCuentaTests(ClinicaBase):
    def setUp(self):
        super().setUp()
        self.nuevo = Paciente.objects.create(rut="13.333.333-9", nombre="Rosa", apellido="Vega", email="rosa@test.cl")

    def activar(self, **extra):
        datos = {"rut": "13333333-9", "email": "ROSA@test.cl", "password": "Clave-muy-segura-9"}
        datos.update(extra)
        return self.client.post(f"{BASE}/auth/activar-cuenta/", datos, format="json")

    def test_activa_la_cuenta_y_deja_la_sesion_iniciada(self):
        respuesta = self.activar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["rol"], "paciente")
        self.nuevo.refresh_from_db()
        self.assertIsNotNone(self.nuevo.usuario)
        ingreso = self.client.post(f"{BASE}/auth/login/", {"username": "13.333.333-9", "password": "Clave-muy-segura-9"}, format="json")
        self.assertEqual(ingreso.status_code, 200)

    def test_exige_que_el_correo_coincida_con_el_registrado(self):
        self.assertEqual(self.activar(email="otro@test.cl").status_code, 400)
        self.assertEqual(self.activar(rut="99.999.999-9").status_code, 400)

    def test_no_permite_activar_pacientes_sin_correo_ni_cuentas_ya_activadas(self):
        self.assertEqual(self.activar(rut="11.111.111-1", email="").status_code, 400)
        self.assertEqual(self.activar(rut="12.345.678-5", email="juan@test.cl").status_code, 400)

    def test_rechaza_contraseñas_debiles(self):
        respuesta = self.activar(password="123")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("password", respuesta.json())
        self.nuevo.refresh_from_db()
        self.assertIsNone(self.nuevo.usuario)


class CuentasTests(ClinicaBase):
    def test_recepcion_crea_la_cuenta_de_un_dentista_y_este_puede_entrar(self):
        nuevo = Dentista.objects.create(nombre="Sofía", apellido="Núñez Álvarez")
        self.como(self.recepcion)
        respuesta = self.client.post(f"{BASE}/api/dentistas/{nuevo.id}/cuenta/")
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual((datos["username"], datos["creada"]), ("dr.nunezalvarez", True))
        nuevo.refresh_from_db()
        self.assertEqual(nuevo.usuario.username, datos["username"])
        self.client.force_authenticate(None)
        ingreso = self.client.post(f"{BASE}/auth/login/", {"username": datos["username"], "password": datos["password"]}, format="json")
        self.assertEqual((ingreso.status_code, ingreso.json()["rol"], ingreso.json()["dentista_id"]), (200, "dentista", nuevo.id))

    def test_evita_nombres_de_usuario_repetidos(self):
        repetido = Dentista.objects.create(nombre="Otra", apellido="Pérez")
        self.como(self.recepcion)
        self.assertEqual(self.client.post(f"{BASE}/api/dentistas/{repetido.id}/cuenta/").json()["username"], "dr.perez2")

    def test_recepcion_crea_la_cuenta_de_un_paciente_con_su_rut(self):
        nuevo = Paciente.objects.create(rut="13.333.333-9", nombre="Rosa", apellido="Vega")
        self.como(self.recepcion)
        datos = self.client.post(f"{BASE}/api/pacientes/{nuevo.id}/cuenta/").json()
        self.assertEqual(datos["username"], "13.333.333-9")
        self.client.force_authenticate(None)
        ingreso = self.client.post(f"{BASE}/auth/login/", {"username": "13333333-9", "password": datos["password"]}, format="json")
        self.assertEqual(ingreso.json()["rol"], "paciente")

    def test_reiniciar_la_cuenta_cambia_la_clave_y_cierra_las_sesiones(self):
        self.client.post(f"{BASE}/auth/login/", {"username": "dr.perez", "password": CLAVE}, format="json")
        self.como(self.recepcion)
        datos = self.client.post(f"{BASE}/api/dentistas/{self.dentista.id}/cuenta/").json()
        self.assertFalse(datos["creada"])
        self.assertEqual(datos["username"], "dr.perez")
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f"{BASE}/auth/login/", {"username": "dr.perez", "password": CLAVE}, format="json").status_code, 400)
        self.assertEqual(self.client.post(f"{BASE}/auth/login/", {"username": "dr.perez", "password": datos["password"]}, format="json").status_code, 200)

    def test_solo_recepcion_gestiona_cuentas(self):
        for usuario in (self.dr, self.paciente.usuario):
            self.como(usuario)
            self.assertEqual(self.client.post(f"{BASE}/api/dentistas/{self.dentista.id}/cuenta/").status_code, 403)
            self.assertEqual(self.client.post(f"{BASE}/api/pacientes/{self.paciente.id}/cuenta/").status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(f"{BASE}/api/pacientes/{self.paciente.id}/cuenta/").status_code, 401)

    def test_las_fichas_indican_si_tienen_cuenta(self):
        sin_cuenta = Dentista.objects.create(nombre="Sin", apellido="Cuenta")
        self.como(self.recepcion)
        dentistas = {d["apellido"]: d["tiene_cuenta"] for d in self.client.get(f"{BASE}/api/dentistas/").json()}
        self.assertEqual((dentistas["Pérez"], dentistas["Cuenta"]), (True, False))
        self.assertTrue(self.client.get(f"{BASE}/api/pacientes/{self.paciente.id}/").json()["tiene_cuenta"])
        self.assertIsNotNone(sin_cuenta.id)


class ClaveTemporalTests(ClinicaBase):
    def crear_cuenta(self):
        nuevo = Dentista.objects.create(nombre="Sofía", apellido="Núñez")
        self.como(self.recepcion)
        datos = self.client.post(f"{BASE}/api/dentistas/{nuevo.id}/cuenta/").json()
        self.client.force_authenticate(None)
        return datos

    def ingresar(self, datos):
        sesion = self.client.post(f"{BASE}/auth/login/", {"username": datos["username"], "password": datos["password"]}, format="json").json()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {sesion['token']}")
        return sesion

    def test_el_primer_ingreso_exige_cambiar_la_clave(self):
        sesion = self.ingresar(self.crear_cuenta())
        self.assertTrue(sesion["debe_cambiar_clave"])
        self.assertEqual(sesion["rol"], "dentista")

    def test_mientras_no_la_cambie_solo_puede_cambiarla_o_salir(self):
        self.ingresar(self.crear_cuenta())
        for ruta in ("/api/pacientes/", "/api/reservas/", "/semana/?desde=2026-01-05"):
            self.assertEqual(self.client.get(f"{BASE}{ruta}").status_code, 403, ruta)
        self.assertEqual(self.client.post(f"{BASE}/api/servicios/", {}, format="json").status_code, 403)
        self.assertEqual(self.client.get(f"{BASE}/auth/me/").json()["debe_cambiar_clave"], True)
        self.assertEqual(self.client.get(f"{BASE}/api/dentistas/").status_code, 200)

    def test_al_cambiar_la_clave_recupera_el_acceso(self):
        datos = self.crear_cuenta()
        self.ingresar(datos)
        respuesta = self.client.post(f"{BASE}/auth/cambiar-clave/", {"actual": datos["password"], "nueva": "Mi-clave-personal-26"}, format="json")
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(respuesta.json()["debe_cambiar_clave"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {respuesta.json()['token']}")
        self.assertEqual(self.client.get(f"{BASE}/api/pacientes/").status_code, 200)

    def test_no_acepta_conservar_la_clave_temporal(self):
        datos = self.crear_cuenta()
        self.ingresar(datos)
        respuesta = self.client.post(f"{BASE}/auth/cambiar-clave/", {"actual": datos["password"], "nueva": datos["password"]}, format="json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("distinta", respuesta.json()["detail"])

    def test_restablecer_el_acceso_vuelve_a_exigir_el_cambio(self):
        self.client.force_authenticate(self.recepcion)
        datos = self.client.post(f"{BASE}/api/dentistas/{self.dentista.id}/cuenta/").json()
        self.client.force_authenticate(None)
        self.assertTrue(self.ingresar(datos)["debe_cambiar_clave"])

    def test_las_cuentas_normales_no_tienen_la_marca(self):
        sesion = self.client.post(f"{BASE}/auth/login/", {"username": "dr.perez", "password": CLAVE}, format="json").json()
        self.assertFalse(sesion["debe_cambiar_clave"])

    def test_activar_la_propia_cuenta_no_exige_cambio(self):
        nuevo = Paciente.objects.create(rut="13.333.333-9", nombre="Rosa", apellido="Vega", email="rosa@test.cl")
        respuesta = self.client.post(f"{BASE}/auth/activar-cuenta/", {"rut": nuevo.rut, "email": "rosa@test.cl", "password": "Clave-muy-segura-9"}, format="json")
        self.assertFalse(respuesta.json()["debe_cambiar_clave"])


class CambiarClaveTests(ClinicaBase):
    def cambiar(self, actual=CLAVE, nueva="Otra-clave-segura-7"):
        return self.client.post(f"{BASE}/auth/cambiar-clave/", {"actual": actual, "nueva": nueva}, format="json")

    def test_cambia_la_clave_y_entrega_un_token_nuevo(self):
        sesion = self.client.post(f"{BASE}/auth/login/", {"username": "dr.perez", "password": CLAVE}, format="json").json()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {sesion['token']}")
        respuesta = self.cambiar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotEqual(respuesta.json()["token"], sesion["token"])
        self.assertEqual(self.client.get(f"{BASE}/auth/me/").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {respuesta.json()['token']}")
        self.assertEqual(self.client.get(f"{BASE}/auth/me/").status_code, 200)
        self.client.credentials()
        self.assertEqual(self.client.post(f"{BASE}/auth/login/", {"username": "dr.perez", "password": "Otra-clave-segura-7"}, format="json").status_code, 200)

    def test_rechaza_la_clave_actual_incorrecta_y_las_claves_debiles(self):
        self.como(self.dr)
        self.assertEqual(self.cambiar(actual="mala").status_code, 400)
        debil = self.cambiar(nueva="123")
        self.assertEqual(debil.status_code, 400)
        self.assertIn("detail", debil.json())

    def test_requiere_sesion(self):
        self.assertEqual(self.cambiar().status_code, 401)


class EstadoDeLaAtencionTests(ClinicaBase):
    def test_registrar_la_atencion_corrige_un_no_asistio(self):
        self.reserva.estado = "no_asistio"
        self.reserva.save()
        self.como(self.dr)
        respuesta = self.client.put(f"{BASE}/api/reservas/{self.reserva.id}/atencion/", {"diagnostico": "Caries"}, format="json")
        self.assertEqual(respuesta.json()["estado"], "atendida")
