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
    ROLE_CHOICES = [
        ('client', 'Клиент'),
        ('courier', 'Доставщик'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Пользователь")
    role = models.CharField("Роль", max_length=10, choices=ROLE_CHOICES, default='client')
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Телефон")
    points = models.IntegerField(default=0, verbose_name="Бонусные баллы")
    is_online = models.BooleanField(default=False, verbose_name="Онлайн")

    # Поля для доставщика (координаты в реальном времени)
    last_lat = models.FloatField(null=True, blank=True)
    last_lng = models.FloatField(null=True, blank=True)
    last_coords_update = models.DateTimeField(null=True, blank=True, verbose_name="Время обновления координат")

    class Meta:
        verbose_name = 'Профиль'
        verbose_name_plural = 'Профили'

    def __str__(self):
        return f'Профиль {self.user.username} ({self.get_role_display()})'


# --- МОДЕЛЬ АДРЕСОВ ДОСТАВКИ (новая) ---
class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    address_line = models.CharField("Адрес", max_length=255)
    lat = models.FloatField("Широта", null=True, blank=True)
    lng = models.FloatField("Долгота", null=True, blank=True)
    is_default = models.BooleanField("Адрес по умолчанию", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Адрес"
        verbose_name_plural = "Адреса"

    def __str__(self):
        return f"{self.user.username} - {self.address_line}"


# --- КАТЕГОРИИ И ТОВАРЫ ---
class Category(models.Model):
    name = models.CharField('Название категории', max_length=100)

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'

    def __str__(self):
        return self.name


class Product(models.Model):
    DISH_TYPE_CHOICES = [
        ('salad', 'Салат'),
        ('soup', 'Суп'),
        ('main', 'Горячее блюдо'),
        ('side', 'Гарнир'),
        ('sauce', 'Соус'),
        ('drink', 'Напиток'),
        ('dessert', 'Десерт'),
        ('other', 'Другое'),
    ]
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE, verbose_name='Категория')
    name = models.CharField('Название блюда', max_length=255)
    description = models.TextField('Описание (состав)', blank=True)
    price = models.DecimalField('Цена', max_digits=10, decimal_places=2)
    weight = models.IntegerField('Вес (гр/мл)', null=True, blank=True)
    calories = models.IntegerField('Калорийность (ккал)', null=True, blank=True, default=0,
                                   validators=[MinValueValidator(0), MaxValueValidator(2000)])
    image = models.ImageField('Фото блюда', upload_to='products/', blank=True, null=True)
    is_active = models.BooleanField('В наличии', default=True)
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="Теги")
    dish_type = models.CharField('Тип блюда', max_length=20, choices=DISH_TYPE_CHOICES, default='other')

    class Meta:
        verbose_name = 'Блюдо'
        verbose_name_plural = 'Блюда'

    def get_rating(self):
        reviews = self.reviews.all()
        if not reviews:
            return 0
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


# --- ЗАКАЗЫ (ГЛАВНАЯ МОДЕЛЬ) ---
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
    
    # Новое поле: имя курьера (строка, а не ForeignKey)
    courier = models.CharField("Курьер (ФИО)", max_length=150, blank=True, null=True)
    courier_order_index = models.IntegerField("Порядок в маршруте курьера", default=0)
    
    address = models.CharField('Адрес доставки', max_length=500)
    phone = models.CharField('Телефон', max_length=20)
    payment_method = models.CharField('Способ оплаты', max_length=20)
    total_price = models.DecimalField('Общая сумма', max_digits=10, decimal_places=2)
    points_used = models.IntegerField(default=0)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    is_operator_viewed = models.BooleanField(default=False, verbose_name="Оператор просмотрел")

    # ВОЗВРАЩАЕМ СТАРОЕ НАЗВАНИЕ: payment_id (не payment_transaction_id)
    payment_id = models.CharField('ID транзакции ЮKassa', max_length=255, null=True, blank=True)
    is_paid = models.BooleanField('Оплачено', default=False)

    # Желаемое время доставки
    delivery_time_from = models.DateTimeField(
        verbose_name="Желаемое время доставки (с)",
        null=True, blank=True,
        help_text="Начало интервала"
    )
    delivery_time_to = models.DateTimeField(
        verbose_name="Желаемое время доставки (по)",
        null=True, blank=True,
        help_text="Конец интервала"
    )

    # Фискальные данные
    fiscal_fd = models.CharField('Номер ФД', max_length=20, null=True, blank=True)
    fiscal_fp = models.CharField('Фискальный признак ФП', max_length=20, null=True, blank=True)
    fiscal_fn = models.CharField('Номер ФН', max_length=30, null=True, blank=True)
    fiscal_kkt = models.CharField('Имя ККТ', max_length=100, null=True, blank=True)  # не kkt_name

    # ВОЗВРАЩАЕМ СТАРЫЕ НАЗВАНИЯ: lat, lng (не delivery_latitude, delivery_longitude)
    lat = models.FloatField("Широта адреса доставки", null=True, blank=True)
    lng = models.FloatField("Долгота адреса доставки", null=True, blank=True)
    route_order = models.PositiveSmallIntegerField(
        "Порядок в оптимальном маршруте",
        default=0,
        help_text="Рассчитывается автоматически для курьера"
    )

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        indexes = [
            models.Index(fields=['status', 'route_order']),
        ]

    def __str__(self):
        return f"Заказ #{self.id} от {self.user.username}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    comment = models.CharField(max_length=255, blank=True, null=True)


# --- ИСТОРИЯ СМЕНЫ СТАТУСОВ ЗАКАЗА ---
class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    old_status = models.CharField(
        max_length=20,
        choices=Order.STATUS_CHOICES,
        blank=True, null=True
    )
    new_status = models.CharField(max_length=20, choices=Order.STATUS_CHOICES)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name="Кто изменил")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "История статуса заказа"
        verbose_name_plural = "Истории статусов заказов"
        ordering = ['created_at']

    def __str__(self):
        return f"Заказ {self.order.id}: {self.old_status} → {self.new_status} в {self.created_at}"


# --- РЕКОМЕНДАЦИИ ---
class ProductRecommendation(models.Model):
    SOURCE_TYPES = (
        ('product', 'Продукт'),
        ('category', 'Категория'),
        ('user', 'Пользователь'),
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES, default='product')
    source_product = models.ForeignKey(
        Product, on_delete=models.CASCADE,
        null=True, blank=True, related_name='recommendations_as_source'
    )
    source_category = models.ForeignKey(
        Category, on_delete=models.CASCADE,
        null=True, blank=True
    )
    source_user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        null=True, blank=True
    )
    recommended_products = models.ManyToManyField(
        Product,
        through='RecommendationItem',
        related_name='recommendations_as_target',
        verbose_name="Рекомендуемые товары"
    )

    class Meta:
        verbose_name = "Рекомендация"
        verbose_name_plural = "Рекомендации"
        unique_together = [['source_type', 'source_product', 'source_category', 'source_user']]

    def __str__(self):
        if self.source_type == 'product' and self.source_product:
            return f"Из {self.source_product.name}"
        elif self.source_type == 'category' and self.source_category:
            return f"Из категории {self.source_category.name}"
        elif self.source_type == 'user' and self.source_user:
            return f"Для пользователя {self.source_user.username}"
        return "Рекомендация"


class RecommendationItem(models.Model):
    recommendation = models.ForeignKey(ProductRecommendation, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    score = models.FloatField(default=0.0, verbose_name="Вес рекомендации")
    pairing_type = models.CharField(max_length=50, blank=True, verbose_name="Тип сочетания")

    class Meta:
        unique_together = ('recommendation', 'product')
        verbose_name = "Элемент рекомендации"
        verbose_name_plural = "Элементы рекомендаций"


# --- НАСТРОЙКИ РЕСТОРАНА (новая модель) ---
class RestaurantSettings(models.Model):
    branch_name = models.CharField("Название филиала", max_length=100)
    address = models.CharField("Адрес ресторана", max_length=255)
    working_hours = models.CharField("График работы", max_length=100)
    latitude = models.FloatField("Широта")
    longitude = models.FloatField("Долгота")

    class Meta:
        verbose_name = "Настройки ресторана"
        verbose_name_plural = "Настройки ресторана"

    def __str__(self):
        return self.branch_name


# --- СТАРЫЕ НАСТРОЙКИ (оставлено для совместимости, в будущем удалить) ---
class RestaurantConfig(models.Model):
    name = models.CharField("Название филиала", max_length=100, default="GINZA")
    address = models.CharField(max_length=255, verbose_name="Адрес ресторана")
    working_hours = models.CharField(max_length=100, verbose_name="График работы (напр. 10:00-22:00)")
    location_coords = models.CharField(max_length=100, blank=True, verbose_name="Координаты (широта, долгота)")

    class Meta:
        verbose_name = "Настройки ресторана (старая)"
        verbose_name_plural = "Настройки ресторана (старые)"


# --- ИЗБРАННОЕ ---
class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'product')


# --- ЧАТ МЕЖДУ КЛИЕНТОМ И КУРЬЕРОМ/ОПЕРАТОРОМ ПО ЗАКАЗУ ---
class OrderMessage(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.username}: {self.text[:20]}"


# --- СКИДКИ ---
class Discount(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('percent', 'Процент'),
        ('fixed', 'Фиксированная сумма'),
    ]
    APPLIES_TO_CHOICES = [
        ('all', 'Всё меню'),
        ('category', 'Категория'),
        ('product', 'Конкретное блюдо'),
    ]

    name = models.CharField("Название скидки", max_length=100)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES, default='percent')
    value = models.DecimalField("Значение", max_digits=10, decimal_places=2, help_text="Процент или сумма в рублях")
    applies_to = models.CharField(max_length=20, choices=APPLIES_TO_CHOICES, default='all')
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True, blank=True,
                                 verbose_name="Категория (если applies_to=category)")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True,
                                verbose_name="Блюдо (если applies_to=product)")
    active = models.BooleanField("Активна", default=True)
    start_date = models.DateTimeField("Начало действия")
    end_date = models.DateTimeField("Конец действия")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Скидка"
        verbose_name_plural = "Скидки"

    def __str__(self):
        return f"{self.name} ({self.get_discount_type_display()} {self.value})"


# --- АВТОМАТИЧЕСКОЕ СОЗДАНИЕ ПРОФИЛЯ ПРИ РЕГИСТРАЦИИ ---
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)

@receiver(post_save, sender=Order)
def update_recommendations_from_order(sender, instance, created, **kwargs):
    """
    Обновляет рекомендации на основе завершённого заказа.
    """
    if instance.status != 'completed':
        return

    product_ids = list(instance.items.values_list('product_id', flat=True))
    if len(product_ids) < 2:
        return

    for i in range(len(product_ids)):
        for j in range(i+1, len(product_ids)):
            p1 = product_ids[i]
            p2 = product_ids[j]
            # Направление p1 -> p2
            rec, _ = ProductRecommendation.objects.get_or_create(
                source_type='product',
                source_product_id=p1,
                defaults={'source_category': None, 'source_user': None}
            )
            item, created = RecommendationItem.objects.get_or_create(
                recommendation=rec,
                product_id=p2,
                defaults={'score': 1.0, 'pairing_type': 'co_purchase'}
            )
            if not created:
                item.score += 1.0
                item.save()

            # Направление p2 -> p1 (симметрично)
            rec2, _ = ProductRecommendation.objects.get_or_create(
                source_type='product',
                source_product_id=p2,
                defaults={'source_category': None, 'source_user': None}
            )
            item2, created2 = RecommendationItem.objects.get_or_create(
                recommendation=rec2,
                product_id=p1,
                defaults={'score': 1.0, 'pairing_type': 'co_purchase'}
            )
            if not created2:
                item2.score += 1.0
                item2.save()
