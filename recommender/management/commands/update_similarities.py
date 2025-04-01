from django.core.management.base import BaseCommand
from recommender.recommendation import update_content_based_similarities, build_als_model, update_similarity_from_collectmoviedb, import_movies_from_collectdb
from recommender.models import MovieSimilarity
import logging
import time

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '更新电影相似度数据，用于推荐系统'
    
    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, help='限制处理的电影数量')
        parser.add_argument('--min-similarity', type=float, default=0.15, help='最小相似度阈值，低于此值的相似度不会被保存')
        parser.add_argument('--min-ratings', type=int, default=10, help='最小评分人数，低于此值的电影将被过滤')
        parser.add_argument('--method', type=str, 
                           choices=['content', 'als', 'collectmovie', 'both'], 
                           default='collectmovie', 
                           help='推荐计算方法，content=基于内容的相似度，als=协同过滤，collectmovie=从collectmoviedb计算，both=多种方法')
        parser.add_argument('--force-import', action='store_true', help='强制导入电影数据')
        parser.add_argument('--import-only', action='store_true', help='仅导入电影数据，不计算相似度')
        parser.add_argument('--max-records', type=int, default=10000, help='最大保存的相似度记录数量，设置为0表示不限制')
        parser.add_argument('--no-prompt', action='store_true', help='不提示确认删除已有的相似度数据')
        
    def handle(self, *args, **options):
        start_time = time.time()
        
        limit = options.get('limit')
        min_similarity = options.get('min_similarity', 0.15)
        min_ratings = options.get('min_ratings', 10)
        method = options.get('method', 'collectmovie')
        force_import = options.get('force_import', False)
        import_only = options.get('import_only', False)
        max_records = options.get('max_records', 10000)
        no_prompt = options.get('no_prompt', False)
        # 如果设置为0，则转换为None表示无限制
        max_records = None if max_records == 0 else max_records
        
        self.stdout.write(self.style.SUCCESS('开始更新电影相似度数据...'))
        
        if limit:
            self.stdout.write(f"处理电影数量限制为: {limit}部")
        if min_similarity != 0.15:
            self.stdout.write(f"最小相似度阈值设为: {min_similarity}")
        if min_ratings != 10:
            self.stdout.write(f"最小评分人数设为: {min_ratings}")
        self.stdout.write(f"使用的推荐算法方法: {method}")
        if max_records:
            self.stdout.write(f"最大相似度记录数: {max_records}")
        else:
            self.stdout.write("相似度记录数: 不限制")
        
        # 检查是否已有相似度数据并提示确认
        if not import_only and not no_prompt:
            similarity_count = MovieSimilarity.objects.count()
            if similarity_count > 0:
                self.stdout.write(self.style.WARNING(f'系统中已有 {similarity_count} 条相似度数据，继续操作将会删除所有已有数据!'))
                confirm = input('是否确认删除已有的相似度数据并重新计算? (y/n): ')
                if confirm.lower() != 'y':
                    self.stdout.write(self.style.ERROR('操作已取消'))
                    return
                self.stdout.write(self.style.SUCCESS('确认删除数据，继续执行...'))
        
        try:
            # 如果需要仅导入电影
            if import_only:
                self.stdout.write(self.style.SUCCESS('执行电影数据导入...'))
                imported_count = import_movies_from_collectdb(limit=limit)
                self.stdout.write(self.style.SUCCESS(f'电影数据导入完成，导入了 {imported_count} 部新电影'))
                return

            valid_pairs = 0
            
            # 根据选择的方法更新相似度
            if method == 'content' or method == 'both':
                self.stdout.write(self.style.SUCCESS('正在使用基于内容的方法更新电影相似度...'))
                content_valid_pairs = update_content_based_similarities(limit=limit, min_similarity=min_similarity, no_prompt=no_prompt)
                self.stdout.write(self.style.SUCCESS(f'基于内容的相似度更新完成，保存了 {content_valid_pairs} 条数据'))
                valid_pairs += content_valid_pairs
                
            if method == 'als' or method == 'both':
                self.stdout.write(self.style.SUCCESS('正在使用协同过滤(ALS)方法更新电影相似度...'))
                als_valid_pairs = build_als_model(min_similarity=min_similarity, no_prompt=no_prompt)
                if als_valid_pairs is not None:
                    self.stdout.write(self.style.SUCCESS(f'协同过滤的相似度更新完成，保存了 {als_valid_pairs} 条数据'))
                    valid_pairs += als_valid_pairs
                else:
                    self.stdout.write(self.style.WARNING('协同过滤模型构建失败，可能是因为没有足够的评分数据'))
            
            if method == 'collectmovie' or method == 'both':
                self.stdout.write(self.style.SUCCESS('正在从电影收集数据库计算电影相似度...'))
                collectmovie_valid_pairs = update_similarity_from_collectmoviedb(
                    limit=limit, 
                    min_similarity=min_similarity, 
                    force_import=force_import,
                    min_ratings=min_ratings,
                    max_similarity_records=max_records,
                    no_prompt=no_prompt
                )
                self.stdout.write(self.style.SUCCESS(f'从收集的电影数据计算相似度完成，保存了 {collectmovie_valid_pairs} 条数据'))
                valid_pairs += collectmovie_valid_pairs
            
            elapsed_time = time.time() - start_time
            self.stdout.write(self.style.SUCCESS(
                f'电影相似度数据更新完成！保存了 {valid_pairs} 条数据，耗时: {elapsed_time:.2f}秒'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'更新电影相似度数据失败: {str(e)}'))
            logger.error(f'更新电影相似度数据失败: {str(e)}', exc_info=True) 