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
    help = '从多个API获取缺失的电影海报，按顺序尝试不同的API'

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
            '--tmdb_key',
            type=str,
            default='3e543f4a9b834ebe753fe40f6086889b',
            help='TMDB API密钥',
            required=False
        )
        parser.add_argument(
            '--omdb_key',
            type=str,
            default='5f070074',
            help='OMDB API密钥',
            required=False
        )
        parser.add_argument(
            '--proxy',
            type=str,
            help='代理服务器地址，格式如 http://127.0.0.1:7890',
            required=False
        )
        parser.add_argument(
            '--no_baidu',
            action='store_true',
            help='不使用百度图片搜索',
            required=False
        )
        parser.add_argument(
            '--no_bing',
            action='store_true',
            help='不使用必应图片搜索',
            required=False
        )
        parser.add_argument(
            '--no_tmdb',
            action='store_true',
            help='不使用TMDB API',
            required=False
        )
        parser.add_argument(
            '--no_omdb',
            action='store_true',
            help='不使用OMDB API',
            required=False
        )

    def handle(self, *args, **options):
        input_file = options.get('input')
        limit = options.get('limit')
        delay = options.get('delay', 1.0)
        tmdb_key = options.get('tmdb_key', '3e543f4a9b834ebe753fe40f6086889b')
        omdb_key = options.get('omdb_key', '5f070074')
        proxy = options.get('proxy')
        
        # 功能开关
        use_baidu = not options.get('no_baidu', False)
        use_bing = not options.get('no_bing', False)
        use_tmdb = not options.get('no_tmdb', False)
        use_omdb = not options.get('no_omdb', False)
        
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
        self.stdout.write(f'开始从多个API获取电影海报，存储目录: {poster_dir}')
        
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
        # 使用sorted函数而不是sort方法，因为missing_posters可能不是列表
        missing_posters = sorted(missing_posters, key=lambda x: x.get('collect_count', 0), reverse=True)
        
        # 限制处理数量
        if limit and len(missing_posters) > limit:
            missing_posters = missing_posters[:limit]
            self.stdout.write(f'根据限制，将处理 {limit} 部电影')
        
        # 开始获取海报
        total_count = len(missing_posters)
        success_count = 0
        failure_count = 0
        
        for i, movie in enumerate(missing_posters):
            movie_id = movie['movie_id']
            title = movie.get('title', '')
            original_title = movie.get('original_title', '')
            year = movie.get('year', '')
            
            self.stdout.write(f'[{i+1}/{total_count}] 处理 {movie_id} ({title}) 的海报...')
            
            # 按顺序尝试不同的API，直到成功获取海报
            # 1. 首先尝试TMDB API
            if use_tmdb and not self._save_poster_exists(movie_id, poster_dir):
                if self._try_tmdb_api(movie_id, title, original_title, year, tmdb_key, poster_dir, proxies):
                    self.stdout.write(self.style.SUCCESS(f'  成功使用TMDB API获取 {movie_id} ({title}) 的海报'))
                    success_count += 1
                    continue
                time.sleep(delay)
            
            # 2. 然后尝试OMDB API
            if use_omdb and not self._save_poster_exists(movie_id, poster_dir):
                if self._try_omdb_api(movie_id, title, original_title, year, omdb_key, poster_dir, proxies):
                    self.stdout.write(self.style.SUCCESS(f'  成功使用OMDB API获取 {movie_id} ({title}) 的海报'))
                    success_count += 1
                    continue
                time.sleep(delay)
            
            # 3. 接着尝试Bing图片搜索
            if use_bing and not self._save_poster_exists(movie_id, poster_dir):
                if self._try_bing_image_search(movie_id, title, original_title, year, poster_dir, proxies):
                    self.stdout.write(self.style.SUCCESS(f'  成功使用Bing图片搜索获取 {movie_id} ({title}) 的海报'))
                    success_count += 1
                    continue
                time.sleep(delay)
            
            # 4. 最后尝试百度图片搜索
            if use_baidu and not self._save_poster_exists(movie_id, poster_dir):
                if self._try_baidu_image_search(movie_id, title, original_title, year, poster_dir, proxies):
                    self.stdout.write(self.style.SUCCESS(f'  成功使用百度图片搜索获取 {movie_id} ({title}) 的海报'))
                    success_count += 1
                    continue
                time.sleep(delay)
            
            # 如果所有API都失败了，增加失败计数
            if not self._save_poster_exists(movie_id, poster_dir):
                self.stdout.write(self.style.ERROR(f'  所有API都无法获取 {movie_id} ({title}) 的海报'))
                failure_count += 1
        
        # 输出统计信息
        remaining_count = total_count - success_count - failure_count
        self.stdout.write('\n获取完成!')
        self.stdout.write(f'总共尝试: {total_count}')
        self.stdout.write(f'成功获取: {success_count}')
        self.stdout.write(f'获取失败: {failure_count}')
        self.stdout.write(f'已存在或跳过: {remaining_count}')
        
        if success_count == total_count:
            self.stdout.write(self.style.SUCCESS('全部获取成功!'))
        elif success_count > 0:
            self.stdout.write(self.style.WARNING(f'部分获取成功, 成功率: {success_count/total_count*100:.2f}%'))
        else:
            self.stdout.write(self.style.ERROR('全部获取失败!'))
    
    def _save_poster_exists(self, movie_id, poster_dir):
        """检查海报是否已存在"""
        local_poster = os.path.join(poster_dir, f'{movie_id}.jpg')
        local_poster_hash = os.path.join(poster_dir, f'{hashlib.md5(str(movie_id).encode()).hexdigest()}.jpg')
        return os.path.exists(local_poster) or os.path.exists(local_poster_hash)
    
    def _save_poster(self, movie_id, image_data, poster_dir):
        """保存海报到本地"""
        try:
            # 保存原始图片
            local_path = os.path.join(poster_dir, f'{movie_id}.jpg')
            hash_path = os.path.join(poster_dir, f'{hashlib.md5(str(movie_id).encode()).hexdigest()}.jpg')
            
            # 使用PIL处理图片
            img = Image.open(BytesIO(image_data))
            img = img.convert('RGB')  # 确保图片为RGB模式
            
            # 调整到合适尺寸，保持比例
            max_width, max_height = 600, 900
            if img.width > max_width or img.height > max_height:
                img.thumbnail((max_width, max_height), Image.LANCZOS)
            
            # 保存图片
            img.save(local_path, 'JPEG', quality=90)
            img.save(hash_path, 'JPEG', quality=90)
            return True
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  保存图片出错: {str(e)}'))
            return False
    
    def _get_random_user_agent(self):
        """获取随机的User-Agent"""
        return f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(80, 100)}.0.{random.randint(4000, 5000)}.{random.randint(1, 200)} Safari/537.36'
    
    def _try_tmdb_api(self, movie_id, title, original_title, year, api_key, poster_dir, proxies=None):
        """尝试使用TMDB API获取海报"""
        try:
            self.stdout.write('  尝试使用TMDB API...')
            
            # 构建搜索参数
            search_title = original_title if original_title else title
            search_url = f'https://api.themoviedb.org/3/search/movie'
            search_params = {
                'api_key': api_key,
                'query': search_title,
                'year': year,
                'language': 'zh-CN',
                'include_adult': 'true'
            }
            
            # 添加随机的User-Agent
            headers = {'User-Agent': self._get_random_user_agent()}
            
            # 发送请求到TMDB API进行搜索
            response = requests.get(search_url, params=search_params, headers=headers, proxies=proxies, timeout=30)
            
            if response.status_code == 200:
                search_results = response.json()
                
                if search_results.get('results') and len(search_results['results']) > 0:
                    # 找到最匹配的结果
                    tmdb_id = None
                    poster_path = None
                    
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
                        self.stdout.write(f'  TMDB找到海报URL: {poster_url}')
                        
                        # 下载海报
                        img_response = requests.get(poster_url, headers=headers, proxies=proxies, timeout=30)
                        
                        if img_response.status_code == 200:
                            # 检查内容类型是否为图片
                            content_type = img_response.headers.get('Content-Type', '')
                            if 'image' in content_type.lower():
                                return self._save_poster(movie_id, img_response.content, poster_dir)
                            else:
                                self.stdout.write(self.style.WARNING(f'  TMDB内容类型不是图片: {content_type}'))
                        else:
                            self.stdout.write(self.style.ERROR(f'  TMDB下载图片失败: {img_response.status_code}'))
                    else:
                        self.stdout.write(self.style.WARNING('  TMDB未找到有效海报路径'))
                else:
                    self.stdout.write(self.style.WARNING('  TMDB搜索结果为空'))
            else:
                self.stdout.write(self.style.ERROR(f'  TMDB API搜索请求失败: {response.status_code}'))
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  TMDB API获取海报出错: {str(e)}'))
        
        return False
    
    def _try_omdb_api(self, movie_id, title, original_title, year, api_key, poster_dir, proxies=None):
        """尝试使用OMDB API获取海报"""
        try:
            self.stdout.write('  尝试使用OMDB API...')
            
            # 构建查询参数
            search_title = original_title if original_title else title
            search_params = {
                'apikey': api_key,
                't': search_title,
                'y': year,
                'plot': 'short',
                'r': 'json'
            }
            
            # 添加随机的User-Agent
            headers = {'User-Agent': self._get_random_user_agent()}
            
            # 发送请求到OMDB API
            response = requests.get('http://www.omdbapi.com/', params=search_params, headers=headers, proxies=proxies, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('Response') == 'True' and data.get('Poster') and data.get('Poster') != 'N/A':
                    poster_url = data.get('Poster')
                    self.stdout.write(f'  OMDB找到海报URL: {poster_url}')
                    
                    # 下载海报
                    img_response = requests.get(poster_url, headers=headers, proxies=proxies, timeout=30)
                    
                    if img_response.status_code == 200:
                        # 检查内容类型是否为图片
                        content_type = img_response.headers.get('Content-Type', '')
                        if 'image' in content_type.lower():
                            return self._save_poster(movie_id, img_response.content, poster_dir)
                        else:
                            self.stdout.write(self.style.WARNING(f'  OMDB内容类型不是图片: {content_type}'))
                    else:
                        self.stdout.write(self.style.ERROR(f'  OMDB下载图片失败: {img_response.status_code}'))
                else:
                    self.stdout.write(self.style.WARNING('  OMDB未找到有效海报'))
            else:
                self.stdout.write(self.style.ERROR(f'  OMDB API请求失败: {response.status_code}'))
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  OMDB API获取海报出错: {str(e)}'))
        
        return False
    
    def _try_bing_image_search(self, movie_id, title, original_title, year, poster_dir, proxies=None):
        """尝试使用Bing图片搜索获取海报"""
        try:
            self.stdout.write('  尝试使用Bing图片搜索...')
            
            # 构建搜索查询
            search_title = original_title if original_title else title
            search_query = f'{search_title} {year} movie poster'
            
            # 添加随机的User-Agent和Referer
            headers = {
                'User-Agent': self._get_random_user_agent(),
                'Referer': 'https://www.bing.com/images/search',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'TE': 'Trailers',
            }
            
            # 发送搜索请求
            search_url = f'https://www.bing.com/images/search?q={search_query.replace(" ", "+")}&form=HDRSC2&first=1'
            response = requests.get(search_url, headers=headers, proxies=proxies, timeout=30)
            
            if response.status_code == 200:
                html_content = response.text
                
                # 简单解析HTML获取图片链接
                # 这种方法不太可靠，实际应用中可能需要使用BeautifulSoup或正则表达式
                image_urls = []
                start_marker = '"murl":"'
                end_marker = '"'
                start_index = 0
                
                while True:
                    start_index = html_content.find(start_marker, start_index)
                    if start_index == -1:
                        break
                    
                    start_index += len(start_marker)
                    end_index = html_content.find(end_marker, start_index)
                    if end_index == -1:
                        break
                    
                    image_url = html_content[start_index:end_index].replace('\\', '')
                    if image_url not in image_urls:
                        image_urls.append(image_url)
                    
                    start_index = end_index
                
                # 尝试从前5个URL获取图片
                for i, image_url in enumerate(image_urls[:5]):
                    try:
                        self.stdout.write(f'  Bing尝试第{i+1}个URL: {image_url}')
                        img_response = requests.get(image_url, headers={'User-Agent': self._get_random_user_agent()}, proxies=proxies, timeout=30)
                        
                        if img_response.status_code == 200:
                            # 检查内容类型是否为图片
                            content_type = img_response.headers.get('Content-Type', '')
                            if 'image' in content_type.lower():
                                if self._save_poster(movie_id, img_response.content, poster_dir):
                                    return True
                            else:
                                self.stdout.write(self.style.WARNING(f'  Bing内容类型不是图片: {content_type}'))
                        else:
                            self.stdout.write(self.style.ERROR(f'  Bing下载图片失败: {img_response.status_code}'))
                    
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'  Bing下载图片出错: {str(e)}'))
                
                if image_urls:
                    self.stdout.write(self.style.WARNING(f'  Bing找到{len(image_urls)}张图片，但下载失败'))
                else:
                    self.stdout.write(self.style.WARNING('  Bing未找到有效图片'))
            else:
                self.stdout.write(self.style.ERROR(f'  Bing搜索请求失败: {response.status_code}'))
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Bing图片搜索出错: {str(e)}'))
        
        return False
    
    def _try_baidu_image_search(self, movie_id, title, original_title, year, poster_dir, proxies=None):
        """尝试使用百度图片搜索获取海报"""
        try:
            self.stdout.write('  尝试使用百度图片搜索...')
            
            # 构建搜索查询
            search_title = title  # 使用中文标题可能更合适
            search_query = f'{search_title} {year} 电影海报'
            
            # 添加随机的User-Agent和Referer
            headers = {
                'User-Agent': self._get_random_user_agent(),
                'Referer': 'https://image.baidu.com/search/index',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Connection': 'keep-alive',
            }
            
            # 发送搜索请求
            search_url = f'https://image.baidu.com/search/index?tn=baiduimage&word={search_query}'
            response = requests.get(search_url, headers=headers, proxies=proxies, timeout=30)
            
            if response.status_code == 200:
                html_content = response.text
                
                # 简单解析HTML获取图片链接
                image_urls = []
                start_marker = '"objURL":"'
                end_marker = '"'
                start_index = 0
                
                while True:
                    start_index = html_content.find(start_marker, start_index)
                    if start_index == -1:
                        break
                    
                    start_index += len(start_marker)
                    end_index = html_content.find(end_marker, start_index)
                    if end_index == -1:
                        break
                    
                    image_url = html_content[start_index:end_index].replace('\\', '')
                    if image_url not in image_urls:
                        image_urls.append(image_url)
                    
                    start_index = end_index
                
                # 尝试从前5个URL获取图片
                for i, image_url in enumerate(image_urls[:5]):
                    try:
                        self.stdout.write(f'  百度尝试第{i+1}个URL: {image_url}')
                        # 百度图片链接可能需要特殊的请求头
                        img_headers = {
                            'User-Agent': self._get_random_user_agent(),
                            'Referer': 'https://image.baidu.com/',
                            'Accept': 'image/webp,image/*,*/*;q=0.8',
                            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                            'Connection': 'keep-alive',
                        }
                        img_response = requests.get(image_url, headers=img_headers, proxies=proxies, timeout=30)
                        
                        if img_response.status_code == 200:
                            # 检查内容类型是否为图片
                            content_type = img_response.headers.get('Content-Type', '')
                            if 'image' in content_type.lower():
                                if self._save_poster(movie_id, img_response.content, poster_dir):
                                    return True
                            else:
                                self.stdout.write(self.style.WARNING(f'  百度内容类型不是图片: {content_type}'))
                        else:
                            self.stdout.write(self.style.ERROR(f'  百度下载图片失败: {img_response.status_code}'))
                    
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'  百度下载图片出错: {str(e)}'))
                
                if image_urls:
                    self.stdout.write(self.style.WARNING(f'  百度找到{len(image_urls)}张图片，但下载失败'))
                else:
                    self.stdout.write(self.style.WARNING('  百度未找到有效图片'))
            else:
                self.stdout.write(self.style.ERROR(f'  百度搜索请求失败: {response.status_code}'))
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  百度图片搜索出错: {str(e)}'))
        
        return False 