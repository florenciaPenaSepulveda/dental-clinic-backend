import os
import sys

if __name__ == '__main__':
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backendClinica.settings')

    import django
    django.setup()

    from django.core.management import call_command

    print(f'Running seed_data with --generate-slots {days} ...')
    call_command('seed_data', '--generate-slots', str(days))
    print('Done')
