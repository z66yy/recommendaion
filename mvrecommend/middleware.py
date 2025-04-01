import logging
import time
from django.db import connection, connections
from django.conf import settings
from django.db.utils import OperationalError
from django.http import HttpResponse

logger = logging.getLogger('django')

class DatabaseConnectionMiddleware:
    """
    中间件，用于确保每个请求结束时关闭数据库连接
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        logger.info("DatabaseConnectionMiddleware 已初始化")
    
    def __call__(self, request):
        # 尝试获取数据库连接
        for i in range(settings.DATABASE_RETRY_COUNT):
            try:
                connections['default'].ensure_connection()
                break
            except OperationalError as e:
                if i == settings.DATABASE_RETRY_COUNT - 1:  # 最后一次重试
                    logger.error(f'数据库连接失败: {str(e)}')
                    return HttpResponse('数据库连接错误，请稍后重试', status=503)
                logger.warning(f'数据库连接重试 {i+1}/{settings.DATABASE_RETRY_COUNT}')
                time.sleep(settings.DATABASE_RETRY_DELAY)

        response = self.get_response(request)
        
        # 请求结束后关闭连接
        connections.close_all()
        
        return response
    
    def process_exception(self, request, exception):
        """处理异常时确保连接被关闭"""
        if isinstance(exception, OperationalError):
            logger.error(f'数据库操作错误: {str(exception)}')
            return HttpResponse('数据库操作错误，请稍后重试', status=503)
        return None

class CacheControlMiddleware:
    """
    中间件用于设置缓存控制头
    解决settings.py中引用错误
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        logger.info("CacheControlMiddleware 已初始化")
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # 根据不同的内容类型设置不同的缓存策略
        content_type = response.get('Content-Type', '')
        
        # 静态资源缓存较长时间
        if any(ct in content_type for ct in ('image/', 'text/css', 'application/javascript')):
            response['Cache-Control'] = 'public, max-age=31536000'  # 1年
        # HTML内容较短时间缓存
        elif 'text/html' in content_type:
            response['Cache-Control'] = 'public, max-age=1800'  # 30分钟
        # 其他内容使用默认缓存
        else:
            response['Cache-Control'] = 'public, max-age=86400'  # 1天
            
        return response

class ImageProcessingMiddleware:
    """
    中间件用于图像处理
    解决settings.py中引用错误
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        logger.info("ImageProcessingMiddleware 已初始化")
    
    def __call__(self, request):
        # 简单实现，后续可扩展
        response = self.get_response(request)
        return response 