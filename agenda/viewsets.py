from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .cuentas import crear_o_reiniciar_cuenta, usuario_de_dentista
from .archivos import adjuntar_archivos, guardar_reserva, validar_archivos
from .models import Atencion, Dentista, Paciente, Region, Reserva, Servicio
from .permissions import (
    DENTISTA,
    RECEPCION,
    EsPersonal,
    EsRecepcion,
    EsUsuarioConRol,
    RecepcionOLectura,
    perfil_dentista,
    puede_ver_reserva,
    rol_de,
)
from .serializers import (
    ArchivoSerializer,
    AtencionSerializer,
    DentistaSerializer,
    HistorialPersonalSerializer,
    PacienteSerializer,
    RegionSerializer,
    ReservaActualizarSerializer,
    ReservaCreateSerializer,
    ReservaDetalleSerializer,
    ServicioSerializer,
)
from .throttles import BuscarThrottle, RegistroThrottle, ReservaThrottle
from .utils import normalizar_rut, ocultar_correo, ocultar_telefono


class RegionViewSet(viewsets.ModelViewSet):
    queryset = Region.objects.all()
    serializer_class = RegionSerializer
    permission_classes = [RecepcionOLectura]


class DentistaViewSet(viewsets.ModelViewSet):
    queryset = Dentista.objects.select_related('region').all()
    serializer_class = DentistaSerializer
    permission_classes = [RecepcionOLectura]

    def get_queryset(self):
        queryset = self.queryset.all()
        region_id = self.request.query_params.get('region', None)
        if region_id is not None:
            queryset = queryset.filter(region=region_id)
        return queryset

    @action(detail=True, methods=['post'], permission_classes=[EsRecepcion])
    def cuenta(self, request, pk=None):
        dentista = self.get_object()
        return Response(crear_o_reiniciar_cuenta(dentista, usuario_de_dentista(dentista)))


class ServicioViewSet(viewsets.ModelViewSet):
    queryset = Servicio.objects.all()
    serializer_class = ServicioSerializer
    permission_classes = [RecepcionOLectura]


class PacienteViewSet(viewsets.ModelViewSet):
    queryset = Paciente.objects.all()
    serializer_class = PacienteSerializer

    def get_permissions(self):
        if self.action in ('create', 'buscar'):
            return [AllowAny()]
        if self.action in ('list', 'retrieve', 'historial'):
            return [EsPersonal()]
        return [EsRecepcion()]

    def get_throttles(self):
        if self.action == 'create':
            return [RegistroThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        perfil = perfil_dentista(self.request.user)
        if perfil is None:
            return self.queryset.all()
        return self.queryset.filter(reservas__slot__dentista=perfil).distinct()

    @action(detail=False, methods=['get'], throttle_classes=[BuscarThrottle])
    def buscar(self, request):
        rut = normalizar_rut(request.query_params.get('rut', ''))
        if rut is None:
            return Response({'detail': 'El RUT ingresado no es válido.'}, status=status.HTTP_400_BAD_REQUEST)
        paciente = Paciente.objects.filter(rut=rut).first()
        if paciente is None:
            return Response({'detail': 'No existe un paciente con este RUT.'}, status=status.HTTP_404_NOT_FOUND)
        datos = self.get_serializer(paciente).data
        if rol_de(request.user) in (RECEPCION, DENTISTA):
            return Response(datos)
        return Response({
            'id': datos['id'],
            'rut': datos['rut'],
            'nombre': datos['nombre'],
            'apellido': datos['apellido'],
            'telefono': ocultar_telefono(datos['telefono']),
            'email': ocultar_correo(datos['email']),
        })

    @action(detail=True, methods=['post'])
    def cuenta(self, request, pk=None):
        paciente = self.get_object()
        return Response(crear_o_reiniciar_cuenta(paciente, paciente.rut))

    @action(detail=True, methods=['get'])
    def historial(self, request, pk=None):
        paciente = self.get_object()
        reservas = (
            Reserva.objects.filter(paciente=paciente)
            .select_related('slot__dentista', 'servicio', 'atencion')
            .prefetch_related('archivos')
            .order_by('-slot__fecha', '-slot__hora')
        )
        perfil = perfil_dentista(request.user)
        if perfil is not None:
            reservas = reservas.filter(slot__dentista=perfil)
        return Response(HistorialPersonalSerializer(reservas, many=True).data)


class ReservaViewSet(viewsets.ModelViewSet):
    queryset = (
        Reserva.objects.select_related('slot', 'slot__dentista', 'paciente', 'servicio', 'atencion')
        .prefetch_related('archivos')
        .all()
    )

    def get_permissions(self):
        if self.action == 'create':
            return [AllowAny()]
        if self.action == 'archivos':
            return [EsUsuarioConRol()]
        return [EsPersonal()]

    def get_throttles(self):
        if self.action == 'create':
            return [ReservaThrottle()]
        return super().get_throttles()

    def get_serializer_class(self):
        if self.action == 'create':
            return ReservaCreateSerializer
        if self.action in ('update', 'partial_update'):
            return ReservaActualizarSerializer
        return ReservaDetalleSerializer

    def get_queryset(self):
        queryset = self.queryset.all()
        perfil = perfil_dentista(self.request.user)
        if perfil is not None:
            queryset = queryset.filter(slot__dentista=perfil)

        dentista_id = self.request.query_params.get('dentista', None)
        if dentista_id is not None:
            queryset = queryset.filter(slot__dentista=dentista_id)

        fecha = self.request.query_params.get('fecha', None)
        if fecha is not None:
            queryset = queryset.filter(slot__fecha=fecha)

        return queryset.order_by('slot__fecha', 'slot__hora')

    def create(self, request, *args, **kwargs):
        archivos = request.FILES.getlist('archivos')
        validar_archivos(archivos)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = guardar_reserva(serializer, archivos)

        return Response({
            'id': instance.id,
            'slot': instance.slot.id,
            'paciente': instance.paciente.id,
            'servicio': instance.servicio.id if instance.servicio else None,
            'sobrecupo': instance.sobrecupo,
            'created': True
        }, status=201)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ReservaActualizarSerializer(instance, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        perfil = perfil_dentista(request.user)
        nuevo = serializer.validated_data.get('slot')
        if perfil is not None and nuevo is not None and nuevo.dentista_id != perfil.id:
            raise PermissionDenied('Solo puedes mover reservas dentro de tu propia agenda.')
        serializer.save()
        return Response(ReservaDetalleSerializer(self.get_queryset().get(pk=instance.pk)).data)

    @action(detail=True, methods=['post'])
    def archivos(self, request, pk=None):
        reserva = get_object_or_404(Reserva.objects.select_related('slot'), pk=pk)
        if not puede_ver_reserva(request.user, reserva):
            return Response({'detail': 'No encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        archivos = request.FILES.getlist('archivos')
        if not archivos:
            return Response({'archivos': 'Selecciona al menos un archivo.'}, status=status.HTTP_400_BAD_REQUEST)
        validar_archivos(archivos, existentes=reserva.archivos.count())
        return Response(ArchivoSerializer(adjuntar_archivos(reserva, archivos), many=True).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['put'])
    def atencion(self, request, pk=None):
        if rol_de(request.user) != DENTISTA:
            raise PermissionDenied('Solo el dentista puede registrar la atención.')
        reserva = self.get_object()
        existente = Atencion.objects.filter(reserva=reserva).first()
        serializer = AtencionSerializer(existente, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(reserva=reserva)
        if reserva.estado != 'atendida':
            reserva.estado = 'atendida'
            reserva.save(update_fields=['estado'])
        return Response(ReservaDetalleSerializer(self.get_queryset().get(pk=reserva.pk)).data)
