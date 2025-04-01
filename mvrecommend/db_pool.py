#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MySQL数据库连接管理模块
直接连接数据库，不使用连接池
"""

import logging
import pymysql
from django.conf import settings

# 使用专用日志器
logger = logging.getLogger('mvrecommend.db_pool')

# 数据库配置
DB_CONFIG = {
    'host': settings.DATABASES['default']['HOST'],
    'port': int(settings.DATABASES['default']['PORT']),
    'user': settings.DATABASES['default']['USER'],
    'password': settings.DATABASES['default']['PASSWORD'],
    'database': settings.DATABASES['default']['NAME'],
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': True,
}

def get_connection():
    """
    直接创建一个新的数据库连接
    """
    try:
        conn = pymysql.connect(**DB_CONFIG)
        logger.debug("创建了新的数据库连接")
        return conn
    except Exception as e:
        logger.error(f"创建数据库连接失败: {str(e)}")
        return None

def release_connection(conn):
    """
    关闭数据库连接
    """
    try:
        if conn and hasattr(conn, 'close'):
            conn.close()
            logger.debug("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接失败: {str(e)}")

# 为了兼容现有代码，保留DBConnectionPool类的空实现
class DBConnectionPool:
    def __init__(self):
        logger.info("数据库连接池已禁用，使用直接连接模式")
        
    def _clean_existing_connections(self):
        logger.debug("连接池已禁用，忽略清理操作")
        pass
        
    def _clean_idle_connections(self):
        logger.debug("连接池已禁用，忽略清理操作")
        return 0, 0

# 创建兼容性实例
db_pool = DBConnectionPool() 