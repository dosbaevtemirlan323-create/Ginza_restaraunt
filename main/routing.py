from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/courier/$', consumers.CourierConsumer.as_asgi()),
    re_path(r'ws/operator/$', consumers.OperatorConsumer.as_asgi()),
    re_path(r'ws/user/(?P<user_id>\d+)/$', consumers.UserConsumer.as_asgi()),
]