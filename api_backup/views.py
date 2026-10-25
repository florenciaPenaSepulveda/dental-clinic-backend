from rest_framework import viewsets
from .models import Paciente, Cita, Dentista, Agenda
from .serializers import PacienteSerializer, CitaSerializer, DentistaSerializer, AgendaSerializer
class DentistaViewSet(viewsets.ModelViewSet):
    queryset = Dentista.objects.all()
    serializer_class = DentistaSerializer

class AgendaViewSet(viewsets.ModelViewSet):
    queryset = Agenda.objects.all()
    serializer_class = AgendaSerializer

class PacienteViewSet(viewsets.ModelViewSet):
    queryset = Paciente.objects.all()
    serializer_class = PacienteSerializer

class CitaViewSet(viewsets.ModelViewSet):
    queryset = Cita.objects.all()
    serializer_class = CitaSerializer
