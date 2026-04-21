from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone



# --- ТЕГИ (Острое, Веган и т.д.) ---
class Tag(models.Model):
    name = models.CharField("Название", max_length=50)
    icon_class = models.CharField("Bootstrap Icon Class", max_length=50, help_text="Например: bi-fire") 

    def __str__(self):
        return self.name

# --- ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ---
class Profile(models.Model):
    # Добавляем роли для пользователей (Клиент или Доставщик)
    ROLE_CHOICES = [
        ('client', 'Клиент'),
        ('courier', 'Доставщик'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Пользователь")
    role = models.CharField("Роль", max_length=10, choices=ROLE_CHOICES, default='client')
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Телефон")
    address = models.TextField(blank=True, null=True, verbose_name="Основной адрес доставки")
    points = models.IntegerField(default=0, verbose_name="Бонусные баллы")
    is_online = models.BooleanField(default=False, verbose_name="Онлайн")
    
    # Поля для доставщика (координаты в реальном времени)
    last_lat = models.FloatField(null=True, blank=True)
    last_lng = models.FloatField(null=True, blank=True)
    last_updated = models.DateTimeField(null=True, blank=True)
    

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return f'Профиль {self.user.username} ({self.get_role_display()})'

# --- КАТЕГОРИИ И ТОВАРЫ ---
class Category(models.Model):
    name = models.CharField('Название категории', max_length=100)
    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
    def __str__(self):
        return self.name

class Product(models.Model):
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE, verbose_name='Категория')
    name = models.CharField('Название блюда', max_length=255)
    description = models.TextField('Описание (состав)', blank=True)
    price = models.DecimalField('Цена', max_digits=10, decimal_places=2)
    weight = models.IntegerField('Вес (гр/мл)', null=True, blank=True)
    calories = models.IntegerField('Калорийность (ккал)', null=True, blank=True, default=0, validators=[MinValueValidator(0), MaxValueValidator(2000)])
    image = models.ImageField('Фото блюда', upload_to='products/', blank=True, null=True)
    is_active = models.BooleanField('В наличии', default=True)
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="Теги")
    
    class Meta:
        verbose_name = 'Блюдо'
        verbose_name_plural = 'Блюда'
    
    def get_rating(self):
        reviews = self.reviews.all()
        if not reviews: return 0
        return sum(r.rating for r in reviews) / reviews.count()

    def __str__(self):
        return self.name

# --- ОТЗЫВЫ ---
class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField("Оценка", default=5)
    text = models.TextField("Текст отзыва")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Отзыв"
        verbose_name_plural = "Отзывы"

# --- АДРЕСА ---
class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    address_line = models.CharField("Адрес", max_length=255)
    lat = models.FloatField("Широта", null=True, blank=True) # Для точного построения маршрута
    lng = models.FloatField("Долгота", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        verbose_name = "Адрес"
        verbose_name_plural = "Адреса"

# --- ЗАКАЗЫ (ГЛАВНАЯ МОДЕЛЬ С ЛОГИКОЙ ДОСТАВКИ) ---
class Order(models.Model):
    STATUS_CHOICES = [
        ('new', 'Новый'), 
        ('cooking', 'Готовится'), 
        ('ready', 'Готов к выдаче'),
        ('delivering', 'В пути'), 
        ('completed', 'Завершен'), 
        ('cancelled', 'Отменен')
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    
    courier = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='deliveries',
        verbose_name="Назначенный доставщик"
    )
    
    address = models.CharField('Адрес доставки', max_length=500) 
    phone = models.CharField('Телефон', max_length=20)
    payment_method = models.CharField('Способ оплаты', max_length=20)
    total_price = models.DecimalField('Общая сумма', max_digits=10, decimal_places=2)
    points_used = models.IntegerField(default=0)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)   # ОДИН РАЗ
    
    delivery_order_index = models.PositiveSmallIntegerField("Порядок в маршруте", default=0)

    payment_id = models.CharField('ID транзакции ЮKassa', max_length=255, null=True, blank=True)
    is_paid = models.BooleanField('Оплачено', default=False)

    fiscal_fd = models.CharField('Номер ФД', max_length=20, null=True, blank=True)
    fiscal_fp = models.CharField('Фискальный признак ФП', max_length=20, null=True, blank=True)
    fiscal_fn = models.CharField('Номер ФН', max_length=30, null=True, blank=True)
    fiscal_kkt = models.CharField('Имя ККТ', max_length=100, null=True, blank=True)

    # НОВОЕ ПОЛЕ
    delivery_time = models.DateTimeField(
        verbose_name="Желаемое время доставки",
        null=True, blank=True,
        help_text="Выберите дату и время, когда вам удобно получить заказ"
    )

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'

    def __str__(self):
        return f"Заказ #{self.id} от {self.user.username}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    comment = models.CharField(max_length=255, blank=True, null=True)

# Модель для ИИ-рекомендаций
class ProductRecommendation(models.Model):
    source_product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='main_prod')
    recommended_product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='suggested_prod')
    score = models.FloatField(default=0.0)

    class Meta:
        verbose_name = "Рекомендация ИИ"
        unique_together = ('source_product', 'recommended_product')

# Модель для настроек ресторана
class RestaurantConfig(models.Model):
    name = models.CharField("Название филиала", max_length=100, default="GINZA")
    address = models.CharField(max_length=255, verbose_name="Адрес ресторана")
    working_hours = models.CharField(max_length=100, verbose_name="График работы (напр. 10:00-22:00)")
    location_coords = models.CharField(max_length=100, blank=True, verbose_name="Координаты (широта, долгота)")

    class Meta:
        verbose_name = "Настройки ресторана"
        verbose_name_plural = "Настройки ресторана"

class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    class Meta:
        unique_together = ('user', 'product')

class OrderMessage(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username}: {self.text[:20]}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created: Profile.objects.get_or_create(user=instance)

class SupportMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='support_messages')
    text = models.TextField(verbose_name="Текст сообщения")
    file = models.FileField(upload_to='support_files/', blank=True, null=True, verbose_name="Вложение")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    is_from_admin = models.BooleanField(default=False, verbose_name="Отправлено оператором")

    class Meta:
        verbose_name = "Сообщение поддержки"
        verbose_name_plural = "Сообщения поддержки"
        ordering = ['created_at']

    def __str__(self):
        return f"{self.user.username} - {self.created_at.strftime('%d.%m.%Y %H:%M')}"