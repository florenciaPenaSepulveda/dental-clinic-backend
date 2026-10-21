from rest_framework import serializers
from .models import Paciente, Cita, Dentista, Agenda
class DentistaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dentista
        fields = '__all__'

class AgendaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agenda
        fields = '__all__'

class PacienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paciente
        fields = '__all__'

class CitaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cita
        fields = '__all__'
