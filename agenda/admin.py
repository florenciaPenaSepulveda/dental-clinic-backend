from django.contrib import admin
from .models import Paciente, Dentista, Servicio, SlotAgenda, Reserva

@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellido', 'email', 'telefono', 'fecha_registro')
    search_fields = ('nombre', 'apellido', 'email')

@admin.register(Dentista)
class DentistaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'apellido', 'especialidad', 'email')
    search_fields = ('nombre', 'apellido', 'especialidad')
    list_editable = ('especialidad',)

@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'duracion_min', 'precio')

@admin.register(SlotAgenda)
class SlotAgendaAdmin(admin.ModelAdmin):
    list_display = ('dentista', 'fecha', 'hora', 'capacidad')
    list_filter = ('dentista', 'fecha')
    list_editable = ('capacidad',)

@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ('paciente', 'slot', 'servicio', 'creado_en', 'sobrecupo')
    list_filter = ('sobrecupo', 'slot__dentista')
    list_editable = ('sobrecupo',)
