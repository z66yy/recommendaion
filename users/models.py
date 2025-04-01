from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from movies.models import Movie

class User(AbstractUser):
    """用户模型"""
    nickname = models.CharField('昵称', max_length=50, blank=True)
    avatar = models.ImageField('头像', upload_to='user_avatars/', blank=True)
    bio = models.TextField('个人简介', max_length=500, blank=True)
    
    class Meta:
        verbose_name = '用户'
        verbose_name_plural = verbose_name
        
    def __str__(self):
        return self.username

class UserFavorite(models.Model):
    """用户收藏"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户', related_name='favorites')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, verbose_name='电影', related_name='favorited_by')
    created_time = models.DateTimeField('收藏时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '用户收藏'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'movie']
        ordering = ['-created_time']
        
    def __str__(self):
        return f'{self.user.username} 收藏 {self.movie.title}'

class UserRating(models.Model):
    """用户评分"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户', related_name='ratings')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, verbose_name='电影', related_name='user_ratings')
    rating = models.FloatField('评分', validators=[MinValueValidator(0), MaxValueValidator(10)])
    comment = models.TextField('评论', blank=True)
    created_time = models.DateTimeField('评分时间', auto_now_add=True)
    updated_time = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = '用户评分'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'movie']
        ordering = ['-updated_time']
        
    def __str__(self):
        return f'{self.user.username} 给 {self.movie.title} 评分 {self.rating}'

class UserHistory(models.Model):
    """用户观看历史"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户', related_name='watch_history')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, verbose_name='电影', related_name='watched_by')
    watch_time = models.DateTimeField('观看时间', auto_now_add=True)
    watch_duration = models.IntegerField('观看时长(分钟)', default=0)
    
    class Meta:
        verbose_name = '观看历史'
        verbose_name_plural = verbose_name
        ordering = ['-watch_time']
        
    def __str__(self):
        return f'{self.user.username} 观看 {self.movie.title}'
