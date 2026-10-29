# Despliegue de la demostración

La demo se publica como *Web Service* en el plan gratuito de Render. Los datos **se reinician**: la base es SQLite y el plan gratuito borra el disco cuando el servicio se duerme (tras unos 15 minutos sin uso) o se redespliega, y lo mismo ocurre con los archivos subidos. Es intencional: el comando de inicio vuelve a ejecutar `seed_data --demo` (idempotente) en cada arranque, así que quien pruebe la demo siempre la encuentra con datos de ejemplo ordenados. La primera visita tras un periodo de inactividad puede tardar hasta un minuto.

| Campo en Render | Valor |
|---|---|
| Runtime | Python 3 (`PYTHON_VERSION=3.11.9`) |
| Build Command | `pip install -r requirements.txt && python manage.py collectstatic --noinput` |
| Start Command | `python manage.py migrate --noinput && python manage.py seed_data --demo && gunicorn backendClinica.wsgi:application --bind 0.0.0.0:$PORT --workers 2` |
| `DJANGO_SECRET_KEY` | cadena aleatoria larga |
| `ALLOWED_HOSTS` | `<tu-backend>.onrender.com` (sin `https://`) |
| `CORS_ALLOWED_ORIGINS` | URL del frontend, sin `/` final |
| `DEMO_STAFF_PASSWORD` | (opcional) contraseña de las cuentas de demostración |

Para conservar datos entre reinicios haría falta una base externa (por ejemplo PostgreSQL) y almacenamiento para los archivos; para una demo pública se prefirió el estado limpio y no tener que mantener ninguno de los dos.
