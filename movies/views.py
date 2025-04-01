from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Count, F, Avg, Q
from django.http import JsonResponse, HttpResponse, Http404, FileResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_page
import json
from .models import Movie, Genre, MovieImageCache, CollectMovieDB, CollectMovieTypeDB, CollectTop250MovieDB, MoviePubdateDB, MovieRatingDB, MovieTagDB
from users.models import UserRating
from django.core.paginator import Paginator
from django.db import connection
from datetime import datetime, timedelta
from django.http import Http404
import logging
import ast
import re
import requests
from django.core.cache import cache
from django.conf import settings
import os
from django.utils.http import urlsafe_base64_decode
import base64
from urllib.parse import unquote, urlparse
import hashlib
from io import BytesIO
import time
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, HTTPError
from urllib3.util.retry import Retry
from PIL import Image, ImageDraw, ImageFont
import pymysql
from concurrent.futures import ThreadPoolExecutor, as_completed

# 检查是否安装了PIL
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    logger.warning("无法导入PIL/Pillow库，图片处理功能将受限")
    HAS_PIL = False

logger = logging.getLogger(__name__)

# 1x1透明GIF常量
TRANSPARENT_1PX_GIF = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')

# 全局变量，存储预加载状态
PRELOAD_COMPLETED = False

# 辅助函数：将数据库游标结果转换为字典列表
def dictfetchall(cursor):
    """将游标结果转换为字典列表"""
    columns = [col[0] for col in cursor.description]
    return [
        dict(zip(columns, row))
        for row in cursor.fetchall()
    ]

# 函数：系统启动时预加载电影图片到内存
def preload_startup_images():
    """
    系统启动时自动预加载电影图片到内存缓存
    这个函数会在应用初始化或首次访问时调用
    可以大幅提高首页和热门电影页面的加载速度
    """
    global PRELOAD_COMPLETED
    
    # 已禁用图片预加载功能
    logger.info("[系统初始化] 图片预加载功能已暂时禁用")
    PRELOAD_COMPLETED = True
    return

def parse_image_data(images_str, size='medium', movie_id=None, title=None):
    """
    解析图片数据
    :param images_str: 图片数据字符串
    :param size: 图片尺寸，可选值：small, medium, large
    :param movie_id: 电影ID
    :param title: 电影标题
    :return: 解析后的图片数据字典
    """
    try:
        if not images_str:
            return None
            
        # 如果是字符串，尝试解析JSON
        if isinstance(images_str, str):
            # 处理Python字典字符串
            if images_str.startswith("{'") or images_str.startswith("{'"):
                images_str = images_str.replace("'", '"')
            try:
                images = json.loads(images_str)
            except json.JSONDecodeError:
                # 如果JSON解析失败，尝试使用ast.literal_eval
                try:
                    images = ast.literal_eval(images_str)
                except (ValueError, SyntaxError):
                    # 如果都解析失败，检查是否是一个URL
                    if images_str.startswith('http'):
                        return {
                            'url': images_str,
                            'movie_id': movie_id,
                            'title': title
                        }
                    return None
        else:
            images = images_str
            
        # 检查是否是字典类型
        if not isinstance(images, dict):
            # 尝试直接作为URL返回
            if isinstance(images_str, str) and images_str.startswith('http'):
                return {
                    'url': images_str,
                    'movie_id': movie_id,
                    'title': title
                }
            return None
            
        # 获取指定尺寸的URL
        url = images.get(size)
        if not url:
            # 如果指定尺寸不存在，尝试其他尺寸
            for size_key in ['medium', 'large', 'small']:
                url = images.get(size_key)
                if url:
                    break
                    
        if not url:
            # 尝试检查本地文件系统中是否存在该电影的海报
            if movie_id:
                poster_path = os.path.join(settings.MEDIA_ROOT, 'movie_posters', f"{movie_id}.jpg")
                if os.path.exists(poster_path):
                    return {
                        'url': f'/media/movie_posters/{movie_id}.jpg',
                        'movie_id': movie_id,
                        'title': title,
                        'local': True
                    }
            return None
            
        return {
            'url': url,
            'movie_id': movie_id,
            'title': title
        }
    except Exception as e:
        logger.error(f"[图片代理] 解析图片数据失败: {str(e)}, 数据: {images_str}")
        # 尝试检查本地文件系统中是否存在该电影的海报
        if movie_id:
            poster_path = os.path.join(settings.MEDIA_ROOT, 'movie_posters', f"{movie_id}.jpg")
            if os.path.exists(poster_path):
                return {
                    'url': f'/media/movie_posters/{movie_id}.jpg',
                    'movie_id': movie_id,
                    'title': title,
                    'local': True
                }
        return None

def home(request):
    """
    电影首页，展示精选电影和类型
    """
    # 启动图片预加载
    if not PRELOAD_COMPLETED:
        # 将预加载放入后台线程执行，不阻塞首页访问
        import threading
        preload_thread = threading.Thread(target=preload_startup_images)
        preload_thread.daemon = True
        preload_thread.start()
        logger.info("[首页] 启动后台线程进行图片预加载")
    
    # 添加顶层异常处理
    try:
        # 根据用户登录状态显示不同内容
        if request.user.is_authenticated:
            return _home_view_for_authenticated_user(request)
        else:
            return _home_view_for_guest(request)
    except pymysql.MySQLError as e:
        # 专门处理MySQL相关错误
        error_code = e.args[0] if len(e.args) > 0 else 'Unknown'
        error_msg = e.args[1] if len(e.args) > 1 else str(e)
        logger.error(f"[首页] 数据库操作出错: ({error_code}) {error_msg}")
        
        # 特殊处理"Lost connection"错误
        if error_code == 2013:
            # 尝试重新连接后重试
            logger.info("[首页] 尝试重新连接后重新加载页面")
            
            # 第二次尝试
            try:
                if request.user.is_authenticated:
                    return _home_view_for_authenticated_user(request)
                else:
                    return _home_view_for_guest(request)
            except Exception as retry_err:
                logger.error(f"[首页] 重试加载失败: {str(retry_err)}")
        
        # 返回特定的数据库错误页面
        return render(request, 'error.html', {
            'error_message': f'数据库连接异常，请稍后再试。错误代码: {error_code}',
            'error_code': 'DATABASE_CONNECTION_ERROR'
        })
    except Exception as e:
        logger.error(f"[首页] 加载首页时出错: {str(e)}")
        # 返回通用错误页面
        return render(request, 'error.html', {
            'error_message': '加载首页时出错，请稍后再试。',
            'error_code': 'GENERAL_ERROR'
        })

def _home_view_for_authenticated_user(request):
    """已登录用户的首页视图"""
    # 用于存储所有要显示的电影
    context = {
        'featured_movies': [],
        'personal_recommendations': [],
        'popular_movies': [],
        'recently_rated_movies': [],
        'genres': []
    }
    
    # 1. 获取精选电影
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.original_title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating,
                       m.directors, m.actor, m.summary, m.countries
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.collect_count > 1000
                ORDER BY RAND()
                LIMIT 6
            """)
            featured_movies_data = dictfetchall(cursor)
            
            context['featured_movies'] = [_process_movie_data(movie) for movie in featured_movies_data]
    except Exception as e:
        logger.error(f"[首页] 获取精选电影时出错: {str(e)}")
    
    # 2. 个人推荐
    try:
        context['personal_recommendations'] = _get_personalized_recommendations(request.user.id)
    except Exception as e:
        logger.error(f"[首页] 获取个人推荐时出错: {str(e)}")
        
    # 3. 热门电影
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                ORDER BY m.collect_count DESC
                LIMIT 6
            """)
            popular_movies = dictfetchall(cursor)
            context['popular_movies'] = [_process_movie_data(movie) for movie in popular_movies]
    except Exception as e:
        logger.error(f"[首页] 获取热门电影推荐时出错: {str(e)}")
    
    # 4. 最近评分的电影
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                FROM users_userrating ur
                JOIN movie_collectmoviedb m ON ur.movie_id = m.movie_id
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE ur.user_id = %s
                ORDER BY ur.updated_time DESC
                LIMIT 6
            """, [request.user.id])
            
            recent_movies = dictfetchall(cursor)
            context['recently_rated_movies'] = [_process_movie_data(movie) for movie in recent_movies]
    except Exception as e:
        logger.error(f"[首页] 获取用户最近评分电影时出错: {str(e)}")
        
    # 5. 电影类型分类
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT movie_type as name, COUNT(*) as movie_count
                FROM movie_collectmovietypedb
                GROUP BY movie_type
                ORDER BY movie_count DESC
                LIMIT 5
            """)
            
            genres = dictfetchall(cursor)
            
            # 过滤掉空的genre条目
            genres = [genre for genre in genres if genre.get('name')]
            
            # 为每个类型添加推荐电影
            for genre in genres:
                try:
                    genre_name = genre['name']
                    if not genre_name:
                        continue
                    
                    # 获取该类型的推荐电影
                    with connection.cursor() as genre_cursor:
                        genre_cursor.execute("""
                            SELECT m.movie_id, m.title, m.year, m.genres, 
                                   m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                            FROM movie_collectmoviedb m
                            LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                            WHERE m.genres LIKE %s
                            AND m.movie_id NOT IN (
                                SELECT movie_id FROM users_userrating WHERE user_id = %s
                            )
                            ORDER BY mr.rating DESC, m.collect_count DESC
                            LIMIT 6
                        """, [f'%{genre_name}%', request.user.id])
                        
                        genre_movies = dictfetchall(genre_cursor)
                        genre['recommended_movies'] = [_process_movie_data(movie) for movie in genre_movies]
                except Exception as e:
                    logger.error(f"[首页] 获取类型 '{genre_name}' 推荐电影时出错: {str(e)}")
                    genre['recommended_movies'] = []
            
            context['genres'] = genres
    except Exception as e:
        logger.error(f"[首页] 获取电影类型时出错: {str(e)}")
    
    return render(request, 'movies/home.html', context)

def _home_view_for_guest(request):
    """未登录用户的首页视图"""
    context = {
        'featured_movies': [],
        'top_rated_movies': [],
        'popular_movies': [],
        'latest_movies': [],
        'genres': []
    }
    
    # 1. 精选电影
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.original_title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating,
                       m.directors, m.actor, m.summary, m.countries
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.rating LIKE '%"average": 9%'
                   OR m.collect_count > 10000
                ORDER BY RAND()
                LIMIT 6
            """)
            featured_movies = dictfetchall(cursor)
            context['featured_movies'] = [_process_movie_data(movie) for movie in featured_movies]
    except Exception as e:
        logger.error(f"[首页] 获取精选电影时出错: {str(e)}")
    
    # 2. 高分电影
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE mr.rating >= 8 OR m.rating LIKE '%"average": 8%'
                ORDER BY mr.rating DESC, m.collect_count DESC
                LIMIT 6
            """)
            top_rated_movies = dictfetchall(cursor)
            context['top_rated_movies'] = [_process_movie_data(movie) for movie in top_rated_movies]
    except Exception as e:
        logger.error(f"[首页] 获取高分电影时出错: {str(e)}")
        
    # 3. 热门电影
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.collect_count > 1000
                ORDER BY m.collect_count DESC
                LIMIT 6
            """)
            popular_movies = dictfetchall(cursor)
            context['popular_movies'] = [_process_movie_data(movie) for movie in popular_movies]
    except Exception as e:
        logger.error(f"[首页] 获取热门电影推荐时出错: {str(e)}")
    
    # 4. 最新上映
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.year >= 2020
                ORDER BY m.year DESC, m.pubdate DESC
                LIMIT 6
            """)
            latest_movies = dictfetchall(cursor)
            context['latest_movies'] = [_process_movie_data(movie) for movie in latest_movies]
    except Exception as e:
        logger.error(f"[首页] 获取最新电影时出错: {str(e)}")
    
    # 5. 电影类型分类
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT movie_type as name, COUNT(*) as movie_count
                FROM movie_collectmovietypedb
                GROUP BY movie_type
                ORDER BY movie_count DESC
                LIMIT 5
            """)
            
            genres = dictfetchall(cursor)
            
            # 过滤掉空的genre条目
            genres = [genre for genre in genres if genre.get('name')]
            
            # 为每个类型添加推荐电影
            for genre in genres:
                try:
                    genre_name = genre['name']
                    if not genre_name:
                        continue
                    
                    # 获取该类型的推荐电影
                    with connection.cursor() as genre_cursor:
                        genre_cursor.execute("""
                            SELECT m.movie_id, m.title, m.year, m.genres, 
                                   m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                            FROM movie_collectmoviedb m
                            LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                            WHERE m.genres LIKE %s
                            ORDER BY mr.rating DESC, m.collect_count DESC
                            LIMIT 6
                        """, [f'%{genre_name}%'])
                        
                        genre_movies = dictfetchall(genre_cursor)
                        genre['recommended_movies'] = [_process_movie_data(movie) for movie in genre_movies]
                except Exception as e:
                    logger.error(f"[首页] 获取类型 '{genre_name}' 推荐电影时出错: {str(e)}")
                    genre['recommended_movies'] = []
            
            context['genres'] = genres
    except Exception as e:
        logger.error(f"[首页] 获取电影类型时出错: {str(e)}")
    
    return render(request, 'movies/home.html', context)

def _process_movie_data(movie):
    """
    处理电影数据，将JSON字符串解析为Python对象，
    并解析图片URL、评分和类别等信息
    """
    processed_movie = dict(movie)
    
    # 处理评分
    try:
        # 1. 先处理rating字段
        if 'rating' in processed_movie:
            # 如果rating是字典类型
            if isinstance(processed_movie['rating'], dict):
                # 从字典中提取average值
                if 'average' in processed_movie['rating']:
                    try:
                        processed_movie['rating'] = float(processed_movie['rating']['average'])
                    except (ValueError, TypeError):
                        processed_movie['rating'] = 0.0
            # 如果rating是字符串类型，且看起来像JSON
            elif isinstance(processed_movie['rating'], str) and processed_movie['rating'].startswith('{'):
                try:
                    import json
                    rating_dict = json.loads(processed_movie['rating'])
                    if 'average' in rating_dict:
                        try:
                            processed_movie['rating'] = float(rating_dict['average'])
                        except (ValueError, TypeError):
                            processed_movie['rating'] = 0.0
                    else:
                        processed_movie['rating'] = 0.0
                except json.JSONDecodeError:
                    # JSON解析失败，尝试使用正则表达式提取
                    import re
                    match = re.search(r'"average":\s*([\d.]+)', processed_movie['rating'])
                    if match:
                        try:
                            processed_movie['rating'] = float(match.group(1))
                        except (ValueError, TypeError):
                            processed_movie['rating'] = 0.0
                    else:
                        processed_movie['rating'] = 0.0
            else:
                # 尝试直接转换为浮点数
                try:
                    processed_movie['rating'] = float(processed_movie['rating'])
                except (ValueError, TypeError):
                    processed_movie['rating'] = 0.0
                    
        # 2. 然后检查avg_rating字段
        if 'avg_rating' in processed_movie:
            try:
                avg_rating = float(processed_movie['avg_rating'])
                # 如果rating不存在或为0，使用avg_rating的值
                if 'rating' not in processed_movie or processed_movie['rating'] == 0.0:
                    processed_movie['rating'] = avg_rating
            except (ValueError, TypeError):
                pass
        
        # 确保评分是非负数
        if 'rating' in processed_movie and (processed_movie['rating'] < 0 or not isinstance(processed_movie['rating'], (int, float))):
            processed_movie['rating'] = 0.0
        elif 'rating' not in processed_movie:
            processed_movie['rating'] = 0.0
    except Exception as e:
        logger.error(f"处理电影评分时出错: {str(e)}")
        processed_movie['rating'] = 0.0
    
    # 确保genres是列表
    try:
        if 'genres' in processed_movie:
            # 如果genres是字符串，尝试解析
            if isinstance(processed_movie['genres'], str):
                # 看起来像列表的字符串
                if processed_movie['genres'].startswith('['):
                    try:
                        import json
                        processed_movie['genres'] = json.loads(processed_movie['genres'])
                    except json.JSONDecodeError:
                        try:
                            import ast
                            processed_movie['genres'] = ast.literal_eval(processed_movie['genres'])
                        except (ValueError, SyntaxError):
                            # 如果解析失败，尝试分割字符串
                            processed_movie['genres'] = [g.strip() for g in processed_movie['genres'].split(',') if g.strip()]
                else:
                    # 普通的逗号分隔字符串
                    processed_movie['genres'] = [g.strip() for g in processed_movie['genres'].split(',') if g.strip()]
            elif isinstance(processed_movie['genres'], list):
                # 已经是列表，确保内部元素都是字符串
                processed_movie['genres'] = [str(g) if not isinstance(g, str) else g for g in processed_movie['genres']]
            else:
                processed_movie['genres'] = [str(processed_movie['genres'])]
        else:
            processed_movie['genres'] = []
    except Exception as e:
        logger.error(f"处理电影类型时出错: {str(e)}")
        processed_movie['genres'] = []
    
    # 处理导演信息
    try:
        if 'directors' in processed_movie:
            # 如果directors是字符串，尝试解析
            if isinstance(processed_movie['directors'], str):
                # 看起来像列表的字符串
                if processed_movie['directors'].startswith('['):
                    try:
                        import json
                        directors_data = json.loads(processed_movie['directors'].replace("'", '"'))
                        processed_movie['directors'] = directors_data
                    except json.JSONDecodeError:
                        try:
                            import ast
                            directors_data = ast.literal_eval(processed_movie['directors'])
                            processed_movie['directors'] = directors_data
                        except (ValueError, SyntaxError):
                            # 如果解析失败，保持字符串格式
                            processed_movie['directors'] = processed_movie['directors']
            
            # 解析directors列表中的name字段
            if isinstance(processed_movie['directors'], list):
                # 确保每个导演对象都有name字段
                for i, director in enumerate(processed_movie['directors']):
                    if isinstance(director, dict) and 'name' in director:
                        continue  # 已经有name字段，无需处理
                    elif isinstance(director, str):
                        # 如果是字符串，将其转换为包含name的字典
                        processed_movie['directors'][i] = {'name': director}
                    else:
                        # 其他情况，尝试转换为字典
                        try:
                            if isinstance(director, str) and (director.startswith('{') or director.startswith('{')):
                                # 尝试解析为字典
                                import json
                                dir_dict = json.loads(director.replace("'", '"'))
                                processed_movie['directors'][i] = dir_dict
                            elif isinstance(director, dict) and not 'name' in director and 'id' in director:
                                # 有ID但没有name，设置一个默认名称
                                processed_movie['directors'][i]['name'] = f"导演{director['id']}"
                        except Exception:
                            # 如果无法解析，使用默认name
                            processed_movie['directors'][i] = {'name': '未知导演'}
            elif isinstance(processed_movie['directors'], dict):
                # 如果是单个字典对象，确保有name字段
                if 'name' not in processed_movie['directors']:
                    # 尝试从其他字段构造name
                    if 'id' in processed_movie['directors']:
                        processed_movie['directors']['name'] = f"导演{processed_movie['directors']['id']}"
                    else:
                        processed_movie['directors']['name'] = '未知导演'
            
            # 确保是一个可迭代对象
            if not isinstance(processed_movie['directors'], (list, tuple, dict)) and processed_movie['directors']:
                # 如果不是列表、元组或字典，尝试转换为字符串
                processed_movie['directors'] = str(processed_movie['directors'])
        else:
            processed_movie['directors'] = []
    except Exception as e:
        logger.error(f"处理电影导演信息时出错: {str(e)}")
        processed_movie['directors'] = "未知导演"
    
    # 处理演员信息
    try:
        if 'actor' in processed_movie:
            # 如果actor是字符串，尝试解析
            if isinstance(processed_movie['actor'], str):
                # 看起来像列表的字符串
                if processed_movie['actor'].startswith('['):
                    try:
                        import json
                        actors_data = json.loads(processed_movie['actor'].replace("'", '"'))
                        processed_movie['actor'] = actors_data
                    except json.JSONDecodeError:
                        try:
                            import ast
                            actors_data = ast.literal_eval(processed_movie['actor'])
                            processed_movie['actor'] = actors_data
                        except (ValueError, SyntaxError):
                            # 如果解析失败，保持字符串格式
                            processed_movie['actor'] = processed_movie['actor']
            
            # 解析actor列表中的name字段
            if isinstance(processed_movie['actor'], list):
                # 确保每个演员对象都有name字段
                for i, actor in enumerate(processed_movie['actor']):
                    if isinstance(actor, dict) and 'name' in actor:
                        continue  # 已经有name字段，无需处理
                    elif isinstance(actor, str):
                        # 如果是字符串，将其转换为包含name的字典
                        processed_movie['actor'][i] = {'name': actor}
                    else:
                        # 其他情况，尝试转换为字典
                        try:
                            if isinstance(actor, str) and (actor.startswith('{') or actor.startswith('{')):
                                # 尝试解析为字典
                                import json
                                act_dict = json.loads(actor.replace("'", '"'))
                                processed_movie['actor'][i] = act_dict
                            elif isinstance(actor, dict) and not 'name' in actor and 'id' in actor:
                                # 有ID但没有name，设置一个默认名称
                                processed_movie['actor'][i]['name'] = f"演员{actor['id']}"
                        except Exception:
                            # 如果无法解析，使用默认name
                            processed_movie['actor'][i] = {'name': '未知演员'}
            elif isinstance(processed_movie['actor'], dict):
                # 如果是单个字典对象，确保有name字段
                if 'name' not in processed_movie['actor']:
                    # 尝试从其他字段构造name
                    if 'id' in processed_movie['actor']:
                        processed_movie['actor']['name'] = f"演员{processed_movie['actor']['id']}"
                    else:
                        processed_movie['actor']['name'] = '未知演员'
            
            # 确保是一个可迭代对象
            if not isinstance(processed_movie['actor'], (list, tuple, dict)) and processed_movie['actor']:
                # 如果不是列表、元组或字典，尝试转换为字符串
                processed_movie['actor'] = str(processed_movie['actor'])
        else:
            processed_movie['actor'] = []
    except Exception as e:
        logger.error(f"处理电影演员信息时出错: {str(e)}")
        processed_movie['actor'] = "未知演员"
    
    # 确保tags是列表
    try:
        if 'tags' in processed_movie:
            # 如果tags是字符串，尝试解析
            if isinstance(processed_movie['tags'], str):
                # 看起来像列表的字符串
                if processed_movie['tags'].startswith('['):
                    try:
                        import json
                        processed_movie['tags'] = json.loads(processed_movie['tags'])
                    except json.JSONDecodeError:
                        try:
                            import ast
                            processed_movie['tags'] = ast.literal_eval(processed_movie['tags'])
                        except (ValueError, SyntaxError):
                            # 如果解析失败，尝试分割字符串
                            processed_movie['tags'] = [t.strip() for t in processed_movie['tags'].split(',') if t.strip()]
                else:
                    # 普通的逗号分隔字符串
                    processed_movie['tags'] = [t.strip() for t in processed_movie['tags'].split(',') if t.strip()]
            elif isinstance(processed_movie['tags'], list):
                # 已经是列表，确保内部元素都是字符串
                processed_movie['tags'] = [str(t) if not isinstance(t, str) else t for t in processed_movie['tags']]
            else:
                processed_movie['tags'] = [str(processed_movie['tags'])]
        else:
            processed_movie['tags'] = []
    except Exception as e:
        logger.error(f"处理电影标签时出错: {str(e)}")
        processed_movie['tags'] = []
    
    # 处理图片URL
    try:
        if 'images' in processed_movie:
            # 解析图片数据
            images = parse_image_data(
                processed_movie['images'], 
                movie_id=processed_movie.get('movie_id'), 
                title=processed_movie.get('title')
            )
            
            # 获取最合适的图片URL
            cover_image = images.get('url') if images else None
            processed_movie['cover_image'] = cover_image
        else:
            # 使用默认图片
            processed_movie['cover_image'] = None
    except Exception as e:
        logger.error(f"处理电影图片时出错: {str(e)}")
        processed_movie['cover_image'] = None
    
    return processed_movie

# @cache_page(60 * 10)  # 缓存10分钟
def movie_list(request):
    """
    电影列表视图，展示所有电影
    优化后支持缓存和高效查询
    """
    page = request.GET.get('page', 1)
    sort = request.GET.get('sort', 'rating')
    
    # 查询所有电影类型
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT DISTINCT movie_type as name
            FROM movie_collectmovietypedb
            WHERE movie_type != ''
            ORDER BY movie_type
        """)
        genres = dictfetchall(cursor)
        
    # 过滤掉空的genre条目
    genres = [genre for genre in genres if genre.get('name')]
    
    # 如果没有从movie_collectmovietypedb获取到类型数据，尝试从movie_movietagdb获取
    if not genres:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT tag_name as name, COUNT(*) as count
                FROM movie_movietagdb
                WHERE tag_type = 'genre' AND tag_name != ''
                GROUP BY tag_name
                ORDER BY count DESC
            """)
            genres = dictfetchall(cursor)
        
        # 再次过滤掉空条目
        genres = [genre for genre in genres if genre.get('name')]
    
    logger.info(f"[电影列表] 获取到电影类型数量: {len(genres)}")
    for i, genre in enumerate(genres[:5]):
        logger.info(f"[电影列表] 类型 {i+1}: {genre.get('name')}")
    
    # 输出所有类型，用于调试
    logger.info(f"[电影列表] 所有类型: {[g.get('name') for g in genres]}")
    
    # 构建排序条件
    order_clause = ""
    if sort == 'rating':
        order_clause = "ORDER BY COALESCE(mr.rating, 0) DESC, m.collect_count DESC"
    elif sort == 'year':
        order_clause = "ORDER BY m.year DESC, COALESCE(mr.rating, 0) DESC"
    elif sort == 'title':
        order_clause = "ORDER BY m.title ASC, COALESCE(mr.rating, 0) DESC"
    else:
        order_clause = "ORDER BY COALESCE(mr.rating, 0) DESC, m.collect_count DESC"
    
    # 使用优化的SQL查询 - 减少查询数量
    with connection.cursor() as cursor:
        # 优化索引使用的正确语法：索引提示必须紧跟在表名后面
        query = f"""
            SELECT 
                m.movie_id,
                m.title,
                m.year,
                m.images as raw_images,
                COALESCE(mr.rating, 0) as rating,
                m.genres,
                m.collect_count
            FROM movie_collectmoviedb m 
            LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
            WHERE m.collect_count > 1000 OR COALESCE(mr.rating, 0) > 7.0
            {order_clause}
            LIMIT 500
        """
        
        cursor.execute(query)
        movies = dictfetchall(cursor)
    
    # 处理电影数据
    for movie in movies:
        # 解析电影封面图片
        movie['cover_image'] = None
        image_data = parse_image_data(movie.get('raw_images', '{}'), movie_id=movie.get('movie_id'), title=movie.get('title'))
        if image_data and image_data.get('url'):
            movie['cover_image'] = image_data['url']
        
        # 解析类型为列表
        try:
            genres_data = movie.get('genres', '')
            if isinstance(genres_data, str):
                movie['genres'] = genres_data.split(',')
            elif isinstance(genres_data, list):
                movie['genres'] = genres_data
            else:
                movie['genres'] = []
        except Exception as e:
            logger.error(f"[电影列表] 解析电影类型时出错: {str(e)}")
            movie['genres'] = []
    
    # 分页处理 - 减少每页显示数量
    paginator = Paginator(movies, 12)  # 每页显示12部电影
    try:
        movies_page = paginator.page(page)
    except PageNotAnInteger:
        movies_page = paginator.page(1)
    except EmptyPage:
        movies_page = paginator.page(paginator.num_pages)
    
    context = {
        'movies': movies_page,
        'genres': genres,
        'selectedGenre': None,
        'paginator': paginator,
        'page_obj': movies_page,
    }
    
    # 打印调试信息
    logger.info(f"[电影列表] 传递到模板的类型数量: {len(context['genres'])}")
    
    return render(request, 'movies/movie_list.html', context)

def movie_list_by_genre(request, genre_name):
    """按类型显示电影列表"""
    with connection.cursor() as cursor:
        # 使用movie_movietagdb表通过tag_name查询相关电影
        cursor.execute("""
            SELECT m.*, 
                   m.genres as raw_genres,
                   GROUP_CONCAT(DISTINCT mt.tag_name) as tags,
                   mr.rating as avg_rating,
                   m.images as raw_images
            FROM movie_collectmoviedb m
            INNER JOIN movie_movietagdb mt ON m.movie_id = mt.movie_id_id
            LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
            WHERE mt.tag_name = %s AND mt.tag_type = 'genre'
            GROUP BY m.id
            ORDER BY mr.rating DESC, m.collect_count DESC
        """, [genre_name])
        genre_movies = dictfetchall(cursor)
        logger.info(f"[类型电影] Genre {genre_name} movies count: {len(genre_movies)}")
        
        # 处理电影数据
        for movie in genre_movies:
            # 解析评分
            movie['rating'] = float(movie.get('avg_rating', 0) or 0)
            
            # 处理图片URL
            try:
                images = parse_image_data(movie.get('raw_images', '{}'), movie_id=movie.get('movie_id'), title=movie.get('title'))
                movie['cover_image'] = images.get('url')
            except (json.JSONDecodeError, AttributeError) as e:
                logger.error(f"[类型电影] 解析图片时出错: {str(e)}")
                movie['cover_image'] = None
                
            # 处理电影类型 - 尝试从raw_genres解析
            try:
                raw_genres = movie.get('raw_genres', '[]')
                if isinstance(raw_genres, list):
                    movie['genres'] = raw_genres
                elif isinstance(raw_genres, str):
                    # 尝试处理Python列表字符串格式
                    if raw_genres.startswith('[') and raw_genres.endswith(']'):
                        try:
                            movie['genres'] = eval(raw_genres)
                        except:
                            movie['genres'] = json.loads(raw_genres)
                    else:
                        movie['genres'] = json.loads(raw_genres)
                    
                    # 确保是列表
                    if isinstance(movie['genres'], str):
                        movie['genres'] = [movie['genres']]
                else:
                    movie['genres'] = []
            except Exception as e:
                logger.error(f"[类型电影] 解析电影类型时出错: {str(e)}")
                # 尝试使用tags字段
                if movie.get('tags'):
                    tags = movie.get('tags')
                    if isinstance(tags, str):
                        movie['genres'] = tags.split(',')
                    elif isinstance(tags, list):
                        movie['genres'] = tags
                    else:
                        movie['genres'] = []
                else:
                    movie['genres'] = []
                
            # 确保genres是列表
            if not isinstance(movie['genres'], list):
                movie['genres'] = [movie['genres']]
        
        # 获取所有电影类型 - 合并两个来源的数据
        # 首先从movie_movietagdb获取带有计数的类型
        cursor.execute("""
            SELECT DISTINCT tag_name as name, tag_name as id, COUNT(*) as count
            FROM movie_movietagdb
            WHERE tag_name != '' AND tag_type = 'genre'
            GROUP BY tag_name
            ORDER BY count DESC
        """)
        genres_from_tags = dictfetchall(cursor)
        
        # 再从movie_collectmovietypedb获取类型
        cursor.execute("""
            SELECT DISTINCT movie_type as name, movie_type as id
            FROM movie_collectmovietypedb
            WHERE movie_type != ''
            ORDER BY movie_type
        """)
        genres_from_types = dictfetchall(cursor)
        
        # 合并两个来源的类型数据
        genres = []
        seen_names = set()
        
        # 首先添加带有计数的类型
        for genre in genres_from_tags:
            if genre.get('name') and genre.get('name') not in seen_names:
                genres.append(genre)
                seen_names.add(genre.get('name'))
        
        # 然后添加类型表中不重复的类型
        for genre in genres_from_types:
            if genre.get('name') and genre.get('name') not in seen_names:
                genres.append(genre)
                seen_names.add(genre.get('name'))
        
        logger.info(f"[类型电影] 获取到电影类型数量: {len(genres)}")
        logger.info(f"[类型电影] 所有类型: {[g.get('name') for g in genres]}")
    
    # 分页
    paginator = Paginator(genre_movies, 12)  # 每页显示12部电影
    page = request.GET.get('page', 1)
    movies = paginator.get_page(page)
    
    context = {
        'genre_name': genre_name,
        'movies': movies,
        'genres': genres,
        'paginator': paginator,
        'page_obj': movies,
        'selectedGenre': genre_name,
    }
    
    # 打印调试信息
    logger.info(f"[类型电影] 传递到模板的类型数量: {len(context['genres'])}")
    
    return render(request, 'movies/movie_list.html', context)

def movie_detail(request, movie_id):
    """电影详情页面"""
    try:
        logger.info(f'[电影详情] 正在加载电影详情页 movie_id={movie_id}')
    
        # 使用原生SQL查询获取电影详情和评分
        with connection.cursor() as cursor:
            cursor.execute('''
                SELECT 
                    m.*, IFNULL(mr.rating, 0) as avg_rating 
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.movie_id = %s
            ''', [movie_id])
            
            result = dictfetchall(cursor)
            
            if not result:
                raise Http404("电影不存在")
            
            movie = result[0]
            
            # 处理电影数据
            movie = _process_movie_data(movie)
            
            # 详细处理评分数据，直接从rating字段中提取average值
            if isinstance(movie.get('rating'), (float, int)):
                # 已经是数值类型，不需要额外处理
                pass
            elif isinstance(movie.get('rating'), str) and movie.get('rating').startswith('{'):
                try:
                    # 尝试解析JSON
                    import json
                    import re
                    
                    # 先尝试标准JSON解析
                    try:
                        rating_data = json.loads(movie.get('rating').replace("'", '"'))
                        if isinstance(rating_data, dict) and 'average' in rating_data:
                            movie['rating'] = float(rating_data['average'])
                    except:
                        # 如果标准解析失败，使用正则表达式提取
                        match = re.search(r'"average":\s*([\d.]+)', movie.get('rating'))
                        if match:
                            movie['rating'] = float(match.group(1))
                except Exception as e:
                    logger.error(f"[电影详情] 评分解析失败: {str(e)}")
            
            # 处理avg_rating字段
            if 'avg_rating' in movie and movie.get('avg_rating') and float(movie.get('avg_rating')) > 0:
                movie['rating'] = float(movie.get('avg_rating'))
                
            # 额外处理评分人数
            if 'ratings_count' not in movie or not movie['ratings_count']:
                movie['ratings_count'] = 0
                # 尝试从rating字段中提取
                if isinstance(movie.get('rating'), str) and movie.get('rating').startswith('{'):
                    try:
                        import json
                        try:
                            rating_data = json.loads(movie.get('rating').replace("'", '"'))
                            if isinstance(rating_data, dict) and 'ratings_count' in rating_data:
                                movie['ratings_count'] = int(rating_data['ratings_count'])
                        except:
                            import re
                            count_match = re.search(r'"ratings_count":\s*(\d+)', movie.get('rating'))
                            if count_match:
                                movie['ratings_count'] = int(count_match.group(1))
                    except Exception as e:
                        logger.error(f"[电影详情] 解析评分人数出错: {str(e)}")
            
            # 打印调试信息
            logger.info(f"[电影详情] 处理后的评分数据: rating={movie.get('rating')}, ratings_count={movie.get('ratings_count')}")
            
            # 更详细的调试信息
            if isinstance(movie.get('rating'), (int, float)):
                logger.info(f"[电影详情] 评分是数值类型: {type(movie.get('rating'))}, 值: {movie.get('rating')}")
            else:
                logger.info(f"[电影详情] 评分不是数值类型: {type(movie.get('rating'))}, 值: {movie.get('rating')}")
            
            # 确保评分为有效的数值类型
            try:
                if not isinstance(movie.get('rating'), (int, float)) or movie.get('rating') <= 0:
                    movie['rating'] = 0.0
                    logger.info("[电影详情] 评分设置为默认值 0.0")
                else:
                    logger.info(f"[电影详情] 评分保持不变: {movie.get('rating')}")
            except Exception as e:
                logger.error(f"[电影详情] 处理评分时出错: {str(e)}")
                movie['rating'] = 0.0
            
            # 查找相似电影，根据类型推荐
            similar_movies = []
            
            # 获取电影类型，最多使用前3个类型
            genres = movie.get('genres', [])
            
            if genres:
                # 限制最多使用3个类型，避免查询过于复杂
                genres = genres[:3]
                
                # 为每个类型创建一个条件
                conditions = []
                params = []
                
                for genre in genres:
                    conditions.append("m.genres LIKE %s")
                    params.append(f'%{genre}%')
                
                # 构建SQL查询，减少连接和聚合操作
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(f"""
                            SELECT 
                                m.movie_id, m.title, m.year, m.genres, 
                                m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                            FROM movie_collectmoviedb m
                            LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                            WHERE ({' OR '.join(conditions)})
                            AND m.movie_id != %s
                            ORDER BY mr.rating DESC, m.collect_count DESC
                            LIMIT 6
                        """, params + [movie_id])
                        
                        similar_results = dictfetchall(cursor)
                        similar_movies = [_process_movie_data(similar) for similar in similar_results]
                except Exception as e:
                    logger.error(f"[电影详情] 获取相似电影时出错: {str(e)}")
            
            # 获取用户评分和评论（如果已登录）
            user_rating = None
            user_comment = None
            
            if request.user.is_authenticated:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute('''
                            SELECT rating, comment
                            FROM users_userrating 
                            WHERE user_id = %s AND movie_id = %s
                        ''', [request.user.id, movie_id])
                        
                        rating_results = dictfetchall(cursor)
                        
                        if rating_results:
                            user_rating_data = rating_results[0]
                            try:
                                user_rating = float(user_rating_data.get('rating', 0))
                            except (ValueError, TypeError):
                                user_rating = 0
                            user_comment = user_rating_data.get('comment', '')
                except Exception as e:
                    logger.error(f"[电影详情] 获取用户评分时出错: {str(e)}")
            
            context = {
                'movie': movie,
                'similar_movies': similar_movies,
                'user_rating': user_rating,
                'user_comment': user_comment
            }
                
            return render(request, 'movies/movie_detail.html', context)
    except Exception as e:
        logger.error(f"[电影详情] 处理电影详情时出错: {str(e)}")
        return render(request, 'error.html', {
            'error_message': f"加载电影详情时出错: {str(e)}",
            'error_code': 'DATABASE_ERROR'
        })

def search_movies(request):
    """电影搜索视图"""
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    movies = []
    
    if query:
        with connection.cursor() as cursor:
            # 搜索电影，限制结果数量
            cursor.execute("""
                SELECT DISTINCT m.*, 
                       GROUP_CONCAT(DISTINCT mt.movie_type) as tags,
                       mr.rating as avg_rating,
                       m.images as raw_images
                FROM movie_collectmoviedb m
                LEFT JOIN movie_collectmovietypedb mt ON m.id = mt.id
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.title LIKE %s OR m.original_title LIKE %s
                GROUP BY m.id
                ORDER BY mr.rating DESC, m.collect_count DESC
                LIMIT 200
            """, [f'%{query}%', f'%{query}%'])
            movies = dictfetchall(cursor)
            logger.info(f"搜索 '{query}' 找到 {len(movies)} 条结果")
            
            # 处理电影数据
            for movie in movies:
                # 解析评分
                movie['rating'] = float(movie.get('avg_rating', 0) or 0)
                
                # 处理图片URL
                try:
                    images = parse_image_data(movie.get('raw_images', '{}'), movie_id=movie.get('movie_id'), title=movie.get('title'))
                    movie['cover_image'] = images.get('url')
                except (json.JSONDecodeError, AttributeError):
                    movie['cover_image'] = None
    
    # 添加分页功能
    paginator = Paginator(movies, 12)  # 每页显示12部电影
    try:
        movies_page = paginator.page(page)
    except PageNotAnInteger:
        movies_page = paginator.page(1)
    except EmptyPage:
        movies_page = paginator.page(paginator.num_pages)
    
    context = {
        'query': query,
        'movies': movies_page,
        'paginator': paginator,
        'page_obj': movies_page,
    }
    return render(request, 'movies/search_results.html', context)

@login_required
@require_POST
def rate_movie(request, movie_id):
    """电影评分API"""
    try:
        # 输出请求体内容，便于调试
        request_body = request.body.decode('utf-8')
        print(f"Rating request body: {request_body}")
        
        data = json.loads(request_body)
        rating_value = data.get('rating')
        
        print(f"Extracted rating value: {rating_value}, type: {type(rating_value)}")
        
        # 验证评分是否存在
        if rating_value is None:
            return JsonResponse({'success': False, 'error': '评分不能为空'})
            
        # 确保评分是有效的数字
        try:
            rating = float(rating_value)
            print(f"Converted rating: {rating}")
        except (ValueError, TypeError) as e:
            print(f"Rating conversion error: {e}")
            return JsonResponse({'success': False, 'error': f'评分必须是有效数字: {e}'})
        
        # 验证评分范围
        if not (0 <= rating <= 10):
            print(f"Rating out of range: {rating}")
            return JsonResponse({'success': False, 'error': '评分必须在0到10之间'})
        
        # 检查电影是否存在
        with connection.cursor() as cursor:
            cursor.execute("SELECT movie_id FROM movie_collectmoviedb WHERE movie_id = %s", [movie_id])
            movie = dictfetchall(cursor)
            if not movie:
                print(f"Movie not found: {movie_id}")
                return JsonResponse({'success': False, 'error': '电影不存在'})
            
            # 尝试直接在users_userrating表中操作，不使用外键
            # 首先禁用外键检查
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            
            try:
                # 检查用户评分是否已存在
                cursor.execute("""
                    SELECT id FROM users_userrating 
                    WHERE user_id = %s AND movie_id = %s
                """, [request.user.id, movie_id])
                existing_rating = dictfetchall(cursor)
                
                print(f"Existing rating: {existing_rating}")
                
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                if existing_rating:
                    # 更新评分
                    cursor.execute("""
                        UPDATE users_userrating
                        SET rating = %s, updated_time = %s
                        WHERE user_id = %s AND movie_id = %s
                    """, [rating, current_time, request.user.id, movie_id])
                    print(f"Updated rating to {rating} for user {request.user.id} and movie {movie_id}")
                else:
                    # 创建新评分
                    cursor.execute("""
                        INSERT INTO users_userrating (user_id, movie_id, rating, comment, created_time, updated_time)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, [request.user.id, movie_id, rating, '', current_time, current_time])
                    print(f"Created new rating {rating} for user {request.user.id} and movie {movie_id}")
            finally:
                # 恢复外键检查
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        return JsonResponse({'success': True})
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return JsonResponse({'success': False, 'error': f'无效的评分数据: {e}'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Unexpected error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def comment_movie(request, movie_id):
    """电影评论API"""
    try:
        # 输出请求体内容，便于调试
        request_body = request.body.decode('utf-8')
        print(f"Comment request body: {request_body}")
        
        data = json.loads(request_body)
        comment = data.get('comment', '').strip()
        
        if not comment:
            return JsonResponse({'success': False, 'error': '评论内容不能为空'})
        
        with connection.cursor() as cursor:
            # 检查电影是否存在
            cursor.execute("SELECT movie_id FROM movie_collectmoviedb WHERE movie_id = %s", [movie_id])
            movie = dictfetchall(cursor)
            if not movie:
                print(f"Movie not found: {movie_id}")
                return JsonResponse({'success': False, 'error': '电影不存在'})
            
            # 尝试直接在users_userrating表中操作，不使用外键
            # 首先禁用外键检查
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            
            try:
                # 检查用户评分是否已存在
                cursor.execute("""
                    SELECT id FROM users_userrating 
                    WHERE user_id = %s AND movie_id = %s
                """, [request.user.id, movie_id])
                existing_rating = dictfetchall(cursor)
                
                print(f"Existing rating for comment: {existing_rating}")
                
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                if existing_rating:
                    # 更新评论
                    cursor.execute("""
                        UPDATE users_userrating
                        SET comment = %s, updated_time = %s
                        WHERE user_id = %s AND movie_id = %s
                    """, [comment, current_time, request.user.id, movie_id])
                    print(f"Updated comment for user {request.user.id} and movie {movie_id}")
                else:
                    # 创建新评论
                    cursor.execute("""
                        INSERT INTO users_userrating (user_id, movie_id, rating, comment, created_time, updated_time)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, [request.user.id, movie_id, 0, comment, current_time, current_time])
                    print(f"Created new comment for user {request.user.id} and movie {movie_id}")
            finally:
                # 恢复外键检查
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        return JsonResponse({'success': True})
    except json.JSONDecodeError as e:
        print(f"JSON decode error for comment: {e}")
        return JsonResponse({'success': False, 'error': f'无效的评论数据: {e}'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Unexpected error in comment: {e}")
        return JsonResponse({'success': False, 'error': str(e)})

def image_proxy(request, image_url):
    """图片代理视图"""
    # 获取参数
    local_only = request.GET.get('local', 'false').lower() == 'true'
    movie_title = request.GET.get('title', '无标题电影')
    movie_id = request.GET.get('movie_id')
    movie_title = unquote(movie_title)
    
    try:
        # 如果是default，返回默认图片
        if image_url == 'default':
            return default_image_response(movie_title)

        # 解码URL
        image_url = unquote(image_url)
        
        # 优先检查movie_id本地存储，将这部分逻辑提前
        if movie_id:
            poster_path = os.path.join(settings.MEDIA_ROOT, 'movie_posters', f"{movie_id}.jpg")
            if os.path.exists(poster_path):
                logger.info(f'[图片代理] 从本地movie_posters加载电影海报: movie_id={movie_id}')
                try:
                    with open(poster_path, 'rb') as f:
                        return HttpResponse(f.read(), content_type='image/jpeg')
                except Exception as e:
                    logger.error(f'[图片代理] 读取本地movie_posters图片失败: {str(e)}')
        
        # 如果URL是字典格式的字符串，提取实际的URL
        if image_url.startswith('{'):
            try:
                url_dict = ast.literal_eval(image_url)
                # 提取movie_id，如果原来没有
                if not movie_id and 'movie_id' in url_dict:
                    movie_id = url_dict.get('movie_id')
                    # 再次检查本地图片是否存在
                    if movie_id:
                        poster_path = os.path.join(settings.MEDIA_ROOT, 'movie_posters', f"{movie_id}.jpg")
                        if os.path.exists(poster_path):
                            logger.info(f'[图片代理] 从本地movie_posters加载电影海报(从URL提取ID): movie_id={movie_id}')
                            try:
                                with open(poster_path, 'rb') as f:
                                    return HttpResponse(f.read(), content_type='image/jpeg')
                            except Exception as e:
                                logger.error(f'[图片代理] 读取本地movie_posters图片失败: {str(e)}')
                
                image_url = url_dict.get('small') or url_dict.get('medium') or url_dict.get('large')
                if not image_url:
                    logger.error(f'[图片代理] 无法从字典中提取图片URL: {url_dict}')
                    return default_image_response(movie_title)
            except Exception as e:
                logger.error(f'[图片代理] 解析图片URL字典失败: {str(e)}')
                return default_image_response(movie_title)
        
        # 构建本地缓存路径
        cache_key = hashlib.md5(image_url.encode()).hexdigest()
        local_path = os.path.join(settings.IMAGE_PROCESSING['LOCAL_STORAGE_PATH'], f'{cache_key}.jpg')
        
        # 检查本地缓存
        if os.path.exists(local_path):
            try:
                with open(local_path, 'rb') as f:
                    return HttpResponse(f.read(), content_type='image/jpeg')
            except Exception as e:
                logger.error(f'[图片代理] 读取本地缓存图片失败: {str(e)}')
                # 如果文件损坏，删除它
                try:
                    os.remove(local_path)
                except:
                    pass
        
        # 如果只使用本地图片，返回默认图片
        if local_only:
            logger.info(f'[图片代理] 仅使用本地图片模式，未找到图片，返回默认图片: {movie_title}')
            return default_image_response(movie_title)
            
        # 检查域名是否允许
        parsed_url = urlparse(image_url)
        if parsed_url.netloc not in settings.ALLOWED_IMAGE_HOSTS:
            logger.warning(f'[图片代理] 不允许的图片域名: {parsed_url.netloc}')
            return default_image_response(movie_title)
            
        # 获取远程图片
        headers = {'User-Agent': settings.IMAGE_PROXY['USER_AGENT']}
        response = requests.get(image_url, headers=headers, timeout=5, verify=False)
        
        if response.status_code == 200:
            # 保存到本地缓存
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(response.content)
                
            # 如果有movie_id，也保存到movie_posters目录
            if movie_id:
                movie_poster_dir = os.path.join(settings.MEDIA_ROOT, 'movie_posters')
                os.makedirs(movie_poster_dir, exist_ok=True)
                movie_poster_path = os.path.join(movie_poster_dir, f"{movie_id}.jpg")
                with open(movie_poster_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f'[图片代理] 新下载的图片已同时保存到movie_posters: movie_id={movie_id}')
                
            return HttpResponse(response.content, content_type='image/jpeg')
        else:
            logger.error(f'[图片代理] 获取远程图片失败: HTTP {response.status_code}')
            return default_image_response(movie_title)
            
    except Exception as e:
        logger.error(f'[图片代理] 处理图片请求失败: {str(e)}')
        return default_image_response(movie_title)

def default_image_response(movie_title='无标题电影'):
    """返回默认图片响应"""
    logger.info(f'[图片代理] 开始加载默认图片，标题: {movie_title}')
    
    # 获取默认图片缓存键
    cache_key = f"default_image_{movie_title}"
    
    # 尝试从缓存获取
    cached_image = cache.get(cache_key)
    if cached_image:
        logger.info(f'[图片代理] 从缓存加载默认图片: {movie_title}')
        return HttpResponse(cached_image, content_type='image/jpeg')
    
    try:
        # 创建一个新的图片
        width, height = 400, 600
        # 使用渐变背景
        image = Image.new('RGB', (width, height), '#121212')
        draw = ImageDraw.Draw(image)
        
        # 创建渐变背景
        for y in range(height):
            r = int(41 + (30 - 41) * y / height)
            g = int(128 + (60 - 128) * y / height)
            b = int(185 + (120 - 185) * y / height)
            for x in range(width):
                draw.point((x, y), fill=(r, g, b))
        
        # 尝试加载自定义字体
        try:
            # 首先尝试加载系统字体
            system_font_path = None
            if os.name == 'nt':  # Windows
                system_font_path = 'C:/Windows/Fonts/msyh.ttc'  # 微软雅黑
            elif os.name == 'posix':  # Linux/Mac
                system_font_path = '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'
                
            if system_font_path and os.path.exists(system_font_path):
                title_font = ImageFont.truetype(system_font_path, 36)
                text_font = ImageFont.truetype(system_font_path, 24)
            else:
                # 如果系统字体不可用，使用默认字体
                title_font = ImageFont.load_default()
                text_font = ImageFont.load_default()
                
        except Exception as e:
            logger.warning(f'[图片代理] 加载系统字体失败: {str(e)}，使用默认字体')
            title_font = ImageFont.load_default()
            text_font = ImageFont.load_default()

        # 绘制一个电影图标
        icon_size = 80
        icon_x = (width - icon_size) // 2
        icon_y = height // 2 - 100
        draw.rectangle([icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], outline='#FFFFFF', width=3)
        draw.rectangle([icon_x + 15, icon_y - 10, icon_x + icon_size - 15, icon_y], fill='#FFFFFF')
        
        # 绘制电影标题
        title_text = movie_title
        if len(movie_title) > 15:
            title_text = movie_title[:15] + '...'
        
        # 添加半透明矩形作为标题背景
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_height = title_bbox[3] - title_bbox[1]
        title_x = (width - title_width) // 2
        title_y = height // 2 + 20
        
        # 绘制标题背景
        padding = 20
        draw.rectangle(
            [title_x - padding, title_y - padding, 
             title_x + title_width + padding, title_y + title_height + padding],
            fill=(0, 0, 0, 128)
        )
        
        # 绘制标题
        draw.text((title_x, title_y), title_text, font=title_font, fill='#FFFFFF')
        
        # 绘制"暂无封面"文本
        text = "暂无封面"
        text_bbox = draw.textbbox((0, 0), text, font=text_font)
        text_width = text_bbox[2] - text_bbox[0]
        text_x = (width - text_width) // 2
        draw.text((text_x, height // 2 + 80), text, font=text_font, fill='#FFFFFF')
        
        # 保存到内存
        output = BytesIO()
        image.save(output, format='JPEG', quality=85)
        image_data = output.getvalue()
        output.close()
        
        # 缓存1小时
        cache.set(cache_key, image_data, 3600)
        
        return HttpResponse(image_data, content_type='image/jpeg')
        
    except Exception as e:
        logger.error(f'[图片代理] 生成默认图片失败: {str(e)}')
        # 返回1x1透明PNG作为最后的备选方案
        return HttpResponse(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='), content_type='image/png')

def preload_popular_movie_images(count=None):
    """预加载热门电影海报"""
    logger = logging.getLogger(__name__)
    start_time = time.time()
    
    # 确保本地存储目录存在
    local_storage_path = settings.IMAGE_PROCESSING['LOCAL_STORAGE_PATH']
    os.makedirs(local_storage_path, exist_ok=True)
    
    # 获取热门电影列表
    with connection.cursor() as cursor:
        sql = """
            SELECT m.movie_id, m.title, m.images, m.rating
                FROM movie_collectmoviedb m
            ORDER BY m.collect_count DESC
        """
        if count:
            sql += " LIMIT %s"
            cursor.execute(sql, [count])
        else:
            cursor.execute(sql)
            movies = dictfetchall(cursor)
    
    def download_and_save_image(movie):
        try:
            # 解析图片数据
            images_data = movie.get('images', '{}')
            if isinstance(images_data, str):
                try:
                    images = json.loads(images_data)
                except json.JSONDecodeError:
                    try:
                        images = ast.literal_eval(images_data)
                    except:
                        logger.error(f"[图片预加载] 图片数据解析失败: {movie['title']} (ID: {movie['movie_id']})")
                        return False
            else:
                images = images_data

            # 获取图片URL
            image_url = None
            for size in ['large', 'medium', 'small']:
                if images.get(size):
                    image_url = images[size]
                    break
            
            if not image_url:
                logger.error(f"[图片预加载] 未找到有效的图片URL: {movie['title']} (ID: {movie['movie_id']})")
                return False

            # 构造本地文件路径
            filename = f"{movie['movie_id']}.jpg"
            local_path = os.path.join(local_storage_path, filename)
            
            # 如果文件已存在且有效，跳过下载
            if os.path.exists(local_path):
                try:
                    with Image.open(local_path) as img:
                        img.verify()
                    return True
                except:
                    pass

            # 下载图片
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(image_url, headers=headers, timeout=10)
            
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
                
                logger.info(f"[图片预加载] 成功: {movie['title']}")
                return True
            else:
                logger.error(f"[图片预加载] 下载失败: {movie['title']} - 状态码: {response.status_code}")
                return False
    
        except Exception as e:
            logger.error(f"[图片预加载] 处理出错: {movie['title']} (ID: {movie['movie_id']}) - {str(e)}")
            return False

    # 使用线程池并发下载
    success_count = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(download_and_save_image, movies))
        success_count = sum(1 for r in results if r)

    duration = time.time() - start_time
    logger.info(f"[图片预加载] 完成! 成功: {success_count}, 失败: {len(movies) - success_count}")
    print(f"预加载完成! 共加载 {success_count} 张海报，耗时 {duration:.2f} 秒")
    
    return success_count

def process_image(image, width=None, height=None, quality=85, img_format='JPEG'):
    """
    处理图片：调整大小、压缩、转换格式
    """
    if not HAS_PIL:
        return image
        
    try:
        # 调整大小
        if width or height:
            orig_width, orig_height = image.size
            if width and height:
                new_width, new_height = width, height
            elif width:
                ratio = width / orig_width
                new_width = width
                new_height = int(orig_height * ratio)
            else:
                ratio = height / orig_height
                new_height = height
                new_width = int(orig_width * ratio)
            image = image.resize((new_width, new_height), Image.LANCZOS)
        
        # 如果是RGBA模式，转换为RGB
        if image.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
            
        return image
    except Exception as e:
        logger.error(f"[图片代理] 处理图片失败: {str(e)}")
        return image

def _get_personalized_recommendations(user_id, limit=6):
    """
    获取用户的个性化电影推荐
    
    使用基于内容的推荐方法，结合以下因素：
    - 类型相似度 (权重: 0.4)
    - 导演相似度 (权重: 0.1)
    - 演员相似度 (权重: 0.1)
    - 标签相似度 (权重: 0.4)
    
    参数:
        user_id: 用户ID
        limit: 返回的推荐电影数量
        
    返回:
        处理过的电影数据列表
    """
    recommendations = []
    
    try:
        # 1. 获取用户评分过或收藏的电影
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT movie_id, rating
                FROM users_userrating
                WHERE user_id = %s
                ORDER BY rating DESC
                LIMIT 10
            """, [user_id])
            
            rated_movies = dictfetchall(cursor)
            
        if not rated_movies:
            # 如果用户没有评分过电影，返回热门电影
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT m.movie_id, m.title, m.year, m.genres, 
                           m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                    FROM movie_collectmoviedb m
                    LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                    ORDER BY m.collect_count DESC
                    LIMIT %s
                """, [limit])
                
                popular_movies = dictfetchall(cursor)
                return [_process_movie_data(movie) for movie in popular_movies]
        
        # 2. 使用相似度计算从推荐系统中获取推荐电影
        # 获取用户已评分电影的ID列表
        rated_movie_ids = [movie['movie_id'] for movie in rated_movies]
        rated_movie_ids_str = ','.join([str(id) for id in rated_movie_ids])
        
        if rated_movie_ids:
            # 查询与已评分电影相似的电影
            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT 
                        m.movie_id, m.title, m.year, m.genres, 
                        m.tags, m.images, m.directors, m.actor,
                        IFNULL(mr.rating, 0) as avg_rating,
                        ms.similarity
                    FROM movie_collectmoviedb m
                    LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                    LEFT JOIN recommender_moviesimilarity ms ON 
                        (ms.movie1_id = m.movie_id AND ms.movie2_id IN ({rated_movie_ids_str})) OR 
                        (ms.movie2_id = m.movie_id AND ms.movie1_id IN ({rated_movie_ids_str}))
                    WHERE m.movie_id NOT IN ({rated_movie_ids_str}) 
                    GROUP BY m.movie_id
                    ORDER BY ms.similarity DESC, m.collect_count DESC
                    LIMIT 20
                """)
                
                similar_movies = dictfetchall(cursor)
                
                # 如果找到相似电影，处理并返回
                if similar_movies:
                    # 对电影进行处理并按相似度排序
                    processed_movies = [_process_movie_data(movie) for movie in similar_movies]
                    
                    # 返回前limit个电影
                    return processed_movies[:limit]
        
        # 3. 如果没有找到相似电影或没有相似度数据，基于用户喜欢的类型推荐
        with connection.cursor() as cursor:
            # 获取用户喜欢的电影类型
            cursor.execute("""
                SELECT DISTINCT m.genres
                FROM movie_collectmoviedb m
                JOIN users_userrating ur ON m.movie_id = ur.movie_id
                WHERE ur.user_id = %s AND ur.rating >= 7
                ORDER BY ur.rating DESC
                LIMIT 5
            """, [user_id])
            
            user_genres_data = dictfetchall(cursor)
            
            # 解析类型数据
            user_genres = set()
            for genre_data in user_genres_data:
                try:
                    if genre_data['genres']:
                        genres_list = ast.literal_eval(genre_data['genres'])
                        user_genres.update(genres_list)
                except Exception as e:
                    logger.error(f"解析类型数据出错: {str(e)}")
            
            if user_genres:
                # 构建类型查询条件
                genre_conditions = []
                genre_params = []
                
                for genre in user_genres:
                    genre_conditions.append("m.genres LIKE %s")
                    genre_params.append(f"%{genre}%")
                
                genre_query = " OR ".join(genre_conditions)
                
                # 查询符合用户喜好类型的电影
                query = f"""
                    SELECT m.movie_id, m.title, m.year, m.genres, 
                           m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                    FROM movie_collectmoviedb m
                    LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                    WHERE ({genre_query})
                    AND m.movie_id NOT IN (
                        SELECT movie_id FROM users_userrating WHERE user_id = %s
                    )
                    ORDER BY mr.rating DESC, m.collect_count DESC
                    LIMIT %s
                """
                
                # 添加参数
                query_params = genre_params + [user_id, limit]
                
                # 执行查询
                cursor.execute(query, query_params)
                genre_based_movies = dictfetchall(cursor)
                
                if genre_based_movies:
                    return [_process_movie_data(movie) for movie in genre_based_movies]
    
    except Exception as e:
        logger.error(f"[推荐系统] 获取个性化推荐时出错: {str(e)}")
    
    # 如果所有推荐策略都失败，返回热门电影
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                ORDER BY m.collect_count DESC
                LIMIT %s
            """, [limit])
            
            popular_movies = dictfetchall(cursor)
            return [_process_movie_data(movie) for movie in popular_movies]
    except Exception as e:
        logger.error(f"[推荐系统] 获取热门电影推荐时出错: {str(e)}")
        return []

def _get_basic_recommendations(user_id, limit=6):
    """获取基础电影推荐，用于用户没有足够评分数据时"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT m.movie_id, m.title, m.year, m.genres, 
                       m.tags, m.images, IFNULL(mr.rating, 0) as avg_rating
                FROM movie_collectmoviedb m
                LEFT JOIN movie_movieratingdb mr ON m.movie_id = mr.movie_id_id
                WHERE m.collect_count > 5000
                AND m.movie_id NOT IN (
                    SELECT movie_id FROM users_userrating WHERE user_id = %s
                )
                ORDER BY IFNULL(mr.rating, 0) DESC, m.collect_count DESC
                LIMIT %s
            """, [user_id, limit])
            
            recommended_movies = dictfetchall(cursor)
            return [_process_movie_data(movie) for movie in recommended_movies]
    except Exception as e:
        logger.error(f"[个人推荐] 获取基础推荐电影时出错: {str(e)}")
        return []
