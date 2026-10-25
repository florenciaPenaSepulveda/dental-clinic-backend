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


def es_correo_de_ejemplo(email):
    dominio = email.rsplit('@', 1)[-1].lower()
    return dominio in DOMINIOS_RESERVADOS or dominio.endswith(SUFIJOS_RESERVADOS)
