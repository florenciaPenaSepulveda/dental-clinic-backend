import re
import secrets
import unicodedata

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token


def _sin_tildes(texto):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode().lower())


def usuario_de_dentista(dentista):
    return f"dr.{_sin_tildes(dentista.apellido) or 'dentista'}"


def _usuario_libre(base):
    User = get_user_model()
    username, numero = base, 2
    while User.objects.filter(username=username).exists():
        username, numero = f"{base}{numero}", numero + 1
    return username


def crear_o_reiniciar_cuenta(perfil, username_base):
    clave = secrets.token_urlsafe(9)
    creada = perfil.usuario_id is None
    if creada:
        perfil.usuario = get_user_model().objects.create_user(username=_usuario_libre(username_base), password=clave)
        perfil.save(update_fields=['usuario'])
    else:
        perfil.usuario.set_password(clave)
        perfil.usuario.save(update_fields=['password'])
        Token.objects.filter(user=perfil.usuario).delete()
    return {'username': perfil.usuario.get_username(), 'password': clave, 'creada': creada}
