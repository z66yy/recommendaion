import os
import json
import ast
import hashlib
import time
import random
import requests
from io import BytesIO
from urllib.parse import urlparse, unquote, quote
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from movies.views import dictfetchall
from PIL import Image

class Command(BaseCommand):
    help = '搜索缺失的电影海报并尝试从其他来源获取'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, help='限制处理的电影数量')
        parser.add_argument('--input', type=str, help='从检查命令生成的JSON文件中读取缺失海报信息')
        parser.add_argument('--delay', type=float, default=1.0, help='请求间隔时间(秒), 默认1.0秒')
        parser.add_argument('--output', type=str, help='输出结果到指定文件')

    def handle(self, *args, **options):
        limit = options.get('limit')
        input_file = options.get('input')
        delay = options.get('delay', 1.0)
        output_file = options.get('output')
        
        # 确保海报存储目录存在
        poster_dir = settings.IMAGE_PROCESSING['LOCAL_STORAGE_PATH']
        os.makedirs(poster_dir, exist_ok=True)
        
        self.stdout.write(self.style.SUCCESS(f"开始搜索缺失的电影海报，存储目录: {poster_dir}"))
        
        missing_posters = []
        
        # 如果提供了输入文件，从文件中读取缺失海报信息
        if input_file and os.path.exists(input_file):
            self.stdout.write(f"从文件 {input_file} 读取缺失海报信息")
            with open(input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                missing_posters = data.get('missing_posters', [])
            
            # 应用下载数量限制
            if limit and limit < len(missing_posters):
                missing_posters = missing_posters[:limit]
                self.stdout.write(f"限制处理数量: {limit}")
        else:
            # 查询数据库获取所有电影
            self.stdout.write("从数据库查询缺失海报的电影")
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
                else:
                    cursor.execute(sql)
                    
                movies = dictfetchall(cursor)
                
                # 处理每部电影，检查海报是否存在
                for movie in movies:
                    movie_id = movie.get('movie_id')
                    title = movie.get('title', '未知标题')
                    
                    # 解析图片数据
                    images_data = movie.get('images', '{}')
                    image_url = None
                    
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
                    
                    # 计算本地文件路径
                    if image_url:
                        cache_key = hashlib.md5(image_url.encode()).hexdigest()
                        local_path = os.path.join(poster_dir, f'{cache_key}.jpg')
                    
                        # 也尝试用movie_id检查
                        movie_id_path = os.path.join(poster_dir, f'{movie_id}.jpg')
                    
                        # 检查海报是否存在
                        if not (os.path.exists(local_path) or os.path.exists(movie_id_path)):
                            # 检查特殊情况：URL的哈希值不同
                            found = False
                            for filename in os.listdir(poster_dir):
                                if filename.startswith(f"{movie_id}_"):
                                    found = True
                                    break
                            
                            if not found:
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
        
        total_missing = len(missing_posters)
        self.stdout.write(f"找到 {total_missing} 部缺失海报的电影需要搜索")
        
        if not total_missing:
            self.stdout.write(self.style.SUCCESS("没有需要搜索的电影海报，任务完成"))
            return
        
        # 按收藏数量排序
        missing_posters = sorted(missing_posters, key=lambda x: x.get('collect_count', 0), reverse=True)
        
        # 初始化搜索结果
        search_results = []
        
        # 搜索替代海报源
        for i, movie in enumerate(missing_posters):
            movie_id = movie.get('movie_id')
            title = movie.get('title', '未知标题')
            original_title = movie.get('original_title', '')
            year = movie.get('year', 0)
            
            self.stdout.write(f"[{i+1}/{total_missing}] 搜索 {movie_id} ({title}) 的海报...")
            
            # 构建搜索关键词
            search_terms = []
            if title:
                search_terms.append(title)
            if original_title and original_title != title:
                search_terms.append(original_title)
            if year:
                search_terms.append(str(year))
            
            search_keywords = " ".join(search_terms) + " movie poster"
            
            # 记录搜索结果
            movie_result = {
                'movie_id': movie_id,
                'title': title,
                'original_title': original_title,
                'year': year,
                'collect_count': movie.get('collect_count', 0),
                'search_keywords': search_keywords,
                'tmdb_results': [],
                'imdb_results': []
            }
            
            # 搜索TMDB
            try:
                tmdb_api_key = "3d1a2d876aa505da48e0b9230dc7d558"  # 样例API密钥，实际使用时应配置在settings中
                tmdb_url = f"https://api.themoviedb.org/3/search/movie?api_key={tmdb_api_key}&query={quote(search_keywords)}"
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'application/json'
                }
                
                response = requests.get(tmdb_url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    tmdb_data = response.json()
                    results = tmdb_data.get('results', [])
                    
                    for result in results[:5]:  # 只取前5个结果
                        poster_path = result.get('poster_path')
                        if poster_path:
                            tmdb_title = result.get('title', '')
                            tmdb_year = result.get('release_date', '')[:4]
                            tmdb_id = result.get('id')
                            
                            tmdb_poster_url = f"https://image.tmdb.org/t/p/original{poster_path}"
                            
                            movie_result['tmdb_results'].append({
                                'tmdb_id': tmdb_id,
                                'title': tmdb_title,
                                'year': tmdb_year,
                                'poster_url': tmdb_poster_url
                            })
                            
                            self.stdout.write(f"  TMDB结果: {tmdb_title} ({tmdb_year})")
                else:
                    self.stdout.write(self.style.WARNING(f"  TMDB搜索失败: HTTP {response.status_code}"))
            
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  TMDB搜索出错: {str(e)}"))
            
            search_results.append(movie_result)
            
            # 请求间隔
            if i < total_missing - 1:
                time.sleep(delay)
        
        # 输出搜索结果统计
        self.stdout.write(self.style.SUCCESS("\n搜索完成!"))
        found_count = sum(1 for r in search_results if r.get('tmdb_results') or r.get('imdb_results'))
        self.stdout.write(f"总共搜索: {total_missing}")
        self.stdout.write(f"找到替代海报: {found_count}")
        self.stdout.write(f"未找到海报: {total_missing - found_count}")
        
        # 如果指定了输出文件，将结果写入文件
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'total': total_missing,
                    'found': found_count,
                    'search_results': search_results
                }, f, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f"\n结果已保存到文件: {output_file}"))
        
        # 是否要马上下载找到的海报？
        if found_count > 0:
            self.stdout.write(self.style.SUCCESS("\n可以运行下面的命令下载找到的替代海报:"))
            if output_file:
                self.stdout.write(f"python manage.py download_alternative_posters --input {output_file}") 