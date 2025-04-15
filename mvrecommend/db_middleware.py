"""
数据库连接池中间件，用于管理数据库连接的生命周期
"""

import logging
from .db_pool import connection_pool
from django.db import connections

logger = logging.getLogger(__name__)

class DatabaseConnectionPoolMiddleware:
    """数据库连接池中间件，用于拦截请求并管理数据库连接"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        """处理请求时管理数据库连接"""
        # 请求处理前，可以从连接池获取连接
        # 但通常由Django的ORM自动管理
        
        # 处理请求
        response = self.get_response(request)
        
        # 请求处理后，关闭所有连接
        # 这确保连接不会被单个请求占用太长时间
        for conn in connections.all():
            try:
                if hasattr(conn, '_pool_connection'):
                    # 这是从连接池获取的连接，释放回连接池
                    connection_pool.release_connection(conn)
                else:
                    # 非池连接，直接关闭
                    conn.close()
            except Exception as e:
                logger.error(f"关闭数据库连接时出错: {str(e)}")
        
        return response 