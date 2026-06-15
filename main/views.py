from .utils import send_order_to_restaurant, send_receipt_email, geocode_address
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.db.models import Prefetch, Sum, F, Q, Count
from django.contrib import messages
from decimal import Decimal
from django.utils import timezone
from .cart import Cart
from .models import Category, OrderItem, Product, Order, Profile, Favorite, Address, Review, RestaurantConfig, OrderMessage, OrderStatusHistory, Discount, Tag
from .forms import UserRegisterForm
import uuid
import requests
from yookassa import Configuration, Payment
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
import string
import random
from django.contrib.auth.models import User
from django.db.models import Count, Max, Q
from datetime import datetime, timedelta          # НОВОЕ: добавили timedelta
from django.contrib.auth.hashers import make_password
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from django.db.models import Avg, F, ExpressionWrapper, fields, Count, Q, DurationField, Sum
from django.db.models.functions import Extract, TruncDate
from geopy.distance import geodesic      
from django.utils.timezone import now
from collections import defaultdict   
from datetime import datetime
import requests
from django.conf import settings

BAIKONUR_LAT_MIN = 45.58
BAIKONUR_LAT_MAX = 45.66
BAIKONUR_LNG_MIN = 63.27
BAIKONUR_LNG_MAX = 63.35

# ========== ЖЁСТКИЕ ПРАВИЛА РЕКОМЕНДАЦИЙ ==========
# Правила по ID (основные блюда → рекомендуемые ID)
HARD_RULES_BY_ID = {
    # Шашлыки
    26: [84, 85, 86, 81, 45, 88, 89],
    27: [84, 85, 86, 81, 45, 88, 89],
    28: [84, 85, 86, 81, 45, 88, 89],
    29: [84, 85, 86, 81, 45, 88, 89],
    # Пицца
    30: [84, 85, 86, 82, 83, 45],
    31: [84, 85, 86, 82, 83, 45],
    32: [84, 85, 86, 82, 83, 45],
    33: [84, 85, 86, 82, 83, 45],
    34: [84, 85, 86, 82, 83, 45],
    35: [84, 85, 86, 82, 83, 45],
    # Паста
    22: [84, 85, 86, 88, 89, 82],
    23: [84, 85, 86, 88, 89, 83],
    24: [84, 85, 86, 88, 89, 82],
    25: [84, 85, 86, 88, 89, 83],
    # Вторые блюда
    63: [84, 85, 86, 44, 45, 82, 83],
    64: [84, 85, 86, 44, 45, 82, 83],
    65: [84, 85, 86, 44, 45, 82, 83],
    66: [84, 85, 86, 44, 45, 82, 83],
    67: [84, 85, 86, 44, 45, 82, 83],
    70: [84, 85, 86, 44, 45, 82, 83],
    # Фастфуд
    36: [81, 84, 85, 86, 82, 83],
    39: [81, 84, 85, 86, 82, 83],
    42: [81, 84, 85, 86, 82, 83],
    # Салаты
    1: [84, 85, 86, 88, 89],
    2: [84, 85, 86, 88, 89],
    3: [84, 85, 86, 88, 89],
    4: [84, 85, 86, 88, 89],
    5: [84, 85, 86, 88, 89],
}

# Правила по названию (дополнительно, если ID не сработает)
HARD_RULES_BY_NAME = {
    'шашлык': ['соус белый', 'соус красный', 'соус сырный', 'картофель фри', 'картофель по-деревенски', 'черный хлеб', 'белый хлеб'],
    'пицца': ['соус белый', 'соус красный', 'соус сырный', 'кола', 'сок в ассортименте', 'картофель фри'],
    'паста': ['соус белый', 'соус красный', 'соус сырный', 'черный хлеб', 'белый хлеб', 'кола'],
    'бургер': ['картофель фри', 'соус белый', 'соус красный', 'кола'],
    'донер': ['картофель фри', 'соус белый', 'соус красный', 'кола'],
}

# ========== УМНЫЕ РЕКОМЕНДАЦИИ (анализ состава корзины) ==========
RECOMMENDATION_TYPES = {
    'sauces': ['соус белый', 'соус красный', 'соус сырный'],
    'fries': ['картофель фри', 'картофель по-деревенски'],
    'bread': ['черный хлеб', 'белый хлеб'],
    'drinks': ['кола', 'сок в ассортименте'],
    'rice': ['рис припущенный'],
}

def get_smart_recommendations(cart_products):
    """
    Умные рекомендации на основе состава корзины.
    Возвращает список до 4 товаров, которых не хватает.
    """
    if not cart_products:
        return []

    # 1. Категории блюд, которые есть в корзине
    cart_category_ids = set(p.category_id for p in cart_products if p.category)

    # 2. Чего уже достаточно (есть в корзине)
    has_sauces = any(p.category_id == 10 for p in cart_products)        # соусы
    has_bread = any(p.category_id == 11 for p in cart_products)         # хлеб
    has_fries = any(p.category_id == 8 for p in cart_products)          # гарниры
    has_drinks = any(p.category_id == 9 for p in cart_products)         # напитки

    # 3. Какие типы блюд присутствуют (по названиям категорий)
    category_names = {p.category.name.lower() for p in cart_products if p.category}
    has_meat = any(c in category_names for c in ['шашлыки', 'вторые блюда'])
    has_pizza = 'пицца' in category_names
    has_pasta = 'паста' in category_names
    has_fastfood = 'фастфуд' in category_names
    has_salad = 'салаты' in category_names

    # 4. Определяем, чего не хватает
    need_sauces = (has_meat or has_pizza or has_pasta or has_fastfood) and not has_sauces
    need_bread = (has_meat or has_pasta or has_salad) and not has_bread
    need_fries = (has_meat or has_pizza or has_fastfood) and not has_fries
    need_drinks = (has_pizza or has_fastfood) and not has_drinks

    # 5. Сопоставляем недостающие типы с реальными товарами
    recommendations = []

    # Приоритет: соусы, хлеб, гарниры, напитки
    if need_sauces:
        sauce = Product.objects.filter(category_id=10, is_active=True).first()
        if sauce:
            recommendations.append(sauce)
    if need_bread and len(recommendations) < 4:
        bread = Product.objects.filter(category_id=11, is_active=True).first()
        if bread:
            recommendations.append(bread)
    if need_fries and len(recommendations) < 4:
        fry = Product.objects.filter(category_id=8, is_active=True).first()
        if fry:
            recommendations.append(fry)
    if need_drinks and len(recommendations) < 4:
        drink = Product.objects.filter(category_id=9, is_active=True).first()
        if drink:
            recommendations.append(drink)

    # Если всё равно не набрали 4 (например, нет товаров в категориях) – добираем популярными
    if len(recommendations) < 4:
        cart_ids = [p.id for p in cart_products]
        existing_ids = [p.id for p in recommendations]
        extra = Product.objects.filter(is_active=True) \
            .exclude(id__in=cart_ids) \
            .exclude(id__in=existing_ids) \
            .annotate(total_sold=Sum('orderitem__quantity')) \
            .order_by('-total_sold')[:4 - len(recommendations)]
        recommendations.extend(extra)

    return recommendations

def get_hardcoded_recommendations(cart_products):
    if not cart_products:
        return Product.objects.none()

    recommended_ids = set()
    cart_ids = [p.id for p in cart_products]
    names = [p.name.lower() for p in cart_products]

    # 1. По ID
    for base_id, recs in HARD_RULES_BY_ID.items():
        if base_id in cart_ids:
            recommended_ids.update(recs)

    # 2. По названию (если ID-правила не сработали)
    if not recommended_ids:
        for base_name, rec_names in HARD_RULES_BY_NAME.items():
            if any(base_name in n for n in names):
                for rec_name in rec_names:
                    prod = Product.objects.filter(name__icontains=rec_name, is_active=True).first()
                    if prod:
                        recommended_ids.add(prod.id)

    # Убираем уже имеющиеся в корзине
    recommended_ids -= set(cart_ids)

    if not recommended_ids:
        return Product.objects.none()

    # Получаем продукты
    products = Product.objects.filter(id__in=recommended_ids, is_active=True)

    # Приоритет: сначала соусы (кат.10), хлеб (11), гарниры (8), напитки (9), потом всё остальное
    priority = {10: 1, 11: 2, 8: 3, 9: 4}
    product_list = sorted(products, key=lambda p: priority.get(p.category_id, 5))
    
    return product_list   # возвращаем список, а не QuerySet

Configuration.configure('1285119', 'test_yOeCjmKe1rtmfgAat4OUl_9V89XI0Z4gIqR3HZXr7wg')


def get_cross_sell_products(cart_products, user=None, limit=4):
    # 1. Умные рекомендации (анализ состава)
    smart = get_smart_recommendations(cart_products)
    if smart:
        return smart[:limit]

    # 2. Запасной вариант – популярные товары (если корзина пуста или не нашлось умных)
    if not cart_products:
        return []
    cart_ids = [p.id for p in cart_products]
    popular = Product.objects.filter(is_active=True) \
        .exclude(id__in=cart_ids) \
        .annotate(total_sold=Sum('orderitem__quantity')) \
        .order_by('-total_sold')[:limit]
    return list(popular)


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def geocode_address(address):
    """Геокодирование через Яндекс. Вернёт (success, lat, lng) с проверкой точности."""
    api_key = "2b6a7d3b-b4ef-4682-a0e0-69dda3376fba"
    url = "https://geocode-maps.yandex.ru/1.x/"
    params = {"apikey": api_key, "geocode": address, "format": "json", "results": 1}
    try:
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        feature_member = data["response"]["GeoObjectCollection"]["featureMember"]
        
        if feature_member:
            geo_object = feature_member[0]["GeoObject"]
            
            # Проверяем точность геокодирования
            # Нам нужно убедиться, что пользователь ввёл конкретный дом или хотя бы улицу,
            # а не просто Яндекс вернул координаты центра города из-за мусора в адресе.
            meta_data = geo_object["metaDataProperty"]["GeocoderMetaData"]
            precision = meta_data.get("precision")  # exact, number, near, range, street, etc.
            kind = meta_data.get("kind")            # house, street, locality...
            
            # Если Яндекс распознал адрес только до уровня города/страны (мусорный ввод)
            if kind in ['locality', 'province', 'country'] or precision == 'other':
                return False, None, None
            
            # Извлекаем координаты
            coords = geo_object["Point"]["pos"].split()
            lng, lat = float(coords[0]), float(coords[1])
            
            # Проверка, что координаты внутри Байконура
            if (BAIKONUR_LAT_MIN <= lat <= BAIKONUR_LAT_MAX and
                BAIKONUR_LNG_MIN <= lng <= BAIKONUR_LNG_MAX):
                return True, lat, lng
            else:
                return False, None, None
                
        return False, None, None
    except Exception as e:
        print(f"Geocoding error: {e}")
        return False, None, None


# --- ГЛАВНАЯ И МЕНЮ ---
def start(request):
    cart = Cart(request)
    popular_dishes = Product.objects.filter(is_active=True).annotate(
        total_sold=Sum('orderitem__quantity')
    ).order_by('-total_sold')[:10]
    cart_products = [item['product'] for item in cart]
    cross_sell_products = get_cross_sell_products(cart_products, limit=4)

    if popular_dishes.count() < 10:
        existing_ids = list(popular_dishes.values_list('id', flat=True))
        additional = Product.objects.filter(is_active=True).exclude(id__in=existing_ids).order_by('?')[:10 - popular_dishes.count()]
        popular_dishes = list(popular_dishes) + list(additional)
    
    context = {
        'cart': cart,
        'cross_sell_products': cross_sell_products,
        'popular_dishes': popular_dishes,
    }
    return render(request, 'main/index.html', context)


def menu_view(request):
    cart = Cart(request)
    
    if request.user.is_staff:
        products_filter = Product.objects.all()
    else:
        products_filter = Product.objects.filter(is_active=True)

    products_filter = products_filter.annotate(
        total_sold=Sum('orderitem__quantity')
    )
    
    categories = Category.objects.prefetch_related(
        Prefetch('products', queryset=products_filter.prefetch_related('reviews'))
    ).all()

    user_favorites = []
    if request.user.is_authenticated:
        user_favorites = Favorite.objects.filter(user=request.user).values_list('product_id', flat=True)
        recommended_for_menu = get_ai_recommendations(request.user, limit=8)
    else:
        user_favorites = []
        recommended_for_menu = get_ai_recommendations(None, limit=8)   # вызываем с None


    context = {
        'categories': categories,
        'cart': cart,
        'user_favorites': user_favorites,
        'recommended_for_menu': recommended_for_menu,
        'all_products': Product.objects.all(),
        'all_tags': Tag.objects.all(),
    }
    return render(request, 'main/menu.html', context)


# --- ИЗБРАННОЕ ---
@login_required
def toggle_favorite(request, product_id):
    if request.user.is_staff or request.user.is_superuser:
        return JsonResponse({'status': 'error', 'message': 'Только для клиентов'}, status=403)
    product = get_object_or_404(Product, id=product_id)
    favorite, created = Favorite.objects.get_or_create(user=request.user, product=product)
    is_favorite = created
    if not created:
        favorite.delete()
    return JsonResponse({'status': 'ok', 'is_favorite': is_favorite})


@login_required
def favorites_list(request):
    cart = Cart(request)
    favorites = Favorite.objects.filter(user=request.user).select_related('product')
    return render(request, 'main/favorites.html', {'favorites': favorites, 'cart': cart})


# --- КОРЗИНА ---

def cart_detail(request):
    cart = Cart(request)
    cart_products = [item['product'] for item in cart]
    cross_sell_products = get_cross_sell_products(cart_products, limit=4)

    user_orders_count = 0
    personal_discount = 0
    if request.user.is_authenticated:
        user_orders_count = Order.objects.filter(user=request.user, status='completed').count()
        total_spent = Order.objects.filter(user=request.user, status='completed').aggregate(Sum('total_price'))['total_price__sum'] or 0
        if total_spent >= 15000:
            personal_discount = 5
        elif total_spent >= 5000:
            personal_discount = 3

    # Акционные скидки (модель Discount)
    from django.utils import timezone
    now = timezone.now()
    active_discounts = Discount.objects.filter(
        active=True,
        applies_to='all',
        start_date__lte=now,
        end_date__gte=now
    )
    campaign_discount_percent = 0
    if active_discounts.exists():
        disc = active_discounts.first()
        if disc.discount_type == 'percent':
            campaign_discount_percent = disc.value

    final_discount = max(personal_discount, campaign_discount_percent)
    total_cart_price = cart.get_total_price()
    discount_amount = total_cart_price * final_discount / 100
    final_total = total_cart_price - discount_amount

    now_local = timezone.localtime(timezone.now())

    return render(request, 'main/cart_detail.html', {
        'cart': cart,
        'cross_sell_products': cross_sell_products,
        'is_new_user': not request.user.is_authenticated or user_orders_count < 4,
        'orders_count': user_orders_count,
        'now': now_local,
        'personal_discount': personal_discount,
        'campaign_discount': campaign_discount_percent,
        'final_discount': final_discount,
        'discount_amount': discount_amount,
        'final_total': final_total,
    })

def cart_add(request, product_id):
    if not request.user.is_authenticated:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'Пожалуйста, войдите в аккаунт'}, status=401)
        return redirect('login')
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.add(product=product)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'ok',
            'item_quantity': cart.cart[str(product_id)]['quantity'],
            'item_total_price': float(cart.cart[str(product_id)]['quantity']) * float(product.price),
            'total_price': float(cart.get_total_price()),
            'cart_total_quantity': len(cart),
            'product_name': product.name,
            'product_price': float(product.price)
        })
    return redirect('cart_detail')

def cart_subtract(request, product_id):
    cart = Cart(request)
    cart.subtract(product_id)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        quantity = cart.cart.get(str(product_id), {}).get('quantity', 0)
        product = Product.objects.get(id=product_id)
        return JsonResponse({
            'status': 'ok',
            'item_quantity': quantity,
            'item_total_price': float(quantity) * float(product.price),
            'total_price': float(cart.get_total_price()),
            'cart_total_quantity': len(cart),
            'product_name': product.name,
            'product_price': float(product.price)
        })
    return redirect('cart_detail')


@login_required
def update_item_comment(request, product_id):
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        cart = Cart(request)
        comment = request.POST.get('comment', '')
        cart.update_comment(product_id, comment)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def remove_from_cart(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'removed',
            'cart_total_quantity': len(cart),
            'total_price': float(cart.get_total_price()),
            'item_quantity': 0,
            'item_total_price': 0
        })
    return redirect('cart_detail')


# --- ЗАКАЗЫ (НОВАЯ ЛОГИКА С СОХРАНЕНИЕМ В СЕССИИ) ---
@login_required
def order_create(request):
    cart = Cart(request)
    if not cart or len(cart) == 0:
        return redirect('menu')
    
    if request.method == 'POST':
        # --- Получаем данные из формы ---
        address_id = request.POST.get('address_id')
        new_address = request.POST.get('new_address')
        phone = request.POST.get('phone')
        payment_method = request.POST.get('payment_method')
        use_points = request.POST.get('use_points') == 'on'
        
        # --- Скидка из скрытых полей ---
        discount_percent = Decimal(request.POST.get('applied_discount_percent', 0))
        discount_amount = Decimal(request.POST.get('discount_amount', 0))
        
        # --- Желаемое время доставки ---
        delivery_time_from_str = request.POST.get('delivery_time_from')
        delivery_time_to_str = request.POST.get('delivery_time_to')
        delivery_time_from = None
        delivery_time_to = None

        if delivery_time_from_str:
            try:
                delivery_time_from = datetime.fromisoformat(delivery_time_from_str)
                delivery_time_from = timezone.make_aware(delivery_time_from)
                if delivery_time_from < timezone.now() + timedelta(minutes=30):
                    messages.error(request, "Начало интервала – не ранее чем через 30 минут")
                    return redirect('cart_detail')
            except ValueError:
                pass

        if delivery_time_to_str:
            try:
                delivery_time_to = datetime.fromisoformat(delivery_time_to_str)
                delivery_time_to = timezone.make_aware(delivery_time_to)
                if delivery_time_to < delivery_time_from:
                    messages.error(request, "Конец интервала не может быть раньше начала")
                    return redirect('cart_detail')
            except ValueError:
                pass
        
        # --- Один адрес ---
        # --- Получение адреса ---
        final_address = None
        lat = lng = None

        if new_address and new_address.strip():
            final_address = new_address.strip()
            if not final_address.lower().startswith('байконур'):
                final_address = "Байконур, " + final_address
            is_valid, lat, lng = geocode_address(final_address)
            if not is_valid:
                messages.error(request, "Адрес не найден в г. Байконур. Проверьте правильность улицы и номера дома.")
                return redirect('cart_detail')
        elif address_id:
            addr_obj = get_object_or_404(Address, id=address_id, user=request.user)
            final_address = addr_obj.address_line
            # ВАЖНО: даже для сохранённого адреса проверяем его сейчас!
            is_valid, lat, lng = geocode_address(final_address)
            if not is_valid:
                messages.error(request, f"Адрес «{final_address}» не найден в г. Байконур. Пожалуйста, удалите его из профиля и введите корректный.")
                return redirect('cart_detail')
        else:
            messages.error(request, "Пожалуйста, выберите или введите адрес доставки")
            return redirect('cart_detail')
        
        # --- Расчёт итоговой цены с учётом скидки ---
        total_cart_price = cart.get_total_price()
        price_after_discount = total_cart_price * (100 - discount_percent) / 100
        
        # --- Баллы ---
        profile, _ = Profile.objects.get_or_create(user=request.user)
        total_points_to_spend = Decimal('0')
        if use_points and profile.points > 0:
            max_by_price = (price_after_discount * Decimal('0.30')).quantize(Decimal('1'))
            max_by_points = (Decimal(profile.points) * Decimal('0.30')).quantize(Decimal('1'))
            max_deductible = min(max_by_price, max_by_points)
            total_points_to_spend = min(Decimal(profile.points), max_deductible)
        
        final_price = price_after_discount - total_points_to_spend
        
        # --- Геокодирование, если координат нет ---
        if lat is None or lng is None:
            is_valid, lat, lng = geocode_address(final_address)
            if not is_valid:
                messages.error(request, "Не удалось определить координаты адреса. Попробуйте выбрать другой адрес.")
                return redirect('cart_detail')
        
        # --- ОПЛАТА НАЛИЧНЫМИ ---
        if payment_method == 'cash':
            try:
                order = Order.objects.create(
                    user=request.user,
                    address=final_address,
                    phone=phone,
                    payment_method='cash',
                    total_price=final_price,
                    points_used=int(total_points_to_spend),
                    status='new',
                    is_paid=False,
                    delivery_time_from=delivery_time_from,
                    delivery_time_to=delivery_time_to,
                    lat=lat,
                    lng=lng,
                )
                OrderStatusHistory.objects.create(
                    order=order,
                    old_status='',
                    new_status='new',
                    changed_by=request.user
                )
                for item in cart:
                    OrderItem.objects.create(
                        order=order,
                        product=item['product'],
                        price=item['price'],
                        quantity=item['quantity'],
                        comment=item.get('comment', '')
                    )
                
                # Списываем баллы
                if total_points_to_spend > 0:
                    profile.points -= int(total_points_to_spend)
                    profile.save()
                # Начисляем кэшбэк
                earned = int(final_price * Decimal('0.05'))
                profile.points += earned
                profile.save()
                
                cart.clear()
                # Отправка в ресторан
                try:
                    send_order_to_restaurant(order)
                    send_receipt_email(order)
                except Exception as e:
                    print(f"Error sending to restaurant: {e}")
                
                request.session['open_receipt_id'] = order.id
                messages.success(request, f"Заказ №{order.id} оформлен! Оплата наличными при получении.")
                return render(request, 'main/order_success.html', {
                    'order': order,
                    'earned': earned,
                    'count': 1
                })
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                import traceback
                traceback.print_exc()
                messages.error(request, f"Ошибка при создании заказа: {e}")
                return redirect('cart_detail')
        
        # --- ОПЛАТА КАРТОЙ (сохраняем в сессию) ---
        request.session['pending_order'] = {
            'address': final_address,
            'phone': phone,
            'payment_method': payment_method,
            'use_points': use_points,
            'total_cart_price': float(total_cart_price),
            'discount_percent': float(discount_percent),
            'discount_amount': float(discount_amount),
            'total_points_to_spend': float(total_points_to_spend),
            'delivery_time_from': delivery_time_from.isoformat() if delivery_time_from else None,
            'delivery_time_to': delivery_time_to.isoformat() if delivery_time_to else None,
            'lat': lat,
            'lng': lng,
        }
        
        # Создаём платёж в ЮKassa
        idempotence_key = str(uuid.uuid4())
        try:
            payment = Payment.create({
                "amount": {"value": str(final_price), "currency": "RUB"},
                "confirmation": {
                    "type": "redirect",
                    "return_url": request.build_absolute_uri('/payment/success/')
                },
                "capture": True,
                "description": f"Заказ GINZA",
                "metadata": {
                    "user_id": request.user.id,
                }
            }, idempotence_key)
        except Exception as e:
            messages.error(request, f"Ошибка при создании платежа: {e}")
            return redirect('cart_detail')
        
        request.session['pending_payment_id'] = payment.id
        return redirect(payment.confirmation.confirmation_url)
    
    return redirect('cart_detail')


@login_required
def payment_success(request):
    pending_order = request.session.get('pending_order')
    pending_payment_id = request.session.get('pending_payment_id')
    
    if not pending_order or not pending_payment_id:
        messages.error(request, "Информация о заказе не найдена. Попробуйте оформить заказ заново.")
        return redirect('cart_detail')
    
    # Проверяем статус платежа в ЮKassa
    try:
        from yookassa import Payment
        payment = Payment.find_one(pending_payment_id)
        if payment.status != 'succeeded':
            request.session.pop('pending_order', None)
            request.session.pop('pending_payment_id', None)
            messages.error(request, "Платёж не был завершён. Попробуйте снова.")
            return redirect('cart_detail')
    except Exception as e:
        request.session.pop('pending_order', None)
        request.session.pop('pending_payment_id', None)
        messages.error(request, f"Ошибка при проверке оплаты: {e}")
        return redirect('cart_detail')
    
    # Восстанавливаем данные из сессии
    address = pending_order['address']
    phone = pending_order['phone']
    payment_method = pending_order['payment_method']
    total_cart_price = Decimal(str(pending_order['total_cart_price']))
    discount_percent = Decimal(str(pending_order['discount_percent']))
    discount_amount = Decimal(str(pending_order['discount_amount']))
    total_points_to_spend = Decimal(str(pending_order['total_points_to_spend']))
    delivery_time_from_str = pending_order.get('delivery_time_from')
    delivery_time_to_str = pending_order.get('delivery_time_to')
    lat = pending_order.get('lat')
    lng = pending_order.get('lng')
    
    delivery_time_from = None
    delivery_time_to = None
    if delivery_time_from_str:
        try:
            delivery_time_from = datetime.fromisoformat(delivery_time_from_str)
        except ValueError:
            pass
    if delivery_time_to_str:
        try:
            delivery_time_to = datetime.fromisoformat(delivery_time_to_str)
        except ValueError:
            pass
    
    profile = request.user.profile
    cart = Cart(request)
    
    # Цена после скидки
    price_after_discount = total_cart_price * (100 - discount_percent) / 100
    final_price = price_after_discount - total_points_to_spend
    
    try:
        order = Order.objects.create(
            user=request.user,
            address=address,
            phone=phone,
            payment_method=payment_method,
            total_price=final_price,
            points_used=int(total_points_to_spend),
            status='new',
            payment_id=pending_payment_id,
            is_paid=True,
            delivery_time_from=delivery_time_from,
            delivery_time_to=delivery_time_to,
            lat=lat,
            lng=lng,
        )
        OrderStatusHistory.objects.create(
            order=order,
            old_status='',
            new_status='new',
            changed_by=request.user
        )
        for item in cart:
            OrderItem.objects.create(
                order=order,
                product=item['product'],
                price=item['price'],
                quantity=item['quantity'],
                comment=item.get('comment', '')
            )
        
        # Списываем баллы
        if total_points_to_spend > 0:
            profile.points -= int(total_points_to_spend)
            profile.save()
        # Начисляем кэшбэк
        earned = int(final_price * Decimal('0.05'))
        profile.points += earned
        profile.save()
        
        cart.clear()
        request.session.pop('pending_order', None)
        request.session.pop('pending_payment_id', None)
        
        # Отправка в ресторан
        try:
            success = send_order_to_restaurant(order)
            if success:
                send_receipt_email(order)
        except Exception as e:
            print(f"Error sending to restaurant: {e}")
        
        request.session['open_receipt_id'] = order.id
        messages.success(request, f"Заказ №{order.id} успешно оплачен и создан!")
        
        return render(request, 'main/order_success.html', {
            'order': order,
            'earned': earned,
            'count': 1
        })
    
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        messages.error(request, f"Ошибка при создании заказа: {e}")
        return redirect('cart_detail')


# Функция автоматического назначения курьера (улучшенная)
# Функция автоматического назначения курьера (без WebSocket)
def auto_assign_order(order):
    """Автоматически назначает заказ ближайшему свободному курьеру."""
    if order.status != 'ready':
        return False

    # Координаты ресторана
    try:
        rest_config = RestaurantConfig.objects.first()
        if rest_config and rest_config.location_coords:
            rest_lat, rest_lng = map(float, rest_config.location_coords.split(','))
        else:
            rest_lat, rest_lng = 45.624828, 63.312162
    except:
        rest_lat, rest_lng = 45.624828, 63.312162

    # Находим онлайн-курьеров с активными заказами < 5
    time_threshold = timezone.now() - timedelta(minutes=5)
    
    candidates = Profile.objects.filter(
        role='courier',
        is_online=True
    ).filter(
        Q(last_updated__gte=time_threshold) | Q(last_lat__isnull=False)
    ).select_related('user')

    best_courier = None
    best_score = None

    for prof in candidates:
        active_count = Order.objects.filter(courier=prof.user, status='delivering').count()
        if active_count >= 5:
            continue

        if prof.last_lat and prof.last_lng:
            dist = geodesic((rest_lat, rest_lng), (prof.last_lat, prof.last_lng)).km
        else:
            dist = 999

        score = dist + active_count * 2
        if best_courier is None or score < best_score:
            best_courier = prof.user
            best_score = score

    if best_courier:
        old_status = order.status
        order.courier = best_courier.username
        order.status = 'delivering'
        order.save()
        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status='delivering',
            changed_by=None   # или можно поставить админа/систему, если нужно
        )
        optimize_courier_route(best_courier)
        print(f"✅ Заказ #{order.id} автоматически назначен курьеру {best_courier.username}")
        return True
    return False


def optimize_courier_route(courier_user):
    """
    Пересчитывает оптимальный порядок доставки для курьера (жадный алгоритм ближайшего соседа).
    Обновляет поле route_order у заказов.
    """
    orders = Order.objects.filter(
        courier=courier_user,
        status='delivering'
    ).exclude(lat__isnull=True, lng__isnull=True)

    if not orders:
        return

    # Текущая позиция курьера (если есть) или ресторан
    profile = courier_user.profile
    if profile.last_lat and profile.last_lng:
        current_point = (profile.last_lat, profile.last_lng)
    else:
        rest_config = RestaurantConfig.objects.first()
        if rest_config and rest_config.location_coords:
            lat, lng = map(float, rest_config.location_coords.split(','))
        else:
            lat, lng = 45.624828, 63.312162
        current_point = (lat, lng)

    order_list = list(orders)
    visited = []
    unvisited = order_list.copy()
    current = current_point

    while unvisited:
        nearest = min(unvisited, key=lambda o: geodesic(current, (o.lat, o.lng)).km)
        visited.append(nearest)
        current = (nearest.lat, nearest.lng)
        unvisited.remove(nearest)

    for idx, order in enumerate(visited, start=1):
        if order.route_order != idx:
            order.route_order = idx
            order.save(update_fields=['route_order'])

""""
@staff_member_required
def get_support_users(request):
    
    users_with_messages = User.objects.filter(
        support_messages__isnull=False
    ).annotate(
        unread_count=Count('support_messages', filter=Q(support_messages__is_read=False)),
        last_message_time=Max('support_messages__created_at')
    ).order_by('-last_message_time')
    
    users_data = []
    for user in users_with_messages:
        last_msg = user.support_messages.order_by('-created_at').first()
        users_data.append({
            'id': user.id,
            'username': user.username,
            'unread_count': user.unread_count,
            'last_message': last_msg.text[:50] if last_msg else '',
            'last_time': last_msg.created_at.strftime('%d.%m.%Y %H:%M') if last_msg else ''
        })
    
    return JsonResponse({'users': users_data})


@staff_member_required
def get_user_messages(request, user_id):
 
    user = get_object_or_404(User, id=user_id)
    messages = SupportMessage.objects.filter(user=user).order_by('created_at')
    messages.filter(is_read=False).update(is_read=True)
    
    data = []
    for msg in messages:
        data.append({
            'id': msg.id,
            'text': msg.text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_admin': msg.is_from_admin
        })
    return JsonResponse({'messages': data})
"""

@staff_member_required
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product_name = product.name
    product.delete()
    messages.success(request, f"Блюдо '{product_name}' удалено")
    
    # Получаем адрес возврата из GET-параметра 'next', если нет — по умолчанию 'menu'
    next_url = request.GET.get('next', 'menu')
    return redirect(next_url)
""""
@staff_member_required
def send_support_reply(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)
    
    user_id = request.POST.get('user_id')
    text = request.POST.get('text', '').strip()
    file = request.FILES.get('file')
    
    if not text and not file:
        return JsonResponse({'status': 'error', 'message': 'Введите текст или прикрепите файл'})
    
    user = get_object_or_404(User, id=user_id)
    
    msg = SupportMessage.objects.create(
        user=user,
        text=text,
        file=file if file else None,
        is_read=False,
        is_from_admin=True
    )
    
    return JsonResponse({
        'status': 'ok',
        'message': {
            'id': msg.id,
            'text': text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_admin': True
        }
    })

@staff_member_required
def get_order_support_messages(request, order_id):

    order = get_object_or_404(Order, id=order_id)
    messages = SupportMessage.objects.filter(order=order).order_by('created_at')
    data = []
    for msg in messages:
        data.append({
            'id': msg.id,
            'text': msg.text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_admin': msg.is_from_admin,  # True – сообщение от оператора
        })
    return JsonResponse({'messages': data})

@staff_member_required
def send_order_support_reply(request, order_id):

    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)
    order = get_object_or_404(Order, id=order_id)
    text = request.POST.get('text', '').strip()
    file = request.FILES.get('file')
    if not text and not file:
        return JsonResponse({'status': 'error', 'message': 'Введите текст или прикрепите файл'})
    msg = SupportMessage.objects.create(
        user=order.user,
        order=order,
        text=text,
        file=file if file else None,
        is_read=False,
        is_from_admin=True
    )
    return JsonResponse({
        'status': 'ok',
        'message': {
            'id': msg.id,
            'text': text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_admin': True
        }
    })

@login_required
def get_client_order_messages(request, order_id):

    order = get_object_or_404(Order, id=order_id, user=request.user)
    messages = SupportMessage.objects.filter(order=order).order_by('created_at')
    data = []
    for msg in messages:
        data.append({
            'id': msg.id,
            'text': msg.text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_admin': msg.is_from_admin,
        })
    return JsonResponse({'messages': data})

@login_required
def send_client_support_message(request, order_id):

    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)
    order = get_object_or_404(Order, id=order_id, user=request.user)
    text = request.POST.get('text', '').strip()
    file = request.FILES.get('file')
    if not text and not file:
        return JsonResponse({'status': 'error', 'message': 'Введите текст или прикрепите файл'})
    msg = SupportMessage.objects.create(
        user=request.user,
        order=order,
        text=text,
        file=file if file else None,
        is_read=False,
        is_from_admin=False
    )
    return JsonResponse({
        'status': 'ok',
        'message': {
            'id': msg.id,
            'text': text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_admin': False
        }
    })
"""

@login_required
def view_receipt(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'main/receipt.html', {'order': order})


@login_required
def payment_success_view_old(request, order_id):
    return redirect('payment_success')


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items__product', 'status_history'), id=order_id)
    
    user_is_admin = request.user.is_staff or request.user.is_superuser
    is_owner = (order.user == request.user)
    
    is_courier = False
    if hasattr(request.user, 'profile') and request.user.profile.role == 'courier':
        if order.status == 'ready' or order.courier == request.user:
            is_courier = True
    
    if user_is_admin:
        pass
    elif not (is_owner or is_courier):
        messages.error(request, "У вас нет прав для просмотра этого заказа.")
        return redirect('profile')
        
    return render(request, 'main/order_detail.html', {
        'order': order,
        'is_courier': is_courier,
        'show_admin_info': user_is_admin,
        'status_history': order.status_history.all(),
    })


@login_required
def order_repeat(request, order_id):
    old_order = get_object_or_404(Order, id=order_id, user=request.user)
    cart = Cart(request)
    cart.clear()
    for item in old_order.items.all():
        for _ in range(item.quantity):
            cart.add(product=item.product)
    messages.success(request, f"Заказ №{old_order.id} скопирован в корзину!")
    return redirect('cart_detail')


# --- КУРЬЕРСКАЯ ЛОГИКА ---
@login_required
def courier_take_order(request, order_id):
    if request.user.profile.role != 'courier':
        return redirect('profile')
    
    order = get_object_or_404(Order, id=order_id, status='ready')
    active_count = Order.objects.filter(courier=request.user, status='delivering').count()
    
    if active_count < 5:
        old_status = order.status
        order.courier = request.user.username
        order.status = 'delivering'
        order.save()
        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status='delivering',
            changed_by=request.user
        )  # поле delivery_order_index больше не нужно, используем route_order
        optimize_courier_route(request.user)   # <-- пересчитать порядок
        messages.success(request, f"Вы приняли заказ №{order.id}!")
    else:
        messages.error(request, "Максимум 5 заказов одновременно!")
    
    return redirect('courier_map')


@login_required
def courier_complete_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, courier=request.user, status='delivering')
    old_status = order.status  # было 'delivering'
    order.status = 'completed'
    order.save()
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status='completed',
        changed_by=request.user
    )
    
    # Пересчитать маршрут для оставшихся заказов курьера
    optimize_courier_route(request.user)
    
    messages.success(request, f"Заказ №{order.id} успешно доставлен!")
    return redirect('courier_map')
    


def courier_map(request):
    if not request.user.is_authenticated or request.user.profile.role != 'courier':
        return redirect('profile')
    
    my_orders = Order.objects.filter(courier=request.user, status='delivering').order_by('route_order', 'created_at')
    available_orders = Order.objects.filter(status='ready', courier__isnull=True).order_by('created_at')
    
    delivered_count = Order.objects.filter(
        courier=request.user, 
        status='completed',
        created_at__date=timezone.now().date()
    ).count()
    
    return render(request, 'main/courier_map.html', {
        'my_orders': my_orders,
        'available_orders': available_orders,
        'delivered_count': delivered_count
    })


# --- УПРАВЛЕНИЕ ТОВАРАМИ ---
@staff_member_required
def update_order_item(request, item_id, action):
    item = get_object_or_404(OrderItem, id=item_id)
    
    if action == 'increase':
        item.quantity += 1
    elif action == 'decrease' and item.quantity > 1:
        item.quantity -= 1
    elif action == 'decrease' and item.quantity == 1:
        item.delete()
        return JsonResponse({'status': 'ok', 'removed': True, 'order_id': item.order.id, 'order_total': float(item.order.total_price)})
    
    item.save()
    order = item.order
    order.total_price = sum(i.get_cost() for i in order.items.all())
    order.save()
    
    return JsonResponse({
        'status': 'ok',
        'quantity': item.quantity,
        'total': float(item.get_cost()),
        'order_id': order.id,
        'order_total': float(order.total_price)
    })


@staff_member_required
def remove_order_item(request, item_id):
    item = get_object_or_404(OrderItem, id=item_id)
    order = item.order
    item.delete()
    order.total_price = sum(i.get_cost() for i in order.items.all())
    order.save()
    
    return JsonResponse({
        'status': 'ok',
        'order_id': order.id,
        'order_total': float(order.total_price)
    })


@staff_member_required
def add_product(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        price = request.POST.get('price')
        category_id = request.POST.get('category')
        description = request.POST.get('description')
        weight = request.POST.get('weight')
        calories = request.POST.get('calories')
        image = request.FILES.get('image')

        product = Product.objects.create(
            name=name, price=price, category_id=category_id,
            description=description, weight=weight, calories=calories,
            image=image
        )
        
        tag_ids = request.POST.getlist('tags')   # получаем список id выбранных тегов
        if tag_ids:
            product.tags.set(tag_ids)            # связываем many-to-many
        
        messages.success(request, "Блюдо успешно добавлено!")
    return redirect('menu')

@staff_member_required
def api_order_detail(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items__product', 'status_history'), id=order_id)
    data = {
        'id': order.id,
        'user': order.user.username,
        'phone': order.phone,
        'address': order.address,
        'total_price': float(order.total_price),
        'payment_method': order.payment_method,
        'delivery_time_from': order.delivery_time_from.strftime('%d.%m.%Y %H:%M') if order.delivery_time_from else None,
        'delivery_time_to': order.delivery_time_to.strftime('%H:%M') if order.delivery_time_to else None,
        'items': [
            {
                'name': item.product.name,
                'quantity': item.quantity,
                'price': float(item.price),
                'comment': item.comment or ''
            } for item in order.items.all()
        ],
        'status_history': [
            {
                'old_status': dict(Order.STATUS_CHOICES).get(h.old_status, h.old_status),
                'new_status': dict(Order.STATUS_CHOICES).get(h.new_status, h.new_status),
                'created_at': h.created_at.strftime('%d.%m.%Y %H:%M'),
                'changed_by': h.changed_by.username if h.changed_by else None
            } for h in order.status_history.all()
        ]
    }
    return JsonResponse(data)


@staff_member_required
def api_analytics_data(request):

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    orders_qs = Order.objects.filter(status='completed')
    if start_date and end_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            orders_qs = orders_qs.filter(created_at__date__range=[start, end])
        except ValueError:
            pass
    else:
        today = timezone.now().date()
        orders_qs = orders_qs.filter(created_at__date=today)

    # --- Выручка, количество заказов, средний чек ---
    total_revenue = orders_qs.aggregate(Sum('total_price'))['total_price__sum'] or 0
    orders_count = orders_qs.count()
    avg_check = int(total_revenue / orders_count) if orders_count else 0

    # --- Среднее время готовки (cooking → ready) ---
    history = OrderStatusHistory.objects.filter(
        order__in=orders_qs,
        new_status__in=['cooking', 'ready']
    ).order_by('order_id', 'created_at')
    
    cooking_durations = []
    order_times = {}
    for h in history:
        oid = h.order_id
        if h.new_status == 'cooking':
            order_times[oid] = {'cooking': h.created_at}
        elif h.new_status == 'ready' and oid in order_times and order_times[oid].get('cooking'):
            delta = h.created_at - order_times[oid]['cooking']
            cooking_durations.append(delta.total_seconds() / 60)

    avg_cooking_time = round(sum(cooking_durations) / len(cooking_durations), 1) if cooking_durations else 0

    # --- Среднее время доставки (delivering → completed) и лучший курьер ---
    delivering_history = OrderStatusHistory.objects.filter(
        order__in=orders_qs,
        new_status__in=['delivering', 'completed']
    ).order_by('order_id', 'created_at')
    
    delivering_durations = []
    courier_times = {}  # courier_id -> {'total': сумма минут, 'count': количество}
    courier_names = {}

    order_deliver = {}
    for h in delivering_history:
        oid = h.order_id
        if h.new_status == 'delivering':
            order_deliver[oid] = {'delivering': h.created_at}
        elif h.new_status == 'completed' and oid in order_deliver and order_deliver[oid].get('delivering'):
            delta = h.created_at - order_deliver[oid]['delivering']
            minutes = delta.total_seconds() / 60
            delivering_durations.append(minutes)

            # Найти курьера, который вёз этот заказ
            try:
                order = Order.objects.get(id=oid, courier__isnull=False)
                courier_id = order.courier.id
                courier_name = order.courier.username
                courier_names[courier_id] = courier_name
                if courier_id not in courier_times:
                    courier_times[courier_id] = {'total': 0, 'count': 0}
                courier_times[courier_id]['total'] += minutes
                courier_times[courier_id]['count'] += 1
            except Order.DoesNotExist:
                pass

    avg_delivery_time = round(sum(delivering_durations) / len(delivering_durations), 1) if delivering_durations else 0

    # Лучший курьер (минимальное среднее время доставки)
    best_courier_name = None
    best_avg = None
    for cid, data in courier_times.items():
        avg = data['total'] / data['count']
        if best_avg is None or avg < best_avg:
            best_avg = avg
            best_courier_name = courier_names.get(cid, f"Курьер #{cid}")
            best_avg_minutes = round(avg, 1)
    if best_courier_name and best_avg is not None:
        best_courier_name = f"{best_courier_name} ({best_avg_minutes} мин.)"

    # --- Хит продаж ---
    popular = OrderItem.objects.filter(order__in=orders_qs)\
        .values('product__name')\
        .annotate(total=Sum('quantity'))\
        .order_by('-total').first()
    most_popular_name = popular['product__name'] if popular else None

    # --- Блюда с долгим приготовлением (>45 мин) ---
    slow_dishes_ids = set()
    for order in orders_qs:
        ready_entry = order.status_history.filter(new_status='ready').first()
        cooking_entry = order.status_history.filter(new_status='cooking').first()
        if ready_entry and cooking_entry:
            duration = (ready_entry.created_at - cooking_entry.created_at).total_seconds() / 60
            if duration > 45:
                for item in order.items.all():
                    slow_dishes_ids.add(item.product.id)
    slow_dishes_names = list(Product.objects.filter(id__in=slow_dishes_ids).values_list('name', flat=True))

    return JsonResponse({
        'total_revenue': total_revenue,
        'orders_count': orders_count,
        'avg_check': avg_check,
        'avg_cooking_time': avg_cooking_time,
        'avg_delivery_time': avg_delivery_time,
        'best_courier': best_courier_name,
        'most_popular': most_popular_name,
        'slow_dishes': slow_dishes_names,
    })


@staff_member_required
def edit_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    categories = Category.objects.all()
    
    if request.method == 'POST':
        product.name = request.POST.get('name')
        product.price = request.POST.get('price')
        product.description = request.POST.get('description')
        product.weight = request.POST.get('weight')
        product.calories = request.POST.get('calories')
        product.category_id = request.POST.get('category')
        product.is_active = request.POST.get('is_active') == 'on'
        
        if request.FILES.get('image'):
            product.image = request.FILES.get('image')
        
        product.save()

        tag_ids = request.POST.getlist('tags')
        product.tags.set(tag_ids) 

        messages.success(request, f"Блюдо '{product.name}' обновлено")
        return redirect('menu')
    
    return render(request, 'main/edit_product.html', {
        'product': product,
        'categories': categories,
        'all_tags': Tag.objects.all(), 
    })


@staff_member_required
def toggle_active(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save()
    messages.success(request, f"Блюдо '{product.name}' {'скрыто' if not product.is_active else 'активировано'}")
    return redirect(request.META.get('HTTP_REFERER', 'menu'))


@staff_member_required
def add_category(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Category.objects.create(name=name)
            messages.success(request, f"Категория '{name}' создана!")
    return redirect('operator_panel')


@staff_member_required
def edit_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            category.name = name
            category.save()
            messages.success(request, f"Категория переименована в '{name}'")
    return redirect('operator_panel')


@staff_member_required
def delete_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if category.products.count() > 0:
        messages.error(request, "Нельзя удалить категорию с товарами!")
    else:
        category_name = category.name
        category.delete()
        messages.success(request, f"Категория '{category_name}' удалена")
    return redirect('operator_panel')


@login_required
def add_review(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        if not OrderItem.objects.filter(order__user=request.user, product=product, order__status='completed').exists():
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'Отзыв можно оставить только после покупки!'}, status=400)
            else:
                messages.error(request, "Отзыв можно оставить только после покупки!")
                return redirect('menu')
        rating = request.POST.get('rating', 5)
        text = request.POST.get('text', '')
        Review.objects.create(
            user=request.user,
            product=product,
            rating=rating,
            text=text
        )
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'ok', 'message': 'Спасибо за отзыв!'})
        else:
            messages.success(request, "Спасибо за отзыв!")
            return redirect('menu')
    return redirect('menu')


# --- ПРОФИЛЬ ---
from django.core.paginator import Paginator

@login_required
def profile_view(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    total_spent = Order.objects.filter(
        user=request.user
    ).exclude(status='cancelled').aggregate(Sum('total_price'))['total_price__sum'] or 0

    # ИЗМЕНЕНО: добавлен discount
    if total_spent < 5000:
        status_name = "Новичок"
        discount = 0
        next_level_amount = 5000
        progress_percent = (total_spent / next_level_amount) * 100
    elif total_spent < 15000:
        status_name = "Гурман"
        discount = 3
        next_level_amount = 15000
        progress_percent = ((total_spent - 5000) / (15000 - 5000)) * 100
    else:
        status_name = "Амбассадор"
        discount = 5
        next_level_amount = None
        progress_percent = 100

    if profile.role == 'courier':
        orders_ready = Order.objects.filter(status='ready', courier__isnull=True).prefetch_related('items__product').order_by('created_at')
        my_delivery = Order.objects.filter(status='delivering', courier=request.user).prefetch_related('items__product')
        return render(request, 'main/profile.html', {
            'profile': profile,
            'orders_ready': orders_ready,
            'my_delivery': my_delivery,
        })
    
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product')
    
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'newest')
    
    if status_filter != 'all':
        orders = orders.filter(status=status_filter)
    
    if search_query:
        orders = orders.filter(id__icontains=search_query)
    
    if sort_by == 'newest':
        orders = orders.order_by('-created_at')
    elif sort_by == 'oldest':
        orders = orders.order_by('created_at')
    elif sort_by == 'price_high':
        orders = orders.order_by('-total_price')
    elif sort_by == 'price_low':
        orders = orders.order_by('total_price')
    else:
        orders = orders.order_by('-created_at')
    
    paginator = Paginator(orders, 5)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    addresses = request.user.addresses.all()
    fav_count = Favorite.objects.filter(user=request.user).count() if not request.user.is_staff else 0
    auto_open_id = request.session.pop('open_receipt_id', None)
    
    return render(request, 'main/profile.html', {
        'profile': profile, 
        'orders': page_obj,
        'addresses': addresses, 
        'fav_count': fav_count,
        'auto_open_id': auto_open_id,
        'status_name': status_name,
        'progress_percent': progress_percent,
        'total_spent': total_spent,  
        'total_spent_neg': -total_spent,
        'next_level_amount': next_level_amount,
        'discount': discount,               # НОВОЕ
        'status_filter': status_filter,
        'sort_by': sort_by,
        'search_query': search_query,
    })


@login_required
def update_profile(request):
    if request.method == 'POST':
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.phone = request.POST.get('phone')
        new_address = request.POST.get('address')
        if new_address:
            profile.address = new_address
        profile.save()
        messages.success(request, "Профиль обновлен!")
    return redirect('profile')


@login_required
def add_address(request):
    if request.method == 'POST':
        address_line = request.POST.get('address_line', '').strip()
        if not address_line:
            messages.error(request, "Введите адрес.")
            return redirect('profile')
        # Добавляем префикс города, если его нет
        if not address_line.lower().startswith('байконур'):
            address_line = "Байконур, " + address_line
        is_valid, lat, lng = geocode_address(address_line)
        if not is_valid:
            messages.error(request, "Адрес не найден в г. Байконур. Укажите существующую улицу и номер дома.")
            return redirect('profile')
        Address.objects.create(user=request.user, address_line=address_line, lat=lat, lng=lng)
        messages.success(request, "Адрес добавлен!")
        return redirect('profile')

@login_required
def delete_address(request, address_id):
    address = get_object_or_404(Address, id=address_id, user=request.user)
    address.delete()
    return redirect('profile')


# --- ПАНЕЛЬ ОПЕРАТОРА ---
@staff_member_required
def operator_panel(request):
    # Фильтр по статусу (GET-параметр)
    status_filter = request.GET.get('status', '')
    orders_qs = Order.objects.all().prefetch_related('items__product', 'user').order_by('-created_at')
    if status_filter and status_filter in dict(Order.STATUS_CHOICES):
        orders_qs = orders_qs.filter(status=status_filter)
    
    paginator = Paginator(orders_qs, 20)  # 20 заказов на страницу
    page_number = request.GET.get('page')
    orders_page = paginator.get_page(page_number)
    
    # Статистика для карточек
    today = timezone.now().date()
    total_revenue = Order.objects.filter(status='completed', created_at__date=today).aggregate(Sum('total_price'))['total_price__sum'] or 0
    today_count = Order.objects.filter(status='completed', created_at__date=today).count()
    avg_check = int(total_revenue / today_count) if today_count else 0
    
    context = {
        'orders': orders_page,
        'status_filter': status_filter,
        'total_revenue': total_revenue,
        'today_count': today_count,
        'avg_check': avg_check,
    }
    return render(request, 'main/operator_panel.html', context)


@staff_member_required
def change_order_status(request, order_id, new_status):
    order = get_object_or_404(Order, id=order_id)
    old_status = order.status
    
    if new_status not in ['new', 'cooking', 'ready', 'delivering', 'completed', 'cancelled']:
        return JsonResponse({'status': 'error', 'message': 'Некорректный статус'}, status=400)
    
    # Запрещаем оператору переводить из ready в delivering
    if old_status == 'ready' and new_status == 'delivering' and request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Оператор не может передать заказ курьеру.'}, status=403)

    # Оператор не может изменять статус delivering (кроме отмены)
    if old_status == 'delivering' and new_status != 'cancelled' and request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Оператор не может изменить статус заказа в доставке.'}, status=403)

    # Только курьер может завершить доставку
    if old_status == 'delivering' and new_status == 'completed':
        if not (hasattr(request.user, 'profile') and request.user.profile.role == 'courier' and order.courier == request.user):
            return JsonResponse({'status': 'error', 'message': 'Только назначенный курьер может завершить заказ.'}, status=403)
    
    

    if new_status not in ['new', 'cooking', 'ready', 'delivering', 'completed', 'cancelled']:
        return JsonResponse({'status': 'error', 'message': 'Некорректный статус'}, status=400)
    
    # Сохраняем старый статус
    order.status = new_status
    order.save()
    
    # Записываем историю
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=new_status,
        changed_by=request.user
    )
    
    # Если статус стал 'ready' – автоматически ищем курьера
    if new_status == 'ready' and old_status != 'ready':
        auto_assign_order(order)
    
    # Если заказ завершён – начисляем кэшбэк (если не начисляли ранее)
    if new_status == 'completed' and old_status != 'completed':
        profile = order.user.profile
        earned = int(order.total_price * Decimal('0.05'))
        profile.points += earned
        profile.save()
    
    # Подготовка ответа
    counts = {
        'new': Order.objects.filter(status='new').count(),
        'cooking': Order.objects.filter(status='cooking').count(),
        'ready': Order.objects.filter(status='ready').count(),
        'delivering': Order.objects.filter(status='delivering').count(),
    }
    
    # Определяем цвет статуса для бейджа
    status_color_map = {
        'new': 'warning',
        'cooking': 'primary',
        'ready': 'success',
        'delivering': 'info',
        'completed': 'success',
        'cancelled': 'danger',
    }
    
    messages_dict = {
        ('new', 'cooking'): f"Заказ №{order.id} передан на кухню.",
        ('cooking', 'ready'): f"Заказ №{order.id} готов к выдаче!",
        ('ready', 'delivering'): f"Заказ №{order.id} передан курьеру.",
        ('delivering', 'completed'): f"Заказ №{order.id} доставлен! Спасибо за заказ.",
    }
    message = messages_dict.get((old_status, new_status), f"Статус заказа №{order.id} изменён на {order.get_status_display()}.")
    
    return JsonResponse({
        'status': 'ok',
        'message': message,
        'counts': counts,
        'status_color': status_color_map.get(new_status, 'secondary'),
        'status_display': order.get_status_display(),
        'order': {
            'id': order.id,
            'user': order.user.username,
            'address': order.address,
            'total_price': float(order.total_price),
            'created_at': order.created_at.strftime('%H:%M'),
        }
    })

@staff_member_required
def discount_list(request):
    """Список скидок и форма создания/редактирования"""
    discounts = Discount.objects.all().order_by('-created_at')
    categories = Category.objects.all()
    products = Product.objects.filter(is_active=True)
    return render(request, 'main/discounts.html', {
        'discounts': discounts,
        'categories': categories,
        'products': products,
    })

@staff_member_required
def create_discount(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        discount_type = request.POST.get('discount_type')
        value = request.POST.get('value')
        applies_to = request.POST.get('applies_to')
        category_id = request.POST.get('category')
        product_id = request.POST.get('product')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        
        try:
            discount = Discount.objects.create(
                name=name,
                discount_type=discount_type,
                value=value,
                applies_to=applies_to,
                category_id=category_id if applies_to == 'category' else None,
                product_id=product_id if applies_to == 'product' else None,
                start_date=start_date,
                end_date=end_date,
                active=True
            )
            messages.success(request, f'Скидка "{name}" создана')
        except Exception as e:
            messages.error(request, f'Ошибка: {e}')
        return redirect('discount_list')
    return redirect('discount_list')

@staff_member_required
def toggle_discount(request, discount_id):
    discount = get_object_or_404(Discount, id=discount_id)
    discount.active = not discount.active
    discount.save()
    messages.success(request, f'Скидка {"активирована" if discount.active else "деактивирована"}')
    return redirect('discount_list')


@staff_member_required
def analytics_dashboard(request):

    
    # 1. Среднее время готовки (от new до ready)
    # Находим время перехода new → cooking и cooking → ready
    cooking_time = None
    delivering_time = None
    
    # Лучший курьер по скорости доставки (delivering → completed)
    best_courier = None
    
    # Блюда с долгим приготовлением
    slow_dishes = []
    
    # Запрашиваем историю
    history = OrderStatusHistory.objects.select_related('order', 'order__user')
    
    # Пример расчёта среднего времени между статусами (можно через raw SQL или цикл)
    # Более простой способ – для каждого заказа вычислить разницу между записями
    order_times = {}
    for h in history.order_by('order_id', 'created_at'):
        key = h.order_id
        if key not in order_times:
            order_times[key] = {}
        order_times[key][h.new_status] = h.created_at
    
    cooking_durations = []
    delivering_durations = []
    
    for order_id, times in order_times.items():
        if 'cooking' in times and 'ready' in times:
            delta = times['ready'] - times['cooking']
            cooking_durations.append(delta.total_seconds() / 60)  # минуты
        if 'delivering' in times and 'completed' in times:
            delta = times['completed'] - times['delivering']
            delivering_durations.append(delta.total_seconds() / 60)
    
    avg_cooking_time = sum(cooking_durations) / len(cooking_durations) if cooking_durations else 0
    avg_delivery_time = sum(delivering_durations) / len(delivering_durations) if delivering_durations else 0
    
    # Лучший курьер – кто быстрее всего доставлял (min avg time)
    courier_data = {}
    for order in Order.objects.filter(status='completed', courier__isnull=False):
        courier_id = order.courier.id
        # Находим время доставки из истории
        delivering_time = None
        completed_time = None
        for h in order.status_history.all():
            if h.new_status == 'delivering':
                delivering_time = h.created_at
            if h.new_status == 'completed':
                completed_time = h.created_at
        if delivering_time and completed_time:
            duration = (completed_time - delivering_time).total_seconds() / 60
            if courier_id not in courier_data:
                courier_data[courier_id] = {'total': 0, 'count': 0}
            courier_data[courier_id]['total'] += duration
            courier_data[courier_id]['count'] += 1
    best_courier_obj = None
    best_avg = None
    for cid, data in courier_data.items():
        avg = data['total'] / data['count']
        if best_avg is None or avg < best_avg:
            best_avg = avg
            best_courier_obj = User.objects.get(id=cid)
    
    # Блюда, которые чаще всего задерживаются на кухне (готовятся дольше 45 минут)
    # Анализируем OrderItem и время перехода cooking→ready
    slow_dishes_ids = set()
    for order in Order.objects.filter(status_history__new_status='ready'):
        ready_time = order.status_history.filter(new_status='ready').first().created_at if order.status_history.filter(new_status='ready').exists() else None
        cooking_time = order.status_history.filter(new_status='cooking').first().created_at if order.status_history.filter(new_status='cooking').exists() else None
        if ready_time and cooking_time:
            duration = (ready_time - cooking_time).total_seconds() / 60
            if duration > 45:
                for item in order.items.all():
                    slow_dishes_ids.add(item.product.id)
    
    slow_dishes = Product.objects.filter(id__in=slow_dishes_ids)
    
    context = {
        'avg_cooking_time': round(avg_cooking_time, 1),
        'avg_delivery_time': round(avg_delivery_time, 1),
        'best_courier': best_courier_obj,
        'slow_dishes': slow_dishes,
    }
    return render(request, 'main/analytics.html', context)


@staff_member_required
def get_online_couriers(request):
    time_threshold = timezone.now() - timedelta(minutes=5)
    
    online_couriers = Profile.objects.filter(
        role='courier'
    ).filter(
        Q(last_updated__gte=time_threshold) | Q(last_lat__isnull=False)
    ).select_related('user')
    
    data = [{
        'id': p.user.id,
        'username': p.user.username,
        'phone': p.phone or '',
        'is_online': True
    } for p in online_couriers]
    
    return JsonResponse({'couriers': data})


@staff_member_required
def get_new_orders(request):
    orders = Order.objects.filter(status='new').order_by('-created_at')
    data = []
    for order in orders:
        data.append({
            'id': order.id,
            'user': order.user.username,
            'address': order.address,
            'total_price': float(order.total_price),
            'created_at': order.created_at.strftime('%H:%M'),
        })
    return JsonResponse({'orders': data})


# --- АУТЕНТИФИКАЦИЯ И ОПЛАТА ---
def check_order_status(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'no_user'})
    last_order = Order.objects.filter(user=request.user).order_by('-created_at').first()
    if last_order:
        return JsonResponse({
            'order_id': last_order.id, 
            'status': last_order.status, 
            'status_display': last_order.get_status_display()
        })
    return JsonResponse({'status': 'no_orders'})


def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('menu')
    else:
        form = UserRegisterForm()
    return render(request, 'main/register.html', {'form': form})


def login_view(request):
    next_url = request.GET.get('next', '')
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if next_url:
                return redirect(next_url)
            if user.is_staff:
                return redirect('operator_panel')
            if hasattr(user, 'profile') and user.profile.role == 'courier':
                return redirect('courier_map')
            return redirect('menu')
    else:
        form = AuthenticationForm()
    return render(request, 'main/login.html', {'form': form, 'next': next_url})


def logout_view(request):
    logout(request)
    #messages.info(request, "Вы вышли из системы.")
    return redirect('start')





# --- УПРАВЛЕНИЕ КУРЬЕРАМИ ---
@staff_member_required
def create_courier_view(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        phone = request.POST.get('phone', '').strip()

        if not username or not password:
            messages.error(request, 'Логин и пароль обязательны для заполнения.')
            return redirect('create_courier')

        if User.objects.filter(username=username).exists():
            messages.error(request, f'Пользователь с логином "{username}" уже существует.')
            return redirect('create_courier')

        user = User.objects.create_user(username=username, password=password)

        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = 'courier'
        if phone:
            profile.phone = phone
        profile.save()

        messages.success(request, f'Курьер {username} успешно создан!')
        return redirect('create_courier')

    return render(request, 'main/create_courier.html')


@login_required
def get_order_messages(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if not (request.user == order.user or request.user == order.courier or request.user.is_staff):
        return JsonResponse({'status': 'error', 'message': 'Доступ запрещён'}, status=403)
    
    messages = OrderMessage.objects.filter(order=order).order_by('created_at')
    data = []
    for msg in messages:
        data.append({
            'text': msg.text,
            'sender': msg.sender.username,
            'time': msg.created_at.strftime('%H:%M'),
            'is_courier': (msg.sender == request.user)
        })
    return JsonResponse({'messages': data})


@staff_member_required
def create_courier_ajax(request):
    if request.method == 'POST':
        username = 'courier_' + ''.join(random.choice(string.digits) for _ in range(4))
        password = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(10))
        user = User.objects.create_user(username=username, password=password)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = 'courier'
        profile.save()
        return JsonResponse({'status': 'success', 'username': username, 'password': password})
    return JsonResponse({'status': 'error'}, status=400)


@login_required
def courier_panel(request):
    if request.user.profile.role != 'courier':
        return redirect('profile')
    orders_ready = Order.objects.filter(status='ready', courier__isnull=True).prefetch_related('items__product').order_by('created_at')
    my_delivery = Order.objects.filter(status='delivering', courier=request.user).prefetch_related('items__product')
    return render(request, 'main/profile.html', {
        'profile': request.user.profile,
        'orders_ready': orders_ready,
        'my_delivery': my_delivery,
    })


@login_required
def update_courier_location(request):
    if request.method == 'POST':
        lat = request.POST.get('lat')
        lng = request.POST.get('lng')
        profile = request.user.profile
        if profile.role == 'courier':
            profile.last_lat = lat
            profile.last_lng = lng
            profile.last_updated = timezone.now() 
            profile.save()
            return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)


def get_ai_recommendations(user, limit=8):
    """
    Для блока «Повар рекомендует»:
    - если пользователь авторизован: популярные блюда из его любимых категорий,
    - иначе – глобально популярные.
    """
    base = Product.objects.filter(is_active=True)
    if not user or not user.is_authenticated:
        # Гость: глобально популярные
        return base.annotate(total_sold=Sum('orderitem__quantity')).order_by('-total_sold')[:limit]

    # Авторизованный: товары, которые он ещё не заказывал
    tried = set(OrderItem.objects.filter(order__user=user).values_list('product_id', flat=True))

    # Любимые категории (топ-2 по частоте заказов)
    fav_cats = (OrderItem.objects.filter(order__user=user)
                .values('product__category')
                .annotate(cnt=Count('product__category'))
                .order_by('-cnt')[:2])
    cat_ids = [c['product__category'] for c in fav_cats if c['product__category']]

    recs = Product.objects.none()
    if cat_ids:
        recs = base.filter(category_id__in=cat_ids).exclude(id__in=tried).distinct()
        if recs.count() >= limit:
            return recs[:limit]

    # Добираем популярными
    needed = limit - recs.count()
    popular = base.annotate(total_sold=Sum('orderitem__quantity')) \
        .exclude(id__in=tried) \
        .exclude(id__in=recs.values_list('id', flat=True)) \
        .order_by('-total_sold')[:needed]

    return (recs | popular).distinct()[:limit] if recs else popular


def get_single_recommendation(request):
    cart_product_ids = [str(item['product'].id) for item in Cart(request)]
    product = Product.objects.filter(is_active=True).exclude(id__in=cart_product_ids).order_by('?').first()
    
    if product:
        return JsonResponse({
            'id': product.id,
            'name': product.name,
            'price': product.price,
            'image_url': product.image.url if product.image else '/static/img/no-image.png',
        })
    return JsonResponse({'error': 'No more products'}, status=404)


@login_required
def add_address_ajax(request):
    if request.method == 'POST':
        address_line = request.POST.get('address_line', '').strip()
        if not address_line:
            return JsonResponse({'status': 'error', 'message': 'Введите адрес'}, status=400)

        city_prefix = "Байконур, "
        if not address_line.startswith(city_prefix):
            address_line = city_prefix + address_line

        # Обязательное геокодирование через Яндекс.Карты
        is_valid, lat, lng = geocode_address(address_line)  # используем функцию geocode_address, а не validate_address

        if not is_valid:
            return JsonResponse({
                'status': 'error', 
                'message': 'Адрес не найден в г. Байконур. Проверьте правильность улицы и номера дома.'
            }, status=400)

        # Сохраняем адрес ТОЛЬКО с реальными координатами
        new_addr = Address.objects.create(
            user=request.user,
            address_line=address_line,
            lat=lat,
            lng=lng
        )
        return JsonResponse({
            'status': 'ok',
            'id': new_addr.id,
            'address': new_addr.address_line
        })
    return JsonResponse({'status': 'error'}, status=400)


def send_message(request, order_id):
    if request.method == 'POST' and request.user.is_authenticated:
        order = get_object_or_404(Order, id=order_id)
        text = request.POST.get('text')
        
        if text:
            msg = OrderMessage.objects.create(
                order=order,
                sender=request.user,
                text=text
            )
            return JsonResponse({
                'status': 'ok',
                'text': msg.text,
                'sender': msg.sender.username,
                'time': msg.created_at.strftime('%H:%M')
            })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)


# --- ТЕХНИЧЕСКАЯ ПОДДЕРЖКА ---
""""
@login_required
def get_support_messages(request):
    messages = SupportMessage.objects.filter(user=request.user).order_by('created_at')
    data = []
    for msg in messages:
        data.append({
            'id': msg.id,
            'text': msg.text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_admin': msg.is_from_admin
        })
    return JsonResponse({'messages': data})
"""

@login_required
def check_single_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return JsonResponse({
        'order_id': order.id,
        'status': order.status,
        'status_display': order.get_status_display()
    })

""""
@login_required
def send_support_message(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Метод не разрешён'}, status=405)
    
    text = request.POST.get('text', '').strip()
    file = request.FILES.get('file')
    order_id = request.POST.get('order_id')  # опционально
    
    if not text and not file:
        return JsonResponse({'status': 'error', 'message': 'Введите текст или прикрепите файл'}, status=400)
    
    order = None
    if order_id:
        order = get_object_or_404(Order, id=order_id, user=request.user)
    
    msg = SupportMessage.objects.create(
        user=request.user,
        order=order,
        text=text,
        file=file if file else None
    )
    
    return JsonResponse({
        'status': 'ok',
        'message': {
            'id': msg.id,
            'text': msg.text,
            'file_url': msg.file.url if msg.file else None,
            'file_name': msg.file.name.split('/')[-1] if msg.file else None,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
        }
    })
"""

@staff_member_required
def get_order_counts(request):
    """Возвращает количество заказов по статусам для оператора"""
    counts = {
        'new': Order.objects.filter(status='new').count(),
        'work': Order.objects.filter(status='cooking').count(),
        'ready': Order.objects.filter(status='ready').count(),
        'delivery': Order.objects.filter(status='delivering').count(),
    }
    return JsonResponse({'counts': counts})

@staff_member_required
def mark_order_viewed(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if not order.is_operator_viewed:
        order.is_operator_viewed = True
        order.save()
    return JsonResponse({'status': 'ok'})

@login_required
def get_available_orders_for_courier(request):
    """Возвращает заказы со статусом 'ready' для курьера"""
    if request.user.profile.role != 'courier':
        return JsonResponse({'error': 'Доступ запрещён'}, status=403)
    orders = Order.objects.filter(status='ready', courier__isnull=True).order_by('-created_at')
    data = []
    for order in orders:
        data.append({
            'id': order.id,
            'address': order.address,
            'total_price': float(order.total_price),
            'created_at': order.created_at.strftime('%H:%M'),
        })
    return JsonResponse({'orders': data})

@login_required
def get_user_orders_statuses(request):
    orders = Order.objects.filter(user=request.user).exclude(status__in=['completed', 'cancelled']).order_by('-created_at')
    data = [{'id': o.id, 'status': o.status, 'status_display': o.get_status_display()} for o in orders]
    return JsonResponse({'orders': data})

@staff_member_required
def get_all_orders_data(request):
    """Возвращает все заказы в JSON с фильтрацией и пагинацией для вкладки 'Все заказы'"""
    try:
        orders = Order.objects.all().prefetch_related('items__product', 'user')

        # Фильтр по статусу
        status = request.GET.get('status')
        if status and status != 'all':
            orders = orders.filter(status=status)

        # Поиск по ID заказа
        search = request.GET.get('search')
        if search and search.isdigit():
            orders = orders.filter(id=int(search))

        # Фильтр по датам
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        if date_from:
            orders = orders.filter(created_at__date__gte=date_from)
        if date_to:
            orders = orders.filter(created_at__date__lte=date_to)

        # Сортировка
        sort = request.GET.get('sort', 'newest')
        if sort == 'newest':
            orders = orders.order_by('-created_at')
        elif sort == 'oldest':
            orders = orders.order_by('created_at')
        elif sort == 'price-high':
            orders = orders.order_by('-total_price')
        elif sort == 'price-low':
            orders = orders.order_by('total_price')
        else:
            orders = orders.order_by('-created_at')

        data = []
        for order in orders:
            comments = [item.comment for item in order.items.all() if item.comment]
            data.append({
                'id': order.id,
                'user': order.user.username if order.user else 'Гость',
                'phone': order.phone,
                'total_price': float(order.total_price),
                'address': order.address,
                'status': order.status,
                'status_display': order.get_status_display(),
                'created_at': order.created_at.isoformat(),
                'created_time': order.created_at.strftime('%H:%M') if order.created_at else '',
                'created_date': order.created_at.date().isoformat() if order.created_at else '',
                'delivery_time_from': order.delivery_time_from.strftime('%H:%M') if order.delivery_time_from else '',
                'delivery_time_to': order.delivery_time_to.strftime('%H:%M') if order.delivery_time_to else '',
                'items_comments': comments,
                'is_operator_viewed': order.is_operator_viewed,
            })
        return JsonResponse({'orders': data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)
    
@staff_member_required
def get_analytics_data(request):
    start = request.GET.get('start_date')
    end = request.GET.get('end_date')
    if not start or not end:
        return JsonResponse({'error': 'start_date and end_date are required'}, status=400)
    
    # Преобразуем строки в объекты date
    try:
        start_date = datetime.strptime(start, '%Y-%m-%d').date()
        end_date = datetime.strptime(end, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format, use YYYY-MM-DD'}, status=400)

    orders = Order.objects.filter(created_at__date__range=[start_date, end_date])
    total_revenue = orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    orders_count = orders.count()
    avg_check = total_revenue / orders_count if orders_count else 0

    # Динамика по дням
    daily = orders.annotate(day=TruncDate('created_at')).values('day').annotate(
        revenue=Sum('total_price'),
        count=Count('id')
    ).order_by('day')
    days = [d['day'].isoformat() for d in daily]
    revenues = [float(d['revenue']) for d in daily]
    order_counts = [d['count'] for d in daily]

    # Топ-5 товаров
    top = OrderItem.objects.filter(order__in=orders).values('product__name').annotate(
        qty=Sum('quantity')
    ).order_by('-qty')[:5]
    top_products = [{'name': t['product__name'], 'qty': t['qty']} for t in top]

    return JsonResponse({
        'total_revenue': float(total_revenue),
        'orders_count': orders_count,
        'avg_check': float(avg_check),
        'days': days,
        'revenues': revenues,
        'order_counts': order_counts,
        'top_products': top_products,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
    })

@staff_member_required
def analytics_api(request):
    try:
        start = request.GET.get('start_date')
        end = request.GET.get('end_date')
        if not start or not end:
            return JsonResponse({'error': 'start_date and end_date required'}, status=400)

        # Преобразуем строки в объекты date
        try:
            start_date = datetime.strptime(start, '%Y-%m-%d').date()
            end_date = datetime.strptime(end, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format, use YYYY-MM-DD'}, status=400)

        # Завершённые заказы за период
        orders = Order.objects.filter(created_at__date__range=[start_date, end_date])
        total_revenue = orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
        orders_count = orders.count()
        avg_check = total_revenue / orders_count if orders_count else 0

        # Динамика по дням (без .extra)
        daily_stats = orders.annotate(day=TruncDate('created_at')) \
            .values('day') \
            .annotate(
                revenue=Sum('total_price'),
                count=Count('id')
            ) \
            .order_by('day')

        days = [str(item['day']) for item in daily_stats]
        revenues = [float(item['revenue']) for item in daily_stats]
        order_counts = [item['count'] for item in daily_stats]

        # Топ‑5 товаров
        top_items = OrderItem.objects.filter(order__in=orders) \
            .values('product__name') \
            .annotate(qty=Sum('quantity')) \
            .order_by('-qty')[:5]

        top_products = [{'name': t['product__name'], 'qty': t['qty']} for t in top_items]

        return JsonResponse({
            'total_revenue': float(total_revenue),
            'orders_count': orders_count,
            'avg_check': float(avg_check),
            'days': days,
            'revenues': revenues,
            'order_counts': order_counts,
            'top_products': top_products,
        })
    except Exception as e:
        # Логируем ошибку на сервер
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@staff_member_required
@csrf_exempt
def ajax_create_tag(request):
    """Создаёт новый тег через AJAX"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name and not Tag.objects.filter(name__iexact=name).exists():
            tag = Tag.objects.create(name=name)
            return JsonResponse({'status': 'ok', 'id': tag.id, 'name': tag.name})
        return JsonResponse({'status': 'error', 'message': 'Тег уже существует или имя пустое'})
    return JsonResponse({'status': 'error'}, status=405)

@staff_member_required
def cancel_order(request, order_id):
    """Отмена заказа оператором (только для статуса 'new')"""
    order = get_object_or_404(Order, id=order_id)
    
    # Проверяем, что заказ в статусе 'new' и ещё не обработан
    if order.status != 'new':
        return JsonResponse({
            'status': 'error',
            'message': f'Нельзя отменить заказ в статусе "{order.get_status_display()}". Отмена доступна только для новых заказов.'
        }, status=400)
    
    # Проверяем, не были ли уже списаны баллы (если заказ в 'new' - баллы ещё не списаны, но проверим)
    # Проверяем, не началось ли приготовление (нет истории статуса 'cooking')
    if OrderStatusHistory.objects.filter(order=order, new_status='cooking').exists():
        return JsonResponse({
            'status': 'error',
            'message': 'Заказ уже передан на кухню. Отмена невозможна.'
        }, status=400)
    
    # Сохраняем старый статус
    old_status = order.status
    
    # Меняем статус на 'cancelled'
    order.status = 'cancelled'
    order.save()
    
    # Записываем историю
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status='cancelled',
        changed_by=request.user
    )
    
    # Возвращаем баллы, если они были списаны (но в статусе 'new' списание ещё не происходит, это на будущее)
    # В вашей системе списание баллов происходит при создании заказа, так что может быть уже списано.
    # Если баллы были списаны - возвращаем их пользователю
    if order.points_used > 0:
        profile = order.user.profile
        profile.points += order.points_used
        profile.save()
    
    # Логируем
    logger.info(f"Заказ №{order.id} отменён оператором {request.user.username}")
    
    # Обновляем счётчики и отправляем уведомление клиенту (если есть WebSocket)
    # ... можно добавить отправку уведомления через WebSocket
    
    # Подсчёт актуальных счётчиков для обновления интерфейса
    counts = {
        'new': Order.objects.filter(status='new').count(),
        'cooking': Order.objects.filter(status='cooking').count(),
        'ready': Order.objects.filter(status='ready').count(),
        'delivering': Order.objects.filter(status='delivering').count(),
    }
    
    return JsonResponse({
        'status': 'ok',
        'message': f'Заказ №{order.id} успешно отменён.',
        'counts': counts,
        'order_id': order.id
    })
