#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
电影推荐系统环境初始化脚本
用于项目环境设置和依赖检查
"""

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path
import traceback

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 必要的目录
REQUIRED_DIRS = [
    'media',
    'media/movie_posters',
    'logs',
    'cache',
    'static',
    'staticfiles',
]

# 必要的Python包
REQUIRED_PACKAGES = [
    'django==4.2.20',
    'pymysql',
    'pyspark',
    'pillow',
    'djangorestframework',
    'django-compressor',
    'django-debug-toolbar',
    'requests',
]

def print_header(message):
    """打印带格式的标题"""
    width = len(message) + 4
    print("\n" + "=" * width)
    print(f"  {message}")
    print("=" * width)

def print_step(message):
    """打印步骤信息"""
    print(f"\n>> {message}")

def print_status(status, message):
    """打印状态信息"""
    if status:
        print(f"✓ {message}")
    else:
        print(f"✗ {message}")

def check_python_version():
    """检查Python版本"""
    print_step("检查Python版本")
    
    version = sys.version_info
    required_version = (3, 8)
    
    if version >= required_version:
        print_status(True, f"Python版本 {version.major}.{version.minor}.{version.micro} - 符合要求")
        return True
    else:
        print_status(False, f"Python版本 {version.major}.{version.minor}.{version.micro} - 不符合要求 (需要 3.8+)")
        return False

def setup_directories():
    """创建必要的目录"""
    print_step("创建必要的目录")
    
    for dir_path in REQUIRED_DIRS:
        full_path = os.path.join(BASE_DIR, dir_path)
        if not os.path.exists(full_path):
            try:
                os.makedirs(full_path)
                print_status(True, f"创建目录: {dir_path}")
            except Exception as e:
                print_status(False, f"创建目录 {dir_path} 失败: {str(e)}")
        else:
            print_status(True, f"目录已存在: {dir_path}")

def check_mysql():
    """检查MySQL配置"""
    print_step("检查MySQL配置")
    
    mysql_dir = os.path.join(BASE_DIR, 'mysql-9.2.0-winx64')
    if os.path.exists(mysql_dir):
        print_status(True, "找到MySQL目录")
        
        # 检查my.ini文件
        my_ini_path = os.path.join(mysql_dir, 'my.ini')
        if os.path.exists(my_ini_path):
            print_status(True, "找到my.ini配置文件")
            
            # 检查数据目录
            data_dir = os.path.join(mysql_dir, 'data')
            if os.path.exists(data_dir):
                print_status(True, "找到数据目录")
                
                # 检查movierecommendation数据库
                movie_db_dir = os.path.join(data_dir, 'movierecommendation')
                if os.path.exists(movie_db_dir):
                    print_status(True, "找到movierecommendation数据库")
                else:
                    print_status(False, "未找到movierecommendation数据库")
            else:
                print_status(False, "未找到数据目录")
        else:
            print_status(False, "未找到my.ini配置文件")
    else:
        print_status(False, "未找到MySQL目录")
        print("    您需要手动下载MySQL 9.2.0并放置在项目根目录的'mysql-9.2.0-winx64'文件夹中")

def install_packages():
    """安装必要的包"""
    print_step("检查和安装必要的Python包")
    
    for package in REQUIRED_PACKAGES:
        try:
            package_name = package.split('==')[0]
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            print_status(True, f"安装包: {package}")
        except Exception as e:
            print_status(False, f"安装包 {package} 失败: {str(e)}")

def check_environment_variables():
    """检查和设置环境变量"""
    print_step("检查环境变量")
    
    env_vars = {
        'DB_HOST': 'localhost',
        'DB_PORT': '3306',
        'DB_USER': 'root',
        'DB_PASSWORD': '123',
        'DB_NAME': 'movierecommendation',
    }
    
    for var, default in env_vars.items():
        current = os.environ.get(var)
        if current:
            print_status(True, f"环境变量 {var} 已设置: {current}")
        else:
            print_status(False, f"环境变量 {var} 未设置，默认值: {default}")

def create_env_file():
    """创建.env文件"""
    print_step("创建.env文件")
    
    env_path = os.path.join(BASE_DIR, '.env')
    
    if os.path.exists(env_path):
        print_status(True, ".env文件已存在")
    else:
        try:
            with open(env_path, 'w') as f:
                f.write("""# 电影推荐系统环境变量
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=123
DB_NAME=movierecommendation

# 图片处理配置
MEDIA_ROOT=./media
LOCAL_STORAGE_PATH=./media/movie_posters
""")
            print_status(True, "已创建.env文件")
        except Exception as e:
            print_status(False, f"创建.env文件失败: {str(e)}")

def finalize():
    """完成环境设置"""
    print_header("环境设置完成")
    print("""
您现在可以:
1. 启动MySQL服务:
   cd mysql-9.2.0-winx64/bin
   mysqld --console

2. 启动Django开发服务器:
   python manage.py runserver

如果环境变量未正确设置，您可以在启动前手动导入.env文件中的环境变量。
请确保MySQL服务正在运行并且movierecommendation数据库已就绪。
""")

def main():
    """主函数"""
    print_header("电影推荐系统环境设置")
    print(f"系统类型: {platform.system()} {platform.version()}")
    print(f"项目根目录: {BASE_DIR}")
    
    try:
        if check_python_version():
            setup_directories()
            check_mysql()
            install_packages()
            check_environment_variables()
            create_env_file()
            finalize()
        else:
            print("环境设置未完成，因为Python版本不符合要求。")
    except Exception as e:
        print("\n设置过程中发生错误:")
        traceback.print_exc()

if __name__ == "__main__":
    main() 