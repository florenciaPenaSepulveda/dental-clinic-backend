# Configuración y puesta en marcha

## Requisitos

- Python 3.11
- (Opcional) Docker

## Puesta en marcha

```
python -m venv .venv
.venv\Scripts\activate        # En Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # En Linux/macOS: cp .env.example .env
python manage.py migrate
python manage.py seed_data --demo
python manage.py runserver
```

La API queda en `http://localhost:8000/agenda/`. El panel de administración está en `/admin/` (crea un usuario con `python manage.py createsuperuser`).

`seed_data --demo` carga un conjunto completo de demostración: 3 regiones, 5 dentistas con distintas especialidades, 7 servicios con precio, 24 pacientes (con RUT válido), unos 650 horarios para los próximos 14 días hábiles y alrededor de 35 reservas, algunas de ellas sobrecupos. Se puede ejecutar varias veces sin duplicar datos. Sin `--demo`, el comando crea datos genéricos (`--dentistas`, `--servicios`, `--pacientes` y `--generate-slots N`).

Los correos de los pacientes de demostración usan `example.com`, un dominio reservado: el sistema nunca les envía confirmaciones. Para recibir una confirmación real, registra un paciente con tu propio correo.

### Con Docker

```
docker compose up --build
```

Aplica las migraciones al iniciar y guarda la base en un volumen. Disponible en `http://localhost:8000`.

## Variables de entorno

Por seguridad, `DEBUG` está apagado por defecto: sin él, `DJANGO_SECRET_KEY` y `ALLOWED_HOSTS` son obligatorias y el servidor no arranca sin ellas. Para trabajar en local copia `.env.example` a `.env`, que activa `DEBUG=True` y valores de desarrollo. Se cargan automáticamente desde un archivo `.env` en la raíz del proyecto (copia `.env.example`); ese archivo está en `.gitignore` y nunca se sube a GitHub. Con Docker, `docker compose` también lee ese mismo archivo.

| Variable | Descripción |
|---|---|
| `DJANGO_SECRET_KEY` | Clave secreta de Django (obligatoria con `DEBUG=False`) |
| `DEBUG` | `True` solo en desarrollo; por defecto `False` |
| `ALLOWED_HOSTS` | Hosts permitidos separados por coma (obligatoria con `DEBUG=False`) |
| `CORS_ALLOWED_ORIGINS` | Orígenes del frontend autorizados, separados por coma (por defecto `http://localhost:5173`) |
| `TOKEN_TTL_HORAS` | Horas de vigencia de una sesión antes de pedir el ingreso otra vez (por defecto 12) |
| `SECURE_SSL_REDIRECT` | Con `DEBUG=False` redirige a HTTPS (por defecto `True`; desactívala solo si un proxy ya lo hace) |
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
