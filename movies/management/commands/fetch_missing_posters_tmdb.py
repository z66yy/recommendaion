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
    help = '从TMDB API获取缺失的电影海报'

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
            default='3e543f4a9b834ebe753fe40f6086889b',  # 这是一个示例API密钥，在实际使用时需要替换成有效的
            help='TMDB API密钥',
            required=False
        )
        parser.add_argument(
            '--proxy',
            type=str,
            help='代理服务器地址，格式如 http://127.0.0.1:7890',
            required=False
        )

    def handle(self, *args, **options):
        input_file = options.get('input')
        limit = options.get('limit')
        delay = options.get('delay', 1.0)
        api_key = options.get('api_key', '3e543f4a9b834ebe753fe40f6086889b')
        proxy = options.get('proxy')
        
        # 代理设置
        proxies = None
        if proxy:
            proxies = {
                'http': proxy,
                'https': proxy
            }
            self.stdout.write(f'使用代理: {proxy}')
        
        # 确定海报存储目录
        poster_dir = os.path.join(settings.MEDIA_ROOT, 'movie_posters')
        self.stdout.write(f'开始从TMDB API获取电影海报，存储目录: {poster_dir}')
        
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
            
            # 先进行电影搜索
            search_title = original_title if original_title else title
            search_url = f'https://api.themoviedb.org/3/search/movie'
            search_params = {
                'api_key': api_key,
                'query': search_title,
                'year': year,
                'language': 'zh-CN',
                'include_adult': 'true'
            }
            
            try:
                # 添加随机的User-Agent以避免被封
                headers = {
                    'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(80, 100)}.0.{random.randint(4000, 5000)}.{random.randint(1, 200)} Safari/537.36'
                }
                
                # 发送请求到TMDB API进行搜索
                response = requests.get(search_url, params=search_params, headers=headers, proxies=proxies, timeout=30)
                
                tmdb_id = None
                poster_path = None
                
                if response.status_code == 200:
                    search_results = response.json()
                    
                    if search_results.get('results') and len(search_results['results']) > 0:
                        # 找到最匹配的结果
                        for result in search_results['results']:
                            result_title = result.get('title', '')
                            result_original_title = result.get('original_title', '')
                            result_year = result.get('release_date', '')[:4] if result.get('release_date') else ''
                            
                            # 尝试匹配标题和年份
                            if (result_title == title or result_original_title == original_title) and (not year or not result_year or result_year == str(year)):
                                tmdb_id = result.get('id')
                                poster_path = result.get('poster_path')
                                break
                        
                        # 如果没有精确匹配，取第一个结果
                        if not tmdb_id:
                            tmdb_id = search_results['results'][0].get('id')
                            poster_path = search_results['results'][0].get('poster_path')
                        
                        if tmdb_id and poster_path:
                            # 构建完整的海报URL
                            poster_url = f'https://image.tmdb.org/t/p/original{poster_path}'
                            self.stdout.write(f'  找到海报URL: {poster_url}')
                            
                            try:
                                # 下载海报
                                img_response = requests.get(poster_url, headers=headers, proxies=proxies, timeout=30)
                                
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
                            self.stdout.write(self.style.WARNING(f'  未找到有效海报路径'))
                            failure_count += 1
                    else:
                        self.stdout.write(self.style.WARNING(f'  搜索结果为空'))
                        failure_count += 1
                else:
                    self.stdout.write(self.style.ERROR(f'  API搜索请求失败: {response.status_code}'))
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