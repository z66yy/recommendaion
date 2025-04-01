#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
MySQL数据库连接管理模块
直接连接数据库，不使用连接池
"""

import logging
import pymysql
from django.conf import settings
import os
from threading import local
import time

# 使用专用日志器
logger = logging.getLogger('mvrecommend.db_pool')

# 数据库配置 - 优先使用环境变量，然后回退到settings配置
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', settings.DATABASES['default']['HOST']),
    'port': int(os.environ.get('DB_PORT', settings.DATABASES['default']['PORT'])),
    'user': os.environ.get('DB_USER', settings.DATABASES['default']['USER']),
    'password': os.environ.get('DB_PASSWORD', settings.DATABASES['default']['PASSWORD']),
    'database': os.environ.get('DB_NAME', settings.DATABASES['default']['NAME']),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': True,
    'connect_timeout': 5,        # 连接超时时间缩短
    'read_timeout': 10,          # 读取超时时间缩短
    'write_timeout': 10,         # 写入超时时间缩短
}

# 线程本地存储，用于缓存数据库连接
_thread_local = local()

def get_connection():
    """
    获取数据库连接，优先使用缓存的连接
    """
    # 尝试获取已缓存的连接
    if hasattr(_thread_local, 'connection'):
        conn = _thread_local.connection
        # 检查连接是否仍然有效
        try:
            conn.ping(reconnect=False)
            return conn
        except:
            # 连接已断开，关闭并创建新连接
            try:
                conn.close()
            except:
                pass
    
    # 创建新连接
    try:
        conn = pymysql.connect(**DB_CONFIG)
        _thread_local.connection = conn  # 缓存连接
        logger.debug("创建了新的数据库连接")
        return conn
    except Exception as e:
        logger.error(f"创建数据库连接失败: {str(e)}")
        # 短暂延迟后重试一次
        time.sleep(0.5)
        try:
            conn = pymysql.connect(**DB_CONFIG)
            _thread_local.connection = conn
            logger.debug("重试成功创建了数据库连接")
            return conn
        except Exception as e:
            logger.error(f"重试创建数据库连接仍然失败: {str(e)}")
            return None

def release_connection(conn):
    """
    关闭数据库连接
    """
    # 我们不立即关闭连接，而是保留它以便重用
    # 连接会在线程结束时自动关闭
    pass

# 为了兼容现有代码，保留DBConnectionPool类的空实现
class DBConnectionPool:
    def __init__(self):
        logger.info("使用优化的直接连接模式，带有连接缓存")
        
    def _clean_existing_connections(self):
        logger.debug("连接池已禁用，忽略清理操作")
        pass
        
    def _clean_idle_connections(self):
        logger.debug("连接池已禁用，忽略清理操作")
        return 0, 0

# 创建兼容性实例
db_pool = DBConnectionPool() 