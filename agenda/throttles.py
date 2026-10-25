from rest_framework.throttling import SimpleRateThrottle


class _PorIp(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginThrottle(_PorIp):
    scope = 'login'


class BuscarThrottle(_PorIp):
    scope = 'buscar'
