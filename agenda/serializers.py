import logging

from rest_framework import serializers
from django.db import IntegrityError
from django.db import transaction
from .models import Atencion, ArchivoReserva, SlotAgenda, Reserva, Servicio, Dentista, Paciente, Region
from django.core.mail import send_mail
from django.conf import settings

from .utils import es_correo_de_ejemplo, normalizar_rut

logger = logging.getLogger(__name__)


class SlotAgendaSerializer(serializers.ModelSerializer):
    dentista = serializers.StringRelatedField()
    servicio = serializers.StringRelatedField()

    class Meta:
        model = SlotAgenda
        fields = ('id', 'dentista', 'servicio', 'fecha', 'hora', 'capacidad', 'max_overbook')


class SlotDisponibilidadSerializer(SlotAgendaSerializer):
    reservas_count = serializers.IntegerField(read_only=True)
    sobrecupos_count = serializers.IntegerField(read_only=True)

    class Meta(SlotAgendaSerializer.Meta):
        fields = SlotAgendaSerializer.Meta.fields + ('reservas_count', 'sobrecupos_count')


class ReservaCreateSerializer(serializers.Serializer):
    slot = serializers.PrimaryKeyRelatedField(queryset=SlotAgenda.objects.all(), required=False, allow_null=True)
    paciente = serializers.IntegerField()
    servicio = serializers.IntegerField(required=False)
    
    dentista = serializers.IntegerField(required=False)
    fecha = serializers.DateField(required=False)
    hora_inicio = serializers.TimeField(required=False)
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def _send_confirmation_email(self, reserva: Reserva):
        """Función privada para manejar el envío de correo."""
        paciente = reserva.paciente
        email_paciente = paciente.email
        
        if not email_paciente:
            logger.info("Paciente %s sin email: se omite el correo de confirmación", paciente.pk)
            return

        if es_correo_de_ejemplo(email_paciente):
            logger.info("Correo de ejemplo (%s): se omite el envío", email_paciente)
            return

        asunto = "Confirmación de Hora Agendada"
        cuerpo_mensaje = f"""
Estimado/a {paciente.nombre} {paciente.apellido},

Su hora ha sido confirmada con éxito.

Detalles de su cita:
- Fecha: {reserva.slot.fecha}
- Hora: {reserva.slot.hora}
- Dentista: {reserva.slot.dentista}
- Servicio: {reserva.slot.servicio}
- Tipo: {'Sobrecupo' if reserva.sobrecupo else 'Normal'}

Por favor, llegue 10 minutos antes.

Atentamente,
La Clínica Dental.
"""
        try:
            send_mail(
                asunto,
                cuerpo_mensaje,
                settings.DEFAULT_FROM_EMAIL,
                [email_paciente],
                fail_silently=False
            )
            logger.info("Correo de confirmación enviado para la reserva %s", reserva.pk)
        except Exception as e:
            logger.warning("No se pudo enviar el correo de la reserva %s: %s", reserva.pk, e)


    def validate(self, data):
        if not data.get('slot'):
            if not all([data.get('dentista'), data.get('fecha'), data.get('hora_inicio')]):
                raise serializers.ValidationError(
                    "Se debe proporcionar 'slot' o los campos 'dentista', 'fecha' y 'hora_inicio'"
                )
        return data

    def create(self, validated_data):
        dentista_id = validated_data.pop('dentista', None)
        fecha = validated_data.pop('fecha', None)
        hora_inicio = validated_data.pop('hora_inicio', None)
        motivo = validated_data.pop('motivo', '')
        self.reutilizada = False
        
        paciente_data = validated_data.get('paciente')
        servicio_id = validated_data.get('servicio')
        
        if isinstance(paciente_data, Paciente):
            paciente = paciente_data
        else:
            try:
                paciente_id = int(paciente_data) if paciente_data else None
                if not paciente_id:
                    raise serializers.ValidationError("ID de paciente es requerido")
                paciente = Paciente.objects.get(id=paciente_id)
            except (ValueError, TypeError):
                raise serializers.ValidationError(f"ID de paciente inválido: {paciente_data}")
            except Paciente.DoesNotExist:
                raise serializers.ValidationError(f"Paciente con ID {paciente_id} no existe")
        
        servicio = None
        if servicio_id:
            if isinstance(servicio_id, Servicio):
                servicio = servicio_id
            else:
                try:
                    servicio_id_int = int(servicio_id)
                    servicio = Servicio.objects.get(id=servicio_id_int)
                except (ValueError, TypeError):
                    raise serializers.ValidationError(f"ID de servicio inválido: {servicio_id}")
                except Servicio.DoesNotExist:
                    raise serializers.ValidationError(f"Servicio con ID {servicio_id} no existe")
        
        slot = validated_data.get('slot')
        if not slot and dentista_id and fecha and hora_inicio:
            try:
                dentista = Dentista.objects.get(id=dentista_id)
                
                slot, created = SlotAgenda.objects.get_or_create(
                    dentista=dentista,
                    fecha=fecha,
                    hora=hora_inicio,
                    defaults={
                        'servicio': servicio,
                        'capacidad': 1,
                        'max_overbook': 0
                    }
                )
            except Dentista.DoesNotExist:
                raise serializers.ValidationError(f"Dentista con ID {dentista_id} no existe")
        
        if not slot:
            raise serializers.ValidationError("No se pudo crear o encontrar un slot válido")
        
        
        with transaction.atomic():
            existing_reserva = Reserva.objects.filter(slot=slot, paciente=paciente).first()
            if existing_reserva:
                self._send_confirmation_email(existing_reserva)
                self.reutilizada = True
                return existing_reserva
            
            reservas_actuales = slot.reservas.select_for_update().count()
            if reservas_actuales < slot.capacidad:
                try:
                    reserva = Reserva.objects.create(slot=slot, paciente=paciente, servicio=servicio, sobrecupo=False, motivo=motivo)
                    self._send_confirmation_email(reserva)
                    return reserva
                except IntegrityError:
                    existing_reserva = Reserva.objects.filter(slot=slot, paciente=paciente).first()
                    if existing_reserva:
                        self._send_confirmation_email(existing_reserva)
                        self.reutilizada = True
                        return existing_reserva
                    raise

            sobrecupos_actuales_slot = slot.reservas.filter(sobrecupo=True).count()
            if sobrecupos_actuales_slot < slot.max_overbook:
                fecha = slot.fecha
                dentista = slot.dentista
                sobrecupos_dia = Reserva.objects.filter(slot__dentista=dentista, slot__fecha=fecha, sobrecupo=True).count()
                if sobrecupos_dia < dentista.max_overbook_day:
                    try:
                        reserva = Reserva.objects.create(slot=slot, paciente=paciente, servicio=servicio, sobrecupo=True, motivo=motivo)
                        self._send_confirmation_email(reserva)
                        return reserva
                    except IntegrityError:
                        existing_reserva = Reserva.objects.filter(slot=slot, paciente=paciente).first()
                        if existing_reserva:
                            self._send_confirmation_email(existing_reserva)
                            self.reutilizada = True
                            return existing_reserva
                        raise

            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({'detail': 'El slot está lleno y no se permiten sobrecupos adicionales.'})


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ('id', 'nombre', 'codigo')


class DentistaSerializer(serializers.ModelSerializer):
    region = RegionSerializer(read_only=True)
    region_id = serializers.IntegerField(write_only=True, required=False)
    
    class Meta:
        model = Dentista
        fields = ('id', 'nombre', 'apellido', 'especialidad', 'email', 'telefono', 'region', 'region_id', 'max_overbook_day')


class ServicioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Servicio
        fields = ('id', 'nombre', 'duracion_min', 'precio')


class PacienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paciente
        fields = ('id', 'rut', 'nombre', 'apellido', 'telefono', 'email', 'fecha_registro')

    def validate_rut(self, value):
        rut = normalizar_rut(value)
        if rut is None:
            raise serializers.ValidationError('El RUT ingresado no es válido.')
        repetidos = Paciente.objects.filter(rut=rut)
        if self.instance is not None:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise serializers.ValidationError('Ya existe un paciente con este RUT.')
        return rut


class ReservaReadSerializer(serializers.ModelSerializer):
    """Serializer para lectura de reservas con información detallada"""
    slot = SlotAgendaSerializer(read_only=True)
    paciente = PacienteSerializer(read_only=True)
    servicio = ServicioSerializer(read_only=True)
    
    class Meta:
        model = Reserva
        fields = ('id', 'slot', 'paciente', 'servicio', 'creado_en', 'sobrecupo', 'estado', 'motivo', 'observaciones')


class ArchivoSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArchivoReserva
        fields = ('id', 'nombre', 'tipo', 'tamano', 'subido_en')


class AtencionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Atencion
        fields = ('diagnostico', 'procedimiento', 'indicaciones', 'actualizado_en')
        read_only_fields = ('actualizado_en',)
        extra_kwargs = {campo: {'max_length': 5000} for campo in ('diagnostico', 'procedimiento', 'indicaciones')}


class _ConAtencion(serializers.Serializer):
    atencion = serializers.SerializerMethodField()

    def get_atencion(self, reserva):
        atencion = getattr(reserva, 'atencion', None)
        return AtencionSerializer(atencion).data if atencion else None


class ReservaDetalleSerializer(_ConAtencion, ReservaReadSerializer):
    archivos = ArchivoSerializer(many=True, read_only=True)

    class Meta(ReservaReadSerializer.Meta):
        fields = ReservaReadSerializer.Meta.fields + ('archivos', 'atencion')


class ReservaActualizarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reserva
        fields = ('estado', 'observaciones', 'servicio', 'slot')
        extra_kwargs = {'observaciones': {'max_length': 2000}}

    def validate(self, data):
        slot = data.get('slot')
        if slot is not None and slot.id != self.instance.slot_id:
            if Reserva.objects.filter(slot=slot, paciente=self.instance.paciente).exists():
                raise serializers.ValidationError({'slot': 'El paciente ya tiene una reserva en ese horario.'})
            if slot.reservas.count() < slot.capacidad:
                data['sobrecupo'] = False
            elif slot.reservas.filter(sobrecupo=True).count() < slot.max_overbook:
                data['sobrecupo'] = True
            else:
                raise serializers.ValidationError({'slot': 'El horario elegido está lleno.'})
        return data


class SlotSemanaSerializer(serializers.ModelSerializer):
    reservas = ReservaDetalleSerializer(many=True, read_only=True)

    class Meta:
        model = SlotAgenda
        fields = ('id', 'dentista', 'fecha', 'hora', 'capacidad', 'max_overbook', 'reservas')


class HistorialSerializer(_ConAtencion, serializers.ModelSerializer):
    fecha = serializers.DateField(source='slot.fecha')
    hora = serializers.TimeField(source='slot.hora')
    dentista = serializers.SerializerMethodField()
    servicio = serializers.StringRelatedField()
    archivos = ArchivoSerializer(many=True, read_only=True)

    class Meta:
        model = Reserva
        fields = ('id', 'fecha', 'hora', 'dentista', 'servicio', 'estado', 'motivo', 'archivos', 'atencion')

    def get_dentista(self, reserva):
        dentista = reserva.slot.dentista
        return {'id': dentista.id, 'nombre': f"{dentista.nombre} {dentista.apellido}", 'especialidad': dentista.especialidad}


class HistorialPersonalSerializer(HistorialSerializer):
    class Meta(HistorialSerializer.Meta):
        fields = HistorialSerializer.Meta.fields + ('observaciones',)
