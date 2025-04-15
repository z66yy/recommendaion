import os
import json
import hashlib
import math
import textwrap
import random
from io import BytesIO
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection
from movies.views import dictfetchall
from PIL import Image, ImageDraw, ImageFont

class Command(BaseCommand):
    help = '为缺失海报的电影生成默认海报图片'

    def add_arguments(self, parser):
        parser.add_argument('--input', type=str, help='从检查命令生成的JSON文件中读取缺失海报信息')
        parser.add_argument('--limit', type=int, help='限制处理的电影数量')
        parser.add_argument('--font', type=str, help='字体文件路径')
        parser.add_argument('--width', type=int, default=400, help='海报宽度，默认400')
        parser.add_argument('--height', type=int, default=600, help='海报高度，默认600')

    def handle(self, *args, **options):
        input_file = options.get('input')
        limit = options.get('limit')
        font_path = options.get('font')
        width = options.get('width', 400)
        height = options.get('height', 600)
        
        # 确保海报存储目录存在
        poster_dir = settings.IMAGE_PROCESSING['LOCAL_STORAGE_PATH']
        os.makedirs(poster_dir, exist_ok=True)
        
        self.stdout.write(self.style.SUCCESS(f"开始生成默认电影海报，存储目录: {poster_dir}"))
        
        missing_posters = []
        
        # 如果提供了输入文件，从文件中读取缺失海报信息
        if input_file and os.path.exists(input_file):
            self.stdout.write(f"从文件 {input_file} 读取缺失海报信息")
            with open(input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                missing_posters = data.get('missing_posters', [])
            
            # 应用数量限制
            if limit and limit < len(missing_posters):
                missing_posters = missing_posters[:limit]
                self.stdout.write(f"限制处理数量: {limit}")
        else:
            # 查询数据库获取所有电影
            self.stdout.write("从数据库查询缺失海报的电影")
            with connection.cursor() as cursor:
                sql = """
                    SELECT m.movie_id, m.title, m.original_title, m.images, m.rating, 
                           m.collect_count, m.year, m.genres
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
                    
                    # 计算本地文件路径
                    local_path = os.path.join(poster_dir, f'{movie_id}.jpg')
                    
                    # 检查海报是否存在
                    if not os.path.exists(local_path):
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
                                'genres': movie.get('genres', '')
                            })
        
        total_missing = len(missing_posters)
        self.stdout.write(f"找到 {total_missing} 部缺失海报的电影需要生成默认海报")
        
        if not total_missing:
            self.stdout.write(self.style.SUCCESS("没有需要生成默认海报的电影，任务完成"))
            return
        
        # 尝试加载字体
        try:
            # 如果提供了字体路径，使用提供的字体
            if font_path and os.path.exists(font_path):
                title_font = ImageFont.truetype(font_path, 36)
                subtitle_font = ImageFont.truetype(font_path, 24)
                text_font = ImageFont.truetype(font_path, 20)
            else:
                # 尝试加载系统字体
                system_font_path = None
                if os.name == 'nt':  # Windows
                    system_font_path = 'C:/Windows/Fonts/msyh.ttc'  # 微软雅黑
                elif os.name == 'posix':  # Linux/Mac
                    system_font_path = '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'
                
                if system_font_path and os.path.exists(system_font_path):
                    title_font = ImageFont.truetype(system_font_path, 36)
                    subtitle_font = ImageFont.truetype(system_font_path, 24)
                    text_font = ImageFont.truetype(system_font_path, 20)
                else:
                    # 使用默认字体
                    title_font = ImageFont.load_default()
                    subtitle_font = ImageFont.load_default()
                    text_font = ImageFont.load_default()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"加载字体失败: {str(e)}，使用默认字体"))
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            text_font = ImageFont.load_default()
        
        # 生成默认海报
        success_count = 0
        for i, movie in enumerate(missing_posters):
            movie_id = movie.get('movie_id')
            title = movie.get('title', '未知标题')
            original_title = movie.get('original_title', '')
            year = movie.get('year', 0)
            
            self.stdout.write(f"[{i+1}/{total_missing}] 生成 {movie_id} ({title}) 的默认海报...")
            
            # 使用movie_id作为文件名
            local_path = os.path.join(poster_dir, f'{movie_id}.jpg')
            
            try:
                # 生成随机背景颜色
                # 避免太亮或太暗的颜色
                r = random.randint(40, 200)
                g = random.randint(40, 200)
                b = random.randint(40, 200)
                background_color = (r, g, b)
                
                # 文本颜色：白色或黑色，取决于背景亮度
                brightness = (r * 299 + g * 587 + b * 114) / 1000
                text_color = '#ffffff' if brightness < 128 else '#000000'
                
                # 创建海报图片
                img = Image.new('RGB', (width, height), background_color)
                draw = ImageDraw.Draw(img)
                
                # 绘制渐变效果
                for y in range(height):
                    for x in range(width):
                        # 随机噪点
                        noise = random.randint(-15, 15)
                        # 顶部到底部的渐变
                        gradient_factor = y / height
                        r_grad = max(0, min(255, r - int(30 * gradient_factor) + noise))
                        g_grad = max(0, min(255, g - int(30 * gradient_factor) + noise))
                        b_grad = max(0, min(255, b - int(30 * gradient_factor) + noise))
                        img.putpixel((x, y), (r_grad, g_grad, b_grad))
                
                # 添加电影标题
                title_y = height // 6
                # 如果标题太长，分行显示
                if len(title) > 15:
                    lines = textwrap.wrap(title, width=15)
                    for line in lines:
                        title_bbox = draw.textbbox((0, 0), line, font=title_font)
                        title_width = title_bbox[2] - title_bbox[0]
                        title_x = (width - title_width) // 2
                        draw.text((title_x, title_y), line, font=title_font, fill=text_color)
                        title_y += title_font.size + 10
                else:
                    title_bbox = draw.textbbox((0, 0), title, font=title_font)
                    title_width = title_bbox[2] - title_bbox[0]
                    title_x = (width - title_width) // 2
                    draw.text((title_x, title_y), title, font=title_font, fill=text_color)
                    title_y += title_font.size + 20
                
                # 添加原始标题（如果存在且与标题不同）
                if original_title and original_title != title:
                    subtitle_y = title_y + 20
                    if len(original_title) > 20:
                        lines = textwrap.wrap(original_title, width=20)
                        for line in lines:
                            subtitle_bbox = draw.textbbox((0, 0), line, font=subtitle_font)
                            subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
                            subtitle_x = (width - subtitle_width) // 2
                            draw.text((subtitle_x, subtitle_y), line, font=subtitle_font, fill=text_color)
                            subtitle_y += subtitle_font.size + 5
                    else:
                        subtitle_bbox = draw.textbbox((0, 0), original_title, font=subtitle_font)
                        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
                        subtitle_x = (width - subtitle_width) // 2
                        draw.text((subtitle_x, subtitle_y), original_title, font=subtitle_font, fill=text_color)
                
                # 添加年份
                if year:
                    year_y = height // 2
                    year_text = f"{year}"
                    year_bbox = draw.textbbox((0, 0), year_text, font=subtitle_font)
                    year_width = year_bbox[2] - year_bbox[0]
                    year_x = (width - year_width) // 2
                    draw.text((year_x, year_y), year_text, font=subtitle_font, fill=text_color)
                
                # 添加类型信息（如果存在）
                genres = movie.get('genres', '')
                if genres:
                    # 简单处理，只取前两个类型
                    try:
                        if isinstance(genres, str):
                            if genres.startswith('[') and genres.endswith(']'):
                                genres = genres[1:-1].replace("'", "").split(', ')
                            else:
                                genres = [g.strip() for g in genres.split(',')]
                        genres_text = ' / '.join(genres[:2])
                        genres_y = height * 2 // 3
                        genres_bbox = draw.textbbox((0, 0), genres_text, font=text_font)
                        genres_width = genres_bbox[2] - genres_bbox[0]
                        genres_x = (width - genres_width) // 2
                        draw.text((genres_x, genres_y), genres_text, font=text_font, fill=text_color)
                    except:
                        pass
                
                # 添加电影ID
                id_y = height - 40
                id_text = f"ID: {movie_id}"
                id_bbox = draw.textbbox((0, 0), id_text, font=text_font)
                id_width = id_bbox[2] - id_bbox[0]
                id_x = (width - id_width) // 2
                draw.text((id_x, id_y), id_text, font=text_font, fill=text_color)
                
                # 保存图片
                img.save(local_path, 
                        format=settings.IMAGE_PROCESSING['DEFAULT_FORMAT'],
                        quality=settings.IMAGE_PROCESSING['DEFAULT_QUALITY'])
                
                self.stdout.write(self.style.SUCCESS(f"  成功生成 {movie_id} ({title}) 的默认海报"))
                success_count += 1
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  生成 {movie_id} ({title}) 的默认海报失败: {str(e)}"))
        
        # 输出统计信息
        self.stdout.write(self.style.SUCCESS("\n生成完成!"))
        self.stdout.write(f"总共尝试: {total_missing}")
        self.stdout.write(f"成功生成: {success_count}")
        self.stdout.write(f"生成失败: {total_missing - success_count}")
        
        if success_count == total_missing:
            self.stdout.write(self.style.SUCCESS("全部生成成功!"))
        elif success_count > 0:
            self.stdout.write(self.style.WARNING(f"部分生成成功 ({success_count}/{total_missing})"))
        else:
            self.stdout.write(self.style.ERROR("全部生成失败!")) 