import os
import django
from django.core.management import call_command

# Указываем путь к настройкам
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant.settings')
django.setup()

# Сохраняем данные в правильном UTF-8
with open('data.json', 'w', encoding='utf-8') as f:
    call_command(
        'dumpdata', 
        exclude=['auth.permission', 'contenttypes', 'sessions', 'admin.logentry'], 
        indent=4, 
        stdout=f
    )
print("Готово! Файл data.json создан в правильной кодировке.")