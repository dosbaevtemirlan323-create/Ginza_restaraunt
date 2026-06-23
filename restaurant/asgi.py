import os
import django
from django.core.asgi import get_asgi_application

# Устанавливаем настройки
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant.settings')
# Инициализируем Django (обязательно до импорта роутов приложения!)
django.setup()

# --- Жесткое обновление домена для сброса паролей ---
try:
    from django.contrib.sites.models import Site
    Site.objects.filter(id=1).update(
        domain='ginza-baikonur.up.railway.app',
        name='Ginza Baikonur'
    )
    print("SUCCESS: Site domain updated via ASGI startup.")
except Exception as e:
    print(f"WARNING: Could not update site domain on ASGI startup: {e}")
# ----------------------------------------------------

# Теперь безопасно импортируем Channels и роуты
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import main.routing

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            main.routing.websocket_urlpatterns
        )
    ),
})
