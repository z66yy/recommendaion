"""
批量预加载电影图片到本地存储的Django命令
"""

import os
import time
import hashlib
import logging
import concurrent.futures
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '批量预加载电影图片到本地存储'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=500,
            help='要预加载的电影数量，默认为500'
        )
        
        parser.add_argument(
            '--concurrency',
            type=int,
            default=10,
            help='同时下载的图片数量，默认为10'
        )
        
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='每批处理的电影数量，默认为100'
        )
        
        parser.add_argument(
            '--batch-pause',
            type=int,
            default=2,
            help='批次之间的暂停时间(秒)，默认为2秒'
        )
        
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='跳过已存在的图片'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        concurrency = options['concurrency']
        batch_size = options['batch_size']
        batch_pause = options['batch_pause']
        skip_existing = options['skip_existing']
        
        self.stdout.write(f"开始批量预加载电影图片...")
        self.stdout.write(f"- 预加载数量: {limit} 部电影")
        self.stdout.write(f"- 并发下载数: {concurrency}")
        self.stdout.write(f"- 批处理大小: {batch_size}")
        self.stdout.write(f"- 批次暂停时间: {batch_pause}秒")
        self.stdout.write(f"- 跳过已存在图片: {'是' if skip_existing else '否'}")
        
        # 确保存储目录存在
        os.makedirs(settings.IMAGE_PROXY['LOCAL_STORAGE_PATH'], exist_ok=True)
        
        start_time = time.time()
        images_processed = 0
        images_downloaded = 0
        failed_downloads = 0
        skipped_images = 0
        
        # 获取热门电影列表
        self.stdout.write("正在获取热门电影列表...")
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.images, m.collect_count
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.images IS NOT NULL AND m.images != '{}'
                ORDER BY m.collect_count DESC, m.ratings_count DESC
                LIMIT %s
            """, [limit])
            
            movies = []
            for row in cursor.fetchall():
                movies.append({
                    'movie_id': row[0],
                    'images': row[1],
                    'collect_count': row[2]
                })
        
        self.stdout.write(f"获取到 {len(movies)} 部电影的信息")
        
        # 按批次处理
        total_batches = (len(movies) + batch_size - 1) // batch_size
        for batch_index in range(total_batches):
            start_idx = batch_index * batch_size
            end_idx = min((batch_index + 1) * batch_size, len(movies))
            batch = movies[start_idx:end_idx]
            
            self.stdout.write(f"正在处理第 {batch_index + 1}/{total_batches} 批 ({start_idx + 1}-{end_idx})")
            
            # 处理所有电影图片
            movie_images = []
            
            for movie in batch:
                try:
                    # 解析图片URL
                    image_str = movie['images']
                    image_data = None
                    
                    try:
                        # 尝试解析JSON
                        import json
                        image_data = json.loads(image_str)
                    except (json.JSONDecodeError, TypeError):
                        try:
                            # 尝试解析Python字典字符串
                            import ast
                            image_data = ast.literal_eval(image_str)
                        except (ValueError, SyntaxError):
                            # 尝试从字符串中提取URL
                            import re
                            urls = re.findall(r'https?://[^\s,\'"]+', image_str)
                            if urls:
                                image_data = {
                                    'large': urls[0],
                                    'medium': urls[0],
                                    'small': urls[0]
                                }
                    
                    if image_data:
                        # 优先使用大图，其次是中图，最后是小图
                        image_url = image_data.get('large') or image_data.get('medium') or image_data.get('small')
                        if image_url:
                            # 计算文件名
                            url_hash = hashlib.md5(image_url.encode('utf-8')).hexdigest()
                            local_path = os.path.join(settings.IMAGE_PROXY['LOCAL_STORAGE_PATH'], f"{url_hash}.jpg")
                            
                            # 检查是否存在
                            if skip_existing and os.path.exists(local_path):
                                skipped_images += 1
                                continue
                            
                            movie_images.append({
                                'movie_id': movie['movie_id'],
                                'image_url': image_url,
                                'local_path': local_path,
                                'url_hash': url_hash
                            })
                except Exception as e:
                    self.stderr.write(f"处理电影 {movie.get('movie_id')} 的图片信息时出错: {str(e)}")
            
            # 并发下载图片
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = {executor.submit(self.download_image, image): image for image in movie_images}
                
                for future in concurrent.futures.as_completed(futures):
                    image = futures[future]
                    try:
                        result = future.result()
                        images_processed += 1
                        
                        if result:
                            images_downloaded += 1
                        else:
                            failed_downloads += 1
                        
                        # 显示进度
                        if images_processed % 10 == 0:
                            elapsed = time.time() - start_time
                            self.stdout.write(f"进度: {images_processed}/{len(movie_images)}, 成功: {images_downloaded}, 失败: {failed_downloads}, 用时: {elapsed:.1f}秒")
                    
                    except Exception as e:
                        self.stderr.write(f"下载电影 {image['movie_id']} 的图片时出错: {str(e)}")
                        failed_downloads += 1
            
            # 批次之间暂停
            if batch_index < total_batches - 1 and batch_pause > 0:
                self.stdout.write(f"批次暂停 {batch_pause} 秒...")
                time.sleep(batch_pause)
        
        # 统计结果
        elapsed = time.time() - start_time
        self.stdout.write(self.style.SUCCESS(
            f"图片预加载完成!\n"
            f"- 处理电影数: {len(movies)}\n"
            f"- 跳过已存在: {skipped_images}\n"
            f"- 尝试下载: {images_processed}\n"
            f"- 成功下载: {images_downloaded}\n"
            f"- 下载失败: {failed_downloads}\n"
            f"- 总用时: {elapsed:.1f}秒\n"
            f"- 平均速度: {images_downloaded / elapsed:.1f}张/秒"
        ))
    
    def download_image(self, image):
        """下载单张图片到本地存储"""
        try:
            with requests.Session() as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Referer': 'https://movie.douban.com/'
                }
                
                response = session.get(
                    image['image_url'],
                    headers=headers,
                    timeout=settings.IMAGE_PROXY.get('TIMEOUT', 5),
                    verify=settings.IMAGE_PROXY.get('VERIFY_SSL', False)
                )
                
                response.raise_for_status()
                
                # 保存图片
                with open(image['local_path'], 'wb') as f:
                    f.write(response.content)
                
                # 可选：添加节流，防止请求过快
                time.sleep(0.1)
                
                return True
        except Exception as e:
            logger.error(f"下载图片失败 (电影ID: {image['movie_id']}): {str(e)}")
            return False 