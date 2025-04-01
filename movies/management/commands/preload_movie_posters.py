from django.core.management.base import BaseCommand
from movies.views import preload_popular_movie_images

class Command(BaseCommand):
    help = '预加载电影海报'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            help='要预加载的电影数量',
            required=False
        )

    def handle(self, *args, **options):
        count = options.get('count')
        self.stdout.write('开始预加载电影海报...')
        loaded_count = preload_popular_movie_images(count)
        self.stdout.write(self.style.SUCCESS(f'成功预加载了 {loaded_count} 张电影海报')) 