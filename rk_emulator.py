from flask import Flask, request, jsonify
import random
import datetime

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
VALID_TOKEN = "Bearer VOSHOD_SECRET_TOKEN_2026"
KKT_NAME = "АТОЛ-30Ф (Эмулятор)"

@app.route('/api/v1/new_order', methods=['POST'])
def receive_order():
    # 1. Проверка авторизации
    auth_header = request.headers.get("Authorization")
    if auth_header != VALID_TOKEN:
        print("\n[!] ОШИБКА: Попытка доступа с неверным токеном!")
        return jsonify({"error": "Unauthorized"}), 401

    # 2. Получение данных от твоего сайта (Django)
    data = request.json
    order_id = data.get('order_id')
    items = data.get('items', [])
    total = data.get('total_sum')

    # 3. Визуализация в консоли (то, что ты покажешь комиссии)
    print("\n" + "="*50)
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ПОЛУЧЕН ЗАКАЗ №{order_id}")
    print(f"СУММА: {total} руб.")
    print("-" * 50)
    for item in items:
        print(f" > {item['name']} | {item['qty']} шт. | {item['price']} руб.")
    print("="*50)

    # 4. Эмуляция работы фискального накопителя
    # Генерируем случайные ФД и ФП
    fiscal_response = {
        "status": "success",
        "order_id": order_id,
        "fiscal_data": {
            "fd": str(random.randint(1000, 9999)),
            "fp": str(random.randint(100000000, 999999999)),
            "fn": "999944030001122",
            "kkt": KKT_NAME
        }
    }
    
    print(f"[OK] Фискальные данные сформированы. ФД: {fiscal_response['fiscal_data']['fd']}")
    return jsonify(fiscal_response), 200

if __name__ == '__main__':
    print(f"=== СЕРВЕР АВТОМАТИЗАЦИИ РЕСТОРАНА (ЗДАНИЕ Г) ЗАПУЩЕН ===")
    print("Адрес: http://127.0.0.1:5000/api/v1/new_order")
    app.run(port=5000, debug=False)