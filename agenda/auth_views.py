from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Paciente
from .permissions import DENTISTA, PACIENTE, EsUsuarioConRol, rol_de
from .throttles import LoginThrottle
from .utils import normalizar_rut


def datos_de_sesion(usuario):
    rol = rol_de(usuario)
    datos = {'username': usuario.get_username(), 'rol': rol, 'nombre': usuario.get_username()}
    if rol == DENTISTA:
        perfil = usuario.dentista_perfil
        datos.update(dentista_id=perfil.id, nombre=f"{perfil.nombre} {perfil.apellido}")
    elif rol == PACIENTE:
        perfil = usuario.paciente_perfil
        datos.update(paciente_id=perfil.id, nombre=f"{perfil.nombre} {perfil.apellido}")
    return datos


def respuesta_de_sesion(usuario):
    token, _ = Token.objects.get_or_create(user=usuario)
    return Response({**datos_de_sesion(usuario), 'token': token.key})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    username = str(request.data.get('username', '')).strip()
    usuario = authenticate(username=normalizar_rut(username) or username, password=str(request.data.get('password', '')))
    if usuario is None or rol_de(usuario) is None:
        return Response({'detail': 'Usuario o contraseña incorrectos.'}, status=status.HTTP_400_BAD_REQUEST)
    return respuesta_de_sesion(usuario)


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def activar_cuenta(request):
    error = Response(
        {'detail': 'No pudimos verificar tus datos o la cuenta ya está activada.'}, status=status.HTTP_400_BAD_REQUEST
    )
    rut = normalizar_rut(str(request.data.get('rut', '')))
    correo = str(request.data.get('email', '')).strip().lower()
    clave = str(request.data.get('password', ''))
    paciente = Paciente.objects.filter(rut=rut).first() if rut else None
    if paciente is None or paciente.usuario_id or not paciente.email or paciente.email.lower() != correo:
        return error
    try:
        validate_password(clave)
    except ValidationError as exc:
        return Response({'password': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    usuario = get_user_model().objects.create_user(username=paciente.rut, password=clave)
    paciente.usuario = usuario
    paciente.save(update_fields=['usuario'])
    return respuesta_de_sesion(usuario)


@api_view(['POST'])
@permission_classes([EsUsuarioConRol])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([EsUsuarioConRol])
def me(request):
    return Response(datos_de_sesion(request.user))
