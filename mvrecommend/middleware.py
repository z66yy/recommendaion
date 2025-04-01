"""
中间件配置
"""

import logging
import time
import re
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from django.db import connection
from django.http import HttpResponse

# 日志记录器
logger = logging.getLogger(__name__)

class ImageProcessingMiddleware:
    """
    图片处理中间件
    处理图片请求并进行必要的处理
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger('movies')
        # 图片URL模式
        self.image_url_pattern = re.compile(r'/image-proxy/(.*)')
        # 缓存控制设置
        self.cache_timeout = getattr(settings, 'IMAGE_CACHE_TIMEOUT', 3600 * 24)  # 默认1天
        # 处理计数
        self.processed_count = 0
        # 启动时间
        self.start_time = timezone.now()

    def __call__(self, request):
        # 如果不是图片请求，直接传递给下一个中间件
        path = request.path_info
        if not self.image_url_pattern.match(path):
            return self.get_response(request)
        
        # 记录图片处理开始时间（仅在DEBUG模式下）
        if settings.DEBUG:
            start_time = time.time()
        
        # 处理计数器
        self.processed_count += 1
        
        # 获取响应
        response = self.get_response(request)
        
        # 设置缓存控制头
        if hasattr(response, 'headers'):
            response.headers['Cache-Control'] = f'max-age={self.cache_timeout}, public'
            response.headers['Expires'] = (timezone.now() + timedelta(seconds=self.cache_timeout)).strftime('%a, %d %b %Y %H:%M:%S GMT')
        
        # 记录图片处理耗时（仅在DEBUG模式下）
        if settings.DEBUG and hasattr(response, 'headers'):
            elapsed = time.time() - start_time
            if elapsed > 0.5:  # 仅记录处理时间超过0.5秒的请求
                self.logger.debug(f"图片处理耗时: {elapsed:.3f}s - {path}")
        
        return response

class CacheControlMiddleware:
    """
    缓存控制中间件
    为静态资源添加缓存控制头
    """
    def __init__(self, get_response):
        self.get_response = get_response
        # 静态文件路径模式
        self.static_url_pattern = re.compile(r'^/static/.*\.(css|js|jpg|jpeg|png|gif|ico|woff|woff2|ttf|svg)$')
        # 缓存时间：1天
        self.cache_timeout = 3600 * 24
        # 已处理的URL缓存，避免重复处理相同的URL
        self.processed_urls = set()
        # 最大缓存URL数量，避免内存泄漏
        self.max_cache_urls = 1000

    def __call__(self, request):
        response = self.get_response(request)
        
        # 判断是否静态资源且不在已处理列表中
        path = request.path_info
        if self.static_url_pattern.match(path) and path not in self.processed_urls:
            if hasattr(response, 'headers'):
                response.headers['Cache-Control'] = f'max-age={self.cache_timeout}, public'
                response.headers['Expires'] = (timezone.now() + timedelta(seconds=self.cache_timeout)).strftime('%a, %d %b %Y %H:%M:%S GMT')
            
            # 将URL添加到已处理列表，避免重复处理
            self.processed_urls.add(path)
            # 如果缓存URL数量超过最大值，清空缓存
            if len(self.processed_urls) > self.max_cache_urls:
                self.processed_urls.clear()
        
        return response

class DatabaseConnectionMiddleware:
    """
    数据库连接中间件
    负责管理数据库连接的创建和关闭
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = logging.getLogger('mvrecommend.db_pool')
        # 连接统计
        self.connection_count = 0
        # 上次执行清理的时间
        self.last_cleanup = time.time()
        # 清理间隔（秒）
        self.cleanup_interval = 300  # 5分钟
        # 长时间运行的阈值（秒）
        self.slow_query_threshold = 0.5
        # 上次记录数据库状态的时间
        self.last_status_log = time.time()
        # 记录数据库状态的间隔（秒）
        self.status_log_interval = 3600  # 1小时

    def __call__(self, request):
        # 记录请求开始时间
        start_time = time.time()
        
        # 执行视图函数
        response = self.get_response(request)
        
        # 记录慢查询
        elapsed = time.time() - start_time
        if elapsed > self.slow_query_threshold and hasattr(connection, 'queries'):
            query_count = len(connection.queries)
            if query_count > 0:
                self.logger.warning(f"慢请求: {request.path} - {elapsed:.3f}s - {query_count}个查询")
        
        # 定期记录数据库连接状态
        now = time.time()
        if now - self.last_status_log > self.status_log_interval:
            self.last_status_log = now
            # 这里只记录状态，不实际执行任何操作
            self.logger.info(f"数据库连接状态: 处理了{self.connection_count}个请求")
        
        # 增加连接计数
        self.connection_count += 1
        
        return response 