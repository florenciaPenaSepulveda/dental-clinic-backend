from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from backendClinica.config import DEV_SECRET_KEY, env_bool, env_list, resolve_secret_key


class EnvBoolTests(SimpleTestCase):
    def test_valores_verdaderos(self):
        for value in ('1', 'true', 'True', ' YES ', 'on'):
            self.assertTrue(env_bool(value))

    def test_valores_falsos(self):
        for value in ('0', 'false', 'no', ''):
            self.assertFalse(env_bool(value, default=True))

    def test_usa_valor_por_defecto_si_no_existe(self):
        self.assertTrue(env_bool(None, default=True))
        self.assertFalse(env_bool(None))


class EnvListTests(SimpleTestCase):
    def test_separa_y_limpia(self):
        self.assertEqual(env_list(' a.com, b.com ,,'), ['a.com', 'b.com'])

    def test_usa_valor_por_defecto(self):
        self.assertEqual(env_list(None, default='*'), ['*'])


class SecretKeyTests(SimpleTestCase):
    def test_usa_la_clave_del_entorno(self):
        self.assertEqual(resolve_secret_key(False, {'DJANGO_SECRET_KEY': 'abc'}), 'abc')

    def test_clave_de_desarrollo_solo_con_debug(self):
        self.assertEqual(resolve_secret_key(True, {}), DEV_SECRET_KEY)

    def test_exige_clave_en_produccion(self):
        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_key(False, {})
        with self.assertRaises(ImproperlyConfigured):
            resolve_secret_key(False, {'DJANGO_SECRET_KEY': '  '})
