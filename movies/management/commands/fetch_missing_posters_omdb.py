import os
import json
import time
import hashlib
import random
import requests
from PIL import Image
from io import BytesIO
from django.core.management.base import BaseCommand
from django.conf import settings
from movies.models import CollectMovieDB

class Command(BaseCommand):
    help = '从OMDB API获取缺失的电影海报'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input',
            type=str,
            help='包含缺失海报信息的JSON文件路径',
            required=False
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='要处理的电影数量限制',
            required=False
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='请求之间的延迟时间(秒)',
            required=False
        )
        parser.add_argument(
            '--api_key',
            type=str,
            default='5f070074',  # 这是一个示例API密钥，在实际使用时需要替换成有效的
            help='OMDB API密钥',
            required=False
        )

    def handle(self, *args, **options):
        input_file = options.get('input')
        limit = options.get('limit')
        delay = options.get('delay', 1.0)
        api_key = options.get('api_key', '5f070074')
        
        # 确定海报存储目录
        poster_dir = os.path.join(settings.MEDIA_ROOT, 'movie_posters')
        self.stdout.write(f'开始从OMDB API获取电影海报，存储目录: {poster_dir}')
        
        # 确保存储目录存在
        if not os.path.exists(poster_dir):
            os.makedirs(poster_dir)
            self.stdout.write(f'创建海报存储目录: {poster_dir}')
        
        # 获取缺失海报的电影列表
        missing_posters = []
        
        if input_file:
            # 从文件读取
            self.stdout.write(f'从文件 {input_file} 读取缺失海报信息')
            try:
                if os.path.exists(input_file):
                    with open(input_file, 'r', encoding='utf-8') as f:
                        missing_posters = json.load(f)
                    self.stdout.write(f'找到 {len(missing_posters)} 部缺失海报的电影')
                else:
                    self.stdout.write(self.style.ERROR(f'文件 {input_file} 不存在'))
                    return
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'读取文件出错: {str(e)}'))
                return
        else:
            # 从数据库中查询
            self.stdout.write('从数据库查询缺失海报的电影')
            movies = CollectMovieDB.objects.all().order_by('-collect_count')
            if limit:
                movies = movies[:limit]
            
            for movie in movies:
                movie_id = movie.movie_id
                title = movie.title
                original_title = movie.original_title
                year = movie.year
                
                # 检查本地是否已存在海报
                local_poster = os.path.join(poster_dir, f'{movie_id}.jpg')
                local_poster_hash = os.path.join(poster_dir, f'{hashlib.md5(str(movie_id).encode()).hexdigest()}.jpg')
                
                if not os.path.exists(local_poster) and not os.path.exists(local_poster_hash):
                    missing_posters.append({
                        'movie_id': movie_id,
                        'title': title,
                        'original_title': original_title,
                        'year': year,
                        'collect_count': movie.collect_count
                    })
            
            self.stdout.write(f'找到 {len(missing_posters)} 部缺失海报的电影')
        
        # 对缺失海报的电影排序，优先处理收藏数较多的电影
        missing_posters.sort(key=lambda x: x.get('collect_count', 0), reverse=True)
        
        # 限制处理数量
        if limit and len(missing_posters) > limit:
            missing_posters = missing_posters[:limit]
            self.stdout.write(f'根据限制，将处理 {limit} 部电影')
        
        # 开始获取海报
        success_count = 0
        failure_count = 0
        
        for i, movie in enumerate(missing_posters):
            movie_id = movie['movie_id']
            title = movie.get('title', '')
            original_title = movie.get('original_title', '')
            year = movie.get('year', '')
            
            self.stdout.write(f'[{i+1}/{len(missing_posters)}] 处理 {movie_id} ({title}) 的海报...')
            
            # 构建查询参数
            search_title = original_title if original_title else title
            search_params = {
                'apikey': api_key,
                't': search_title,
                'y': year,
                'plot': 'short',
                'r': 'json'
            }
            
            try:
                # 发送请求到OMDB API
                response = requests.get('http://www.omdbapi.com/', params=search_params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get('Response') == 'True' and data.get('Poster') and data.get('Poster') != 'N/A':
                        poster_url = data.get('Poster')
                        
                        # 下载海报
                        self.stdout.write(f'  找到海报URL: {poster_url}')
                        
                        try:
                            # 添加随机的User-Agent以避免被封
                            headers = {
                                'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(80, 100)}.0.{random.randint(4000, 5000)}.{random.randint(1, 200)} Safari/537.36'
                            }
                            img_response = requests.get(poster_url, headers=headers, timeout=10)
                            
                            if img_response.status_code == 200:
                                # 检查内容类型是否为图片
                                content_type = img_response.headers.get('Content-Type', '')
                                if 'image' in content_type.lower():
                                    # 保存原始图片
                                    local_path = os.path.join(poster_dir, f'{movie_id}.jpg')
                                    
                                    # 使用PIL处理图片，以确保格式正确
                                    img = Image.open(BytesIO(img_response.content))
                                    img = img.convert('RGB')  # 确保图片为RGB模式
                                    img.save(local_path, 'JPEG', quality=90)
                                    
                                    # 同时以哈希文件名保存一份，兼容两种访问方式
                                    hash_path = os.path.join(poster_dir, f'{hashlib.md5(str(movie_id).encode()).hexdigest()}.jpg')
                                    img.save(hash_path, 'JPEG', quality=90)
                                    
                                    self.stdout.write(self.style.SUCCESS(f'  成功保存 {movie_id} ({title}) 的海报'))
                                    success_count += 1
                                else:
                                    self.stdout.write(self.style.WARNING(f'  内容类型不是图片: {content_type}'))
                                    failure_count += 1
                            else:
                                self.stdout.write(self.style.ERROR(f'  下载图片失败: {img_response.status_code}'))
                                failure_count += 1
                                
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f'  下载海报出错: {str(e)}'))
                            failure_count += 1
                    else:
                        self.stdout.write(self.style.WARNING(f'  未找到有效海报'))
                        failure_count += 1
                else:
                    self.stdout.write(self.style.ERROR(f'  API请求失败: {response.status_code}'))
                    failure_count += 1
            
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  获取海报出错: {str(e)}'))
                failure_count += 1
            
            # 添加延迟以避免API限制
            time.sleep(delay)
        
        # 输出统计信息
        self.stdout.write('\n获取完成!')
        self.stdout.write(f'总共尝试: {len(missing_posters)}')
        self.stdout.write(f'成功获取: {success_count}')
        self.stdout.write(f'获取失败: {failure_count}')
        
        if success_count == len(missing_posters):
            self.stdout.write(self.style.SUCCESS('全部获取成功!'))
        elif success_count > 0:
            self.stdout.write(self.style.WARNING(f'部分获取成功, 成功率: {success_count/len(missing_posters)*100:.2f}%'))
        else:
            self.stdout.write(self.style.ERROR('全部获取失败!')) 