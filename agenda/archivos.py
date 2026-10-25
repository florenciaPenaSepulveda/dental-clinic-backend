import os

from django.db import transaction
from rest_framework import serializers

from .models import ArchivoReserva

MAX_ARCHIVOS = 5
MAX_BYTES = 5 * 1024 * 1024
TIPOS = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png'}
FIRMAS = {'pdf': b'%PDF-', 'jpg': b'\xff\xd8\xff', 'jpeg': b'\xff\xd8\xff', 'png': b'\x89PNG\r\n\x1a\n'}


def _extension(archivo):
    return archivo.name.rsplit('.', 1)[-1].lower() if '.' in archivo.name else ''


def validar_archivos(archivos, existentes=0):
    if len(archivos) + existentes > MAX_ARCHIVOS:
        raise serializers.ValidationError({'archivos': f'Se permiten hasta {MAX_ARCHIVOS} archivos por reserva.'})
    for archivo in archivos:
        extension = _extension(archivo)
        if extension not in TIPOS:
            raise serializers.ValidationError({'archivos': 'Solo se aceptan archivos PDF, JPG o PNG.'})
        if archivo.size > MAX_BYTES:
            raise serializers.ValidationError({'archivos': f'{os.path.basename(archivo.name)} supera los 5 MB permitidos.'})
        cabecera = archivo.read(8)
        archivo.seek(0)
        if not cabecera.startswith(FIRMAS[extension]):
            raise serializers.ValidationError({'archivos': f'{os.path.basename(archivo.name)} no corresponde a un archivo {extension.upper()} válido.'})


def adjuntar_archivos(reserva, archivos):
    return [
        ArchivoReserva.objects.create(
            reserva=reserva,
            archivo=archivo,
            nombre=os.path.basename(archivo.name)[:255],
            tipo=TIPOS[_extension(archivo)],
            tamano=archivo.size,
        )
        for archivo in archivos
    ]


def guardar_reserva(serializer, archivos):
    with transaction.atomic():
        reserva = serializer.save()
        if archivos and not serializer.reutilizada:
            adjuntar_archivos(reserva, archivos)
    return reserva
