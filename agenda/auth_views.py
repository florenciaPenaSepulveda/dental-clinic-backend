from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .permissions import IsStaff
from .throttles import LoginThrottle


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    usuario = authenticate(
        username=str(request.data.get('username', '')).strip(),
        password=str(request.data.get('password', '')),
    )
    if usuario is None or not usuario.is_staff:
        return Response({'detail': 'Usuario o contraseña incorrectos.'}, status=status.HTTP_400_BAD_REQUEST)
    token, _ = Token.objects.get_or_create(user=usuario)
    return Response({'token': token.key, 'username': usuario.get_username()})


@api_view(['POST'])
@permission_classes([IsStaff])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsStaff])
def me(request):
    return Response({'username': request.user.get_username()})
