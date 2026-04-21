from .utils import send_order_to_restaurant, send_receipt_email
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.db.models import Prefetch, Sum, F, Q
from django.contrib import messages
from decimal import Decimal
from django.utils import timezone
from .models import Category, OrderItem, Product, Order, Profile, Favorite, Address, Review, RestaurantConfig, OrderMessage, SupportMessage
from .cart import Cart
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
from geopy.distance import geodesic              # НОВОЕ: для автоназначения курьера (pip install geopy)

Configuration.configure('1285119', 'test_yOeCjmKe1rtmfgAat4OUl_9V89XI0Z4gIqR3HZXr7wg')


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def validate_address(address):
    """
    Проверяет адрес на наличие ключевых слов (улица, проспект, микрорайон и т.д.)
    и номера дома. Возвращает (is_valid, lat, lng).
    """
    if "Байконур" in address and len(address) > 15:
        return True, 45.624828, 63.312162

    address_lower = address.lower()

    # Расширенный список ключевых слов
    street_keywords = [
        'ул.', 'улица', 'пр.', 'проспект', 'пер.', 'переулок',
        'микрорайон', 'мкр', 'мкр.', 'посёлок', 'п.', 'городок',
        'жилмассив', 'ж/м', 'жм', 'проезд', 'бульвар', 'набережная',
        'шоссе', 'тупик', 'аллея', 'линия', 'квартал'
    ]
    
    has_street = any(keyword in address_lower for keyword in street_keywords)
    has_house = any(char.isdigit() for char in address)

    # Для микрорайона/посёлка номер дома может не требоваться
    micro_district = any(kw in address_lower for kw in ['микрорайон', 'мкр', 'посёлок', 'п.'])
    if micro_district and has_street:
        has_house = True

    if not has_street or not has_house:
        return False, None, None

    # Здесь можно добавить реальное геокодирование через Yandex Maps API
    return True, 45.624828, 63.312162


# --- ГЛАВНАЯ И МЕНЮ ---
def start(request):
    cart = Cart(request)
    popular_dishes = Product.objects.filter(is_active=True).annotate(
        total_sold=Sum('orderitem__quantity')
    ).order_by('-total_sold')[:10]
    
    if popular_dishes.count() < 10:
        existing_ids = list(popular_dishes.values_list('id', flat=True))
        additional = Product.objects.filter(is_active=True).exclude(id__in=existing_ids).order_by('?')[:10 - popular_dishes.count()]
        popular_dishes = list(popular_dishes) + list(additional)
    
    context = {
        'cart': cart,
        'popular_dishes': popular_dishes,
    }
    return render(request, 'main/index.html', context)


def menu_view(request):
    cart = Cart(request)
    
    if request.user.is_staff:
        products_filter = Product.objects.all()
    else:
        products_filter = Product.objects.filter(is_active=True)
    
    categories = Category.objects.prefetch_related(
        Prefetch('products', queryset=products_filter.prefetch_related('reviews'))
    ).all()

    user_favorites = []
    if request.user.is_authenticated:
        user_favorites = Favorite.objects.filter(user=request.user).values_list('product_id', flat=True)

    context = {
        'categories': categories,
        'cart': cart,
        'user_favorites': user_favorites,
        'all_products': Product.objects.all(),
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

    recommended_products = []
    cart_product_ids = [int(pid) for pid in cart.cart.keys()]
    
    user_orders_count = 0
    if request.user.is_authenticated:
        user_orders_count = Order.objects.filter(user=request.user, status='completed').count()
    
    if not request.user.is_authenticated or user_orders_count < 4:
        # Для новых пользователей – популярное
        popular_products = OrderItem.objects.values('product_id')\
            .annotate(total_sold=Sum('quantity'))\
            .order_by('-total_sold')[:12]
        popular_ids = [p['product_id'] for p in popular_products]
        recommended_products = list(Product.objects.filter(
            id__in=popular_ids, is_active=True
        ).exclude(id__in=cart_product_ids)[:4])
        if len(recommended_products) < 4:
            extra = Product.objects.filter(is_active=True)\
                .exclude(id__in=cart_product_ids)\
                .order_by('?')[:4-len(recommended_products)]
            recommended_products += list(extra)
    else:
        # Для опытных: анализ тегов и состава
        from collections import Counter
        # Получаем все купленные товары пользователя
        purchased_products = OrderItem.objects.filter(
            order__user=request.user, order__status='completed'
        ).select_related('product')
        
        # Собираем теги всех купленных товаров
        tag_counter = Counter()
        product_ids_purchased = []
        for item in purchased_products:
            product_ids_purchased.append(item.product.id)
            for tag in item.product.tags.all():
                tag_counter[tag.id] += 1
        
        # Самые частые теги
        top_tags = [tag_id for tag_id, count in tag_counter.most_common(3)]
        
        # Рекомендуем товары с этими тегами, исключая уже купленные и в корзине
        if top_tags:
            recommended_products = list(Product.objects.filter(
                tags__id__in=top_tags, is_active=True
            ).exclude(id__in=product_ids_purchased)
             .exclude(id__in=cart_product_ids)
             .distinct()[:4])
        
        # Если не хватает – добавляем популярные
        if len(recommended_products) < 4:
            needed = 4 - len(recommended_products)
            popular = Product.objects.filter(is_active=True)\
                .exclude(id__in=product_ids_purchased)\
                .exclude(id__in=cart_product_ids)\
                .order_by('-orderitem__quantity')[:needed]
            recommended_products += list(popular)
        
        # Если всё равно пусто – случайные
        if len(recommended_products) < 4:
            needed = 4 - len(recommended_products)
            random_products = Product.objects.filter(is_active=True)\
                .exclude(id__in=product_ids_purchased)\
                .exclude(id__in=cart_product_ids)\
                .order_by('?')[:needed]
            recommended_products += list(random_products)
    
    discount = 0
    if request.user.is_authenticated:
        total_spent = Order.objects.filter(user=request.user, status='completed').aggregate(Sum('total_price'))['total_price__sum'] or 0
        if total_spent >= 15000:
            discount = 5
        elif total_spent >= 5000:
            discount = 3


    # Текущее локальное время для поля datetime-local
    now = timezone.localtime(timezone.now())
    
    return render(request, 'main/cart_detail.html', {
        'cart': cart,
        'recommended_products': recommended_products,
        'is_new_user': not request.user.is_authenticated or user_orders_count < 4,
        'orders_count': user_orders_count,
        'now': now,
        'discount': discount,
    })


def cart_add(request, product_id):
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
        address_ids = request.POST.getlist('address_ids')
        new_address = request.POST.get('new_address')
        phone = request.POST.get('phone')
        payment_method = request.POST.get('payment_method')
        use_points = request.POST.get('use_points') == 'on'
        
        # Получаем время доставки
        delivery_time_str = request.POST.get('delivery_time')
        delivery_time = None
        if delivery_time_str:
            try:
                delivery_time = datetime.fromisoformat(delivery_time_str)
                # Делаем его aware, используя текущий часовой пояс
                delivery_time = timezone.make_aware(delivery_time)
                min_time = timezone.now() + timedelta(minutes=30)
                if delivery_time < min_time:
                    messages.error(request, "Выберите время не ранее чем через 30 минут")
                    return redirect('cart_detail')
            except ValueError:
                pass
        
        # Сбор адресов
        final_addresses = []
        if new_address and new_address.strip():
            final_addresses.append(new_address.strip())
        if address_ids:
            db_addresses = Address.objects.filter(id__in=address_ids, user=request.user)
            for addr_obj in db_addresses:
                final_addresses.append(addr_obj.address_line)
        final_addresses = list(dict.fromkeys(final_addresses))
        prefix = "Байконур, "
        final_addresses = [addr for addr in final_addresses 
                           if addr and len(addr.strip()) > len(prefix) and addr.strip() != prefix.strip()]
        if not final_addresses:
            messages.error(request, "Пожалуйста, выберите или введите адрес доставки")
            return redirect('cart_detail')
        
        # Валидация нового адреса
        if new_address and new_address.strip():
            clean_new_address = new_address.strip()
            if len(clean_new_address) > len(prefix) and clean_new_address != prefix.strip():
                is_valid, lat, lng = validate_address(clean_new_address)
                if not is_valid:
                    messages.error(request, f"Адрес '{clean_new_address}' не найден. Проверьте правильность написания (укажите улицу и номер дома)")
                    return redirect('cart_detail')
        
        profile, _ = Profile.objects.get_or_create(user=request.user)
        
        address_count = len(final_addresses)
        total_cart_price = cart.get_total_price()
        total_full_price = total_cart_price * address_count

        # Расчёт баллов
        total_points_to_spend = Decimal('0')
        if use_points and profile.points > 0:
            max_spend_limit = (total_full_price * Decimal('0.30')).quantize(Decimal('1'))
            total_points_to_spend = min(Decimal(profile.points), max_spend_limit)

        points_per_order = [0] * address_count
        if total_points_to_spend > 0:
            base_per_order = int(total_points_to_spend // address_count)
            remainder = int(total_points_to_spend % address_count)
            for i in range(address_count):
                points_per_order[i] = base_per_order
                if i < remainder:
                    points_per_order[i] += 1

        actual_payment_amount = total_full_price - total_points_to_spend

        # Если оплата наличными – создаём заказ сразу, без ЮKassa
        if payment_method == 'cash':
            created_orders = []
            try:
                for idx, addr_text in enumerate(final_addresses):
                    points_used = Decimal(str(points_per_order[idx])) if idx < len(points_per_order) else 0
                    current_order_price = total_cart_price - points_used
                    order = Order.objects.create(
                        user=request.user,
                        address=addr_text,
                        phone=phone,
                        payment_method='cash',
                        total_price=current_order_price,
                        points_used=int(points_used),
                        status='new',
                        is_paid=False,  # наличные – оплата при получении
                        delivery_time=delivery_time,
                    )
                    for item in cart:
                        OrderItem.objects.create(
                            order=order,
                            product=item['product'],
                            price=item['price'],
                            quantity=item['quantity'],
                            comment=item.get('comment', '')
                        )
                    created_orders.append(order)
                
                # Списываем баллы
                if total_points_to_spend > 0:
                    profile.points -= int(total_points_to_spend)
                    profile.save()
                # Начисляем кэшбэк
                total_earned = 0
                for o in created_orders:
                    earned = int(o.total_price * Decimal('0.05'))
                    total_earned += earned
                profile.points += total_earned
                profile.save()
                
                cart.clear()
                # Отправка в ресторан (если нужно)
                for order in created_orders:
                    try:
                        send_order_to_restaurant(order)
                        send_receipt_email(order)
                    except Exception as e:
                        print(f"Error sending to restaurant: {e}")
                
                request.session['open_receipt_id'] = created_orders[0].id
                messages.success(request, f"Заказ №{created_orders[0].id} оформлен! Оплата наличными при получении.")
                return render(request, 'main/order_success.html', {
                    'order': created_orders[0],
                    'earned': total_earned,
                    'count': address_count
                })
            except Exception as e:
                print(f"CRITICAL ERROR: {e}")
                import traceback
                traceback.print_exc()
                for o in created_orders:
                    o.delete()
                messages.error(request, f"Ошибка при создании заказа: {e}")
                return redirect('cart_detail')
        
        # Для оплаты картой – идём в ЮKassa
        # Сохраняем данные в сессию
        request.session['pending_order'] = {
            'final_addresses': final_addresses,
            'phone': phone,
            'payment_method': payment_method,
            'use_points': use_points,
            'total_cart_price': float(total_cart_price),
            'address_count': address_count,
            'points_per_order': points_per_order,
            'total_points_to_spend': float(total_points_to_spend),
            'delivery_time': delivery_time.isoformat() if delivery_time else None,
        }
        
        # Создаём платёж в ЮKassa
        idempotence_key = str(uuid.uuid4())
        try:
            payment = Payment.create({
                "amount": {"value": str(actual_payment_amount), "currency": "RUB"},
                "confirmation": {
                    "type": "redirect",
                    "return_url": request.build_absolute_uri('/payment/success/')
                },
                "capture": True,
                "description": f"Заказ GINZA",
                "metadata": {
                    "user_id": request.user.id,
                    "address_count": str(address_count)
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
    """Обработка успешной оплаты. Заказ создаётся здесь."""
    
    print("=" * 50)
    print("PAYMENT_SUCCESS called")
    print(f"Session pending_order: {request.session.get('pending_order')}")
    print(f"Session pending_payment_id: {request.session.get('pending_payment_id')}")
    print("=" * 50)
    
    pending_order = request.session.get('pending_order')
    pending_payment_id = request.session.get('pending_payment_id')
    
    if not pending_order or not pending_payment_id:
        messages.error(request, "Информация о заказе не найдена. Попробуйте оформить заказ заново.")
        print("ERROR: No data in session!")
        return redirect('cart_detail')
    
    # Проверяем статус платежа в ЮKassa
    try:
        from yookassa import Payment
        payment = Payment.find_one(pending_payment_id)
        print(f"Payment status: {payment.status}")
        
        if payment.status != 'succeeded':
            request.session.pop('pending_order', None)
            request.session.pop('pending_payment_id', None)
            messages.error(request, "Платёж не был завершён. Попробуйте снова.")
            return redirect('cart_detail')
    except Exception as e:
        print(f"ERROR checking payment: {e}")
        request.session.pop('pending_order', None)
        request.session.pop('pending_payment_id', None)
        messages.error(request, f"Ошибка при проверке оплаты: {e}")
        return redirect('cart_detail')
    
    # Восстанавливаем данные из сессии
    final_addresses = pending_order['final_addresses']
    phone = pending_order['phone']
    payment_method = pending_order['payment_method']
    total_cart_price = Decimal(str(pending_order['total_cart_price']))
    address_count = pending_order['address_count']
    points_per_order = pending_order['points_per_order']
    total_points_to_spend = Decimal(str(pending_order['total_points_to_spend']))
    delivery_time_str = pending_order.get('delivery_time')
    delivery_time = None
    if delivery_time_str:
        try:
            delivery_time = datetime.fromisoformat(delivery_time_str)
        except ValueError:
            pass
    
    print(f"Creating orders for {len(final_addresses)} addresses")
    
    profile = request.user.profile
    cart = Cart(request)
    created_orders = []
    
    try:
        for idx, addr_text in enumerate(final_addresses):
            points_used = Decimal(str(points_per_order[idx])) if idx < len(points_per_order) else 0
            current_order_price = total_cart_price - points_used
            
            order = Order.objects.create(
                user=request.user,
                address=addr_text,
                phone=phone,
                payment_method=payment_method,
                total_price=current_order_price,
                points_used=int(points_used),
                status='new',
                payment_id=pending_payment_id,
                is_paid=True,
                delivery_time=delivery_time,
            )
            
            print(f"Order #{order.id} created, total: {current_order_price}")
            
            for item in cart:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    price=item['price'],
                    quantity=item['quantity'],
                    comment=item.get('comment', '')
                )
            created_orders.append(order)
        
        # Списываем баллы
        if total_points_to_spend > 0:
            profile.points -= int(total_points_to_spend)
            profile.save()
        
        # Начисляем кэшбэк
        total_earned = 0
        for o in created_orders:
            earned = int(o.total_price * Decimal('0.05'))
            total_earned += earned
        profile.points += total_earned
        profile.save()
        
        # Очищаем корзину и сессию
        cart.clear()
        request.session.pop('pending_order', None)
        request.session.pop('pending_payment_id', None)
        
        # Отправка в ресторан
        for order in created_orders:
            try:
                success = send_order_to_restaurant(order)
                if success:
                    send_receipt_email(order)
            except Exception as e:
                print(f"Error sending to restaurant: {e}")
        
        request.session['open_receipt_id'] = created_orders[0].id
        
        messages.success(request, f"Order #{created_orders[0].id} created successfully!")
        
        return render(request, 'main/order_success.html', {
            'order': created_orders[0],
            'earned': total_earned,
            'count': address_count
        })
    
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        
        for o in created_orders:
            o.delete()
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
        order.courier = best_courier
        order.status = 'delivering'
        order.save()
        print(f"✅ Заказ #{order.id} автоматически назначен курьеру {best_courier.username}")
        return True
    return False


@staff_member_required
def get_support_users(request):
    """Получение списка пользователей с сообщениями для оператора"""
    
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
    """Сообщения конкретного пользователя"""
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
            'is_admin': False
        })
    return JsonResponse({'messages': data})


@staff_member_required
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product_name = product.name
    product.delete()
    messages.success(request, f"Блюдо '{product_name}' удалено")
    
    # Получаем адрес возврата из GET-параметра 'next', если нет — по умолчанию 'menu'
    next_url = request.GET.get('next', 'menu')
    return redirect(next_url)

@staff_member_required
def send_support_reply(request):
    """Отправка ответа от оператора"""
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


@login_required
def view_receipt(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'main/receipt.html', {'order': order})


@login_required
def payment_success_view_old(request, order_id):
    return redirect('payment_success')


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), id=order_id)
    
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
        'show_admin_info': user_is_admin
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
        order.courier = request.user
        order.status = 'delivering'
        order.delivery_order_index = active_count + 1
        order.save()
        messages.success(request, f"Вы приняли заказ №{order.id}!")
    else:
        messages.error(request, "Максимум 5 заказов одновременно!")
    
    return redirect('courier_map')


@login_required
def courier_complete_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, courier=request.user, status='delivering')
    order.status = 'completed'
    order.save()
    
    remaining_orders = Order.objects.filter(
        courier=request.user, 
        status='delivering'
    ).order_by('created_at')
    
    for idx, o in enumerate(remaining_orders, 1):
        o.delivery_order_index = idx
        o.save()
    
    messages.success(request, f"Заказ №{order.id} успешно доставлен!")
    return redirect('courier_map')


def courier_map(request):
    if not request.user.is_authenticated or request.user.profile.role != 'courier':
        return redirect('profile')
    
    my_orders = Order.objects.filter(courier=request.user, status='delivering').order_by('created_at')
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
        Product.objects.create(
            name=name, price=price, category_id=category_id,
            description=description, weight=weight, calories=calories,
            image=image
        )
        messages.success(request, "Блюдо успешно добавлено!")
    return redirect('menu')


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
        messages.success(request, f"Блюдо '{product.name}' обновлено")
        return redirect('menu')
    
    return render(request, 'main/edit_product.html', {
        'product': product,
        'categories': categories
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
        address_line = request.POST.get('address_line')
        if address_line:
            Address.objects.create(user=request.user, address_line=address_line)
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
    today = timezone.now().date()
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    report_orders = Order.objects.filter(status='completed')
    if start_date and end_date:
        report_orders = report_orders.filter(created_at__date__range=[start_date, end_date])
    else:
        report_orders = report_orders.filter(created_at__date=today)

    total_revenue = report_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    today_count = report_orders.count()
    avg_check = int(total_revenue / today_count) if today_count > 0 else 0
    
    popular_items_data = OrderItem.objects.filter(order__in=report_orders)\
        .values('product__name')\
        .annotate(total_qty=Sum('quantity'), total_sum=Sum(F('price') * F('quantity')))\
        .order_by('-total_qty')
    most_popular = popular_items_data.first() if popular_items_data else None

    orders_new = Order.objects.filter(status='new').prefetch_related('items__product').order_by('-created_at')
    orders_cooking = Order.objects.filter(status='cooking').prefetch_related('items__product').order_by('-created_at')
    orders_ready = Order.objects.filter(status='ready').prefetch_related('items__product').order_by('-created_at')
    orders_delivering = Order.objects.filter(status='delivering').prefetch_related('items__product').order_by('-created_at')
    orders_history = Order.objects.filter(status__in=['completed', 'cancelled']).order_by('-created_at')[:50]
    all_orders = Order.objects.all().prefetch_related('items__product')

    context = {
        'orders_new': orders_new, 
        'orders_cooking': orders_cooking,
        'orders_ready': orders_ready,
        'orders_delivering': orders_delivering,
        'orders_history': orders_history,
        'all_orders': all_orders,
        'total_revenue': total_revenue,
        'today_count': today_count,
        'avg_check': avg_check,
        'most_popular': most_popular,
        'popular_items_full': popular_items_data,
        'start_date': start_date,
        'end_date': end_date
    }
    
    return render(request, 'main/operator_panel.html', context)


@staff_member_required
def change_order_status(request, order_id, new_status):
    order = get_object_or_404(Order, id=order_id)
    
    old_status = order.status
    message = f"Статус заказа №{order.id} изменён"
    
    if old_status == 'new' and new_status == 'cooking':
        message = f"Заказ №{order.id} передан на кухню."
    elif old_status == 'cooking' and new_status == 'ready':
        message = f"Заказ №{order.id} готов к выдаче!"
    elif new_status == 'delivering':
        message = f"Заказ №{order.id} передан курьеру."
    elif new_status == 'completed':
        message = f"Заказ №{order.id} доставлен! Спасибо за заказ."
    elif new_status == 'cancelled':
        message = f"Заказ №{order.id} отменён."

    valid_statuses = ['new', 'cooking', 'ready', 'delivering', 'completed', 'cancelled']
    
    if new_status in valid_statuses:
        order.status = new_status
        order.save()
        
        # Получаем свежие счётчики для обновления через polling
        counts = {
            'new': Order.objects.filter(status='new').count(),
            'cooking': Order.objects.filter(status='cooking').count(),
            'ready': Order.objects.filter(status='ready').count(),
            'delivering': Order.objects.filter(status='delivering').count(),
        }
        
        # Автоматическое назначение курьера, если заказ стал готов
        if new_status == 'ready' and old_status != 'ready':
            auto_assign_order(order)
            print(f"🔔 Автоматическое назначение курьера для заказа #{order.id}")
        
        return JsonResponse({
            'status': 'ok',
            'message': message,
            'counts': counts,
            'order': {
                'id': order.id,
                'user': order.user.username,
                'address': order.address,
                'total_price': float(order.total_price),
                'created_at': order.created_at.strftime('%H:%M'),
            }
        })
    else:
        return JsonResponse({'status': 'error', 'message': 'Некорректный статус'}, status=400)


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
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('profile')
    else: 
        form = AuthenticationForm()
    return render(request, 'main/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "Вы вышли из системы.")
    return redirect('start')


def send_receipt_email(order):
    html_content = render_to_string('main/receipt.html', {'order': order}) 
    email = EmailMessage(
        f'Электронный чек по заказу №{order.id} — GINZA',
        html_content, 'noreply@ginzaproject.ru', [order.user.email],
    )
    email.content_subtype = "html"
    email.send()


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


def get_ai_recommendations(user, limit=4):
    if not user.is_authenticated:
        return Product.objects.filter(is_active=True).order_by('-id')[:limit]

    favorite_categories = OrderItem.objects.filter(order__user=user)\
        .values('product__category')\
        .annotate(count=Count('product__category'))\
        .order_by('-count')[:2]
    
    cat_ids = [item['product__category'] for item in favorite_categories]
    tried_products = OrderItem.objects.filter(order__user=user).values_list('product_id', flat=True)
    
    recommendations = Product.objects.filter(
        category_id__in=cat_ids,
        is_active=True
    ).exclude(id__in=tried_products).distinct()[:limit]

    if recommendations.count() < limit:
        additional = Product.objects.filter(is_active=True)\
            .exclude(id__in=recommendations.values_list('id', flat=True))[:limit - recommendations.count()]
        recommendations = list(recommendations) + list(additional)

    return recommendations


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
        address_line = request.POST.get('address_line')
        if address_line:
            city_prefix = "Байконур, "
            if not address_line.startswith(city_prefix):
                address_line = city_prefix + address_line
            
            is_valid, lat, lng = validate_address(address_line)
            if not is_valid:
                return JsonResponse({'status': 'error', 'message': 'Адрес не найден. Укажите улицу и номер дома'}, status=400)
            
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


@login_required
def check_single_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return JsonResponse({
        'order_id': order.id,
        'status': order.status,
        'status_display': order.get_status_display()
    })


@login_required
def send_support_message(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Метод не разрешён'}, status=405)
    
    text = request.POST.get('text', '').strip()
    file = request.FILES.get('file')
    
    if not text and not file:
        return JsonResponse({'status': 'error', 'message': 'Введите текст или прикрепите файл'}, status=400)
    
    msg = SupportMessage.objects.create(
        user=request.user,
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