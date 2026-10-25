import os
import sys

if __name__ == '__main__':
    # usage: python tools/run_seed.py [days]
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    # ensure DJANGO_SETTINGS_MODULE points to the project settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backendClinica.settings')

    import django
    django.setup()

    from django.core.management import call_command

    # Call the seed_data command programmatically
    print(f'Running seed_data with --generate-slots {days} ...')
    call_command('seed_data', '--generate-slots', str(days))
    print('Done')
