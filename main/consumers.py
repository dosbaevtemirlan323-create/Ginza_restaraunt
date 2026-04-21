# main/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

# Убираем импорты моделей из верхнего уровня
# from django.contrib.auth.models import User
# from .models import Order, Profile

class CourierConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_authenticated:
            self.group_name = 'couriers_all'
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
            print(f"✅ Курьер {self.user.username} подключен")
            
            # Отправляем текущие заказы
            await self.send_available_orders()
        else:
            await self.close()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
    
    @database_sync_to_async
    def get_available_orders(self):
        from .models import Order
        orders = Order.objects.filter(status='ready', courier__isnull=True).select_related('user')
        return [{
            'id': order.id,
            'address': order.address,
            'total_price': float(order.total_price),
            'created_at': order.created_at.strftime('%H:%M'),
            'client_name': order.user.username,
            'client_phone': order.user.profile.phone if order.user.profile.phone else order.phone,
        } for order in orders]
    
    async def send_available_orders(self):
        orders = await self.get_available_orders()
        await self.send(text_data=json.dumps({
            'type': 'initial_orders',
            'orders': orders,
            'count': len(orders)
        }))
    
    # ЭТОТ МЕТОД ВАЖЕН - он вызывается при отправке уведомления
    async def new_order_notification(self, event):
        print(f"📨 Отправка уведомления курьеру {self.user.username} о заказе #{event['order_id']}")
        await self.send(text_data=json.dumps({
            'type': 'new_order',
            'order_id': event['order_id'],
            'address': event['address'],
            'total_price': event['total_price'],
            'client_name': event['client_name'],
            'message': event['message']
        }))


class OperatorConsumer(AsyncWebsocketConsumer):
    """WebSocket для операторов"""
    
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_authenticated and self.user.is_staff:
            self.group_name = f'operator_{self.user.id}'
            self.all_operators_group = 'operators_all'
            
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.channel_layer.group_add(self.all_operators_group, self.channel_name)
            await self.accept()
            print(f"✅ Оператор {self.user.username} подключен к WebSocket")
        else:
            await self.close()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if hasattr(self, 'all_operators_group'):
            await self.channel_layer.group_discard(self.all_operators_group, self.channel_name)
    
    async def order_created_notification(self, event):
        await self.send(text_data=json.dumps({
            'type': 'order_created',
            'order_id': event['order_id'],
            'message': event['message'],
            'sound': True
        }))
    
    async def order_status_changed(self, event):
        """Обновление статуса заказа - отправляем оператору новые счётчики"""
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'order_id': event['order_id'],
            'new_status': event['new_status'],
            'old_status': event['old_status'],
            'counts': event['counts'],
            'message': event['message']
        }))

class UserConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user_id = self.scope['url_route']['kwargs']['user_id']
        self.user = self.scope['user']
        if self.user.is_authenticated and str(self.user.id) == self.user_id:
            self.group_name = f'user_{self.user_id}'
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def order_status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'order_id': event['order_id'],
            'status': event['status'],
            'status_display': event['status_display'],
            'message': event['message']
        }))