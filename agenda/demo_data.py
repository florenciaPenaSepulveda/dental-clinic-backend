import datetime
import os
import random

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Dentista, Paciente, Region, Reserva, Servicio, SlotAgenda
from .slots_generator import generate_slots_for_day
from .utils import rut_con_dv

REGIONES = [("Biobío", "08"), ("Metropolitana", "13"), ("Valparaíso", "05")]

DENTISTAS = [
    ("Camila", "Rojas", "Ortodoncia", "08", 2),
    ("Matías", "Fuentes", "Endodoncia", "08", 1),
    ("Valentina", "Araya", "Odontopediatría", "13", 2),
    ("Andrés", "Pizarro", "Implantología", "13", 1),
    ("Javiera", "Soto", "Odontología general", "05", 3),
]

SERVICIOS = [
    ("Consulta de evaluación", 30, 20000),
    ("Limpieza dental", 30, 35000),
    ("Extracción simple", 45, 45000),
    ("Tratamiento de conducto", 60, 120000),
    ("Blanqueamiento", 60, 150000),
    ("Control de ortodoncia", 30, 40000),
    ("Radiografía panorámica", 30, 25000),
]

NOMBRES = ["Sofía", "Mateo", "Isidora", "Benjamín", "Florencia", "Vicente", "Antonella", "Joaquín", "Josefa", "Tomás", "Catalina", "Martín"]
APELLIDOS = ["González", "Muñoz", "Rojas", "Díaz", "Pérez", "Soto", "Contreras", "Silva", "Martínez", "Sepúlveda", "Morales", "Fuentes", "Torres", "Araya"]

DIAS_DE_AGENDA = 14
BLOQUES = (("09:00", "13:00"), ("15:00", "17:30"))


def _normalizar(texto):
    tabla = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")
    return texto.translate(tabla).lower()


def _crear_catalogos(rng):
    regiones = {codigo: Region.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})[0] for nombre, codigo in REGIONES}
    dentistas = []
    for nombre, apellido, especialidad, codigo, sobrecupos in DENTISTAS:
        dentista, _ = Dentista.objects.get_or_create(
            nombre=nombre,
            apellido=apellido,
            defaults={
                "especialidad": especialidad,
                "region": regiones[codigo],
                "max_overbook_day": sobrecupos,
                "email": f"{_normalizar(nombre)}.{_normalizar(apellido)}@clinica.example.com",
                "telefono": f"+5692{rng.randint(1000000, 9999999)}",
            },
        )
        dentistas.append(dentista)
    servicios = [
        Servicio.objects.get_or_create(nombre=nombre, defaults={"duracion_min": minutos, "precio": precio})[0]
        for nombre, minutos, precio in SERVICIOS
    ]
    return dentistas, servicios


def _crear_pacientes(rng, cantidad=24):
    pacientes = []
    for indice in range(cantidad):
        nombre = NOMBRES[indice % len(NOMBRES)]
        apellido = f"{APELLIDOS[(indice * 3) % len(APELLIDOS)]} {APELLIDOS[(indice * 5 + 1) % len(APELLIDOS)]}"
        rut = rut_con_dv(14000000 + indice * 137)
        correo = f"{_normalizar(nombre)}.{_normalizar(apellido.split()[0])}{indice}@example.com" if indice % 3 else ""
        paciente, _ = Paciente.objects.get_or_create(
            rut=rut,
            defaults={
                "nombre": nombre,
                "apellido": apellido,
                "telefono": f"+5699{rng.randint(1000000, 9999999)}",
                "email": correo,
            },
        )
        pacientes.append(paciente)
    return pacientes


def _crear_agenda(dentistas, hoy):
    for dentista in dentistas:
        for desplazamiento in range(DIAS_DE_AGENDA):
            dia = hoy + datetime.timedelta(days=desplazamiento)
            if dia.weekday() >= 5:
                continue
            for desde, hasta in BLOQUES:
                generate_slots_for_day(dentista, dia, desde=desde, hasta=hasta)
        if dentista.max_overbook_day:
            SlotAgenda.objects.filter(dentista=dentista, fecha__gte=hoy).update(max_overbook=1)


def _crear_reservas(rng, pacientes, servicios, hoy):
    if Reserva.objects.exists():
        return 0
    slots = list(SlotAgenda.objects.filter(fecha__gte=hoy, fecha__lt=hoy + datetime.timedelta(days=7)).order_by("fecha", "hora", "dentista_id"))
    rng.shuffle(slots)
    creadas = 0
    disponibles = list(pacientes)
    for slot in slots[:30]:
        if len(disponibles) < 2:
            disponibles = list(pacientes)
        paciente = disponibles.pop(rng.randrange(len(disponibles)))
        Reserva.objects.create(slot=slot, paciente=paciente, servicio=rng.choice(servicios), sobrecupo=False)
        creadas += 1
    for slot in slots[:5]:
        sobrecupos_dia = Reserva.objects.filter(slot__dentista=slot.dentista, slot__fecha=slot.fecha, sobrecupo=True).count()
        if slot.max_overbook and sobrecupos_dia < slot.dentista.max_overbook_day:
            ocupados = set(slot.reservas.values_list("paciente_id", flat=True))
            candidatos = [paciente for paciente in pacientes if paciente.id not in ocupados]
            Reserva.objects.create(slot=slot, paciente=rng.choice(candidatos), servicio=rng.choice(servicios), sobrecupo=True)
            creadas += 1
    return creadas


USUARIO_DEMO = 'recepcion'


def _crear_personal():
    User = get_user_model()
    usuario, creado = User.objects.get_or_create(username=USUARIO_DEMO, defaults={'is_staff': True})
    if creado:
        usuario.set_password(os.environ.get('DEMO_STAFF_PASSWORD', 'recepcion123'))
        usuario.save()
    return usuario


@transaction.atomic
def cargar_demo(hoy=None):
    rng = random.Random(2026)
    hoy = hoy or datetime.date.today()
    dentistas, servicios = _crear_catalogos(rng)
    pacientes = _crear_pacientes(rng)
    _crear_personal()
    _crear_agenda(dentistas, hoy)
    reservas = _crear_reservas(rng, pacientes, servicios, hoy)
    return {
        "regiones": Region.objects.count(),
        "dentistas": len(dentistas),
        "servicios": len(servicios),
        "pacientes": len(pacientes),
        "slots": SlotAgenda.objects.count(),
        "reservas": reservas,
    }
