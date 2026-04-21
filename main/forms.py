from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Profile
from django.core.exceptions import ValidationError
import re

class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})
        
        # Кастомные сообщения-подсказки
        self.fields['password1'].help_text = None
        self.fields['password1'].widget.attrs['placeholder'] = 'Придумайте надежный пароль'
        self.fields['password2'].widget.attrs['placeholder'] = 'Повторите пароль'

    def clean_password1(self):
        password = self.cleaned_data.get('password1')
        errors = []
        
        if len(password) < 8:
            errors.append('Пароль должен содержать минимум 8 символов.')
        if not re.search(r'[A-Z]', password):
            errors.append('Пароль должен содержать хотя бы одну заглавную букву (A-Z).')
        if not re.search(r'[a-z]', password):
            errors.append('Пароль должен содержать хотя бы одну строчную букву (a-z).')
        if not re.search(r'\d', password):
            errors.append('Пароль должен содержать хотя бы одну цифру (0-9).')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            errors.append('Пароль должен содержать хотя бы один спецсимвол (!@#$%^&*).')
        
        if errors:
            raise ValidationError(' '.join(errors))
        
        return password

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['phone', 'address']
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Телефон'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Ваш адрес'}),
        }