import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant.settings')

# Сначала полностью инициализируем WSGI-приложение Django
application = get_wsgi_application()

# --- Жесткое обновление домена для сброса паролей ---
try:
    from django.contrib.sites.models import Site
    Site.objects.filter(id=1).update(
        domain='ginza-baikonur.up.railway.app',
        name='Ginza Baikonur'
    )
    print("SUCCESS: Site domain updated via WSGI startup.")
except Exception as e:
    print(f"WARNING: Could not update site domain on WSGI startup: {e}")
