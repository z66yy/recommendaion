from django.urls import path
from . import views

app_name = 'recommender'

urlpatterns = [
    path('recommendations/', views.user_recommendations, name='user_recommendations'),
    path('movie/<int:movie_id>/similar/', views.movie_recommendations, name='movie_recommendations'),
] 