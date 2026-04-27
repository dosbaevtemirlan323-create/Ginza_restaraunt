import requests
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

def send_order_to_restaurant(order):
    """
    Функция отправки заказа в здание Г (Эмулятор РестАрт/R-Keeper)
    """
    # Адрес твоего запущенного эмулятора
    url = "http://127.0.0.1:5000/api/v1/new_order"
    
    # Секретный ключ для авторизации
    headers = {
        "Authorization": "Bearer VOSHOD_SECRET_TOKEN_2026",
        "Content-Type": "application/json"
    }

    # Формируем данные заказа для ресторана
    payload = {
        "order_id": order.id,
        "customer_name": order.user.username,
        "total_sum": float(order.total_price),
        "items": [
            {
                "name": item.product.name,
                "qty": item.quantity,
                "price": float(item.price)
            } for item in order.items.all()
        ]
    }

    try:
        # Шлем запрос в эмулятор
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            # ЗАПИСЫВАЕМ ДАННЫЕ ИЗ ЭМУЛЯТОРА В ТВОЮ БД
            order.fiscal_fd = data['fiscal_data']['fd']
            order.fiscal_fp = data['fiscal_data']['fp']
            order.fiscal_fn = data['fiscal_data']['fn']
            order.fiscal_kkt = data['fiscal_data']['kkt']
            order.is_paid = True # Ставим отметку об оплате
            order.save()
            return True
        else:
            print(f"Ошибка эмулятора: {response.status_code}")
            return False
    except Exception as e:
        print(f"Не удалось связаться со зданием Г: {e}")
        return False
    

def send_receipt_email(order):
    """
    Отправка электронного чека на почту пользователя
    """
    subject = f'Электронный чек по заказу №{order.id} — GINZA'
    
    # Используем новый шаблон чека
    html_message = render_to_string('main/receipt_email.html', {'order': order})
    
    # Создаем PDF версию для вложения (опционально)
    try:
        from io import BytesIO
        from xhtml2pdf import pisa
        
        # Создаем PDF из HTML
        html_content = render_to_string('main/receipt_print.html', {'order': order})
        pdf_file = BytesIO()
        pisa.CreatePDF(html_content, dest=pdf_file)
        pdf_file.seek(0)
        
        email = EmailMessage(
            subject,
            html_message,
            'no-reply@ginza-rest.ru',
            [order.user.email]
        )
        email.content_subtype = "html"
        email.attach(f'cheque_{order.id}.pdf', pdf_file.read(), 'application/pdf')
        email.send()
    except Exception as e:
        # Если нет xhtml2pdf, отправляем просто HTML
        send_mail(
            subject,
            'Ваш электронный чек во вложении',
            'no-reply@ginza-rest.ru',
            [order.user.email],
            html_message=html_message,
            fail_silently=True,
        )

def geocode_address(address):
    api_key = "2b6a7d3b-b4ef-4682-a0e0-69dda3376fba"  # ваш ключ Яндекс.Карт
    url = "https://geocode-maps.yandex.ru/1.x/"
    params = {"apikey": api_key, "geocode": address, "format": "json", "results": 1}
    try:
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        found = data["response"]["GeoObjectCollection"]["featureMember"]
        if found:
            coords = found[0]["GeoObject"]["Point"]["pos"].split()
            lng, lat = float(coords[0]), float(coords[1])
            return True, lat, lng
        return False, None, None
    except Exception as e:
        print(f"Geocoding error: {e}")
        return False, None, None