import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant.settings')
django.setup()

from main.models import ProductRecommendation, RecommendationItem, Category, Product

try:
    salad_cat = Category.objects.get(name='Салаты')
    rec, created = ProductRecommendation.objects.get_or_create(
        source_type='category',
        source_category=salad_cat
    )
    hot_products = Product.objects.filter(is_active=True)[:5]
    for prod in hot_products:
        RecommendationItem.objects.get_or_create(
            recommendation=rec,
            product=prod,
            defaults={'score': 1.0, 'pairing_type': 'salad_main'}
        )
    print(f"✅ Создано рекомендаций: {len(hot_products)} для категории 'Салаты'")
except Category.DoesNotExist:
    print("❌ Категория 'Салаты' не найдена. Создайте её сначала.")