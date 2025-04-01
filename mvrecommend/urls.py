"""
URL configuration for mvrecommend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.decorators.cache import cache_page
from movies.views import home, image_proxy

# 导入serve视图
from django.contrib.staticfiles.views import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('users/', include('users.urls')),
    path('movies/', include('movies.urls')),
    path('recommender/', include('recommender.urls')),
    path('image-proxy/', image_proxy, name='image_proxy'),
    # 添加静态资源缓存路由
    path('static/<path:path>', cache_page(60*60*24*7)(serve), {'document_root': settings.STATIC_ROOT, 'show_indexes': False}),
]

# Debug Toolbar URL
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]

# 添加媒体文件URL
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# 添加响应头中间件
from django.utils.cache import patch_response_headers

class CacheControlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # 为静态资源添加长期缓存
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            patch_response_headers(response, cache_timeout=60*60*24*30)  # 30天
            response['Cache-Control'] = 'public, max-age=2592000'  # 30天
        
        # 为HTML响应添加短期缓存
        elif response.get('Content-Type', '').startswith('text/html'):
            patch_response_headers(response, cache_timeout=60*10)  # 10分钟
            response['Cache-Control'] = 'public, max-age=600, must-revalidate'  # 10分钟，必须重新验证
        
        return response

# 在settings.MIDDLEWARE中添加上述中间件
