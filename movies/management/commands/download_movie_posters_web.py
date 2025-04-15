import os
import json
import time
import hashlib
import random
import requests
import urllib.parse
from PIL import Image
from io import BytesIO
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = '使用Web搜索直接下载电影海报图片'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input',
            type=str,
            help='包含缺失海报信息的JSON文件路径',
            required=False
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=2.0,
            help='请求之间的延迟时间(秒)',
            required=False
        )
        parser.add_argument(
            '--retry',
            type=int,
            default=3,
            help='下载重试次数',
            required=False
        )
        parser.add_argument(
            '--source',
            type=str,
            choices=['all', 'douban', 'mtime', 'google'],
            default='all',
            help='图片来源',
            required=False
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='要处理的电影数量限制',
            required=False
        )

    def handle(self, *args, **options):
        input_file = options.get('input')
        limit = options.get('limit')
        delay = options.get('delay', 2.0)
        retry_count = options.get('retry', 3)
        source = options.get('source', 'all')
        
        # 确定海报存储目录
        poster_dir = os.path.join(settings.MEDIA_ROOT, 'movie_posters')
        self.stdout.write(f'开始从Web直接下载电影海报，存储目录: {poster_dir}')
        
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
                        data = json.load(f)
                        # 处理特定结构的JSON文件
                        if 'missing_posters' in data:
                            missing_posters = data['missing_posters']
                        else:
                            missing_posters = data  # 假设是直接的列表
                    self.stdout.write(f'找到 {len(missing_posters)} 部缺失海报的电影')
                else:
                    self.stdout.write(self.style.ERROR(f'文件 {input_file} 不存在'))
                    return
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'读取文件出错: {str(e)}'))
                return
        else:
            self.stdout.write(self.style.ERROR('没有指定输入文件'))
            return
        
        # 限制处理数量
        if limit and len(missing_posters) > limit:
            missing_posters = missing_posters[:limit]
            self.stdout.write(f'根据限制，将处理 {limit} 部电影')
        
        # 开始下载海报
        success_count = 0
        failure_count = 0
        
        for i, movie in enumerate(missing_posters):
            movie_id = movie['movie_id']
            title = movie.get('title', '')
            original_title = movie.get('original_title', '')
            year = movie.get('year', '')
            
            self.stdout.write(f'[{i+1}/{len(missing_posters)}] 处理 {movie_id} ({title}) 的海报...')
            
            # 检查本地是否已存在海报
            local_poster = os.path.join(poster_dir, f'{movie_id}.jpg')
            local_poster_hash = os.path.join(poster_dir, f'{hashlib.md5(str(movie_id).encode()).hexdigest()}.jpg')
            
            if os.path.exists(local_poster) or os.path.exists(local_poster_hash):
                self.stdout.write(f'  海报已存在，跳过处理')
                continue
            
            # 尝试使用不同的源获取海报
            image_data = None
            
            # 优先尝试使用Douban的原始URL（如果有）
            if 'image_url' in movie and movie['image_url']:
                image_url = movie['image_url']
                if image_data is None and 'doubanio.com' in image_url and (source in ['all', 'douban']):
                    self.stdout.write(f'  尝试使用Douban原始URL: {image_url}')
                    image_data = self._download_image(image_url, retry_count)
            
            # 尝试豆瓣备用URL格式（p + movie_id）
            if image_data is None and (source in ['all', 'douban']):
                patterns = [
                    f'https://img9.doubanio.com/view/photo/s_ratio_poster/public/p{movie_id}.jpg',
                    f'https://img1.doubanio.com/view/photo/s_ratio_poster/public/p{movie_id}.jpg',
                    f'https://img2.doubanio.com/view/photo/l_ratio_poster/public/p{movie_id}.jpg'
                ]
                for pattern_url in patterns:
                    self.stdout.write(f'  尝试使用Douban备用URL: {pattern_url}')
                    image_data = self._download_image(pattern_url, retry_count)
                    if image_data:
                        break
                    time.sleep(delay / 2)  # 减少同源请求间隔
            
            # 尝试Mtime时光网
            if image_data is None and (source in ['all', 'mtime']):
                # 构建搜索查询
                search_query = f'{title} {year}'
                if original_title and original_title != title:
                    search_query = f'{search_query} {original_title}'
                
                search_url = f'http://front-gateway.mtime.com/library/movie/search.api?keyword={urllib.parse.quote(search_query)}&pageIndex=1&pageSize=20&searchType=0'
                self.stdout.write(f'  尝试使用Mtime搜索: {search_query}')
                
                try:
                    # 添加随机的User-Agent
                    headers = {
                        'User-Agent': self._get_random_user_agent(),
                        'Referer': 'http://www.mtime.com/',
                    }
                    
                    # 发送搜索请求
                    response = requests.get(search_url, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        search_data = response.json()
                        if 'data' in search_data and 'movies' in search_data['data'] and search_data['data']['movies']:
                            movie_result = search_data['data']['movies'][0]  # 取第一个结果
                            
                            # 获取海报URL
                            if 'posterUrl' in movie_result and movie_result['posterUrl']:
                                poster_url = movie_result['posterUrl']
                                if poster_url.startswith('//'):
                                    poster_url = 'http:' + poster_url
                                self.stdout.write(f'  Mtime找到海报URL: {poster_url}')
                                
                                # 下载海报
                                image_data = self._download_image(poster_url, retry_count)
                    else:
                        self.stdout.write(self.style.ERROR(f'  Mtime API请求失败: {response.status_code}'))
                
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Mtime搜索出错: {str(e)}'))
                
                time.sleep(delay)  # 添加延迟
            
            # 尝试直接网页搜索
            if image_data is None and (source in ['all', 'google']):
                # 构建搜索查询
                search_query = f'{title} {year} movie poster'
                if original_title and original_title != title:
                    search_query = f'{original_title} {year} movie poster'
                
                self.stdout.write(f'  尝试使用网页搜索: {search_query}')
                
                # 尝试直接访问一些常见的电影海报网站
                sites = [
                    f'https://m.media-amazon.com/images/M/MV5B{hashlib.md5(search_query.encode()).hexdigest()[:10]}.jpg',  # IMDb风格URL
                    f'https://image.tmdb.org/t/p/original/{hashlib.md5(search_query.encode()).hexdigest()[:10]}.jpg',  # TMDB风格URL
                ]
                
                for site_url in sites:
                    self.stdout.write(f'  尝试直接URL格式: {site_url}')
                    image_data = self._download_image(site_url, retry_count)
                    if image_data:
                        break
                    time.sleep(delay / 2)
            
            # 保存海报
            if image_data:
                try:
                    # 保存原始图片
                    img = Image.open(BytesIO(image_data))
                    img = img.convert('RGB')  # 确保图片为RGB模式
                    
                    # 调整到合适尺寸，保持比例
                    max_width, max_height = 600, 900
                    if img.width > max_width or img.height > max_height:
                        img.thumbnail((max_width, max_height), Image.LANCZOS)
                    
                    # 保存图片
                    img.save(local_poster, 'JPEG', quality=90)
                    img.save(local_poster_hash, 'JPEG', quality=90)
                    
                    self.stdout.write(self.style.SUCCESS(f'  成功保存 {movie_id} ({title}) 的海报'))
                    success_count += 1
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  保存图片出错: {str(e)}'))
                    failure_count += 1
            else:
                self.stdout.write(self.style.ERROR(f'  所有方法都无法获取 {movie_id} ({title}) 的海报'))
                failure_count += 1
            
            # 添加延迟以避免API限制
            time.sleep(delay)
        
        # 输出统计信息
        self.stdout.write('\n下载完成!')
        self.stdout.write(f'总共尝试: {len(missing_posters)}')
        self.stdout.write(f'成功获取: {success_count}')
        self.stdout.write(f'获取失败: {failure_count}')
        
        if success_count == len(missing_posters):
            self.stdout.write(self.style.SUCCESS('全部获取成功!'))
        elif success_count > 0:
            self.stdout.write(self.style.WARNING(f'部分获取成功, 成功率: {success_count/len(missing_posters)*100:.2f}%'))
        else:
            self.stdout.write(self.style.ERROR('全部获取失败!'))
    
    def _download_image(self, url, retry_count=3):
        """下载图片并返回图片数据"""
        for i in range(retry_count):
            try:
                headers = {
                    'User-Agent': self._get_random_user_agent(),
                    'Referer': 'https://www.google.com/',
                    'Accept': 'image/webp,image/*,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Connection': 'keep-alive',
                }
                
                response = requests.get(url, headers=headers, timeout=10)
                
                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'image' in content_type.lower():
                        return response.content
                    else:
                        self.stdout.write(self.style.WARNING(f'    内容类型不是图片: {content_type}'))
                else:
                    self.stdout.write(self.style.WARNING(f'    HTTP错误: {response.status_code} (尝试 {i+1}/{retry_count})'))
            
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'    下载出错: {str(e)} (尝试 {i+1}/{retry_count})'))
            
            time.sleep(1)  # 重试前等待
        
        return None
    
    def _get_random_user_agent(self):
        """获取随机的User-Agent"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36 Edg/91.0.864.54',
        ]
        return random.choice(user_agents) 