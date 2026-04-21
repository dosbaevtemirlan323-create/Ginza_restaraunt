from django import template

register = template.Library()

@register.simple_tag
def get_cart_item_quantity(cart, product_id):
    """Возвращает количество товара в корзине для отображения кнопок +/-"""
    if not cart:
        return 0
    
    # В сессиях Django ключи всегда строки
    p_id = str(product_id)
    
    # Пытаемся достать количество в зависимости от структуры твоего класса Cart
    if hasattr(cart, 'cart'):
        return cart.cart.get(p_id, {}).get('quantity', 0)
    return cart.get(p_id, {}).get('quantity', 0)