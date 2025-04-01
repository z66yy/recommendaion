from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User

class UserRegistrationForm(UserCreationForm):
    """用户注册表单"""
    class Meta:
        model = User
        fields = ('username', 'password1', 'password2')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = '用户名'
        self.fields['password1'].label = '密码'
        self.fields['password2'].label = '确认密码'
        
        # 自定义错误消息
        self.error_messages.update({
            'password_mismatch': '两次输入的密码不一致',
        })

class UserProfileForm(forms.ModelForm):
    """用户个人资料表单"""
    class Meta:
        model = User
        fields = ('nickname', 'avatar', 'bio')
        labels = {
            'nickname': '昵称',
            'avatar': '头像',
            'bio': '个人简介',
        }
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 3}),
        } 