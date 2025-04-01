from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from mvrecommend.db_pool import db_pool, get_connection, release_connection
import pymysql

class PooledManager(models.Manager):
    """
    使用连接池的Manager类，用于解决Too many connections问题
    """
    def execute_raw_sql(self, sql, params=None):
        """执行原始SQL并返回结果"""
        conn = None
        try:
            conn = get_connection()
            if not conn:
                raise Exception("无法获取数据库连接")
                
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            results = cursor.fetchall()
            cursor.close()
            return results
        except Exception as e:
            raise e
        finally:
            if conn:
                release_connection(conn)
    
    def execute_update(self, sql, params=None):
        """执行更新SQL并返回影响的行数"""
        conn = None
        try:
            conn = get_connection()
            if not conn:
                raise Exception("无法获取数据库连接")
                
            cursor = conn.cursor()
            rows = cursor.execute(sql, params or ())
            conn.commit()
            cursor.close()
            return rows
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                release_connection(conn)

class Genre(models.Model):
    """电影类型模型"""
    name = models.CharField('类型名称', max_length=20)
    
    class Meta:
        verbose_name = '电影类型'
        verbose_name_plural = verbose_name
        
    def __str__(self):
        return self.name

class Movie(models.Model):
    """电影模型"""
    title = models.CharField('电影名称', max_length=200)
    original_title = models.CharField('原始名称', max_length=200, blank=True)
    director = models.CharField('导演', max_length=100, blank=True)
    actors = models.CharField('主演', max_length=200, blank=True)
    release_date = models.DateField('上映日期', null=True, blank=True)
    duration = models.IntegerField('时长(分钟)', null=True, blank=True)
    genres = models.ManyToManyField(Genre, verbose_name='电影类型', related_name='movies')
    rating = models.FloatField('评分', validators=[MinValueValidator(0), MaxValueValidator(10)], default=0)
    rating_count = models.IntegerField('评分人数', default=0)
    poster = models.ImageField('海报', upload_to='movie_posters/', blank=True)
    description = models.TextField('剧情简介', blank=True)
    created_time = models.DateTimeField('创建时间', auto_now_add=True)
    updated_time = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '电影'
        verbose_name_plural = verbose_name
        ordering = ['-rating', '-rating_count']
        indexes = [
            models.Index(fields=['rating']),  # 按评分排序常用
        ]
        
    def __str__(self):
        return self.title

class MovieImageCache(models.Model):
    """电影图片缓存模型"""
    movie_id = models.IntegerField('电影ID', unique=True, db_index=True)
    small_url = models.URLField('小图URL', max_length=500, null=True, blank=True)
    medium_url = models.URLField('中图URL', max_length=500, null=True, blank=True)
    large_url = models.URLField('大图URL', max_length=500, null=True, blank=True)
    last_updated = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        verbose_name = '电影图片缓存'
        verbose_name_plural = verbose_name
        db_table = 'movie_image_cache'
        
    def __str__(self):
        return f"电影图片缓存 #{self.movie_id}"

class CollectMovieDB(models.Model):
    movie_id = models.IntegerField(unique=True, verbose_name='电影ID')
    original_title = models.CharField(max_length=1000, verbose_name='原始标题')
    title = models.CharField(max_length=1000, verbose_name='标题')
    rating = models.TextField(verbose_name='评分')
    ratings_count = models.IntegerField(verbose_name='评分数')
    pubdate = models.CharField(max_length=1000, verbose_name='发布日期')
    pubdates = models.CharField(max_length=1000, verbose_name='发布日期列表')
    year = models.IntegerField(verbose_name='年份')
    countries = models.CharField(max_length=1000, verbose_name='国家')
    mainland_pubdate = models.CharField(max_length=1000, verbose_name='大陆发布日期')
    aka = models.CharField(max_length=1000, verbose_name='别名')
    tags = models.CharField(max_length=1000, verbose_name='标签')
    durations = models.TextField(verbose_name='时长')
    genres = models.CharField(max_length=1000, verbose_name='类型')
    videos = models.TextField(verbose_name='视频')
    wish_count = models.IntegerField(verbose_name='想看数')
    reviews_count = models.IntegerField(verbose_name='评论数')
    comments_count = models.IntegerField(verbose_name='短评数')
    collect_count = models.IntegerField(verbose_name='收藏数')
    images = models.TextField(verbose_name='图片')
    photos = models.TextField(verbose_name='照片')
    languages = models.CharField(max_length=1000, verbose_name='语言')
    writers = models.TextField(verbose_name='编剧')
    actor = models.TextField(verbose_name='演员')
    summary = models.TextField(verbose_name='简介')
    directors = models.TextField(verbose_name='导演')
    record_time = models.DateTimeField(verbose_name='记录时间')

    class Meta:
        db_table = 'movie_collectmoviedb'
        verbose_name = '电影信息'
        verbose_name_plural = verbose_name

class CollectMovieTypeDB(models.Model):
    movie_type = models.CharField(max_length=100, unique=True, verbose_name='电影类型')

    class Meta:
        db_table = 'movie_collectmovietypedb'
        verbose_name = '电影类型'
        verbose_name_plural = verbose_name

class CollectTop250MovieDB(models.Model):
    movie_id = models.IntegerField(unique=True, verbose_name='电影ID')
    movie_title = models.TextField(verbose_name='中文标题')
    movie_original_title = models.TextField(verbose_name='原始标题')
    movie_rating = models.TextField(verbose_name='评分')
    movie_year = models.IntegerField(verbose_name='年份')
    movie_pubdates = models.TextField(verbose_name='发布日期')
    movie_directors = models.TextField(verbose_name='导演')
    movie_genres = models.TextField(verbose_name='类型')
    movie_actor = models.TextField(verbose_name='演员')
    movie_durations = models.TextField(verbose_name='时长')
    movie_collect_count = models.IntegerField(verbose_name='收藏数')
    movie_mainland_pubdate = models.TextField(verbose_name='大陆发布日期')
    movie_images = models.TextField(verbose_name='封面图片')
    record_time = models.DateTimeField(verbose_name='记录时间')

    class Meta:
        db_table = 'movie_collecttop250moviedb'
        verbose_name = 'Top250电影'
        verbose_name_plural = verbose_name

class MoviePubdateDB(models.Model):
    movie_id = models.OneToOneField(CollectMovieDB, on_delete=models.CASCADE, to_field='movie_id', verbose_name='电影')
    pubdate = models.DateField(null=True, verbose_name='发布日期')

    class Meta:
        db_table = 'movie_moviepubdatedb'
        verbose_name = '电影发布日期'
        verbose_name_plural = verbose_name

class MovieRatingDB(models.Model):
    movie_id = models.OneToOneField(CollectMovieDB, on_delete=models.CASCADE, to_field='movie_id', verbose_name='电影')
    rating = models.DecimalField(max_digits=4, decimal_places=2, verbose_name='评分')

    class Meta:
        db_table = 'movie_movieratingdb'
        verbose_name = '电影评分'
        verbose_name_plural = verbose_name

class MovieTagDB(models.Model):
    movie_id = models.ForeignKey(CollectMovieDB, on_delete=models.CASCADE, to_field='movie_id', verbose_name='电影')
    tag_type = models.CharField(max_length=100, verbose_name='标签类型')
    tag_name = models.CharField(max_length=100, verbose_name='标签名')

    class Meta:
        db_table = 'movie_movietagdb'
        verbose_name = '电影标签'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['tag_type']),
            models.Index(fields=['tag_name']),
        ]
