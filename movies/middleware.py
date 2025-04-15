import time
from django.core.cache import cache
from django.http import HttpResponse
import logging

logger = logging.getLogger(__name__)

class ImageProcessingMiddleware:
    """
    图片处理中间件
    - 为图片请求添加缓存控制
    - 记录图片加载时间
    - 优化频繁访问的图片响应
    """
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # 如果是对图片的请求，加入缓存控制
        if request.path.startswith('/image-proxy/') or ('.jpg' in request.path or '.jpeg' in request.path or '.png' in request.path or '.gif' in request.path):
            cache_key = f"img_req_{request.path}"
            cached_response = cache.get(cache_key)
            if cached_response:
                logger.debug(f"返回缓存的图片响应: {request.path}")
                return cached_response
                
            # 记录图片加载开始时间
            start_time = time.time()
            response = self.get_response(request)
            load_time = time.time() - start_time
            
            # 只缓存成功的响应
            if response.status_code == 200:
                # 添加缓存控制头
                response['Cache-Control'] = 'public, max-age=86400'  # 缓存1天
                response['X-Image-Load-Time'] = str(load_time)
                
                # 缓存响应对象
                cache.set(cache_key, response, 86400)  # 缓存24小时
                
                # 记录加载时间
                if load_time > 0.5:  # 如果加载时间超过0.5秒
                    logger.warning(f"图片加载缓慢: {request.path} 耗时: {load_time:.2f}秒")
            return response
        
        # 非图片请求正常处理
        return self.get_response(request) 