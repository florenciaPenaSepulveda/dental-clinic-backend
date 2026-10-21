from django.contrib import admin
from .models import Paciente, Cita, Dentista, Agenda
@admin.register(Dentista)
class DentistaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "apellido", "especialidad", "email", "telefono")
    search_fields = ("nombre", "apellido", "especialidad", "email")

@admin.register(Agenda)
class AgendaAdmin(admin.ModelAdmin):
    list_display = ("dentista", "fecha", "hora", "paciente", "sobrecupo")
    search_fields = ("dentista__nombre", "dentista__apellido", "paciente__nombre")
    list_filter = ("fecha", "dentista", "sobrecupo")

@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "apellido", "email", "telefono", "fecha_registro")
    search_fields = ("nombre", "apellido", "email")

@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = ("paciente", "fecha", "motivo")
    search_fields = ("paciente__nombre", "paciente__apellido", "motivo")
    list_filter = ("fecha",)
