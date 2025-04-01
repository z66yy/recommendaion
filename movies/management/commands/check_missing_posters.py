import os
import json
import ast
import hashlib
from urllib.parse import urlparse, unquote
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from movies.views import dictfetchall, parse_image_data

class Command(BaseCommand):
    help = '检查哪些电影没有在本地存储海报，并生成报告'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, help='限制检查的电影数量')
        parser.add_argument('--output', type=str, help='输出结果到指定文件')
        parser.add_argument('--verbose', action='store_true', help='显示详细信息')

    def handle(self, *args, **options):
        limit = options.get('limit')
        output_file = options.get('output')
        verbose = options.get('verbose', False)
        
        # 确保海报存储目录存在
        poster_dir = settings.IMAGE_PROCESSING['LOCAL_STORAGE_PATH']
        os.makedirs(poster_dir, exist_ok=True)
        
        self.stdout.write(self.style.SUCCESS(f"开始检查电影海报情况，存储目录: {poster_dir}"))
        
        # 查询所有电影
        with connection.cursor() as cursor:
            sql = """
                SELECT m.movie_id, m.title, m.original_title, m.images, m.rating, 
                       m.collect_count, m.year
                FROM movie_collectmoviedb m
                ORDER BY m.collect_count DESC
            """
            if limit:
                sql += " LIMIT %s"
                cursor.execute(sql, [limit])
                self.stdout.write(f"限制查询 {limit} 部电影")
            else:
                cursor.execute(sql)
            
            movies = dictfetchall(cursor)
            
        total_movies = len(movies)
        self.stdout.write(f"找到 {total_movies} 部电影")
        
        # 检查每部电影的海报情况
        missing_posters = []
        has_posters = []
        error_posters = []
        
        for i, movie in enumerate(movies):
            if i % 100 == 0 and i > 0:
                self.stdout.write(f"已处理 {i}/{total_movies} 部电影...")
                
            movie_id = movie.get('movie_id')
            title = movie.get('title', '未知标题')
            
            # 解析图片数据
            images_data = movie.get('images', '{}')
            image_url = None
            
            try:
                # 尝试获取图片URL
                if isinstance(images_data, str):
                    try:
                        if images_data.startswith("{'") or images_data.startswith("{'"):
                            images_data = images_data.replace("'", '"')
                        images = json.loads(images_data)
                    except json.JSONDecodeError:
                        try:
                            images = ast.literal_eval(images_data)
                        except:
                            images = {}
                else:
                    images = images_data
                
                # 获取图片URL
                for size in ['large', 'medium', 'small']:
                    if images and isinstance(images, dict) and images.get(size):
                        image_url = images.get(size)
                        break
                
                if not image_url:
                    if verbose:
                        self.stdout.write(self.style.WARNING(f"电影 {movie_id} ({title}) 没有图片URL"))
                    missing_posters.append({
                        'movie_id': movie_id,
                        'title': title,
                        'original_title': movie.get('original_title', ''),
                        'year': movie.get('year', 0),
                        'collect_count': movie.get('collect_count', 0),
                        'rating': movie.get('rating', 0),
                        'reason': '没有图片URL'
                    })
                    continue
                
                # 计算本地文件路径
                cache_key = hashlib.md5(image_url.encode()).hexdigest()
                local_path = os.path.join(poster_dir, f'{cache_key}.jpg')
                
                # 也尝试用movie_id检查
                movie_id_path = os.path.join(poster_dir, f'{movie_id}.jpg')
                
                # 检查海报是否存在
                if os.path.exists(local_path) or os.path.exists(movie_id_path):
                    if verbose:
                        self.stdout.write(f"电影 {movie_id} ({title}) 海报已存在")
                    has_posters.append(movie_id)
                else:
                    # 检查特殊情况：URL的哈希值不同
                    found = False
                    parsed_url = urlparse(image_url)
                    for filename in os.listdir(poster_dir):
                        if filename.startswith(f"{movie_id}_"):
                            found = True
                            break
                    
                    if found:
                        if verbose:
                            self.stdout.write(f"电影 {movie_id} ({title}) 海报已存在（使用movie_id前缀）")
                        has_posters.append(movie_id)
                    else:
                        if verbose:
                            self.stdout.write(self.style.WARNING(f"电影 {movie_id} ({title}) 海报不存在"))
                        missing_posters.append({
                            'movie_id': movie_id,
                            'title': title,
                            'original_title': movie.get('original_title', ''),
                            'year': movie.get('year', 0),
                            'collect_count': movie.get('collect_count', 0),
                            'rating': movie.get('rating', 0),
                            'image_url': image_url,
                            'reason': '本地文件不存在'
                        })
                
            except Exception as e:
                error_message = f"处理电影 {movie_id} ({title}) 图片信息时出错: {str(e)}"
                if verbose:
                    self.stdout.write(self.style.ERROR(error_message))
                error_posters.append({
                    'movie_id': movie_id,
                    'title': title,
                    'error': str(e)
                })
        
        # 输出统计信息
        self.stdout.write(self.style.SUCCESS("\n统计信息:"))
        self.stdout.write(f"总电影数: {total_movies}")
        self.stdout.write(f"已有海报: {len(has_posters)}")
        self.stdout.write(f"缺少海报: {len(missing_posters)}")
        self.stdout.write(f"处理错误: {len(error_posters)}")
        
        # 输出TOP 10缺少海报的热门电影
        if missing_posters:
            self.stdout.write(self.style.SUCCESS("\nTOP 10缺少海报的热门电影:"))
            # 按收藏数量排序
            top_missing = sorted(missing_posters, key=lambda x: x.get('collect_count', 0), reverse=True)[:10]
            for i, movie in enumerate(top_missing):
                self.stdout.write(f"{i+1}. ID: {movie['movie_id']}, 标题: {movie['title']} ({movie.get('year', '未知')}), "
                                f"收藏: {movie.get('collect_count', 0)}, 评分: {movie.get('rating', 0)}")
        
        # 如果指定了输出文件，将结果写入文件
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'total': total_movies,
                    'has_posters': len(has_posters),
                    'missing_posters': missing_posters,
                    'errors': error_posters
                }, f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f"\n结果已保存到文件: {output_file}")) 