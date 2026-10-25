from rest_framework.permissions import SAFE_METHODS, BasePermission

RECEPCION = 'recepcion'
DENTISTA = 'dentista'
PACIENTE = 'paciente'


def rol_de(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return RECEPCION
    if hasattr(user, 'dentista_perfil'):
        return DENTISTA
    if hasattr(user, 'paciente_perfil'):
        return PACIENTE
    if user.is_staff:
        return RECEPCION
    return None


def perfil_dentista(user):
    return user.dentista_perfil if rol_de(user) == DENTISTA else None


def puede_ver_reserva(user, reserva):
    rol = rol_de(user)
    if rol == RECEPCION:
        return True
    if rol == DENTISTA:
        return reserva.slot.dentista_id == user.dentista_perfil.id
    if rol == PACIENTE:
        return reserva.paciente_id == user.paciente_perfil.id
    return False


class _PorRol(BasePermission):
    roles = ()

    def has_permission(self, request, view):
        return rol_de(request.user) in self.roles


class EsRecepcion(_PorRol):
    roles = (RECEPCION,)


class EsPersonal(_PorRol):
    roles = (RECEPCION, DENTISTA)


class EsPaciente(_PorRol):
    roles = (PACIENTE,)


class EsUsuarioConRol(_PorRol):
    roles = (RECEPCION, DENTISTA, PACIENTE)


class RecepcionOLectura(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return rol_de(request.user) == RECEPCION
