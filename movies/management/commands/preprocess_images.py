from django.core.management.base import BaseCommand
from django.db import connection
from movies.models import MovieImageCache
from movies.views import parse_image_data
import logging
import traceback

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '预处理热门电影的图片URL并缓存'
    
    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1000, help='处理的电影数量')
        parser.add_argument('--debug', action='store_true', help='启用调试输出')
        parser.add_argument('--force', action='store_true', help='强制更新已存在的缓存')
        
    def handle(self, *args, **options):
        limit = options['limit']
        debug = options['debug']
        force = options['force']
        self.stdout.write(f'开始预处理 {limit} 部热门电影的图片...')
        
        # 获取已缓存的电影ID
        cached_movie_ids = set(MovieImageCache.objects.values_list('movie_id', flat=True))
        if debug:
            self.stdout.write(f'已有 {len(cached_movie_ids)} 部电影的图片被缓存')
        
        processed = 0
        skipped = 0
        errors = 0
        
        with connection.cursor() as cursor:
            # 获取评分最高的电影，使用COALESCE处理NULL值
            cursor.execute(f"""
                SELECT m.movie_id, m.images as raw_images
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                ORDER BY COALESCE(mr.rating, 0) DESC, m.collect_count DESC
                LIMIT {limit}
            """)
            
            # 转换为字典
            movies = self.dictfetchall(cursor)
            self.stdout.write(f'获取到 {len(movies)} 部电影')
            
            # 查看第一部电影的信息
            if movies and debug:
                self.stdout.write(f"第一部电影ID: {movies[0]['movie_id']}")
                self.stdout.write(f"图片数据: {movies[0].get('raw_images', '')[:100]}...")
            
            for i, movie in enumerate(movies):
                try:
                    movie_id = movie['movie_id']
                    
                    # 如果不是强制更新且电影已缓存，则跳过
                    if not force and movie_id in cached_movie_ids:
                        skipped += 1
                        if debug and skipped <= 5:
                            self.stdout.write(f"跳过已缓存电影 {movie_id}")
                        continue
                        
                    raw_images = movie.get('raw_images', '')
                    
                    if debug and i < 3:  # 只打印前3部电影的详细信息
                        self.stdout.write(f"处理电影 {i+1}/{len(movies)}: ID={movie_id}")
                        self.stdout.write(f"原始图片数据: {raw_images[:50]}...")
                    
                    if raw_images:
                        # 使用封装的图片解析函数
                        result = parse_image_data(raw_images, movie_id=movie_id)
                        
                        if debug and i < 3:
                            self.stdout.write(f"解析结果: {result}")
                        
                        if result:
                            # 检查是否已存储
                            cache_obj, created = MovieImageCache.objects.get_or_create(movie_id=movie_id)
                            
                            # 更新或保存URL
                            update_needed = False
                            if 'small' in result and (not cache_obj.small_url or created or force):
                                cache_obj.small_url = result['small']
                                update_needed = True
                                
                            if 'medium' in result and (not cache_obj.medium_url or created or force):
                                cache_obj.medium_url = result['medium']
                                update_needed = True
                                
                            if 'large' in result and (not cache_obj.large_url or created or force):
                                cache_obj.large_url = result['large']
                                update_needed = True
                                
                            if update_needed:
                                cache_obj.save()
                                processed += 1
                                
                                if processed % 100 == 0 or (debug and processed < 10):
                                    self.stdout.write(self.style.SUCCESS(f'已处理 {processed} 部电影'))
                            elif debug and i < 10:
                                self.stdout.write(f"跳过电影 {movie_id}: 缓存已存在且无需更新")
                        elif debug and i < 10:
                            self.stdout.write(f"跳过电影 {movie_id}: 解析结果为空")
                    elif debug and i < 10:
                        self.stdout.write(f"跳过电影 {movie_id}: 无图片数据")
                                
                except Exception as e:
                    errors += 1
                    error_msg = f"处理电影 {movie.get('movie_id')} 图片时出错: {str(e)}"
                    logger.error(error_msg)
                    if debug:
                        self.stdout.write(self.style.ERROR(error_msg))
                        self.stdout.write(traceback.format_exc())
        
        self.stdout.write(self.style.SUCCESS(f'成功预处理 {processed}/{len(movies)} 部电影的图片，跳过 {skipped} 部，错误数量: {errors}'))
    
    def dictfetchall(self, cursor):
        """将游标返回的结果转换为字典"""
        columns = [col[0] for col in cursor.description]
        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ] 