from django import template

register = template.Library()

@register.filter
def status_color(status):
    """Возвращает класс Bootstrap для цвета бейджа статуса."""
    colors = {
        'new': 'warning',
        'cooking': 'primary',
        'ready': 'success',
        'delivering': 'info',
        'completed': 'success',
        'cancelled': 'danger',
    }
    return colors.get(status, 'secondary')