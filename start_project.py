#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
电影推荐系统启动脚本
用于启动MySQL服务和Django服务器
"""

import os
import sys
import time
import subprocess
import platform
import signal
import traceback
import threading
import socket
import argparse

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def print_colored(message, color_code=0):
    """
    打印带颜色的消息
    color_code:
        0 - 默认
        1 - 红色 (错误)
        2 - 绿色 (成功)
        3 - 黄色 (警告)
        4 - 蓝色 (信息)
    """
    colors = {
        0: '',  # 默认
        1: '\033[91m',  # 红色
        2: '\033[92m',  # 绿色
        3: '\033[93m',  # 黄色
        4: '\033[94m',  # 蓝色
    }
    reset = '\033[0m'
    
    # Windows命令行不支持ANSI颜色代码，除非使用Windows Terminal或启用了ANSI支持
    if platform.system() == 'Windows' and 'TERM' not in os.environ:
        print(message)
    else:
        print(f"{colors.get(color_code, '')}{message}{reset}")

def print_header(message):
    """打印带格式的标题"""
    print_colored("\n" + "=" * 40, 4)
    print_colored(f" {message}", 2)
    print_colored("=" * 40 + "\n", 4)

def load_env_vars():
    """加载环境变量"""
    env_file = os.path.join(BASE_DIR, '.env')
    env_vars = {
        'DB_HOST': 'localhost',
        'DB_PORT': '3306',
        'DB_USER': 'root',
        'DB_PASSWORD': '123',
        'DB_NAME': 'movierecommendation',
    }
    
    # 如果存在.env文件，从中加载环境变量
    if os.path.exists(env_file):
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
        except Exception as e:
            print_colored(f"加载.env文件时出错: {str(e)}", 1)
    
    # 设置环境变量
    for key, value in env_vars.items():
        os.environ[key] = value
    
    return env_vars

def is_port_in_use(port, host='localhost'):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='启动电影推荐系统')
    parser.add_argument('--stop-services', '-s', action='store_true', help='停止所有运行的服务')
    parser.add_argument('--mysql-only', '-m', action='store_true', help='只启动MySQL服务，不启动Django')
    parser.add_argument('--django-args', '-d', default='', help='传递给Django runserver的额外参数')
    return parser.parse_args()

class MySQLManager:
    """MySQL服务管理器"""
    
    def __init__(self):
        """初始化MySQL服务管理器"""
        # MySQL路径
        self.mysql_bin_dir = os.path.join(BASE_DIR, 'mysql-9.2.0-winx64', 'bin')
        self.mysql_cmd = os.path.join(self.mysql_bin_dir, 'mysqld')
        
        # 检查MySQL二进制文件是否存在
        if not os.path.exists(self.mysql_cmd):
            if platform.system() == 'Windows':
                self.mysql_cmd += '.exe'
                if not os.path.exists(self.mysql_cmd):
                    print_colored(f"错误: MySQL可执行文件不存在 ({self.mysql_cmd})", 1)
                    sys.exit(1)
            else:
                print_colored(f"错误: MySQL可执行文件不存在 ({self.mysql_cmd})", 1)
                sys.exit(1)
                
        # MySQL进程
        self.mysql_process = None
        self.mysql_output_thread = None
        self.env_vars = load_env_vars()
        
    def is_mysql_running(self):
        """检查MySQL是否已经在运行"""
        return is_port_in_use(int(self.env_vars.get('DB_PORT', 3306)))
    
    def start_mysql(self):
        """启动MySQL服务"""
        if self.is_mysql_running():
            print_colored("MySQL服务已经在运行", 2)
            return True
            
        print_colored("正在启动MySQL服务...", 4)
        
        try:
            # 在MySQL目录下启动服务
            mysql_dir = os.path.dirname(self.mysql_bin_dir)
            
            # 添加MySQL终止处理器
            def mysql_exit_handler(signum=None, frame=None):
                if self.mysql_process:
                    try:
                        if platform.system() == 'Windows':
                            subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.mysql_process.pid)])
                        else:
                            self.mysql_process.terminate()
                        print_colored("MySQL服务已终止", 3)
                    except Exception as e:
                        print_colored(f"终止MySQL服务时出错: {str(e)}", 1)
            
            # 启动MySQL进程
            if platform.system() == 'Windows':
                # Windows平台使用start命令在新窗口中启动MySQL
                self.mysql_process = subprocess.Popen(
                    [self.mysql_cmd, '--console'],
                    cwd=mysql_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # 其他平台直接启动进程
                self.mysql_process = subprocess.Popen(
                    [self.mysql_cmd, '--console'],
                    cwd=mysql_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True
                )
            
            # 启动读取输出线程
            self.mysql_output_thread = threading.Thread(target=self._read_mysql_output)
            self.mysql_output_thread.daemon = True
            self.mysql_output_thread.start()
            
            # 等待MySQL启动
            if not self._check_mysql_connection():
                print_colored("MySQL服务启动失败", 1)
                mysql_exit_handler()
                return False
                
            print_colored("MySQL服务已成功启动", 2)
            return True
            
        except Exception as e:
            print_colored(f"启动MySQL服务时出错: {str(e)}", 1)
            traceback.print_exc()
            return False
    
    def _read_mysql_output(self):
        """读取MySQL输出"""
        try:
            for line in iter(self.mysql_process.stdout.readline, ''):
                if line:
                    # 只打印关键信息，减少输出量
                    if 'error' in line.lower() or 'warning' in line.lower() or 'ready for connections' in line.lower():
                        print_colored(f"MySQL: {line.strip()}", 4 if 'ready for connections' in line.lower() else 3)
        except Exception as e:
            pass
    
    def _check_mysql_connection(self, retries=5, delay=2):
        """检查MySQL连接是否就绪"""
        mysql_client = os.path.join(self.mysql_bin_dir, 'mysql')
        if platform.system() == 'Windows' and not os.path.exists(mysql_client):
            mysql_client += '.exe'
        
        print_colored("正在等待MySQL服务就绪...", 4)
        
        for i in range(retries):
            if self.is_mysql_running():
                try:
                    # 使用MySQL客户端检查连接
                    cmd = [
                        mysql_client,
                        f"-u{self.env_vars.get('DB_USER', 'root')}",
                        f"-p{self.env_vars.get('DB_PASSWORD', '123')}",
                        f"-h{self.env_vars.get('DB_HOST', 'localhost')}",
                        f"-P{self.env_vars.get('DB_PORT', '3306')}",
                        "-e", "SELECT 'MySQL connection successful' AS status;"
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0 and 'successful' in result.stdout:
                        print_colored("MySQL连接测试成功", 2)
                        return True
                except Exception as e:
                    pass
                
            if i < retries - 1:
                print_colored(f"等待MySQL启动... ({i+1}/{retries})", 3)
                time.sleep(delay)
        
        return False

    def stop_mysql(self):
        """停止MySQL服务"""
        if not self.is_mysql_running():
            print_colored("MySQL服务未运行", 3)
            return True
        
        print_colored("正在停止MySQL服务...", 3)
        
        try:
            # 尝试优雅关闭
            mysqladmin = os.path.join(self.mysql_bin_dir, 'mysqladmin')
            if platform.system() == 'Windows':
                mysqladmin += '.exe'
            
            cmd = [
                mysqladmin,
                f"-u{self.env_vars.get('DB_USER', 'root')}",
                f"-p{self.env_vars.get('DB_PASSWORD', '123')}",
                "shutdown"
            ]
            
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            
            # 等待端口释放
            for _ in range(5):
                if not self.is_mysql_running():
                    print_colored("MySQL服务已停止", 2)
                    return True
                time.sleep(1)
            
            # 如果优雅关闭失败，尝试强制终止
            if platform.system() == 'Windows':
                os.system('taskkill /F /IM mysqld.exe /T')
            else:
                os.system('killall -9 mysqld')
            
            print_colored("MySQL服务已强制停止", 3)
            return True
            
        except Exception as e:
            print_colored(f"停止MySQL服务时出错: {str(e)}", 1)
            return False

def stop_running_services():
    """停止正在运行的服务"""
    print_header("停止所有服务")
    
    # 停止MySQL
    mysql_manager = MySQLManager()
    mysql_manager.stop_mysql()
    
    # 检查Django进程
    if platform.system() == 'Windows':
        # 在Windows上查找Python进程，尝试关闭运行manage.py runserver的进程
        os.system('tasklist | findstr python')
        django_cmd = input("请输入要终止的Django进程的PID (留空则不终止): ")
        if django_cmd.strip():
            os.system(f'taskkill /F /PID {django_cmd}')
            print_colored("Django服务已停止", 2)
    else:
        # 在Linux/Mac上尝试找到Django进程
        os.system('ps aux | grep "manage.py runserver" | grep -v grep')
        os.system('pkill -f "manage.py runserver"')
        print_colored("Django服务已停止", 2)

def handle_sigint(sig, frame):
    """处理Ctrl+C信号"""
    print_colored("\n收到退出信号，但服务将继续在后台运行", 3)
    print_colored("您可以使用以下命令停止服务:", 4)
    print_colored("  python start_project.py --stop-services", 4)
    sys.exit(0)

def main():
    """主函数"""
    # 解析命令行参数
    args = parse_arguments()
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, handle_sigint)
    
    # 停止服务
    if args.stop_services:
        stop_running_services()
        return
    
    print_header("电影推荐系统启动脚本")
    
    # MySQL服务管理
    mysql_manager = MySQLManager()
    if not mysql_manager.start_mysql():
        print_colored("MySQL服务启动失败，无法继续", 1)
        return
    
    # 如果只需要启动MySQL
    if args.mysql_only:
        print_colored("MySQL服务已启动并将在后台运行", 2)
        print_colored("您可以安全关闭此窗口，MySQL将继续运行", 4)
        print_colored("若要停止MySQL服务，请运行:", 4)
        print_colored("  python start_project.py --stop-services", 4)
        try:
            # 保持脚本运行，直到用户按下Ctrl+C
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print_colored("\n退出脚本，MySQL服务将继续在后台运行", 3)
        return
    
    # 启动Django服务器
    print_header("启动Django服务器")
    django_cmd = [sys.executable, "manage.py", "runserver"]
    
    # 添加额外的Django参数
    if args.django_args:
        django_cmd.extend(args.django_args.split())
    
    print_colored(f"执行命令: {' '.join(django_cmd)}", 4)
    print_colored("注意: 关闭此窗口不会停止MySQL和Django服务", 3)
    print_colored("要停止所有服务，请使用:", 4)
    print_colored("  python start_project.py --stop-services", 4)
    
    try:
        # 直接运行Django，不捕获其输出（让它直接输出到控制台）
        subprocess.run(django_cmd)
        # Django退出后显示提示信息
        print_colored("\nDjango服务器已退出，但MySQL服务仍在后台运行", 3)
        print_colored("要停止所有服务，请使用:", 4)
        print_colored("  python start_project.py --stop-services", 4)
    except KeyboardInterrupt:
        print_colored("\n退出脚本，服务将继续在后台运行", 3)
        print_colored("要停止所有服务，请使用:", 4)
        print_colored("  python start_project.py --stop-services", 4)
    except Exception as e:
        print_colored(f"运行Django服务器时出错: {str(e)}", 1)
        traceback.print_exc()

if __name__ == "__main__":
    main() 