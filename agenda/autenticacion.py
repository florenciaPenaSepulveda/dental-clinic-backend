import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


def token_vencido(token):
    return timezone.now() - token.created > datetime.timedelta(hours=settings.TOKEN_TTL_HORAS)


class TokenConExpiracion(TokenAuthentication):
    def authenticate_credentials(self, key):
        usuario, token = super().authenticate_credentials(key)
        if token_vencido(token):
            token.delete()
            raise AuthenticationFailed('La sesión expiró. Inicia sesión nuevamente.')
        return usuario, token
