import re

PATRON_RUT = re.compile(r'^\s*([1-9]\d?(?:\.?\d{3}){2})\s*-?\s*([\dkK])\s*$')
RUT_MINIMO = 1_000_000

DOMINIOS_RESERVADOS = ("example.com", "example.org", "example.net")
SUFIJOS_RESERVADOS = (".test", ".invalid", ".localhost", ".example")


def rut_con_dv(cuerpo):
    suma = 0
    multiplicador = 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    resto = 11 - (suma % 11)
    dv = '0' if resto == 11 else 'K' if resto == 10 else str(resto)
    texto = f"{cuerpo:,}".replace(',', '.')
    return f"{texto}-{dv}"


def normalizar_rut(valor):
    coincidencia = PATRON_RUT.match(valor or '')
    if not coincidencia:
        return None
    cuerpo = int(coincidencia.group(1).replace('.', ''))
    if cuerpo < RUT_MINIMO:
        return None
    normalizado = rut_con_dv(cuerpo)
    if normalizado[-1] != coincidencia.group(2).upper():
        return None
    return normalizado


def es_correo_de_ejemplo(email):
    dominio = email.rsplit('@', 1)[-1].lower()
    return dominio in DOMINIOS_RESERVADOS or dominio.endswith(SUFIJOS_RESERVADOS)
