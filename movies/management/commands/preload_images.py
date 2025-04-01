from django.core.management.base import BaseCommand
from movies.views import preload_popular_movie_images
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '预加载热门电影的图片到本地存储'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=100,
            help='要预加载的电影数量，默认为100'
        )
        
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='显示详细日志'
        )

    def handle(self, *args, **options):
        count = options['count']
        verbose = options['verbose']
        
        if verbose:
            logger.setLevel(logging.INFO)
            
        self.stdout.write(f"开始预加载 {count} 部热门电影的图片...")
        
        # 调用预加载函数
        preload_popular_movie_images(count)
        
        self.stdout.write(self.style.SUCCESS(f"成功预加载了 {count} 部热门电影的图片!")) 