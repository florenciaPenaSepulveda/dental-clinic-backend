from django.db import models

class Paciente(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField()
    telefono = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
    direccion = models.CharField(max_length=255, blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

class Dentista(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    telefono = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.nombre} {self.apellido} - {self.especialidad}"

class Cita(models.Model):
    paciente = models.ForeignKey('Paciente', on_delete=models.CASCADE, related_name='citas')
    fecha = models.DateTimeField()
    motivo = models.CharField(max_length=255)
    notas = models.TextField(blank=True)

    def __str__(self):
        return f"Cita de {self.paciente} el {self.fecha.strftime('%Y-%m-%d %H:%M')}"

class Agenda(models.Model):
    dentista = models.ForeignKey('Dentista', on_delete=models.CASCADE, related_name='agendas')
    fecha = models.DateField()
    hora = models.TimeField()
    paciente = models.ForeignKey('Paciente', on_delete=models.SET_NULL, null=True, blank=True, related_name='agendas')
    sobrecupo = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.dentista} - {self.fecha} {self.hora} {'(Sobrecupo)' if self.sobrecupo else ''}"
