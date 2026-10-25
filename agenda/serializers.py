import logging
import re

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils.formats import date_format
from rest_framework import serializers

from .models import ArchivoReserva, Atencion, Dentista, Paciente, Region, Reserva, Servicio, SlotAgenda
from .utils import es_correo_de_ejemplo, horario_pasado, normalizar_rut

logger = logging.getLogger(__name__)

FORMATO_FECHA = r'l j \d\e F \d\e Y'
TELEFONO = re.compile(r'\+?[0-9(][0-9 ()-]{6,18}[0-9]')


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
    paciente = serializers.PrimaryKeyRelatedField(queryset=Paciente.objects.all())
    servicio = serializers.PrimaryKeyRelatedField(queryset=Servicio.objects.all(), required=False, allow_null=True)
    dentista = serializers.IntegerField(required=False)
    fecha = serializers.DateField(required=False)
    hora_inicio = serializers.TimeField(required=False)
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, data):
        slot = data.get('slot')
        if slot is None:
            if not all([data.get('dentista'), data.get('fecha'), data.get('hora_inicio')]):
                raise serializers.ValidationError("Se debe proporcionar 'slot' o los campos 'dentista', 'fecha' y 'hora_inicio'")
            slot = SlotAgenda.objects.filter(dentista_id=data['dentista'], fecha=data['fecha'], hora=data['hora_inicio']).first()
            if slot is None:
                raise serializers.ValidationError('No existe un horario disponible en esa fecha y hora.')
            data['slot'] = slot
        if horario_pasado(slot.fecha, slot.hora):
            raise serializers.ValidationError('Ese horario ya pasó. Elige otro.')
        return data

    def _es_sobrecupo(self, slot):
        if slot.reservas.count() < slot.capacidad:
            return False
        dentista = slot.dentista
        sobrecupos_del_dia = Reserva.objects.filter(slot__dentista=dentista, slot__fecha=slot.fecha, sobrecupo=True).count()
        if slot.reservas.filter(sobrecupo=True).count() < slot.max_overbook and sobrecupos_del_dia < dentista.max_overbook_day:
            return True
        raise serializers.ValidationError({'detail': 'El slot está lleno y no se permiten sobrecupos adicionales.'})

    def create(self, validated_data):
        slot = validated_data['slot']
        paciente = validated_data['paciente']
        self.reutilizada = False
        try:
            with transaction.atomic():
                existente = Reserva.objects.filter(slot=slot, paciente=paciente).first()
                if existente:
                    self.reutilizada = True
                    return existente
                reserva = Reserva.objects.create(
                    slot=slot,
                    paciente=paciente,
                    servicio=validated_data.get('servicio'),
                    motivo=validated_data.get('motivo', ''),
                    sobrecupo=self._es_sobrecupo(slot),
                )
        except IntegrityError:
            self.reutilizada = True
            return Reserva.objects.get(slot=slot, paciente=paciente)
        self._enviar_confirmacion(reserva)
        return reserva

    def _enviar_confirmacion(self, reserva):
        paciente = reserva.paciente
        if not paciente.email:
            logger.info("Paciente %s sin email: se omite el correo de confirmación", paciente.pk)
            return
        if es_correo_de_ejemplo(paciente.email):
            logger.info("Correo de ejemplo (%s): se omite el envío", paciente.email)
            return
        slot = reserva.slot
        dentista = slot.dentista
        fecha = date_format(slot.fecha, FORMATO_FECHA)
        lineas = [
            f"Estimado/a {paciente.nombre} {paciente.apellido},",
            "",
            "Su hora fue confirmada.",
            "",
            f"Fecha: {fecha}",
            f"Hora: {slot.hora:%H:%M}",
            f"Dentista: {dentista.nombre} {dentista.apellido}" + (f" ({dentista.especialidad})" if dentista.especialidad else ""),
            f"Servicio: {reserva.servicio.nombre if reserva.servicio else 'Por definir en la consulta'}",
        ]
        if reserva.sobrecupo:
            lineas.append("Tipo: sobrecupo (se atenderá según la disponibilidad del dentista)")
        lineas += ["", "Por favor, llegue 10 minutos antes de su hora.", "", "Atentamente,", "Clínica Dental"]
        try:
            send_mail("Confirmación de hora agendada", "\n".join(lineas), settings.DEFAULT_FROM_EMAIL, [paciente.email], fail_silently=False)
            logger.info("Correo de confirmación enviado para la reserva %s", reserva.pk)
        except Exception as error:
            logger.warning("No se pudo enviar el correo de la reserva %s: %s", reserva.pk, error)


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ('id', 'nombre', 'codigo')


class DentistaSerializer(serializers.ModelSerializer):
    region = RegionSerializer(read_only=True)
    region_id = serializers.IntegerField(write_only=True, required=False)
    tiene_cuenta = serializers.SerializerMethodField()

    class Meta:
        model = Dentista
        fields = ('id', 'nombre', 'apellido', 'especialidad', 'email', 'telefono', 'region', 'region_id', 'max_overbook_day', 'tiene_cuenta')

    def get_tiene_cuenta(self, dentista):
        return dentista.usuario_id is not None


class ServicioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Servicio
        fields = ('id', 'nombre', 'duracion_min', 'precio')


class PacienteSerializer(serializers.ModelSerializer):
    tiene_cuenta = serializers.SerializerMethodField()

    class Meta:
        model = Paciente
        fields = ('id', 'rut', 'nombre', 'apellido', 'telefono', 'email', 'fecha_registro', 'tiene_cuenta')

    def get_tiene_cuenta(self, paciente):
        return paciente.usuario_id is not None

    def validate_telefono(self, value):
        valor = value.strip()
        if valor and not TELEFONO.fullmatch(valor):
            raise serializers.ValidationError('Ingresa un teléfono válido (números, espacios, + y guiones).')
        return valor

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
