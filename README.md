# Clínica Dental · Backend

[![CI](https://github.com/florenciaPenaSepulveda/dental-clinic-backend/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/florenciaPenaSepulveda/dental-clinic-backend/actions/workflows/ci.yml)

API REST para la gestión de agenda de una clínica dental: dentistas, servicios, pacientes, horarios (slots) y reservas con control de sobrecupo y correo de confirmación.

Construida con **Django 4.2**, **Django REST Framework** y SQLite.

## Repositorios del proyecto

| Repositorio | Descripción |
|---|---|
| **dental-clinic-backend** (este) | API REST de agenda y reservas |
| [dental-clinic-frontend](https://github.com/florenciaPenaSepulveda/dental-clinic-frontend) | Interfaz web para reservar y administrar la agenda |

## Funcionalidades

- Catálogos de regiones, dentistas, servicios y pacientes (RUT único por paciente, validado con su dígito verificador y guardado siempre como `12.345.678-5`).
- Horarios en bloques de 30 minutos entre 08:00 y 18:00, sin duplicados por dentista, fecha y hora.
- Generación masiva de horarios por día o por rango de días.
- Reservas transaccionales: si el horario está lleno, se permite **sobrecupo** solo mientras no se superen el límite del horario ni el límite diario del dentista.
- Correo de confirmación al paciente (si tiene email); un fallo del correo nunca bloquea la reserva.

## Requisitos

- Python 3.11
- (Opcional) Docker

## Puesta en marcha

```
python -m venv .venv
.venv\Scripts\activate        # En Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data --demo
python manage.py runserver
```

La API queda en `http://localhost:8000/agenda/`. El panel de administración está en `/admin/` (crea un usuario con `python manage.py createsuperuser`).

`seed_data --demo` carga un conjunto completo de demostración: 3 regiones, 5 dentistas con distintas especialidades, 7 servicios con precio, 24 pacientes (con RUT válido), unos 750 horarios para los próximos 14 días hábiles y alrededor de 35 reservas, algunas de ellas sobrecupos. Se puede ejecutar varias veces sin duplicar datos. Sin `--demo`, el comando crea datos genéricos (`--dentistas`, `--servicios`, `--pacientes` y `--generate-slots N`).

Los correos de los pacientes de demostración usan `example.com`, un dominio reservado: el sistema nunca les envía confirmaciones. Para recibir una confirmación real, registra un paciente con tu propio correo.

### Con Docker

```
docker compose up --build
```

Aplica las migraciones al iniciar y guarda la base en un volumen. Disponible en `http://localhost:8000`.

## Variables de entorno

Todas son opcionales mientras `DEBUG` esté activo; sin ellas se usan valores de desarrollo. Con `DEBUG=False` (producción) `DJANGO_SECRET_KEY` es obligatoria y el servidor no arranca sin ella. Se cargan automáticamente desde un archivo `.env` en la raíz del proyecto (copia `.env.example`); ese archivo está en `.gitignore` y nunca se sube a GitHub. Con Docker, `docker compose` también lee ese mismo archivo.

| Variable | Descripción |
|---|---|
| `DJANGO_SECRET_KEY` | Clave secreta de Django (obligatoria con `DEBUG=False`) |
| `DEBUG` | `True` o `False` |
| `ALLOWED_HOSTS` | Hosts permitidos separados por coma |
| `SQLITE_PATH` | Ruta del archivo de base de datos |
| `MEDIA_ROOT` | Carpeta donde se guardan los exámenes adjuntos (por defecto `media/`) |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Cuenta de Gmail y contraseña de aplicación para enviar los correos |
| `DEFAULT_FROM_EMAIL` | Remitente de los correos |
| `DEMO_STAFF_PASSWORD` | Contraseña del usuario `recepcion` que crea `seed_data --demo` (por defecto `recepcion123`) |

Django no lee `.env` por sí solo: `settings.py` lo carga con `python-dotenv` y nunca pisa variables que ya existan en el entorno. En desarrollo basta el archivo `.env`; en producción se definen variables de entorno reales en el servidor o en la plataforma de despliegue (Render, Docker, etc.) y no se despliega ningún `.env`.

### Envío de correos

1. Activa la verificación en dos pasos en la cuenta de Gmail.
2. Crea una contraseña de aplicación en myaccount.google.com/apppasswords (16 caracteres).
3. Escribe tu correo en `EMAIL_HOST_USER` y esa contraseña en `EMAIL_HOST_PASSWORD` dentro de `.env`, y reinicia el servidor.

Sin credenciales de correo, los mensajes se imprimen en la consola del servidor. Las pruebas automáticas nunca envían correos reales.

## Endpoints principales

Prefijo `/agenda/`.

| Método y ruta | Descripción |
|---|---|
| `GET /slots/` | Horarios desde hoy en adelante |
| `GET /slots_por_fecha/?fecha=AAAA-MM-DD&dentista_id=1` | Horarios de un día, opcionalmente de un dentista |
| `POST /dentistas/{id}/generar_slots/` | Genera horarios (`fecha`, `desde`, `hasta`, `dias`) |
| `POST /reservas/` | Crea una reserva con `slot` o con `dentista`, `fecha` y `hora_inicio`, más `paciente` |
| `GET /api/pacientes/buscar/?rut=` | Devuelve solo al paciente con ese RUT (200), 404 si no existe o 400 si el RUT no es válido |
| `POST /auth/login/` | Inicia sesión (`username` o RUT, `password`) y devuelve un token con el rol (`recepcion`, `dentista` o `paciente`) |
| `POST /auth/activar-cuenta/` | Un paciente crea su cuenta con su RUT, el correo registrado en la clínica y una contraseña |
| `POST /auth/logout/`, `GET /auth/me/` | Cierra la sesión / devuelve el usuario actual (requieren token) |
| `GET /semana/?desde=AAAA-MM-DD&dentista=1` | Horarios de 7 días con el detalle de sus reservas (personal) |
| `PATCH /api/reservas/{id}/` | Cambia estado, observaciones, servicio o reprograma la reserva (personal) |
| `POST /api/reservas/{id}/archivos/`, `GET/DELETE /archivos/{id}/` | Sube, descarga o elimina exámenes adjuntos |
| `PUT /api/reservas/{id}/atencion/` | El dentista registra diagnóstico, procedimiento e indicaciones |
| `GET /api/pacientes/{id}/historial/` | Historial clínico del paciente (personal) |
| `GET /mi/historial/` | Citas próximas e historial del paciente que inició sesión |
| `/api/regiones/`, `/api/dentistas/`, `/api/servicios/`, `/api/pacientes/`, `/api/reservas/` | CRUD de cada recurso (`?region=` para dentistas; `?dentista=` y `?fecha=` para reservas) |

### Acceso y permisos

Las operaciones del público son: consultar dentistas, servicios y horarios (con la cantidad de reservas de cada horario, sin datos de pacientes), buscar un paciente por RUT, registrarse como paciente y reservar una hora, opcionalmente adjuntando exámenes. Todo lo demás exige un token en la cabecera `Authorization: Token <token>` y depende del rol:

| Rol | Cómo se define | Qué puede hacer |
|---|---|---|
| Recepción | Usuario con `is_staff` | Ver y modificar todo: pacientes, reservas, agenda de cualquier dentista y catálogo. Lee las atenciones clínicas, pero no las escribe |
| Dentista | Usuario enlazado al campo `usuario` de un dentista | Ver solo sus pacientes, sus reservas y su agenda; registrar la atención clínica de sus reservas |
| Paciente | Usuario enlazado al campo `usuario` de un paciente | Ver solo su propio historial, con el profesional que lo atendió |

Las observaciones internas de una reserva solo las ven recepción y el dentista; el paciente ve el motivo, el diagnóstico, el procedimiento y las indicaciones. Los exámenes se guardan fuera de las rutas públicas y solo se descargan con sesión, por quien tiene acceso a esa reserva. Se aceptan PDF, JPG y PNG de hasta 5 MB, máximo 5 por reserva, y se comprueba que el contenido corresponda a la extensión. El inicio de sesión se limita a 20 intentos por minuto y la búsqueda por RUT a 60 por minuto por dirección IP.

Crea una cuenta de recepción con `python manage.py createsuperuser`. Para un dentista o un paciente, crea el usuario en `/admin/` y enlázalo en el campo `usuario` de su ficha. `seed_data --demo` crea además el usuario `recepcion`, un usuario `dr.<apellido>` por dentista (por ejemplo `dr.rojas`) y cuentas para tres pacientes (usuario = su RUT), todos con la contraseña `recepcion123` o la de la variable `DEMO_STAFF_PASSWORD`; es solo para demostración. También carga atenciones pasadas para probar el historial clínico.

## Pruebas

```
pip install -r requirements-dev.txt
python -m coverage run manage.py test
python -m coverage report
```

130 pruebas con 99 % de cobertura. El flujo de integración continua (`.github/workflows/ci.yml`) exige un mínimo de 80 %.

## Estructura

```
agenda/             modelos, serializadores, vistas, viewsets, pruebas y comandos
backendClinica/     configuración del proyecto Django
tools/run_seed.py   atajo para sembrar datos de ejemplo
```

## Nota de seguridad

Los permisos de la API están abiertos (`AllowAny`) y CORS permite todos los orígenes: es una configuración pensada para desarrollo y demostración. Antes de publicarla hay que agregar autenticación y restringir los orígenes.

## Autoría

Proyecto académico desarrollado en equipo; esta versión forma parte del portafolio de [Florencia Peña Sepúlveda](https://github.com/florenciaPenaSepulveda).
