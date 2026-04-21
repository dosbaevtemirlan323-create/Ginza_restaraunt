# run_all.py
import subprocess
import os
import sys
import signal

os.environ.setdefault('PYTHONPATH', 'D:\\_restaraunt')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant.settings')

processes = []

def signal_handler(sig, frame):
    print("\n🛑 Остановка сервисов...")
    for p in processes:
        p.terminate()
    print("✅ Все сервисы остановлены")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

try:
    # Запуск Daphne
    p1 = subprocess.Popen(
        ['daphne', '-b', '0.0.0.0', '-p', '8000', 'restaurant.asgi:application'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    processes.append(p1)
    print("✅ Daphne запущен на порту 8000")
    
    # Запуск эмулятора
    p2 = subprocess.Popen(
        [sys.executable, 'rk_emulator.py'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    processes.append(p2)
    print("✅ Эмулятор ресторана запущен")
    
    print("\n" + "="*50)
    print("🚀 GINZA DELIVERY ЗАПУЩЕН")
    print("="*50)
    print("📡 Сайт: http://localhost:8000")
    print("📡 Панель оператора: http://localhost:8000/operator/")
    print("📡 Панель курьера: http://localhost:8000/courier/map/")
    print("="*50)
    print("Нажмите Ctrl+C для остановки\n")
    
    # Вывод логов в реальном времени
    import threading
    def print_output(proc, name):
        for line in proc.stdout:
            print(f"[{name}] {line.strip()}")
    
    for i, p in enumerate(processes):
        name = "Daphne" if i == 0 else "Emulator"
        threading.Thread(target=print_output, args=(p, name), daemon=True).start()
    
    # Ожидание завершения
    for p in processes:
        p.wait()
        
except KeyboardInterrupt:
    signal_handler(None, None)