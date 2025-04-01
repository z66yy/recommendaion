from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile/', views.profile_view, name='profile'),
    path('favorites/', views.favorites_view, name='favorites'),
    path('history/', views.history_view, name='history'),
    path('favorite/<int:movie_id>/', views.toggle_favorite, name='toggle_favorite'),
    path('api/check_favorite/<int:movie_id>/', views.check_favorite, name='check_favorite'),
] 