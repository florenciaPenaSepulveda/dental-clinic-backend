import datetime
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


class Region(models.Model):
    nombre = models.CharField(max_length=100)
    codigo = models.CharField(max_length=10, unique=True)
    
    class Meta:
        ordering = ['nombre']
    
    def __str__(self):
        return self.nombre


class Paciente(models.Model):
  
    rut = models.CharField(max_length=15, unique=True, help_text='RUT del paciente (ej: 12.345.678-9)')
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='paciente_perfil')

    class Meta:
        ordering = ['apellido', 'nombre']

    def __str__(self):
        return f"{self.nombre} {self.apellido}"


class Dentista(models.Model):
   
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='dentistas', null=True, blank=True)
    max_overbook_day = models.PositiveIntegerField(default=0, help_text='Sobrecupos que admite por día, salvo que se defina otro valor para una fecha')
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='dentista_perfil')

    class Meta:
        ordering = ['apellido', 'nombre']

    def __str__(self):
        base = f"{self.nombre} {self.apellido}"
        return f"{base} - {self.especialidad}" if self.especialidad else base


class Servicio(models.Model):
    nombre = models.CharField(max_length=150)
    duracion_min = models.PositiveIntegerField(help_text='Duración en minutos')
    precio = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return self.nombre


class SlotAgenda(models.Model):
    dentista = models.ForeignKey(Dentista, on_delete=models.CASCADE, related_name='slots')
    servicio = models.ForeignKey(Servicio, on_delete=models.SET_NULL, null=True, blank=True)
    fecha = models.DateField()
    hora = models.TimeField()
    capacidad = models.PositiveIntegerField(default=1, help_text='Cuántos pacientes caben en este slot')
    creador = models.CharField(max_length=100, blank=True)

    class Meta:
        unique_together = ('dentista', 'fecha', 'hora')
        ordering = ('fecha', 'hora')

    def __str__(self):
        return f"{self.dentista} - {self.fecha} {self.hora}"

    def clean(self):
        min_hora = datetime.time(8, 0)
        max_hora = datetime.time(17, 30)
        if self.hora < min_hora or self.hora > max_hora:
            raise ValidationError({'hora': 'La hora de inicio debe estar entre 08:00 y 17:30 (la clínica atiende hasta las 18:00).'})

        if self.hora.minute not in (0, 30):
            raise ValidationError({'hora': 'La hora debe estar en bloques de 30 minutos (mm = 00 o 30).'})

        qs = SlotAgenda.objects.filter(dentista=self.dentista, fecha=self.fecha, hora=self.hora)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if qs.exists():
            raise ValidationError('Ya existe un slot para este dentista en la misma fecha y hora.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SobrecupoDia(models.Model):
    dentista = models.ForeignKey(Dentista, on_delete=models.CASCADE, related_name='sobrecupos_por_dia')
    fecha = models.DateField()
    cupos = models.PositiveSmallIntegerField(help_text='Sobrecupos que admite el dentista esa fecha')

    class Meta:
        unique_together = ('dentista', 'fecha')

    def __str__(self):
        return f"{self.dentista} - {self.fecha}: {self.cupos}"


class Reserva(models.Model):
    ESTADOS = [('pendiente', 'Pendiente'), ('atendida', 'Atendida'), ('no_asistio', 'No asistió')]

    slot = models.ForeignKey(SlotAgenda, on_delete=models.CASCADE, related_name='reservas')
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='reservas')
    servicio = models.ForeignKey(Servicio, on_delete=models.SET_NULL, null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    sobrecupo = models.BooleanField(default=False)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    motivo = models.TextField(blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        unique_together = ('slot', 'paciente')

    def __str__(self):
        return f"Reserva {self.paciente} -> {self.slot} {'(Sobrecupo)' if self.sobrecupo else ''}"


def ruta_archivo(instance, nombre):
    extension = nombre.rsplit('.', 1)[-1].lower() if '.' in nombre else 'bin'
    return f"reservas/{instance.reserva_id}/{uuid.uuid4().hex}.{extension}"


class ArchivoReserva(models.Model):
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='archivos')
    archivo = models.FileField(upload_to=ruta_archivo)
    nombre = models.CharField(max_length=255)
    tipo = models.CharField(max_length=100)
    tamano = models.PositiveIntegerField()
    subido_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['subido_en']

    def __str__(self):
        return self.nombre


class Atencion(models.Model):
    reserva = models.OneToOneField(Reserva, on_delete=models.CASCADE, related_name='atencion')
    diagnostico = models.TextField(blank=True)
    procedimiento = models.TextField(blank=True)
    indicaciones = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Atención de {self.reserva.paciente}"


class ClaveTemporal(models.Model):
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='clave_temporal')
    creada_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Clave temporal de {self.usuario}"


@receiver(post_delete, sender=ArchivoReserva)
def eliminar_archivo_del_disco(sender, instance, **kwargs):
    instance.archivo.delete(save=False)
