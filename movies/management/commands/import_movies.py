import json
import datetime
from django.core.management.base import BaseCommand
from django.db import connection
from movies.models import Movie, Genre
from django.utils.text import slugify
import logging
import ast
import re
import os
import sys

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '从现有数据表movie_collectmoviedb导入电影数据到Django ORM的Movie模型'
    
    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, help='限制导入数量')
    
    def handle(self, *args, **options):
        limit = options.get('limit')
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        self.stdout.write(self.style.SUCCESS('开始导入电影数据...'))
        
        # 先导入电影类型
        self.import_genres()
        
        # 再导入电影数据
        self.import_movies(limit_clause)
        
        # 最后建立电影和类型的关联
        self.link_movies_to_genres()
        
        self.stdout.write(self.style.SUCCESS('电影数据导入完成！'))
    
    def dictfetchall(self, cursor):
        """将游标返回的结果转换为字典列表"""
        columns = [col[0] for col in cursor.description]
        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]
    
    def import_genres(self):
        """导入电影类型"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT movie_type as name
                FROM movie_collectmovietypedb
                WHERE movie_type != ''
                ORDER BY movie_type
            """)
            genres = self.dictfetchall(cursor)
            
            for genre in genres:
                Genre.objects.get_or_create(name=genre['name'])
            
            self.stdout.write(self.style.SUCCESS(f'成功导入 {len(genres)} 个电影类型'))
    
    def import_movies(self, limit_clause):
        """导入电影数据"""
        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT m.*, mr.rating as avg_rating
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                {limit_clause}
            """)
            movies = self.dictfetchall(cursor)
            
            count = 0
            for movie_data in movies:
                try:
                    # 尝试查找现有电影
                    movie, created = Movie.objects.get_or_create(
                        title=movie_data['title'],
                        defaults={
                            'original_title': movie_data['original_title'],
                            'director': self.extract_director(movie_data.get('directors', '')),
                            'actors': self.extract_actors(movie_data.get('actor', '')),
                            'release_date': self.parse_date(movie_data.get('pubdate')),
                            'duration': self.extract_duration(movie_data.get('durations', '')),
                            'rating': float(movie_data.get('avg_rating') or 0),
                            'rating_count': movie_data.get('ratings_count', 0),
                            'description': movie_data.get('summary', '')
                        }
                    )
                    
                    # 提取并保存图片URL到poster字段
                    if created:
                        poster_url = self.extract_poster_url(movie_data.get('images', ''))
                        if poster_url:
                            # 注意：这只保存URL，不下载图片
                            movie.poster = poster_url
                            movie.save()
                    
                    count += 1
                    if count % 100 == 0:
                        self.stdout.write(f'已导入 {count} 部电影...')
                except Exception as e:
                    logger.error(f"导入电影 {movie_data.get('title')} 失败: {str(e)}")
                    continue
            
            self.stdout.write(self.style.SUCCESS(f'成功导入 {count} 部电影'))
    
    def link_movies_to_genres(self):
        """建立电影和类型的关联"""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.title, GROUP_CONCAT(mt.movie_type) as genres
                FROM movie_collectmoviedb m
                LEFT JOIN movie_collectmovietypedb mt ON m.id = mt.id
                GROUP BY m.id
            """)
            movie_genres = self.dictfetchall(cursor)
            
            count = 0
            for item in movie_genres:
                try:
                    movie = Movie.objects.filter(title=item['title']).first()
                    if not movie:
                        continue
                    
                    # 清除旧的类型关联
                    movie.genres.clear()
                    
                    # 添加新的类型关联
                    if item['genres']:
                        genres = item['genres'].split(',')
                        for genre_name in genres:
                            genre, _ = Genre.objects.get_or_create(name=genre_name)
                            movie.genres.add(genre)
                    
                    count += 1
                    if count % 100 == 0:
                        self.stdout.write(f'已关联 {count} 部电影的类型...')
                except Exception as e:
                    logger.error(f"关联电影 {item.get('title')} 的类型失败: {str(e)}")
                    continue
            
            self.stdout.write(self.style.SUCCESS(f'成功关联 {count} 部电影的类型'))
    
    def extract_director(self, directors_json):
        """从导演JSON提取第一个导演名"""
        try:
            directors = json.loads(directors_json)
            if directors and isinstance(directors, list) and len(directors) > 0:
                return directors[0].get('name', '')
        except:
            pass
        return ''
    
    def extract_actors(self, actors_json):
        """从演员JSON提取演员名列表"""
        try:
            actors = json.loads(actors_json)
            if actors and isinstance(actors, list):
                actor_names = [actor.get('name', '') for actor in actors if actor.get('name')]
                return ', '.join(actor_names[:5])  # 只取前5个演员
        except:
            pass
        return ''
    
    def extract_duration(self, durations_str):
        """从时长字符串提取时长（分钟）"""
        try:
            if not durations_str:
                return None
            
            durations = json.loads(durations_str)
            if not durations or not isinstance(durations, list):
                return None
            
            # 尝试从第一个时长字符串提取数字
            duration_str = durations[0]
            import re
            duration_match = re.search(r'(\d+)', duration_str)
            if duration_match:
                return int(duration_match.group(1))
        except:
            pass
        return None
    
    def parse_date(self, date_str):
        """尝试解析日期字符串"""
        if not date_str:
            return None
        
        try:
            # 尝试多种格式
            formats = ['%Y-%m-%d', '%Y-%m', '%Y']
            for fmt in formats:
                try:
                    return datetime.datetime.strptime(date_str, fmt).date()
                except:
                    continue
        except:
            pass
        return None
    
    def extract_poster_url(self, images_json):
        """从图片JSON提取海报URL"""
        if not images_json or images_json == '{}':
            return None
            
        try:
            # 尝试解析为JSON
            images = json.loads(images_json)
            if images and isinstance(images, dict):
                # 依次尝试large, medium, small
                for size in ['large', 'medium', 'small']:
                    if images.get(size):
                        return images.get(size)
        except json.JSONDecodeError:
            try:
                # 尝试解析Python字典字符串
                images = ast.literal_eval(images_json)
                if images and isinstance(images, dict):
                    # 依次尝试large, medium, small
                    for size in ['large', 'medium', 'small']:
                        if images.get(size):
                            return images.get(size)
            except (ValueError, SyntaxError):
                # 如果无法解析，尝试从字符串中提取URL
                urls = re.findall(r'https?://[^\s,\'"]+', images_json)
                if urls:
                    return urls[0]
        return None 