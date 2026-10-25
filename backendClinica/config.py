from django.core.exceptions import ImproperlyConfigured

DEV_SECRET_KEY = 'dev-only-insecure-key-change-me'


def env_bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_list(value, default=''):
    raw = default if value is None else value
    return [item.strip() for item in raw.split(',') if item.strip()]


def resolve_secret_key(debug, environ):
    key = environ.get('DJANGO_SECRET_KEY', '').strip()
    if key:
        return key
    if debug:
        return DEV_SECRET_KEY
    raise ImproperlyConfigured('DJANGO_SECRET_KEY es obligatoria cuando DEBUG está desactivado.')
