#!/usr/bin/env python
import subprocess
import sys
import os
import time
import signal
import threading

def run_django():
    """Запускает Django runserver"""
    os.system("python manage.py runserver")

def run_emulator():
    """Запускает эмулятор (Flask)"""
    # Укажите правильный путь к вашему эмулятору
    # Если эмулятор лежит в папке `emulator/`:
    # os.system("python emulator/app.py")
    # Если это отдельный файл `rk_emulator.py` в корне:
    os.system("python rk_emulator.py")

if __name__ == "__main__":
    print("🚀 Запуск Django и эмулятора РестАрт...")
    
    # Запускаем Django в отдельном потоке
    django_thread = threading.Thread(target=run_django)
    django_thread.daemon = True
    django_thread.start()
    
    # Небольшая пауза, чтобы Django успел инициализироваться
    time.sleep(2)
    
    # Запускаем эмулятор в основном потоке (он заблокирует консоль)
    run_emulator()