import os
import json
import ast
import hashlib
import time
import random
import requests
from io import BytesIO
from urllib.parse import urlparse, unquote
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from movies.views import dictfetchall
from PIL import Image

class Command(BaseCommand):
    help = '下载缺失的电影海报'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, help='限制下载的电影数量')
        parser.add_argument('--input', type=str, help='从检查命令生成的JSON文件中读取缺失海报信息')
        parser.add_argument('--delay', type=float, default=0.5, help='下载间隔时间(秒), 默认0.5秒')
        parser.add_argument('--retry', type=int, default=3, help='下载重试次数, 默认3次')
        parser.add_argument('--min-collect', type=int, default=0, help='最小收藏数量，只下载收藏数量大于此值的电影海报')

    def handle(self, *args, **options):
        limit = options.get('limit')
        input_file = options.get('input')
        delay = options.get('delay', 0.5)
        retry_count = options.get('retry', 3)
        min_collect = options.get('min-collect', 0)
        
        # 确保海报存储目录存在
        poster_dir = settings.IMAGE_PROCESSING['LOCAL_STORAGE_PATH']
        os.makedirs(poster_dir, exist_ok=True)
        
        self.stdout.write(self.style.SUCCESS(f"开始下载缺失的电影海报，存储目录: {poster_dir}"))
        
        missing_posters = []
        
        # 如果提供了输入文件，从文件中读取缺失海报信息
        if input_file and os.path.exists(input_file):
            self.stdout.write(f"从文件 {input_file} 读取缺失海报信息")
            with open(input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                missing_posters = data.get('missing_posters', [])
            
            # 应用最小收藏数量过滤
            if min_collect > 0:
                original_count = len(missing_posters)
                missing_posters = [m for m in missing_posters if m.get('collect_count', 0) >= min_collect]
                self.stdout.write(f"根据最小收藏数量 {min_collect} 过滤: {original_count} -> {len(missing_posters)}")
            
            # 应用下载数量限制
            if limit and limit < len(missing_posters):
                missing_posters = missing_posters[:limit]
                self.stdout.write(f"限制下载数量: {limit}")
        else:
            # 查询数据库获取缺失海报的电影
            self.stdout.write("从数据库查询缺失海报的电影")
            with connection.cursor() as cursor:
                sql = """
                    SELECT m.movie_id, m.title, m.original_title, m.images, m.rating, 
                           m.collect_count, m.year
                    FROM movie_collectmoviedb m
                    WHERE m.collect_count >= %s
                    ORDER BY m.collect_count DESC
                """
                
                params = [min_collect]
                if limit:
                    sql += " LIMIT %s"
                    params.append(limit)
                    
                cursor.execute(sql, params)
                movies = dictfetchall(cursor)
                
                # 处理每部电影，找出缺失海报的
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
                    
                    if not image_url:
                        continue
                    
                    # 计算本地文件路径
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
        self.stdout.write(f"找到 {total_missing} 部缺失海报的电影需要下载")
        
        if not total_missing:
            self.stdout.write(self.style.SUCCESS("没有需要下载的海报，任务完成"))
            return
        
        # 按收藏数量排序
        missing_posters = sorted(missing_posters, key=lambda x: x.get('collect_count', 0), reverse=True)
        
        # 下载缺失的海报
        success_count = 0
        error_count = 0
        
        for i, movie in enumerate(missing_posters):
            movie_id = movie.get('movie_id')
            title = movie.get('title', '未知标题')
            image_url = movie.get('image_url')
            
            # 如果没有图片URL，跳过
            if not image_url:
                self.stdout.write(self.style.WARNING(f"电影 {movie_id} ({title}) 没有图片URL，跳过"))
                continue
            
            self.stdout.write(f"[{i+1}/{total_missing}] 下载 {movie_id} ({title}) 的海报...")
            
            # 计算本地文件路径
            cache_key = hashlib.md5(image_url.encode()).hexdigest()
            local_path = os.path.join(poster_dir, f'{cache_key}.jpg')
            
            # 下载重试
            success = False
            for attempt in range(retry_count):
                try:
                    # 添加随机User-Agent
                    user_agents = [
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
                    ]
                    
                    headers = {
                        'User-Agent': random.choice(user_agents),
                        'Referer': 'https://movie.douban.com/',
                        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Connection': 'keep-alive'
                    }
                    
                    # 下载图片
                    response = requests.get(image_url, headers=headers, timeout=10, verify=False)
                    
                    if response.status_code == 200:
                        # 处理和保存图片
                        img = Image.open(BytesIO(response.content))
                        
                        # 调整图片大小
                        max_size = settings.IMAGE_PROCESSING['MAX_SIZE']
                        if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
                            img.thumbnail(max_size, Image.Resampling.LANCZOS)
                        
                        # 保存图片
                        img.save(local_path, 
                                format=settings.IMAGE_PROCESSING['DEFAULT_FORMAT'],
                                quality=settings.IMAGE_PROCESSING['DEFAULT_QUALITY'])
                        
                        self.stdout.write(self.style.SUCCESS(f"成功下载 {movie_id} ({title}) 的海报"))
                        success = True
                        success_count += 1
                        break
                    else:
                        self.stdout.write(self.style.WARNING(
                            f"下载失败 (尝试 {attempt+1}/{retry_count}): HTTP {response.status_code}"
                        ))
                        
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"下载出错 (尝试 {attempt+1}/{retry_count}): {str(e)}"
                    ))
                    
                # 失败后等待一段时间再重试
                if attempt < retry_count - 1:
                    wait_time = delay * (1 + random.uniform(0, 0.5))
                    time.sleep(wait_time)
            
            if not success:
                self.stdout.write(self.style.ERROR(f"下载 {movie_id} ({title}) 的海报失败，已重试 {retry_count} 次"))
                error_count += 1
            
            # 下载间隔
            if i < total_missing - 1:
                wait_time = delay * (1 + random.uniform(-0.2, 0.2))
                time.sleep(wait_time)
        
        # 输出统计信息
        self.stdout.write(self.style.SUCCESS("\n下载完成!"))
        self.stdout.write(f"总共尝试: {total_missing}")
        self.stdout.write(f"成功下载: {success_count}")
        self.stdout.write(f"下载失败: {error_count}")
        
        if success_count == total_missing:
            self.stdout.write(self.style.SUCCESS("全部下载成功!"))
        elif success_count > 0:
            self.stdout.write(self.style.WARNING(f"部分下载成功 ({success_count}/{total_missing})"))
        else:
            self.stdout.write(self.style.ERROR("全部下载失败!")) 