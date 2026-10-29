# Clínica Dental · Backend

[![CI](https://github.com/florenciaPenaSepulveda/dental-clinic-backend/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/florenciaPenaSepulveda/dental-clinic-backend/actions/workflows/ci.yml)

API REST para la gestión de agenda de una clínica dental: dentistas, servicios, pacientes, horarios (slots) y reservas con control de sobrecupo y correo de confirmación.

Construida con **Django 5.2**, **Django REST Framework** y SQLite.

## Probar la demo

**API:** https://dental-clinic-backend-4eov.onrender.com/agenda/api/dentistas/ · **Interfaz:** https://dental-clinic-frontend-sjnv.onrender.com

| Rol | Usuario | Contraseña | Qué puedes probar |
|---|---|---|---|
| Recepción | `recepcion` | `Demo-h1eur-Clinica-6l8ax` | Agenda, pacientes, equipo, servicios y generación de horarios |
| Dentista | `dr.rojas` | `Demo-h1eur-Clinica-6l8ax` | Su agenda, sus pacientes y la ficha clínica de cada atención |
| Paciente | `14.000.000-0` (su RUT) | `Demo-h1eur-Clinica-6l8ax` | Reservar a su nombre y ver su historial |

Sin iniciar sesión también puedes **reservar una hora** desde "Reservar hora". Son cuentas de demostración con datos ficticios.

> **Los datos se reinician** cuando el servidor se duerme (unos 15 minutos sin uso) o se actualiza la demo, y la primera carga puede tardar hasta un minuto. Lo que crees (cuentas, reservas) no se conserva; las cuentas de arriba siempre vuelven a existir.

## Inicio rápido

```
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # Windows: copy .env.example .env
python manage.py migrate && python manage.py seed_data --demo
python manage.py runserver
```

API en `http://localhost:8000/agenda/`. Necesitas Python 3.11. Pruebas: 204 con 99 % de cobertura.

## Funcionalidades

- Catálogos de regiones, dentistas, servicios y pacientes (RUT único por paciente, validado con su dígito verificador y guardado siempre como `12.345.678-5`).
- Horarios en bloques de 30 minutos entre 08:00 y 18:00, sin duplicados por dentista, fecha y hora.
- Generación masiva de horarios por día o por rango de días.
- Reservas transaccionales: si el horario está lleno, se permite **sobrecupo** solo mientras no se superen el límite del horario ni el límite diario del dentista.
- Correo de confirmación al paciente (si tiene email); un fallo del correo nunca bloquea la reserva.
- Duración por servicio: una reserva ocupa los bloques seguidos que necesite su servicio, y cambiar una duración detecta las citas que dejarían de caber.
- Roles (recepción, dentista y paciente) con permisos por vista y sesiones con vencimiento.

## Documentación

- [API, permisos y seguridad](docs/api.md)
- [Configuración, variables de entorno y datos de ejemplo](docs/configuracion.md)
- [Despliegue de la demo en Render](docs/despliegue.md)

## Pruebas

```
pip install -r requirements-dev.txt
python -m coverage run manage.py test
python -m coverage report
```

204 pruebas con 99 % de cobertura. El flujo de integración continua (`.github/workflows/ci.yml`) exige un mínimo de 80 %.

## Estructura

```
agenda/             modelos, serializadores, vistas, viewsets, pruebas y comandos
backendClinica/     configuración del proyecto Django
```

## Repositorios del proyecto

| Repositorio | Descripción |
|---|---|
| **dental-clinic-backend** (este) | API REST de agenda y reservas |
| [dental-clinic-frontend](https://github.com/florenciaPenaSepulveda/dental-clinic-frontend) | Interfaz web para reservar y administrar la agenda |

## Autoría

Proyecto académico desarrollado en equipo; esta versión forma parte del portafolio de [Florencia Peña Sepúlveda](https://github.com/florenciaPenaSepulveda).
