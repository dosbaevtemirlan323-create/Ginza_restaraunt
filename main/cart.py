from decimal import Decimal
from django.conf import settings
from .models import Product

class Cart:
    def __init__(self, request):
        self.session = request.session
        cart = self.session.get('cart')
        if not cart:
            cart = self.session['cart'] = {}
        self.cart = cart

    def __len__(self):
        return sum(item['quantity'] for item in self.cart.values())

    def __iter__(self):
        product_ids = self.cart.keys()
        products = Product.objects.filter(id__in=product_ids)
        cart = self.cart.copy()
        
        for product in products:
            # ОБЯЗАТЕЛЬНО str(product.id), так как ключи в сессии - строки
            pid = str(product.id)
            if pid in cart:
                cart[pid]['product'] = product

        for item in cart.values():
            item['price'] = Decimal(item['price'])
            item['total_price'] = item['price'] * item['quantity']
            item['comment'] = item.get('comment', '')
            yield item

            
    def get_total_price_multiplied(self, address_count=1):
        """Возвращает общую сумму, умноженную на количество адресов"""
        if address_count < 1:
            address_count = 1
        return self.get_total_price() * address_count

    def add(self, product, quantity=1, override_quantity=False):
        product_id = str(product.id)
        if product_id not in self.cart:
            self.cart[product_id] = {'quantity': 0, 'price': str(product.price), 'comment': ''}
        
        if override_quantity:
            self.cart[product_id]['quantity'] = int(quantity)
        else:
            self.cart[product_id]['quantity'] += int(quantity)
        self.save()

    def subtract(self, product_id):
        product_id = str(product_id)
        if product_id in self.cart:
            self.cart[product_id]['quantity'] -= 1
            if self.cart[product_id]['quantity'] <= 0:
                del self.cart[product_id]
            self.save()

    def update_comment(self, product_id, comment):
        product_id = str(product_id)
        if product_id in self.cart:
            self.cart[product_id]['comment'] = comment
            self.save()

    def save(self):
        self.session.modified = True

    def remove(self, product):
        product_id = str(product.id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def get_total_price(self):
        return sum(Decimal(item['price']) * item['quantity'] for item in self.cart.values())

    def clear(self):
        del self.session['cart']
        self.save()