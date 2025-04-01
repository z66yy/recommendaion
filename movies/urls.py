from django.urls import path, re_path
from . import views

app_name = 'movies'

urlpatterns = [
    path('list/', views.movie_list, name='movie_list'),
    path('genre/<str:genre_name>/', views.movie_list_by_genre, name='movie_list_by_genre'),
    path('detail/<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('detail/<int:movie_id>/', views.movie_detail, name='detail'),
    path('search/', views.search_movies, name='search'),
    path('rate/<int:movie_id>/', views.rate_movie, name='rate_movie'),
    path('comment/<int:movie_id>/', views.comment_movie, name='comment_movie'),
    re_path(r'^image-proxy/(?P<image_url>.+)$', views.image_proxy, name='image_proxy'),
] 