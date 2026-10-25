from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Dentista, Servicio, Paciente, Region, Reserva
from .permissions import IsStaff, IsStaffOrReadOnly
from .throttles import BuscarThrottle
from .utils import normalizar_rut
from .serializers import DentistaSerializer, ServicioSerializer, PacienteSerializer, RegionSerializer, ReservaCreateSerializer, ReservaReadSerializer


class RegionViewSet(viewsets.ModelViewSet):
    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    permission_classes = [IsStaffOrReadOnly]


class DentistaViewSet(viewsets.ModelViewSet):
    queryset = Dentista.objects.select_related('region').all()
    serializer_class = DentistaSerializer
    permission_classes = [IsStaffOrReadOnly]
    
    def get_queryset(self):
        queryset = self.queryset.all()
        region_id = self.request.query_params.get('region', None)
        if region_id is not None:
            queryset = queryset.filter(region=region_id)
        return queryset


class ServicioViewSet(viewsets.ModelViewSet):
    queryset = Servicio.objects.all()
    serializer_class = ServicioSerializer
    permission_classes = [IsStaffOrReadOnly]


class PacienteViewSet(viewsets.ModelViewSet):
    queryset = Paciente.objects.all()
    serializer_class = PacienteSerializer

    def get_permissions(self):
        if self.action in ('create', 'buscar'):
            return [AllowAny()]
        return [IsStaff()]

    @action(detail=False, methods=['get'], throttle_classes=[BuscarThrottle])
    def buscar(self, request):
        rut = normalizar_rut(request.query_params.get('rut', ''))
        if rut is None:
            return Response({'detail': 'El RUT ingresado no es válido.'}, status=status.HTTP_400_BAD_REQUEST)
        paciente = self.get_queryset().filter(rut=rut).first()
        if paciente is None:
            return Response({'detail': 'No existe un paciente con este RUT.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(paciente).data)


class ReservaViewSet(viewsets.ModelViewSet):
    queryset = Reserva.objects.select_related('slot', 'slot__dentista', 'paciente', 'servicio').all()

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        return [IsStaff()]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return ReservaCreateSerializer
        return ReservaReadSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        
        return Response({
            'id': instance.id,
            'slot': instance.slot.id,
            'paciente': instance.paciente.id,
            'servicio': instance.servicio.id if instance.servicio else None,
            'sobrecupo': instance.sobrecupo,
            'created': True
        }, status=201)
    
    def get_queryset(self):
        queryset = self.queryset.all()

        dentista_id = self.request.query_params.get('dentista', None)
        if dentista_id is not None:
            queryset = queryset.filter(slot__dentista=dentista_id)
            
        fecha = self.request.query_params.get('fecha', None)
        if fecha is not None:
            queryset = queryset.filter(slot__fecha=fecha)
        
        return queryset.order_by('slot__fecha', 'slot__hora')
