from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from users.models import User
from movies.models import Movie

class UserBehavior(models.Model):
    """用户行为模型"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, verbose_name='电影')
    rating = models.FloatField('评分', validators=[MinValueValidator(0), MaxValueValidator(10)], null=True, blank=True)
    watch_time = models.DateTimeField('观看时间', auto_now_add=True)
    
    class Meta:
        verbose_name = '用户行为'
        verbose_name_plural = verbose_name
        unique_together = ['user', 'movie']
        ordering = ['-watch_time']
        
    def __str__(self):
        return f'{self.user.username} - {self.movie.title}'

class MovieSimilarity(models.Model):
    """电影相似度模型"""
    movie1 = models.ForeignKey(Movie, on_delete=models.CASCADE, verbose_name='电影1', related_name='similar_to')
    movie2 = models.ForeignKey(Movie, on_delete=models.CASCADE, verbose_name='电影2', related_name='similar_from')
    similarity = models.FloatField('相似度', validators=[MinValueValidator(0), MaxValueValidator(1)])
    
    class Meta:
        verbose_name = '电影相似度'
        verbose_name_plural = verbose_name
        unique_together = ['movie1', 'movie2']
        ordering = ['-similarity']
        
    def __str__(self):
        return f'{self.movie1.title} - {self.movie2.title}: {self.similarity}'
