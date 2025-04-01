from django.apps import AppConfig


class RecommenderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recommender'
    
    def ready(self):
        """当应用程序准备好时，检查推荐系统状态"""
        # 避免在管理命令中执行，如migrate, runserver等
        import sys
        if 'runserver' in sys.argv:
            print("\n正在启动推荐系统并检查状态...")
            # 导入需要在app加载后才能使用的功能
            from .recommendation import get_recommendation_system_status
            # 等待数据库连接就绪后执行
            import threading
            def delayed_check():
                import time
                # 等待5秒，确保Django完全启动
                time.sleep(5)
                try:
                    # 执行推荐系统状态检查
                    get_recommendation_system_status()
                except Exception as e:
                    print(f"推荐系统状态检查失败: {e}")
            
            # 在后台线程中执行，避免阻塞应用启动
            thread = threading.Thread(target=delayed_check)
            thread.daemon = True
            thread.start()