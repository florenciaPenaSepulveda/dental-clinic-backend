import logging
import re

from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError as ErrorDeDjango
from django.db import IntegrityError, transaction
from django.utils.formats import date_format
from rest_framework import serializers

from .ocupacion import validar_espacio
from .sobrecupos import MAX_SOBRECUPOS_DIA, puede_gestionar, validar_sobrecupo
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
        fields = ('id', 'dentista', 'servicio', 'fecha', 'hora', 'capacidad')


def _o_rechazar(funcion, *argumentos, **opciones):
    try:
        funcion(*argumentos, **opciones)
    except ErrorDeDjango as error:
        raise serializers.ValidationError({'detail': ' '.join(error.messages)})


def _validar_espacio(slot, servicio, excluir=None):
    _o_rechazar(validar_espacio, slot, servicio, excluir=excluir)


class SlotDisponibilidadSerializer(SlotAgendaSerializer):
    reservas_count = serializers.IntegerField(read_only=True)
    sobrecupos_count = serializers.IntegerField(read_only=True)
    bloqueado = serializers.SerializerMethodField()
    cabe = serializers.SerializerMethodField()
    sobrecupo_disponible = serializers.SerializerMethodField()

    class Meta(SlotAgendaSerializer.Meta):
        fields = SlotAgendaSerializer.Meta.fields + ('reservas_count', 'sobrecupos_count', 'bloqueado', 'cabe', 'sobrecupo_disponible')

    def get_sobrecupo_disponible(self, slot):
        return slot.id in self.context.get('con_sobrecupo', set())

    def get_bloqueado(self, slot):
        return self.context.get('disponibilidad', {}).get(slot.id, {}).get('bloqueado', False)

    def get_cabe(self, slot):
        return self.context.get('disponibilidad', {}).get(slot.id, {}).get('cabe', True)


class ReservaCreateSerializer(serializers.Serializer):
    slot = serializers.PrimaryKeyRelatedField(queryset=SlotAgenda.objects.all(), required=False, allow_null=True)
    paciente = serializers.PrimaryKeyRelatedField(queryset=Paciente.objects.all())
    servicio = serializers.PrimaryKeyRelatedField(queryset=Servicio.objects.all(), required=False, allow_null=True)
    dentista = serializers.IntegerField(required=False)
    fecha = serializers.DateField(required=False)
    hora_inicio = serializers.TimeField(required=False)
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=500)
    sobrecupo = serializers.BooleanField(required=False, default=False)

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

    def _usuario(self):
        solicitud = self.context.get('request')
        return getattr(solicitud, 'user', None)

    def _decidir_tipo(self, slot, pide_sobrecupo):
        principales = slot.reservas.filter(sobrecupo=False).count()
        hay_espacio = principales < slot.capacidad
        gestiona = puede_gestionar(self._usuario(), slot.dentista_id)
        if pide_sobrecupo:
            if not gestiona:
                raise serializers.ValidationError({'detail': 'Solo recepción o el propio dentista pueden agendar sobrecupos.'})
            if hay_espacio:
                raise serializers.ValidationError({'detail': 'Ese horario aún tiene espacio: agéndalo como una cita normal.'})
            _o_rechazar(validar_sobrecupo, slot)
            return True
        if not hay_espacio:
            sugerencia = ' Puedes agendarlo como sobrecupo.' if gestiona else ''
            raise serializers.ValidationError({'detail': f'Ese horario ya está completo.{sugerencia}'})
        return False

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
                sobrecupo = self._decidir_tipo(slot, validated_data.get('sobrecupo', False))
                if not sobrecupo:
                    _validar_espacio(slot, validated_data.get('servicio'))
                reserva = Reserva.objects.create(
                    slot=slot,
                    paciente=paciente,
                    servicio=validated_data.get('servicio'),
                    motivo=validated_data.get('motivo', ''),
                    sobrecupo=sobrecupo,
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

    def validate_max_overbook_day(self, valor):
        if valor > MAX_SOBRECUPOS_DIA:
            raise serializers.ValidationError(f'Los sobrecupos por día no pueden superar {MAX_SOBRECUPOS_DIA}.')
        return valor


class ServicioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Servicio
        fields = ('id', 'nombre', 'duracion_min', 'precio')

    def validate_nombre(self, valor):
        valor = valor.strip()
        if not valor:
            raise serializers.ValidationError('Ingresa el nombre del servicio.')
        return valor

    def validate_duracion_min(self, valor):
        if valor < 15 or valor > 240 or valor % 15:
            raise serializers.ValidationError('La duración debe estar entre 15 y 240 minutos, en múltiplos de 15.')
        return valor

    def validate_precio(self, valor):
        if valor < 0:
            raise serializers.ValidationError('El precio no puede ser negativo.')
        return valor


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
            principales = slot.reservas.exclude(pk=self.instance.pk).filter(sobrecupo=False).count()
            if principales < slot.capacidad:
                data['sobrecupo'] = False
            else:
                _o_rechazar(validar_sobrecupo, slot, excluir=self.instance)
                data['sobrecupo'] = True
        if 'slot' in data or 'servicio' in data:
            destino = data.get('slot') or self.instance.slot
            servicio = data['servicio'] if 'servicio' in data else self.instance.servicio
            if not data.get('sobrecupo', self.instance.sobrecupo):
                _validar_espacio(destino, servicio, excluir=self.instance)
        return data


class SlotSemanaSerializer(serializers.ModelSerializer):
    reservas = ReservaDetalleSerializer(many=True, read_only=True)
    bloqueado = serializers.SerializerMethodField()
    conflictos = serializers.SerializerMethodField()

    class Meta:
        model = SlotAgenda
        fields = ('id', 'dentista', 'fecha', 'hora', 'capacidad', 'reservas', 'bloqueado', 'conflictos')

    def get_conflictos(self, slot):
        encontrados = self.context.get('conflictos', {})
        return [{'reserva': r.id, 'motivo': encontrados[r.id]} for r in slot.reservas.all() if r.id in encontrados]

    def get_bloqueado(self, slot):
        return (slot.dentista_id, slot.fecha, slot.hora) in self.context.get('bloqueados', set())


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
