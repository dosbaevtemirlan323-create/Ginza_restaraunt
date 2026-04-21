from django.contrib import admin
from .models import Category, Product, Order, OrderItem, ProductRecommendation, RestaurantConfig, OrderMessage

# Регистрируем новые модели, чтобы они появились в панели управления
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'weight', 'is_active']
    list_filter = ['category', 'is_active']
    search_fields = ['name']

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'total_price', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    inlines = [OrderItemInline]

admin.site.register(ProductRecommendation)
admin.site.register(RestaurantConfig)
admin.site.register(OrderMessage)