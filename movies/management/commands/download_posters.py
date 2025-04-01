import os
import hashlib
import random
import time
import asyncio
import aiohttp
import aiofiles
from urllib.parse import urlparse
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from functools import partial

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '高性能下载电影海报到本地并测量占用空间'
    
    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1000, help='处理的电影数量')
        parser.add_argument('--size', type=str, default='medium', help='图片尺寸 (small/medium/large)')
        parser.add_argument('--output-dir', type=str, default='movie_posters', help='保存图片的目录')
        parser.add_argument('--min-delay', type=float, default=0.2, help='最小下载间隔(秒)')
        parser.add_argument('--max-delay', type=float, default=1.0, help='最大下载间隔(秒)')
        parser.add_argument('--timeout', type=int, default=10, help='请求超时时间(秒)')
        parser.add_argument('--retries', type=int, default=3, help='重试次数')
        parser.add_argument('--batch-size', type=int, default=200, help='批次大小')
        parser.add_argument('--batch-pause', type=int, default=10, help='批次间暂停时间(秒)')
        parser.add_argument('--debug', action='store_true', help='启用调试输出')
        parser.add_argument('--continue-from', type=int, default=0, help='从指定索引继续下载')
        parser.add_argument('--concurrency', type=int, default=10, help='并发下载数')
        parser.add_argument('--no-async', action='store_true', help='不使用异步下载')
        
    def handle(self, *args, **options):
        limit = options['limit']
        size = options['size']
        output_dir = options['output_dir']
        min_delay = options['min_delay']
        max_delay = options['max_delay']
        timeout = options['timeout']
        retries = options['retries']
        batch_size = options['batch_size']
        batch_pause = options['batch_pause']
        debug = options['debug']
        continue_from = options['continue_from']
        concurrency = options['concurrency']
        no_async = options['no_async']
        
        # 创建输出目录
        full_output_dir = os.path.join(settings.MEDIA_ROOT, output_dir)
        if not os.path.exists(full_output_dir):
            os.makedirs(full_output_dir)
            
        self.stdout.write(f'开始高性能下载电影海报到 {full_output_dir}...')
        self.stdout.write(f'批次大小: {batch_size}, 批次间暂停: {batch_pause}秒, 并发数: {concurrency}')
        
        # 用户代理列表 - 扩充更多现代浏览器
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 12_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.2 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:96.0) Gecko/20100101 Firefox/96.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 12.1; rv:95.0) Gecko/20100101 Firefox/95.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36 Edg/96.0.1054.62',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36 Edg/97.0.1072.62',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:95.0) Gecko/20100101 Firefox/95.0'
        ]
        
        # 引荐来源列表 - 扩充
        referers = [
            'https://movie.douban.com/',
            'https://www.douban.com/',
            'https://search.douban.com/movie/',
            'https://movie.douban.com/explore',
            'https://movie.douban.com/chart',
            'https://movie.douban.com/tag/',
            'https://movie.douban.com/subject/',
            'https://movie.douban.com/review/best/',
            'https://book.douban.com/',
            'https://music.douban.com/'
        ]
        
        with connection.cursor() as cursor:
            # 获取评分最高的电影
            cursor.execute(f"""
                SELECT m.movie_id, m.title, m.images as raw_images
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                ORDER BY COALESCE(mr.rating, 0) DESC, m.collect_count DESC
                LIMIT {limit}
            """)
            
            # 转换为字典
            movies = self.dictfetchall(cursor)
            self.stdout.write(f'获取到 {len(movies)} 部电影')
            
            # 如果需要从特定位置继续，裁剪电影列表
            if continue_from > 0:
                if continue_from < len(movies):
                    self.stdout.write(f'从索引 {continue_from} 继续下载')
                    movies = movies[continue_from:]
                else:
                    self.stdout.write(self.style.ERROR(f'指定的索引 {continue_from} 超出范围'))
                    return
            
            # 根据是否使用异步选择不同的下载方法
            if no_async:
                self.sync_download_posters(
                    movies, full_output_dir, size, min_delay, max_delay, 
                    timeout, retries, batch_size, batch_pause, debug,
                    user_agents, referers
                )
            else:
                # 使用异步下载
                asyncio.run(self.async_download_posters(
                    movies, full_output_dir, size, min_delay, max_delay, 
                    timeout, retries, batch_size, batch_pause, debug,
                    user_agents, referers, concurrency
                ))
    
    def sync_download_posters(self, movies, full_output_dir, size, min_delay, max_delay, 
                             timeout, retries, batch_size, batch_pause, debug,
                             user_agents, referers):
        """同步下载方法（原有的下载逻辑，保留以备不需要异步时使用）"""
        processed = 0
        skipped = 0
        errors = 0
        total_size = 0
        downloaded = 0
        batch_count = 0
        total_processed = 0
        
        # 计算子任务进度的函数
        def update_progress(current, total):
            bar_length = 50
            progress = current / total if total > 0 else 0
            arrow = '=' * int(bar_length * progress)
            spaces = ' ' * (bar_length - len(arrow))
            return f"[{arrow}{spaces}] {int(progress * 100)}% ({current}/{total})"
        
        for i, movie in enumerate(movies):
            try:
                movie_id = movie['movie_id']
                title = movie.get('title', '未知标题')
                raw_images = movie.get('raw_images', '')
                
                # 显示进度条
                if i % 5 == 0 or i == len(movies) - 1:
                    progress = update_progress(i + 1, len(movies))
                    self.stdout.write(f"\r处理进度: {progress}", ending='\r')
                    self.stdout.flush()
                
                # 解析图片数据
                image_data = self.parse_image_data(raw_images)
                
                if not image_data or size not in image_data:
                    skipped += 1
                    if debug and skipped <= 10:
                        self.stdout.write(f"\n跳过电影 {movie_id} ({title}): 无{size}尺寸图片")
                    continue
                    
                image_url = image_data[size]
                
                # 生成文件名
                url_hash = hashlib.md5(image_url.encode()).hexdigest()[:10]
                filename = f"{movie_id}_{url_hash}"
                
                # 获取扩展名
                parsed_url = urlparse(image_url)
                path = parsed_url.path
                ext = os.path.splitext(path)[1]
                if not ext:
                    ext = '.jpg'  # 默认扩展名
                
                full_filename = f"{filename}{ext}"
                output_path = os.path.join(full_output_dir, full_filename)
                
                # 如果文件已存在，跳过下载但统计大小
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    total_size += file_size
                    processed += 1
                    total_processed += 1
                    if debug and processed <= 10:
                        self.stdout.write(f"\n电影 {movie_id} ({title}) 图片已存在，大小: {self.format_size(file_size)}")
                    
                    batch_count += 1
                    if batch_count >= batch_size:
                        self.stdout.write(f"\n\n已完成第 {total_processed // batch_size} 批 ({batch_count}张)，暂停{batch_pause}秒...")
                        time.sleep(batch_pause)
                        batch_count = 0
                        self.stdout.write("继续下载...\n")
                        
                    continue
                
                # 下载图片
                success = False
                for attempt in range(retries + 1):
                    try:
                        # 随机选择用户代理和引荐来源
                        headers = {
                            'User-Agent': random.choice(user_agents),
                            'Referer': random.choice(referers),
                            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                            'Connection': 'keep-alive',
                            'Sec-Fetch-Dest': 'image',
                            'Sec-Fetch-Mode': 'no-cors',
                            'Sec-Fetch-Site': 'same-site',
                            'Pragma': 'no-cache',
                            'Cache-Control': 'no-cache'
                        }
                        
                        import requests
                        response = requests.get(
                            image_url, 
                            timeout=timeout, 
                            stream=True,
                            headers=headers
                        )
                        response.raise_for_status()
                        
                        # 写入文件
                        with open(output_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        
                        # 获取文件大小
                        file_size = os.path.getsize(output_path)
                        total_size += file_size
                        downloaded += 1
                        
                        if debug or processed % 20 == 0 or processed < 10:
                            self.stdout.write(f"\n下载电影 {movie_id} ({title}) 图片成功，大小: {self.format_size(file_size)}")
                        
                        success = True
                        break
                    except Exception as e:
                        if attempt < retries:
                            wait_time = 2 ** (attempt + 1) + random.uniform(1, 3)
                            self.stdout.write(f"\n下载失败，{wait_time:.1f}秒后重试: {str(e)}")
                            time.sleep(wait_time)
                        else:
                            raise
                
                if not success:
                    raise Exception("达到最大重试次数，下载失败")
                
                processed += 1
                total_processed += 1
                batch_count += 1
                
                # 检查是否需要批次暂停
                if batch_count >= batch_size:
                    current_batch = total_processed // batch_size
                    self.stdout.write(f"\n\n已完成第 {current_batch} 批 ({batch_count}张)，暂停{batch_pause}秒...")
                    self.stdout.write(f"当前进度: {i+1}/{len(movies)} ({((i+1)/len(movies))*100:.1f}%)")
                    
                    # 输出当前统计
                    avg_size = total_size / processed if processed > 0 else 0
                    estimated_full_size = avg_size * 112864  # 根据总电影数量估算
                    
                    self.stdout.write(
                        f"中间统计:\n"
                        f"处理电影: {processed}部\n"
                        f"下载成功: {downloaded}部\n"
                        f"平均大小: {self.format_size(avg_size)}\n"
                        f"预估总空间: {self.format_size(estimated_full_size)}"
                    )
                    
                    time.sleep(batch_pause)
                    batch_count = 0
                    self.stdout.write("\n继续下载...\n")
                
                # 随机延迟，避免请求过于频繁
                delay = random.uniform(min_delay, max_delay)
                time.sleep(delay)
                
            except Exception as e:
                errors += 1
                error_msg = f"\n下载电影 {movie.get('movie_id')} ({movie.get('title', '未知')}) 图片时出错: {str(e)}"
                logger.error(error_msg)
                self.stdout.write(self.style.ERROR(error_msg))
                if debug:
                    self.stdout.write(traceback.format_exc())
                
                # 额外延迟，以防被阻止
                time.sleep(random.uniform(2, 5))
                
                # 错误也计入批次
                batch_count += 1
                if batch_count >= batch_size:
                    self.stdout.write(f"\n\n发生错误后，已达到批次大小，暂停{batch_pause}秒...")
                    time.sleep(batch_pause)
                    batch_count = 0
                    self.stdout.write("\n继续下载...\n")
        
        # 汇总报告
        self.print_summary(processed, len(movies), downloaded, skipped, errors, total_size)

    async def async_download_posters(self, movies, full_output_dir, size, min_delay, max_delay, 
                                   timeout, retries, batch_size, batch_pause, debug,
                                   user_agents, referers, concurrency):
        """异步下载方法，支持并发下载多个图片"""
        processed = 0
        skipped = 0
        errors = 0
        defaults_used = 0  # 计数使用默认图片的次数
        not_found = 0      # 计数404错误的次数
        total_size = 0
        downloaded = 0
        batch_count = 0
        total_processed = 0
        
        # 进度显示函数
        def update_progress(current, total):
            bar_length = 50
            progress = current / total if total > 0 else 0
            arrow = '=' * int(bar_length * progress)
            spaces = ' ' * (bar_length - len(arrow))
            return f"[{arrow}{spaces}] {int(progress * 100)}% ({current}/{total})"
        
        # 预处理所有电影，准备下载任务
        download_tasks = []
        for i, movie in enumerate(movies):
            movie_id = movie.get('movie_id')
            title = movie.get('title', '未知标题')
            raw_images = movie.get('raw_images', '')
            
            # 解析图片数据
            image_data = self.parse_image_data(raw_images)
            
            if not image_data or size not in image_data:
                skipped += 1
                if debug and skipped <= 10:
                    self.stdout.write(f"\n跳过电影 {movie_id} ({title}): 无{size}尺寸图片")
                continue
                
            image_url = image_data[size]
            
            # 生成文件名
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:10]
            filename = f"{movie_id}_{url_hash}"
            
            # 获取扩展名
            parsed_url = urlparse(image_url)
            path = parsed_url.path
            ext = os.path.splitext(path)[1]
            if not ext:
                ext = '.jpg'  # 默认扩展名
            
            full_filename = f"{filename}{ext}"
            output_path = os.path.join(full_output_dir, full_filename)
            
            # 如果文件已存在，跳过下载但统计大小
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                total_size += file_size
                processed += 1
                total_processed += 1
                if debug and processed <= 10:
                    self.stdout.write(f"\n电影 {movie_id} ({title}) 图片已存在，大小: {self.format_size(file_size)}")
                continue
            
            # 创建下载任务
            download_tasks.append({
                'movie_id': movie_id,
                'title': title,
                'image_url': image_url,
                'output_path': output_path,
                'index': i
            })
        
        # 显示预处理结果
        self.stdout.write(f"\n预处理完成，需要下载 {len(download_tasks)} 张图片，已跳过 {skipped} 张")
        
        # 分批次处理下载任务
        for batch_index, batch_start in enumerate(range(0, len(download_tasks), batch_size)):
            batch_end = min(batch_start + batch_size, len(download_tasks))
            current_batch = download_tasks[batch_start:batch_end]
            
            self.stdout.write(f"\n开始下载第 {batch_index + 1} 批次 ({len(current_batch)} 张图片)")
            
            # 创建并发下载任务
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                # 限制并发数的信号量
                semaphore = asyncio.Semaphore(concurrency)
                
                # 创建下载协程
                tasks = []
                for task in current_batch:
                    download_coro = self.download_single_file(
                        session, task, semaphore, user_agents, referers, 
                        timeout, retries, min_delay, max_delay, debug
                    )
                    tasks.append(download_coro)
                
                # 同时执行批次中的所有下载任务
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 处理结果
                for result in batch_results:
                    if isinstance(result, Exception):
                        errors += 1
                        self.stdout.write(self.style.ERROR(f"\n下载错误: {str(result)}"))
                    elif result:
                        # 检查是否是404错误但使用了默认图片
                        if result.get('is_default', False):
                            defaults_used += 1
                            processed += 1
                            total_processed += 1
                            total_size += result['file_size']
                            self.stdout.write(
                                f"\n电影 {result['movie_id']} ({result['title']}) 使用默认图片替代"
                            )
                        # 检查是否是404错误但被跳过
                        elif result.get('is_error', False):
                            not_found += 1
                            self.stdout.write(self.style.WARNING(
                                f"\n电影 {result['movie_id']} ({result['title']}) 图片未找到，已跳过"
                            ))
                        else:
                            downloaded += 1
                            processed += 1
                            total_processed += 1
                            total_size += result['file_size']
                            
                            if debug or downloaded % 20 == 0 or downloaded < 10:
                                self.stdout.write(
                                    f"\n下载电影 {result['movie_id']} ({result['title']}) 成功，"
                                    f"大小: {self.format_size(result['file_size'])}"
                                )
            
            # 批次完成后显示进度
            progress = update_progress(batch_end, len(download_tasks))
            self.stdout.write(f"\n批次进度: {progress}")
            self.stdout.write(f"总进度: {total_processed}/{len(movies) - skipped} "
                             f"({(total_processed/(len(movies) - skipped))*100:.1f}%)")
            
            # 输出当前统计
            avg_size = total_size / processed if processed > 0 else 0
            estimated_full_size = avg_size * 112864  # 根据总电影数量估算
            
            self.stdout.write(
                f"当前统计:\n"
                f"处理电影: {processed}部\n"
                f"下载成功: {downloaded}部\n"
                f"使用默认图片: {defaults_used}部\n"
                f"图片未找到: {not_found}部\n"
                f"跳过: {skipped}部\n"
                f"错误: {errors}部\n"
                f"平均大小: {self.format_size(avg_size)}\n"
                f"预估总空间: {self.format_size(estimated_full_size)}"
            )
            
            # 批次间暂停
            if batch_end < len(download_tasks):
                self.stdout.write(f"\n批次完成，暂停{batch_pause}秒...")
                await asyncio.sleep(batch_pause)
                self.stdout.write("继续下载下一批次...\n")
        
        # 汇总报告
        self.print_summary(processed, len(movies), downloaded, defaults_used, not_found, skipped, errors, total_size)
    
    async def download_single_file(self, session, task, semaphore, user_agents, referers, 
                                 timeout, retries, min_delay, max_delay, debug):
        """异步下载单个文件"""
        movie_id = task['movie_id']
        title = task['title']
        image_url = task['image_url']
        output_path = task['output_path']
        
        # 使用信号量限制并发数
        async with semaphore:
            # 随机延迟
            await asyncio.sleep(random.uniform(min_delay, max_delay))
            
            # 记录原始URL，以便在出错时尝试其他尺寸
            original_url = image_url
            
            for attempt in range(retries + 1):
                try:
                    # 随机选择用户代理和引荐来源
                    headers = {
                        'User-Agent': random.choice(user_agents),
                        'Referer': random.choice(referers),
                        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                        'Connection': 'keep-alive',
                        'Sec-Fetch-Dest': 'image',
                        'Sec-Fetch-Mode': 'no-cors',
                        'Sec-Fetch-Site': 'same-site',
                        'Pragma': 'no-cache',
                        'Cache-Control': 'no-cache'
                    }
                    
                    async with session.get(image_url, headers=headers, timeout=timeout) as response:
                        if response.status == 404 and attempt == 0:
                            # 404错误时尝试其他尺寸的URL
                            if 's_ratio_poster' in image_url:
                                # 尝试m尺寸
                                image_url = image_url.replace('s_ratio_poster', 'm_ratio_poster')
                                logger.info(f"图片404，尝试更大尺寸: {image_url}")
                                continue
                            elif 'm_ratio_poster' in image_url:
                                # 尝试l尺寸
                                image_url = image_url.replace('m_ratio_poster', 'l_ratio_poster')
                                logger.info(f"图片404，尝试更大尺寸: {image_url}")
                                continue
                            elif 'photo/s/' in image_url:
                                # 尝试不同路径格式
                                image_url = image_url.replace('photo/s/', 'photo/m/')
                                logger.info(f"图片404，尝试不同路径: {image_url}")
                                continue
                        
                        response.raise_for_status()
                        
                        # 读取内容
                        content = await response.read()
                        
                        # 检查内容是否为空或太小
                        if len(content) < 500:  # 假设小于500字节的图片可能是无效的
                            raise Exception(f"图片内容太小 ({len(content)} 字节)，可能是无效图片")
                        
                        # 异步写入文件
                        async with aiofiles.open(output_path, 'wb') as f:
                            await f.write(content)
                        
                        # 获取文件大小
                        file_size = os.path.getsize(output_path)
                        
                        return {
                            'movie_id': movie_id,
                            'title': title,
                            'file_size': file_size
                        }
                        
                except aiohttp.ClientResponseError as e:
                    if e.status == 404:
                        # 404错误特别处理
                        if attempt < retries:
                            # 尝试图片ID变形
                            if attempt == 0 and 'p' in image_url:
                                # 尝试修改图片ID (例如p1234567.jpg尝试p1234567890.jpg)
                                try:
                                    # 提取p后面的数字
                                    import re
                                    p_id_match = re.search(r'p(\d+)\.', image_url)
                                    if p_id_match:
                                        p_id = p_id_match.group(1)
                                        # 尝试查找替代图片ID (这里使用简单算法，实际项目应使用API或数据库)
                                        alt_ids = [str(int(p_id) + i) for i in [-100, -10, -1, 1, 10, 100]]
                                        for alt_id in alt_ids:
                                            alt_url = re.sub(r'p\d+\.', f'p{alt_id}.', image_url)
                                            image_url = alt_url
                                            logger.info(f"尝试替代图片ID: {alt_url}")
                                            break
                                except Exception as id_err:
                                    logger.warning(f"尝试替代图片ID时出错: {str(id_err)}")
                                
                                # 继续尝试新URL
                                continue
                            
                            wait_time = 1.0 + random.uniform(0.5, 1.5)  # 404错误等待较短
                            if debug:
                                logger.warning(f"图片404错误 {movie_id} ({title}): {e.status}, {e.message}, url='{image_url}'")
                            await asyncio.sleep(wait_time)
                        else:
                            # 最后一次尝试，检查是否有默认图片可用
                            try:
                                # 使用默认图片
                                default_path = os.path.join(settings.STATIC_ROOT, 'images', 'default-poster.jpg')
                                if os.path.exists(default_path):
                                    import shutil
                                    shutil.copy(default_path, output_path)
                                    file_size = os.path.getsize(output_path)
                                    logger.warning(f"使用默认图片替代 {movie_id} ({title})")
                                    return {
                                        'movie_id': movie_id,
                                        'title': title,
                                        'file_size': file_size,
                                        'is_default': True
                                    }
                            except Exception as copy_err:
                                logger.error(f"复制默认图片失败: {str(copy_err)}")
                            
                            # 记录错误但不抛出异常，允许继续下载其他图片
                            error_msg = f"图片404错误 {movie_id} ({title}): {e.status}, {e.message}, url='{original_url}'"
                            logger.error(error_msg)
                            return {
                                'movie_id': movie_id,
                                'title': title,
                                'file_size': 0,
                                'error': error_msg,
                                'is_error': True
                            }
                    else:
                        # 其他HTTP错误
                        if attempt < retries:
                            wait_time = 2 ** (attempt + 1) + random.uniform(1, 3)
                            if debug:
                                logger.warning(f"下载 {movie_id} ({title}) 失败: HTTP {e.status}, {e.message}，将在 {wait_time:.1f} 秒后重试")
                            await asyncio.sleep(wait_time)
                        else:
                            error_msg = f"下载 {movie_id} ({title}) 失败: HTTP {e.status}, {e.message}"
                            logger.error(error_msg)
                            if debug:
                                logger.error(traceback.format_exc())
                            raise Exception(error_msg)
                except Exception as e:
                    if attempt < retries:
                        wait_time = 2 ** (attempt + 1) + random.uniform(1, 3)
                        if debug:
                            logger.warning(f"下载 {movie_id} ({title}) 失败: {str(e)}，将在 {wait_time:.1f} 秒后重试")
                        await asyncio.sleep(wait_time)
                    else:
                        error_msg = f"下载 {movie_id} ({title}) 失败: {str(e)}"
                        logger.error(error_msg)
                        if debug:
                            logger.error(traceback.format_exc())
                        raise Exception(error_msg)
        
        return None  # 不应该执行到这里
    
    def print_summary(self, processed, total_movies, downloaded, defaults_used, not_found, skipped, errors, total_size):
        """打印下载汇总信息"""
        avg_size = total_size / processed if processed > 0 else 0
        estimated_full_size = avg_size * 112864  # 根据总电影数量估算
        
        self.stdout.write(self.style.SUCCESS(
            f"\n\n下载完成！总统计数据:\n"
            f"处理电影: {processed}/{total_movies} 部\n"
            f"实际下载: {downloaded} 部\n"
            f"使用默认图片: {defaults_used} 部\n"
            f"图片未找到: {not_found} 部\n"
            f"跳过: {skipped} 部\n"
            f"错误: {errors} 部\n"
            f"总大小: {self.format_size(total_size)}\n"
            f"平均大小: {self.format_size(avg_size)} / 电影\n"
            f"预估112864部电影所需空间: {self.format_size(estimated_full_size)}"
        ))
    
    def parse_image_data(self, image_str):
        """解析电影图片数据，返回不同尺寸的URL"""
        import json
        import ast
        import re
        
        if not image_str or image_str == '{}':
            return None
            
        try:
            # 尝试解析JSON
            data = json.loads(image_str)
            return data
        except json.JSONDecodeError:
            try:
                # 尝试解析Python字典字符串
                data = ast.literal_eval(image_str)
                return data
            except (ValueError, SyntaxError):
                # 如果无法解析，尝试从字符串中提取URL
                urls = re.findall(r'https?://[^\s,\'"]+', image_str)
                if urls:
                    return {
                        'large': urls[0],
                        'medium': urls[0],
                        'small': urls[0]
                    }
        return None
    
    def dictfetchall(self, cursor):
        """将游标返回的结果转换为字典"""
        columns = [col[0] for col in cursor.description]
        return [
            dict(zip(columns, row))
            for row in cursor.fetchall()
        ]
    
    def format_size(self, size_bytes):
        """格式化文件大小显示"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0 or unit == 'TB':
                break
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} {unit}" 