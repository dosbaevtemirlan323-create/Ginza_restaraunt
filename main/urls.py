# main/urls.py (исправленный)
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    # --- ГЛАВНАЯ И МЕНЮ ---
    path('', views.start, name='start'),
    path('menu/', views.menu_view, name='menu'),
    
    # --- КОРЗИНА ---
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('cart/subtract/<int:product_id>/', views.cart_subtract, name='cart_subtract'),
    path('cart/remove/<int:product_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('product/delete/<int:product_id>/', views.delete_product, name='delete_product'),
    
    # Комментарии к товарам
    path('update_comment/<int:product_id>/', views.update_item_comment, name='update_comment'),
    
    # --- ИЗБРАННОЕ ---
    path('favorites/', views.favorites_list, name='favorites_list'),
    path('toggle-favorite/<int:product_id>/', views.toggle_favorite, name='toggle_favorite'),
    
    # --- ЗАКАЗЫ ---
    path('order/create/', views.order_create, name='order_create'),
    path('order/<int:order_id>/', views.order_detail, name='order_detail'),
    path('order/repeat/<int:order_id>/', views.order_repeat, name='repeat_order'),
    path('order/status/<int:order_id>/<str:new_status>/', views.change_order_status, name='change_order_status'),
    
    # --- ОПЛАТА ---
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment-success/<int:order_id>/', views.payment_success_view_old, name='payment_success_old'),
    path('receipt/<int:order_id>/', views.view_receipt, name='view_receipt'),
    path('api/check-order-status/<int:order_id>/', views.check_single_order_status, name='check_single_order_status'),
    
    # --- ПРОФИЛЬ И АДРЕСА ---
    path('profile/', views.profile_view, name='profile'),
    path('profile/update/', views.update_profile, name='update_profile'),
    path('address/add/', views.add_address, name='add_address'),
    path('address/delete/<int:address_id>/', views.delete_address, name='delete_address'),
    path('add_address_ajax/', views.add_address_ajax, name='add_address_ajax'),
    path('api/operator/counts/', views.get_order_counts, name='operator_counts'),
    
    # --- АВТОРИЗАЦИЯ ---
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # --- ПАНЕЛЬ ОПЕРАТОРА И API ---
    path('operator/', views.operator_panel, name='operator_panel'),
    path('api/check-last-order-status/', views.check_order_status, name='check_order_status'),
    path('get-single-rec/', views.get_single_recommendation, name='get_single_rec'),
    
    # --- УПРАВЛЕНИЕ ТОВАРАМИ (АДМИНКА) ---
    path('product/add/', views.add_product, name='add_product'),
    path('product/edit/<int:product_id>/', views.edit_product, name='edit_product'),
    path('product/toggle/<int:pk>/', views.toggle_active, name='toggle_active'),
    path('product/<int:product_id>/review/', views.add_review, name='add_review'),
    
    # --- КУРЬЕРСКАЯ СЛУЖБА ---
    path('courier/take/<int:order_id>/', views.courier_take_order, name='courier_take_order'),
    path('courier/complete/<int:order_id>/', views.courier_complete_order, name='courier_complete_order'),
    path('courier/map/', views.courier_map, name='courier_map'),
    path('management/create-courier/', views.create_courier_view, name='create_courier'),
    path('update-courier-location/', views.update_courier_location, name='update_courier_location'),
    path('order/<int:order_id>/messages/', views.get_order_messages, name='get_order_messages'),
    path('order/<int:order_id>/send_message/', views.send_message, name='send_message'),
    
    # --- УПРАВЛЕНИЕ КАТЕГОРИЯМИ И ЗАКАЗАМИ ---
    path('category/add/', views.add_category, name='add_category'),
    path('category/edit/<int:category_id>/', views.edit_category, name='edit_category'),
    path('category/delete/<int:category_id>/', views.delete_category, name='delete_category'),
    path('order-item/update/<int:item_id>/<str:action>/', views.update_order_item, name='update_order_item'),
    path('order-item/remove/<int:item_id>/', views.remove_order_item, name='remove_order_item'),
    path('api/support/messages/', views.get_support_messages, name='support_messages'),
    path('api/support/send/', views.send_support_message, name='send_support_message'),
    path('api/support/admin/users/', views.get_support_users, name='support_admin_users'),
    path('api/support/admin/messages/<int:user_id>/', views.get_user_messages, name='support_user_messages'),
    path('api/support/admin/reply/', views.send_support_reply, name='support_admin_reply'),
    path('api/online-couriers/', views.get_online_couriers, name='online_couriers'),
    path('api/operator/new-orders/', views.get_new_orders, name='new_orders_api'),


    
    # --- СБРОС ПАРОЛЯ ---
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(template_name='main/password_reset_form.html'), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(template_name='main/password_reset_done.html'), 
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name='main/password_reset_confirm.html'), 
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name='main/password_reset_complete.html'), 
         name='password_reset_complete'),
]