from django.core.management.base import BaseCommand
from main.models import OrderItem, Product, ProductRecommendation
from collections import Counter, defaultdict

class Command(BaseCommand):
    help = 'Заполняет таблицу ProductRecommendation на основе истории заказов'

    def handle(self, *args, **options):
        self.stdout.write("Анализ заказов...")
        
        # Группируем товары по заказам
        order_items = OrderItem.objects.filter(order__status='completed').select_related('product')
        orders_dict = defaultdict(list)
        for item in order_items:
            orders_dict[item.order_id].append(item.product.id)
        
        # Считаем пары товаров
        pair_counter = Counter()
        for product_ids in orders_dict.values():
            product_ids = list(set(product_ids))  # уникальные в заказе
            for i in range(len(product_ids)):
                for j in range(i + 1, len(product_ids)):
                    a, b = product_ids[i], product_ids[j]
                    if a != b:
                        pair_counter[(a, b)] += 1
                        pair_counter[(b, a)] += 1
        
        # Очищаем старые рекомендации
        ProductRecommendation.objects.all().delete()
        
        # Создаём новые
        created = 0
        for (src_id, rec_id), count in pair_counter.items():
            try:
                src = Product.objects.get(id=src_id)
                rec = Product.objects.get(id=rec_id)
                ProductRecommendation.objects.create(
                    source_product=src,
                    recommended_product=rec,
                    score=count
                )
                created += 1
            except Product.DoesNotExist:
                continue
        
        self.stdout.write(self.style.SUCCESS(f'Создано {created} рекомендаций'))