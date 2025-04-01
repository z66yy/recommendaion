import os
import json
import hashlib
import time
import random
import requests
from io import BytesIO
from django.core.management.base import BaseCommand
from django.conf import settings
from PIL import Image

class Command(BaseCommand):
    help = '下载搜索到的替代电影海报'

    def add_arguments(self, parser):
        parser.add_argument('--input', type=str, required=True, help='从搜索命令生成的JSON文件中读取海报信息')
        parser.add_argument('--limit', type=int, help='限制下载的电影数量')
        parser.add_argument('--delay', type=float, default=0.5, help='下载间隔时间(秒), 默认0.5秒')
        parser.add_argument('--retry', type=int, default=3, help='下载重试次数, 默认3次')
        parser.add_argument('--source', type=str, default='tmdb', help='图片来源，默认tmdb')

    def handle(self, *args, **options):
        input_file = options.get('input')
        limit = options.get('limit')
        delay = options.get('delay', 0.5)
        retry_count = options.get('retry', 3)
        source = options.get('source', 'tmdb')
        
        if not input_file or not os.path.exists(input_file):
            self.stdout.write(self.style.ERROR(f"输入文件不存在: {input_file}"))
            return
            
        # 确保海报存储目录存在
        poster_dir = settings.IMAGE_PROCESSING['LOCAL_STORAGE_PATH']
        os.makedirs(poster_dir, exist_ok=True)
        
        self.stdout.write(self.style.SUCCESS(f"开始下载替代的电影海报，存储目录: {poster_dir}"))
        
        # 从文件中读取搜索结果
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            search_results = data.get('search_results', [])
        
        # 过滤有结果的电影
        movies_with_posters = []
        for movie in search_results:
            movie_id = movie.get('movie_id')
            title = movie.get('title', '未知标题')
            
            if source == 'tmdb' and movie.get('tmdb_results'):
                # 取第一个结果作为最匹配的
                poster_info = movie.get('tmdb_results')[0]
                poster_url = poster_info.get('poster_url')
                
                if poster_url:
                    movies_with_posters.append({
                        'movie_id': movie_id,
                        'title': title,
                        'poster_url': poster_url,
                        'source': 'tmdb',
                        'source_id': poster_info.get('tmdb_id'),
                        'source_title': poster_info.get('title'),
                        'source_year': poster_info.get('year')
                    })
            elif source == 'imdb' and movie.get('imdb_results'):
                # 取第一个结果作为最匹配的
                poster_info = movie.get('imdb_results')[0]
                poster_url = poster_info.get('poster_url')
                
                if poster_url:
                    movies_with_posters.append({
                        'movie_id': movie_id,
                        'title': title,
                        'poster_url': poster_url,
                        'source': 'imdb',
                        'source_id': poster_info.get('imdb_id'),
                        'source_title': poster_info.get('title'),
                        'source_year': poster_info.get('year')
                    })
        
        total_posters = len(movies_with_posters)
        self.stdout.write(f"找到 {total_posters} 部电影的替代海报需要下载")
        
        if not total_posters:
            self.stdout.write(self.style.SUCCESS("没有需要下载的替代海报，任务完成"))
            return
        
        # 应用数量限制
        if limit and limit < total_posters:
            movies_with_posters = movies_with_posters[:limit]
            total_posters = len(movies_with_posters)
            self.stdout.write(f"限制下载数量: {total_posters}")
        
        # 下载海报
        success_count = 0
        error_count = 0
        
        for i, movie in enumerate(movies_with_posters):
            movie_id = movie.get('movie_id')
            title = movie.get('title', '未知标题')
            poster_url = movie.get('poster_url')
            source = movie.get('source')
            source_title = movie.get('source_title')
            source_year = movie.get('source_year')
            
            self.stdout.write(f"[{i+1}/{total_posters}] 下载 {movie_id} ({title}) 的海报...")
            self.stdout.write(f"  来源: {source} - {source_title} ({source_year})")
            
            # 使用movie_id作为文件名
            local_path = os.path.join(poster_dir, f'{movie_id}.jpg')
            
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
                        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Connection': 'keep-alive'
                    }
                    
                    # 下载图片
                    response = requests.get(poster_url, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        # 检查内容是否为图片
                        content_type = response.headers.get('Content-Type', '')
                        if not content_type.startswith('image/'):
                            self.stdout.write(self.style.WARNING(
                                f"  下载失败 (尝试 {attempt+1}/{retry_count}): 内容类型不是图片 ({content_type})"
                            ))
                            if attempt < retry_count - 1:
                                time.sleep(delay)
                            continue
                        
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
                        
                        # 为了兼容性，也保存一个URL哈希版本
                        if poster_url:
                            try:
                                cache_key = hashlib.md5(poster_url.encode()).hexdigest()
                                hash_path = os.path.join(poster_dir, f'{cache_key}.jpg')
                                img.save(hash_path,
                                        format=settings.IMAGE_PROCESSING['DEFAULT_FORMAT'],
                                        quality=settings.IMAGE_PROCESSING['DEFAULT_QUALITY'])
                            except Exception as e:
                                self.stdout.write(self.style.WARNING(f"  保存哈希版本失败: {str(e)}"))
                        
                        self.stdout.write(self.style.SUCCESS(f"  成功下载 {movie_id} ({title}) 的海报"))
                        success = True
                        success_count += 1
                        break
                    else:
                        self.stdout.write(self.style.WARNING(
                            f"  下载失败 (尝试 {attempt+1}/{retry_count}): HTTP {response.status_code}"
                        ))
                        
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"  下载出错 (尝试 {attempt+1}/{retry_count}): {str(e)}"
                    ))
                    
                # 失败后等待一段时间再重试
                if attempt < retry_count - 1:
                    wait_time = delay * (1 + random.uniform(0, 0.5))
                    time.sleep(wait_time)
            
            if not success:
                self.stdout.write(self.style.ERROR(f"  下载 {movie_id} ({title}) 的海报失败，已重试 {retry_count} 次"))
                error_count += 1
            
            # 下载间隔
            if i < total_posters - 1:
                wait_time = delay * (1 + random.uniform(-0.2, 0.2))
                time.sleep(wait_time)
        
        # 输出统计信息
        self.stdout.write(self.style.SUCCESS("\n下载完成!"))
        self.stdout.write(f"总共尝试: {total_posters}")
        self.stdout.write(f"成功下载: {success_count}")
        self.stdout.write(f"下载失败: {error_count}")
        
        if success_count == total_posters:
            self.stdout.write(self.style.SUCCESS("全部下载成功!"))
        elif success_count > 0:
            self.stdout.write(self.style.WARNING(f"部分下载成功 ({success_count}/{total_posters})"))
        else:
            self.stdout.write(self.style.ERROR("全部下载失败!")) 