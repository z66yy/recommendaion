from django.db.models import Q, Count, Avg, F
from django.db import connection
import numpy as np
from scipy.sparse import csr_matrix
from sklearn.metrics.pairwise import cosine_similarity
from movies.models import Movie, Genre
from users.models import UserRating, UserFavorite, UserHistory
from .models import MovieSimilarity
import logging
import json
import os
import pandas as pd
import time
import pyspark
from pyspark.sql import SparkSession
from pyspark.ml.linalg import Vectors
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.recommendation import ALS
from .utils import parse_image_data
import sys
import random
import math
from tqdm import tqdm
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models.functions import Round, Cast
from pyspark.sql.functions import col, expr
from pyspark.sql.types import IntegerType, DoubleType

# 初始化日志
logger = logging.getLogger('django')

User = get_user_model()

def get_spark_session():
    """获取或创建Spark会话"""
    # 设置环境变量以确保Spark使用当前Python环境
    os.environ['PYSPARK_PYTHON'] = sys.executable
    os.environ['PYSPARK_DRIVER_PYTHON'] = sys.executable
    
    builder = SparkSession.builder
    
    # 根据系统资源调整配置
    max_memory = "16g"  # 根据系统内存调整
    memory_fraction = 0.8  # 系统内存占用比例
    
    return builder \
        .config("spark.driver.memory", max_memory) \
        .config("spark.executor.memory", max_memory) \
        .config("spark.memory.fraction", memory_fraction) \
        .config("spark.memory.storageFraction", "0.3") \
        .config("spark.memory.offHeap.enabled", "true") \
        .config("spark.memory.offHeap.size", "4g") \
        .config("spark.sql.shuffle.partitions", "100") \
        .config("spark.default.parallelism", "100") \
        .config("spark.ui.enabled", "false") \
        .config("spark.local.dir", "D:/pycharm/pythonProject2/movierecommends/spark_temp") \
        .config("spark.driver.maxResultSize", "2g") \
        .config("spark.executor.heartbeatInterval", "60s") \
        .config("spark.network.timeout", "600s") \
        .config("spark.rdd.compress", "true") \
        .config("spark.kryoserializer.buffer.max", "512m") \
        .config("spark.kryoserializer.buffer", "64m") \
        .config("spark.serializer", "org.apache.spark.serializer.KryoSerializer") \
        .config("spark.sql.adaptive.enabled", "true") \
        .config("spark.sql.adaptive.skewJoin.enabled", "true") \
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true") \
        .config("spark.sql.adaptive.localShuffleReader.enabled", "true") \
        .config("spark.dynamicAllocation.enabled", "true") \
        .config("spark.executor.cores", "2") \
        .config("spark.task.cpus", "1") \
        .config("spark.driver.host", "localhost") \
        .getOrCreate()

def calculate_content_similarity(movie1, movie2):
    """计算两部电影的内容相似度"""
    similarity = 0.0
    # 初始化所有相似度变量，避免引用前未定义
    genre_similarity = 0.0
    director_similarity = 0.0
    actor_similarity = 0.0
    tag_similarity = 0.0
    
    try:
        # 获取电影类型
        genres1 = set([g.name for g in movie1.genres.all()])
        genres2 = set([g.name for g in movie2.genres.all()])

        # 类型相似度 (权重: 0.4)
        if genres1 and genres2:
            genre_similarity = len(genres1.intersection(genres2)) / max(len(genres1), len(genres2), 1)
            similarity += 0.4 * genre_similarity
        
        # 导演相似度 (权重: 0.1)
        if movie1.director and movie2.director:
            director1 = set(movie1.director.lower().split(','))
            director2 = set(movie2.director.lower().split(','))
            if director1 and director2:
                director_similarity = len(director1.intersection(director2)) / max(len(director1), len(director2), 1)
        similarity += 0.1 * director_similarity
        
        # 演员相似度 (权重: 0.1)
        if movie1.actors and movie2.actors:
            actors1 = set(movie1.actors.lower().split(','))
            actors2 = set(movie2.actors.lower().split(','))
            if actors1 and actors2:
                actor_similarity = len(actors1.intersection(actors2)) / max(len(actors1), len(actors2), 1)
        similarity += 0.1 * actor_similarity
        
        # 标签相似度 (权重: 0.4) - 从电影类型再次作为标签进行计算
        tag_similarity = genre_similarity  # 使用类型作为标签的近似
        similarity += 0.4 * tag_similarity
        
        return similarity
    except Exception as e:
        logger.error(f"计算电影 {movie1.id} 和 {movie2.id} 的相似度时出错: {str(e)}")
        return 0.0

def update_content_based_similarities(limit=None, min_similarity=0.1, no_prompt=False):
    """更新基于内容的电影相似度"""
    print(f"[推荐系统] 开始更新电影内容相似度数据...")
    
    # 获取所有电影
    movies = Movie.objects.all().prefetch_related('genres')
    if limit:
        movies = movies[:limit]
        print(f"[推荐系统] 处理有限数量的电影: {limit}部")
    else:
        print(f"[推荐系统] 处理所有电影: {movies.count()}部")
    
    # 检查是否已有相似度数据
    similarity_count = MovieSimilarity.objects.count()
    if similarity_count > 0 and not no_prompt:
        # 如果在命令行调用已有提示，这里不需要重复提示
        # 该提示主要用于直接调用此函数时使用
        if 'DJANGO_SETTINGS_MODULE' not in os.environ:
            confirm = input(f'[推荐系统] 系统中已有 {similarity_count} 条相似度数据，继续操作将会删除所有已有数据! 是否确认? (y/n): ')
            if confirm.lower() != 'y':
                print("[推荐系统] 用户取消了相似度计算操作")
                return 0
    
    # 清除旧的相似度数据
    print(f"[推荐系统] 清除旧的相似度数据...")
    MovieSimilarity.objects.all().delete()
    
    # 计算并更新相似度
    batch_size = 1000
    similarity_objects = []
    total_pairs = 0
    valid_pairs = 0
    
    start_time = time.time()
    movie_list = list(movies)
    movie_count = len(movie_list)
    
    for i, movie1 in enumerate(movie_list):
        if i % 10 == 0:
            elapsed = time.time() - start_time
            eta = (elapsed / (i+1)) * (movie_count - i - 1) if i > 0 else 0
            print(f"[推荐系统] 处理进度: {i}/{movie_count} ({i/movie_count*100:.2f}%), 已用时间: {elapsed:.0f}秒, 预计剩余: {eta:.0f}秒")
        
        for j in range(i+1, len(movie_list)):
            movie2 = movie_list[j]
            similarity = calculate_content_similarity(movie1, movie2)
            total_pairs += 1
            
            if similarity >= min_similarity:
                similarity_objects.append(
                    MovieSimilarity(
                        movie1=movie1,
                        movie2=movie2,
                        similarity=similarity
                    )
                )
                valid_pairs += 1
            
            if len(similarity_objects) >= batch_size:
                MovieSimilarity.objects.bulk_create(
                    similarity_objects,
                    ignore_conflicts=True
                )
                print(f"[推荐系统] 已保存 {valid_pairs} 条相似度数据 (有效比例: {valid_pairs/total_pairs*100:.2f}%)")
                similarity_objects = []
    
    if similarity_objects:
        MovieSimilarity.objects.bulk_create(
            similarity_objects,
            ignore_conflicts=True
        )
    
    print(f"[推荐系统] 电影相似度更新完成！总共处理了 {total_pairs} 对电影，保存了 {valid_pairs} 条相似度数据")
    print(f"[推荐系统] 有效相似度比例: {valid_pairs/total_pairs*100:.2f}%")
    return valid_pairs

def build_als_model(min_similarity=0.1, no_prompt=False):
    """使用ALS(交替最小二乘法)构建协同过滤推荐模型"""
    print(f"[推荐系统] 开始构建ALS协同过滤模型...")
    
    try:
        # 创建Spark会话
        spark = get_spark_session()
        print(f"[推荐系统] Spark会话已创建，版本: {spark.version}")
        
        # 从数据库获取评分数据
        print(f"[推荐系统] 从数据库加载评分数据...")
        ratings = UserRating.objects.all().values('user_id', 'movie_id', 'rating')
        
        if not ratings.exists():
            print(f"[推荐系统] 没有评分数据，无法构建ALS模型")
            spark.stop()
            return 0
        
        # 检查是否已有相似度数据
        similarity_count = MovieSimilarity.objects.count()
        if similarity_count > 0 and not no_prompt:
            # 如果在命令行调用已有提示，这里不需要重复提示
            # 该提示主要用于直接调用此函数时使用
            if 'DJANGO_SETTINGS_MODULE' not in os.environ:
                confirm = input(f'[推荐系统] 系统中已有 {similarity_count} 条相似度数据，继续操作将会删除所有已有数据! 是否确认? (y/n): ')
                if confirm.lower() != 'y':
                    print("[推荐系统] 用户取消了相似度计算操作")
                    spark.stop()
                    return 0
        
        # 清除现有的相似度数据
        MovieSimilarity.objects.all().delete()
        print(f"[推荐系统] 已清除旧的相似度数据")
        
        # 转换为Pandas DataFrame进行预处理
        ratings_df = pd.DataFrame(list(ratings))
        print(f"[推荐系统] 从数据库加载了 {len(ratings_df)} 条评分数据")
        
        # 用整数索引替换用户ID和电影ID
        user_ids = ratings_df['user_id'].unique()
        movie_ids = ratings_df['movie_id'].unique()
        
        user_id_map = {uid: i for i, uid in enumerate(user_ids)}
        movie_id_map = {mid: i for i, mid in enumerate(movie_ids)}
        reverse_movie_map = {i: mid for mid, i in movie_id_map.items()}
        
        ratings_df['user_idx'] = ratings_df['user_id'].map(user_id_map)
        ratings_df['movie_idx'] = ratings_df['movie_id'].map(movie_id_map)
        
        # 使用Spark DataFrame
        spark_ratings = spark.createDataFrame(ratings_df[['user_idx', 'movie_idx', 'rating']])
        
        # 创建ALS模型
        als = ALS(
            userCol="user_idx",
            itemCol="movie_idx",
            ratingCol="rating",
            coldStartStrategy="drop",
            nonnegative=True,
            rank=10,
            maxIter=10,
            regParam=0.1
        )
        
        print(f"[推荐系统] 拟合ALS模型...")
        model = als.fit(spark_ratings)
        
        # 获取电影特征
        movie_factors = model.itemFactors.toPandas()
        
        # 获取电影对象
        movie_objects = {m.id: m for m in Movie.objects.filter(id__in=movie_ids)}
        
        # 计算相似度
        print(f"[推荐系统] 基于ALS模型计算电影相似度...")
        similarities = []
        total_pairs = 0
        valid_pairs = 0
        
        for i in range(len(movie_factors)):
            if i % 10 == 0:
                print(f"[推荐系统] ALS相似度计算进度: {i}/{len(movie_factors)} ({i/len(movie_factors)*100:.2f}%)")
            
            movie1_idx = movie_factors.iloc[i]['id']
            movie1_id = reverse_movie_map[movie1_idx]
            
            if movie1_id not in movie_objects:
                continue
                
            movie1 = movie_objects[movie1_id]
            vec1 = np.array(movie_factors.iloc[i]['features'])
            
            for j in range(i + 1, len(movie_factors)):
                movie2_idx = movie_factors.iloc[j]['id']
                movie2_id = reverse_movie_map[movie2_idx]
                
                if movie2_id not in movie_objects:
                    continue
                    
                movie2 = movie_objects[movie2_id]
                vec2 = np.array(movie_factors.iloc[j]['features'])
                
                # 计算余弦相似度
                similarity = float(cosine_similarity([vec1], [vec2])[0][0])
                
                total_pairs += 1
                
                if similarity >= min_similarity:
                    similarities.append(
                        MovieSimilarity(
                            movie1=movie1,
                            movie2=movie2,
                            similarity=similarity
                        )
                    )
                    valid_pairs += 1
                
                # 批量插入
                if len(similarities) >= 1000:
                    MovieSimilarity.objects.bulk_create(similarities, ignore_conflicts=True)
                    print(f"[推荐系统] 已保存 {valid_pairs} 条相似度数据 (共 {total_pairs} 对, 有效率: {valid_pairs/total_pairs*100:.2f}%)")
                    similarities = []
        
        # 保存剩余数据
        if similarities:
            MovieSimilarity.objects.bulk_create(similarities, ignore_conflicts=True)
        
        print(f"[推荐系统] ALS电影相似度更新完成！总共处理了 {total_pairs} 对电影，保存了 {valid_pairs} 条相似度数据")
        
        # 关闭Spark会话
        spark.stop()
        print(f"[推荐系统] Spark会话已关闭")
        
        return valid_pairs
    except Exception as e:
        print(f"[推荐系统] ALS模型构建失败: {str(e)}")
        logger.error(f"ALS模型构建失败: {str(e)}", exc_info=True)
        return 0

def get_movie_recommendations(movie, limit=6):
    """获取电影推荐"""
    print(f"[推荐系统] 开始为电影 ID:{movie.id} 标题:{movie.title} 生成推荐")
    print(f"[推荐系统] 请求推荐数量: {limit}")
    
    # 获取基于内容的相似电影
    print(f"[推荐系统] 正在获取基于内容的相似电影...")
    content_similar = MovieSimilarity.objects.filter(
        Q(movie1=movie) | Q(movie2=movie)
    ).select_related('movie1', 'movie2').order_by('-similarity')[:limit*2]
    
    print(f"[推荐系统] 内容相似度模型找到 {content_similar.count()} 部相似电影")
    
    similar_movies = []
    for sim in content_similar:
        similar_movie = sim.movie2 if sim.movie1_id == movie.id else sim.movie1
        if similar_movie not in similar_movies:
            similar_movies.append(similar_movie)
            print(f"[推荐系统] 添加内容相似电影: ID:{similar_movie.id} 标题:{similar_movie.title} 相似度:{sim.similarity:.4f}")
    
    # 如果基于内容的推荐不足，补充协同过滤推荐
    if len(similar_movies) < limit:
        print(f"[推荐系统] 内容相似电影不足 ({len(similar_movies)}/{limit})，使用协同过滤补充推荐...")
        
        # 获取电影的类型
        movie_genres = list(movie.genres.all())
        print(f"[推荐系统] 原始电影类型: {', '.join([g.movie_type for g in movie_genres])}")
        
        collaborative_similar = Movie.objects.filter(
            genres__in=movie_genres
        ).exclude(
            id__in=[m.id for m in similar_movies] + [movie.id]
        ).annotate(
            avg_rating=Avg('user_ratings__rating'),
            rating_count=Count('user_ratings')
        ).order_by('-avg_rating', '-rating_count')[:limit-len(similar_movies)]
        
        print(f"[推荐系统] 协同过滤找到 {collaborative_similar.count()} 部相似电影")
        
        for movie in collaborative_similar:
            similar_movies.append(movie)
            print(f"[推荐系统] 添加协同过滤推荐电影: ID:{movie.id} 标题:{movie.title} 评分:{getattr(movie, 'avg_rating', 0)}")
    
    final_recommendations = similar_movies[:limit]
    print(f"[推荐系统] 最终推荐电影数量: {len(final_recommendations)}")
    return final_recommendations

def get_user_recommendations(user, limit=10):
    """获取用户推荐"""
    print(f"[推荐系统] 开始为用户 ID:{user.id} 用户名:{user.username} 生成个性化推荐")
    print(f"[推荐系统] 请求推荐数量: {limit}")
    
    # 获取用户已评分的电影
    rated_movies = set(user.ratings.values_list('movie_id', flat=True))
    print(f"[推荐系统] 用户已评分电影数量: {len(rated_movies)}")
    
    # 获取用户最喜欢的电影类型
    favorite_genres = Movie.objects.filter(
        user_ratings__user=user,
        user_ratings__rating__gte=7
    ).values(
        'genres'
    ).annotate(
        count=Count('id')
    ).order_by('-count')[:3]
    
    genre_ids = [g['genres'] for g in favorite_genres]
    print(f"[推荐系统] 用户喜爱的电影类型ID: {genre_ids}")
    
    # 基于用户喜好的电影推荐
    recommended_movies = Movie.objects.filter(
        genres__id__in=genre_ids
    ).exclude(
        id__in=rated_movies
    ).annotate(
        avg_rating=Avg('user_ratings__rating'),
        rating_count=Count('user_ratings')
    ).filter(
        rating_count__gte=10,  # 至少有10个评分
        avg_rating__gte=7      # 平均评分至少7分
    ).order_by('-avg_rating', '-rating_count')[:limit]
    
    print(f"[推荐系统] 找到符合用户喜好的推荐电影: {recommended_movies.count()}部")
    for movie in recommended_movies:
        print(f"[推荐系统] 推荐电影: ID:{movie.id} 标题:{movie.title} 评分:{getattr(movie, 'avg_rating', 0)}")
    
    return recommended_movies

def get_recommendation_system_status():
    """获取推荐系统的状态信息"""
    status = {}
    
    try:
        # 统计电影总数
        total_movies = Movie.objects.count()
        status['total_movies'] = total_movies
    except Exception as e:
        print(f"[推荐系统错误] 获取电影总数时出错: {e}")
        status['total_movies'] = 0
    
    try:
        # 统计用户总数
        from users.models import User
        total_users = User.objects.count()
        status['total_users'] = total_users
    except Exception as e:
        print(f"[推荐系统错误] 获取用户总数时出错: {e}")
        status['total_users'] = 0
    
    try:
        # 统计评分总数
        total_ratings = UserRating.objects.count()
        status['total_ratings'] = total_ratings
    except Exception as e:
        print(f"[推荐系统错误] 获取评分总数时出错: {e}")
        status['total_ratings'] = 0
    
    try:
        # 统计收藏总数
        total_favorites = UserFavorite.objects.count()
        status['total_favorites'] = total_favorites
    except Exception as e:
        print(f"[推荐系统错误] 获取收藏总数时出错: {e}")
        status['total_favorites'] = 0
    
    try:
        # 统计历史记录总数
        total_history = UserHistory.objects.count()
        status['total_history'] = total_history
    except Exception as e:
        print(f"[推荐系统错误] 获取历史记录总数时出错: {e}")
        status['total_history'] = 0
    
    try:
        # 统计电影相似度记录数
        total_similarities = MovieSimilarity.objects.count()
        status['total_similarities'] = total_similarities
    except Exception as e:
        print(f"[推荐系统错误] 获取相似度记录数时出错: {e}")
        status['total_similarities'] = 0
    
    try:
        # 评估推荐系统的覆盖率
        movies_with_similarities = MovieSimilarity.objects.values('movie1').distinct().count()
        status['movies_with_similarities'] = movies_with_similarities
    except Exception as e:
        print(f"[推荐系统错误] 获取具有相似度的电影数时出错: {e}")
        movies_with_similarities = 0
        status['movies_with_similarities'] = 0
    
    # 计算覆盖率
    status['similarity_coverage'] = round(movies_with_similarities / total_movies * 100, 2) if total_movies > 0 else 0
    
    try:
        # 评估用户的活跃度
        users_with_ratings = UserRating.objects.values('user').distinct().count()
        status['users_with_ratings'] = users_with_ratings
    except Exception as e:
        print(f"[推荐系统错误] 获取有评分的用户数时出错: {e}")
        users_with_ratings = 0
        status['users_with_ratings'] = 0
    
    # 计算用户评分覆盖率
    status['user_rating_coverage'] = round(users_with_ratings / total_users * 100, 2) if total_users > 0 else 0
    
    # 检查推荐系统状态
    status['has_similarity_data'] = total_similarities > 0
    status['has_rating_data'] = total_ratings > 0
    status['recommendation_ready'] = status['has_similarity_data'] and status['has_rating_data']
    
    # 记录状态到日志
    logger.info(f"[推荐系统状态] 电影总数: {status['total_movies']}")
    logger.info(f"[推荐系统状态] 用户总数: {status['total_users']}")
    logger.info(f"[推荐系统状态] 评分总数: {status['total_ratings']}")
    logger.info(f"[推荐系统状态] 收藏总数: {status['total_favorites']}")
    logger.info(f"[推荐系统状态] 历史记录: {status['total_history']}")
    logger.info(f"[推荐系统状态] 相似度记录: {status['total_similarities']}")
    logger.info(f"[推荐系统状态] 推荐系统就绪: {status['recommendation_ready']}")
    
    print(f"\n======================= 推荐系统状态 =======================")
    print(f"电影总数: {status['total_movies']}")
    print(f"用户总数: {status['total_users']}")
    print(f"评分总数: {status['total_ratings']}")
    print(f"收藏总数: {status['total_favorites']}")
    print(f"历史记录: {status['total_history']}")
    print(f"相似度记录: {status['total_similarities']}")
    print(f"相似度覆盖率: {status['similarity_coverage']}% ({status['movies_with_similarities']}/{status['total_movies']})")
    print(f"用户评分覆盖率: {status['user_rating_coverage']}% ({status['users_with_ratings']}/{status['total_users']})")
    print(f"推荐系统就绪: {'是' if status['recommendation_ready'] else '否'}")
    print(f"===============================================================\n")
    
    return status 

def update_similarity_from_collectmoviedb(limit=None, min_similarity=0.15, force_import=True, min_ratings=10, max_similarity_records=10000, no_prompt=False):
    """
    从movie_collectmoviedb表计算电影相似度并更新数据库
    
    参数:
        limit: 限制处理的电影数量
        min_similarity: 最小相似度阈值，默认提高到0.15
        force_import: 是否强制导入电影数据
        min_ratings: 最小评分人数，过滤冷门电影，默认10人
        max_similarity_records: 最大保存的相似度记录数，默认10000条，设为None则不限制
        no_prompt: 是否跳过确认提示
    """
    logger.info("[推荐系统] 开始从电影收集表计算相似度")
    
    # 记录开始时间
    start_time = time.time()
    
    # 检查是否已有相似度数据
    similarity_count = MovieSimilarity.objects.count()
    if similarity_count > 0 and not no_prompt:
        # 如果在命令行调用已有提示，这里不需要重复提示
        # 该提示主要用于直接调用此函数时使用
        if 'DJANGO_SETTINGS_MODULE' not in os.environ:
            confirm = input(f'[推荐系统] 系统中已有 {similarity_count} 条相似度数据，继续操作将会删除所有已有数据! 是否确认? (y/n): ')
            if confirm.lower() != 'y':
                logger.info("[推荐系统] 用户取消了相似度计算操作")
                return 0
    
    # 清除现有的相似度数据
    MovieSimilarity.objects.all().delete()
    logger.info("[推荐系统] 已清除旧的相似度数据")
    
    # 如果需要，强制导入电影
    if force_import:
        imported_count = import_movies_from_collectdb(limit)
        logger.info(f"[推荐系统] 已导入 {imported_count} 部新电影")
    
    # 查询电影数据 - 直接从CollectMovieDB获取，过滤冷门电影
    with connection.cursor() as cursor:
        movie_query = """
            SELECT 
                movie_id, title, original_title, 
                directors, actor, genres, 
                tags, rating, year, ratings_count
            FROM movie_collectmoviedb
            WHERE ratings_count >= %s
        """
        
        # 添加排序，让热门电影优先计算
        movie_query += " ORDER BY ratings_count DESC"
        
        if limit:
            movie_query += f" LIMIT {limit}"
            
        cursor.execute(movie_query, [min_ratings])
        movie_data = cursor.fetchall()
    
    logger.info(f"[推荐系统] 从数据库获取了 {len(movie_data)} 部电影数据（评分人数 >= {min_ratings}）")
    
    # 处理电影数据
    movies = []
    for row in movie_data:
        movie_id, title, original_title, directors, actors, genres, tags, rating, year, ratings_count = row
            
        try:
            # 解析JSON字段
            try:
                directors_data = json.loads(directors.replace("'", "\"")) if directors else []
            except:
                directors_data = []
                
            try:
                actors_data = json.loads(actors.replace("'", "\"")) if actors else []
            except:
                actors_data = []
                
            # 提取导演和演员名字
            directors_names = [d.get('name', '') for d in directors_data if isinstance(d, dict)]
            actors_names = [a.get('name', '') for a in actors_data if isinstance(a, dict)]
            
            # 清理类型数据
            if genres:
                genres = genres.strip("[]").replace("'", "").split(", ")
            else:
                genres = []
                
            if tags:
                tags = tags.strip("[]").replace("'", "").split(", ")
            else:
                tags = []
            
            # 提取评分
            try:
                if rating:
                    rating_data = json.loads(rating.replace("'", "\""))
                    avg_rating = rating_data.get('average', 0)
                else:
                    avg_rating = 0
            except:
                avg_rating = 0
            
            # 过滤无类型和无标签的电影
            if not genres and not tags:
                continue
                
            # 将处理后的数据添加到电影列表
            movies.append({
                'movie_id': movie_id,
                'title': title,
                'original_title': original_title,
                'directors': directors_names,
                'actors': actors_names,
                'genres': genres,
                'tags': tags,
                'rating': avg_rating,
                'year': year,
                'ratings_count': ratings_count
            })
            
        except Exception as e:
            logger.error(f"[推荐系统] 处理电影数据出错 (ID={movie_id}): {str(e)}")
    
    logger.info(f"[推荐系统] 成功处理 {len(movies)} 部电影数据")
    
    # 使用Spark进行并行计算
    if len(movies) > 0:
        valid_pairs = 0
        n = len(movies)
        max_pairs = n * (n-1) // 2  # 最大可能的电影对数量
        logger.info(f"[推荐系统] 开始处理 {n} 部电影的相似度计算，共 {max_pairs} 对...")
        
        # 定义批处理大小，确保在所有代码路径中都可用
        batch_size = 1000
        similarity_batch = []
        
        # 创建Spark会话
        try:
            spark = get_spark_session()
            logger.info("[推荐系统] 成功创建Spark会话")
            
            # 准备数据，创建电影对列表
            movie_pairs = []
            for i in range(n):
                for j in range(i+1, n):
                    movie_pairs.append((i, j))
                    
            # 创建RDD并分区 - 控制分区数量以平衡内存使用和并行度
            partition_count = min(200, max(20, len(movie_pairs) // 10000))
            movie_pairs_rdd = spark.sparkContext.parallelize(movie_pairs, numSlices=partition_count)
            logger.info(f"[推荐系统] 创建RDD，分区数: {partition_count}")
            
            # 使用广播变量传递电影数据，避免在每个任务中复制
            broadcast_movies = spark.sparkContext.broadcast(movies)
            
            # 定义相似度计算函数
            def calculate_similarity_pair(pair):
                i, j = pair
                movie1 = broadcast_movies.value[i]
                movie2 = broadcast_movies.value[j]
                
                try:
                    # 计算类型相似度
                    genre_similarity = 0
                    if movie1['genres'] and movie2['genres']:
                        common_genres = set(movie1['genres']) & set(movie2['genres'])
                        if common_genres:
                            genre_similarity = len(common_genres) / max(len(movie1['genres']), len(movie2['genres']))
                    
                    # 计算导演相似度
                    director_similarity = 0
                    if movie1['directors'] and movie2['directors']:
                        common_directors = set(movie1['directors']) & set(movie2['directors'])
                        if common_directors:
                            director_similarity = len(common_directors) / max(len(movie1['directors']), len(movie2['directors']))
                    
                    # 计算演员相似度
                    actor_similarity = 0
                    if movie1['actors'] and movie2['actors']:
                        common_actors = set(movie1['actors']) & set(movie2['actors'])
                        if common_actors:
                            actor_similarity = len(common_actors) / max(len(movie1['actors']), len(movie2['actors']))
                    
                    # 标签相似度
                    tag_similarity = 0
                    if movie1['tags'] and movie2['tags']:
                        common_tags = set(movie1['tags']) & set(movie2['tags'])
                        if common_tags:
                            tag_similarity = len(common_tags) / max(len(movie1['tags']), len(movie2['tags']))
                    
                    # 计算总相似度 - 各部分权重可调整
                    similarity = (
                        genre_similarity * 0.4 +  # 类型相似度权重
                        director_similarity * 0.1 +  # 导演相似度权重
                        actor_similarity * 0.1 +  # 演员相似度权重
                        tag_similarity * 0.4  # 标签相似度权重
                    )
                    
                    # 如果只有类型匹配也给一个基础分
                    if genre_similarity > 0 and similarity < min_similarity:
                        similarity = max(similarity, 0.05)
                        
                    # 返回符合条件的相似度
                    if similarity >= min_similarity:
                        return (movie1['movie_id'], movie2['movie_id'], similarity)
                    else:
                        return None
                
                except Exception as e:
                    # 出错则返回None
                    return None
            
            # 执行并行计算
            logger.info("[推荐系统] 开始Spark并行计算相似度...")
            similarity_results = movie_pairs_rdd.map(calculate_similarity_pair).filter(lambda x: x is not None).collect()
            logger.info(f"[推荐系统] Spark计算完成，获得 {len(similarity_results)} 个有效相似度对")
            
            # 批量处理相似度结果
            saved_records = 0  # 跟踪已保存的记录数
            for result in similarity_results:
                # 如果已达到最大记录限制，则停止保存
                if max_similarity_records is not None and saved_records >= max_similarity_records:
                    logger.info(f"[推荐系统] 已达到最大相似度记录限制 ({max_similarity_records})，停止保存")
                    break
                    
                movie1_id, movie2_id, similarity = result
                
                try:
                    # 尝试获取或创建Movie对象
                    movie1_obj, created1 = Movie.objects.get_or_create(
                        id=movie1_id, 
                        defaults={
                            'title': next((m['title'] for m in movies if m['movie_id'] == movie1_id), ''),
                            'original_title': next((m['original_title'] for m in movies if m['movie_id'] == movie1_id), ''),
                            'director': next((', '.join(m['directors'][:1]) if m['directors'] else '' for m in movies if m['movie_id'] == movie1_id), ''),
                            'actors': next((', '.join(m['actors'][:5]) if m['actors'] else '' for m in movies if m['movie_id'] == movie1_id), ''),
                            'rating': next((m['rating'] for m in movies if m['movie_id'] == movie1_id), 0)
                        }
                    )
                    
                    movie2_obj, created2 = Movie.objects.get_or_create(
                        id=movie2_id, 
                        defaults={
                            'title': next((m['title'] for m in movies if m['movie_id'] == movie2_id), ''),
                            'original_title': next((m['original_title'] for m in movies if m['movie_id'] == movie2_id), ''),
                            'director': next((', '.join(m['directors'][:1]) if m['directors'] else '' for m in movies if m['movie_id'] == movie2_id), ''),
                            'actors': next((', '.join(m['actors'][:5]) if m['actors'] else '' for m in movies if m['movie_id'] == movie2_id), ''),
                            'rating': next((m['rating'] for m in movies if m['movie_id'] == movie2_id), 0)
                        }
                    )
                    
                    similarity_batch.append(
                        MovieSimilarity(
                            movie1=movie1_obj,
                            movie2=movie2_obj,
                            similarity=similarity
                        )
                    )
                    valid_pairs += 1
                    
                    # 批量插入相似度记录
                    if len(similarity_batch) >= batch_size:
                        MovieSimilarity.objects.bulk_create(similarity_batch, ignore_conflicts=True)
                        saved_records += len(similarity_batch)
                        logger.info(f"[推荐系统] 已保存 {saved_records}/{max_similarity_records if max_similarity_records else '无限制'} 条相似度记录")
                        similarity_batch = []
                        
                        # 如果已达到最大记录限制，则停止保存
                        if max_similarity_records is not None and saved_records >= max_similarity_records:
                            logger.info(f"[推荐系统] 已达到最大相似度记录限制 ({max_similarity_records})，停止保存")
                            break
                        
                except Exception as e:
                    logger.error(f"[推荐系统] 创建相似度记录时出错: {str(e)}")
            
            # 插入剩余的相似度记录，仍需检查限制
            if similarity_batch and (max_similarity_records is None or saved_records < max_similarity_records):
                # 如果有限制，可能需要截断batch
                if max_similarity_records is not None:
                    remaining_slots = max_similarity_records - saved_records
                    if remaining_slots < len(similarity_batch):
                        similarity_batch = similarity_batch[:remaining_slots]
                        logger.info(f"[推荐系统] 最后批次截断至 {remaining_slots} 条记录以满足最大限制")
                
                MovieSimilarity.objects.bulk_create(similarity_batch, ignore_conflicts=True)
                saved_records += len(similarity_batch)
                logger.info(f"[推荐系统] 最终共保存 {saved_records} 条相似度记录")
            
            # 停止Spark会话以释放资源
            spark.stop()
            logger.info("[推荐系统] 已停止Spark会话")
            
        except Exception as e:
            logger.error(f"[推荐系统] Spark处理出错: {str(e)}")
            # 如果Spark处理失败，回退到非并行处理方法
            logger.info("[推荐系统] 回退到非并行处理方法...")
            
            # 重置计数器和批处理列表，确保在回退路径中也是干净的状态
            similarity_batch = []
            valid_pairs = 0
            total_pairs = 0
            saved_records = 0  # 跟踪已保存的记录数
            
            # 逐对计算相似度
            for i in range(n):
                for j in range(i+1, n):  # 只计算上三角矩阵，避免重复
                    movie1 = movies[i]
                    movie2 = movies[j]
                    
                    total_pairs += 1
                    
                    # 计算相似度分数
                    try:
                        # 计算类型相似度
                        genre_similarity = 0
                        if movie1['genres'] and movie2['genres']:
                            common_genres = set(movie1['genres']) & set(movie2['genres'])
                            if common_genres:
                                genre_similarity = len(common_genres) / max(len(movie1['genres']), len(movie2['genres']))
                        
                        # 计算导演相似度
                        director_similarity = 0
                        if movie1['directors'] and movie2['directors']:
                            common_directors = set(movie1['directors']) & set(movie2['directors'])
                            if common_directors:
                                director_similarity = len(common_directors) / max(len(movie1['directors']), len(movie2['directors']))
                        
                        # 计算演员相似度
                        actor_similarity = 0
                        if movie1['actors'] and movie2['actors']:
                            common_actors = set(movie1['actors']) & set(movie2['actors'])
                            if common_actors:
                                actor_similarity = len(common_actors) / max(len(movie1['actors']), len(movie2['actors']))
                        
                        # 标签相似度
                        tag_similarity = 0
                        if movie1['tags'] and movie2['tags']:
                            common_tags = set(movie1['tags']) & set(movie2['tags'])
                            if common_tags:
                                tag_similarity = len(common_tags) / max(len(movie1['tags']), len(movie2['tags']))
                        
                        # 计算总相似度 - 各部分权重可调整
                        similarity = (
                            genre_similarity * 0.4 +  # 类型相似度权重
                            director_similarity * 0.1 +  # 导演相似度权重
                            actor_similarity * 0.1 +  # 演员相似度权重
                            tag_similarity * 0.4  # 标签相似度权重
                        )
                        
                        # 如果只有类型匹配也给一个基础分
                        if genre_similarity > 0 and similarity < min_similarity:
                            similarity = max(similarity, 0.05)
                            
                        # 保存符合条件的相似度
                        if similarity >= min_similarity:
                            # 先检查电影ID是否已存在于Movie表
                            movie1_id = movie1['movie_id']
                            movie2_id = movie2['movie_id']
                            
                            # 尝试获取或创建Movie对象
                            movie1_obj, created1 = Movie.objects.get_or_create(
                                id=movie1_id, 
                                defaults={
                                    'title': movie1['title'],
                                    'original_title': movie1['original_title'] or movie1['title'],
                                    'director': ', '.join(movie1['directors'][:1]) if movie1['directors'] else '',
                                    'actors': ', '.join(movie1['actors'][:5]) if movie1['actors'] else '',
                                    'rating': movie1['rating']
                                }
                            )
                            
                            movie2_obj, created2 = Movie.objects.get_or_create(
                                id=movie2_id, 
                                defaults={
                                    'title': movie2['title'],
                                    'original_title': movie2['original_title'] or movie2['title'],
                                    'director': ', '.join(movie2['directors'][:1]) if movie2['directors'] else '',
                                    'actors': ', '.join(movie2['actors'][:5]) if movie2['actors'] else '',
                                    'rating': movie2['rating']
                                }
                            )
                            
                            similarity_batch.append(
                                MovieSimilarity(
                                    movie1=movie1_obj,
                                    movie2=movie2_obj,
                                    similarity=similarity
                                )
                            )
                            valid_pairs += 1
                    
                    except Exception as e:
                        logger.error(f"[推荐系统] 计算相似度时出错: {str(e)}")
                    
                    # 批量插入相似度记录
                    if len(similarity_batch) >= batch_size:
                        MovieSimilarity.objects.bulk_create(similarity_batch, ignore_conflicts=True)
                        saved_records += len(similarity_batch)
                        similarity_batch = []
                        
                        # 如果已达到最大记录限制，则停止保存
                        if max_similarity_records is not None and saved_records >= max_similarity_records:
                            logger.info(f"[推荐系统] 已达到最大相似度记录限制 ({max_similarity_records})，停止保存")
                            break
                    
                    # 更新进度
                    if total_pairs % (max_pairs // 10) == 0 or total_pairs == max_pairs:
                        progress = (total_pairs / max_pairs) * 100
                        logger.info(f"[推荐系统] 相似度计算进度: {progress:.2f}% 完成")
            
            # 插入剩余的相似度记录，仍需检查限制
            if similarity_batch and (max_similarity_records is None or saved_records < max_similarity_records):
                # 如果有限制，可能需要截断batch
                if max_similarity_records is not None:
                    remaining_slots = max_similarity_records - saved_records
                    if remaining_slots < len(similarity_batch):
                        similarity_batch = similarity_batch[:remaining_slots]
                        logger.info(f"[推荐系统] 最后批次截断至 {remaining_slots} 条记录以满足最大限制")
                
                MovieSimilarity.objects.bulk_create(similarity_batch, ignore_conflicts=True)
                saved_records += len(similarity_batch)
                logger.info(f"[推荐系统] 最终共保存 {saved_records} 条相似度记录")
        
        # 计算有效相似度比率和耗时
        total_time = time.time() - start_time
        logger.info(f"[推荐系统] 相似度计算完成! 保存了 {valid_pairs} 条相似度数据")
        logger.info(f"[推荐系统] 总耗时: {total_time:.2f}秒")
    else:
        logger.warning("[推荐系统] 没有找到有效的电影数据，无法计算相似度")
    
    return valid_pairs

def import_movies_from_collectdb(limit=None):
    """
    从movie_collectmoviedb表导入电影数据到movies_movie表
    
    参数:
        limit: 可选，限制处理的电影数量
        
    返回:
        导入的电影数量
    """
    logger.info(f"[推荐系统] 开始从电影收集表导入电影数据...")
    
    # 获取已有的电影ID
    existing_movie_ids = set(Movie.objects.values_list('id', flat=True))
    logger.info(f"[推荐系统] 当前已有 {len(existing_movie_ids)} 部电影")
    
    # 查询电影收集表中的电影
    with connection.cursor() as cursor:
        query = """
            SELECT 
                movie_id, title, original_title, year, 
                rating, genres, directors, actor,
                tags, images, durations, summary
            FROM movie_collectmoviedb
            WHERE movie_id NOT IN (
                SELECT id FROM movies_movie
            )
        """
        
        if limit:
            query += f" LIMIT {limit}"
            
        cursor.execute(query)
        movies_to_import = cursor.fetchall()
    
    logger.info(f"[推荐系统] 找到 {len(movies_to_import)} 部需要导入的电影")
    
    # 批量创建电影对象
    imported_count = 0
    batch_size = 100
    movie_batches = []
    
    for movie_data in movies_to_import:
        try:
            movie_id, title, original_title, year, rating_json, genres_str, directors_json, actors_json, tags_str, images_json, durations, summary = movie_data
            
            # 解析评分
            rating = 0
            try:
                if rating_json:
                    rating_data = json.loads(rating_json.replace("'", "\""))
                    rating = float(rating_data.get('average', 0))
            except Exception as e:
                logger.error(f"[推荐系统] 解析评分出错(ID={movie_id}): {str(e)}")
            
            # 提取导演
            director = ''
            try:
                if directors_json:
                    directors_data = json.loads(directors_json.replace("'", "\""))
                    if directors_data and isinstance(directors_data, list) and len(directors_data) > 0:
                        director = directors_data[0].get('name', '')
            except Exception as e:
                logger.warning(f"[推荐系统] 解析导演出错(ID={movie_id}): {str(e)}")
            
            # 提取演员
            actors = ''
            try:
                if actors_json:
                    actors_data = json.loads(actors_json.replace("'", "\""))
                    if actors_data and isinstance(actors_data, list):
                        actor_names = [actor.get('name', '') for actor in actors_data if actor.get('name')]
                        actors = ', '.join(actor_names[:5])  # 只取前5个演员
            except Exception as e:
                logger.warning(f"[推荐系统] 解析演员出错(ID={movie_id}): {str(e)}")
            
            # 提取时长
            duration = None
            try:
                if durations:
                    durations_data = json.loads(durations.replace("'", "\""))
                    if durations_data and isinstance(durations_data, list):
                        duration_str = durations_data[0]
                        import re
                        duration_match = re.search(r'(\d+)', duration_str)
                        if duration_match:
                            duration = int(duration_match.group(1))
            except Exception as e:
                logger.warning(f"[推荐系统] 解析时长出错(ID={movie_id}): {str(e)}")
            
            # 创建电影对象
            movie = Movie(
                id=movie_id,
                title=title,
                original_title=original_title or title,
                director=director,
                actors=actors,
                duration=duration,
                rating=rating,
                description=summary or f'电影ID: {movie_id}'
            )
            
            # 设置release_date
            if year:
                from datetime import date
                movie.release_date = date(year=int(year), month=1, day=1)
            
            # 尝试从images中提取封面图片
            if images_json:
                try:
                    images_data = parse_image_data(images_json)
                    # 根据实际字段结构调整
                    if isinstance(images_data, dict) and 'large' in images_data:
                        poster_url = images_data.get('large', '')
                        if poster_url:
                            movie.poster = poster_url
                except Exception as e:
                    logger.warning(f"[推荐系统] 解析电影图片出错(ID={movie_id}): {str(e)}")
            
            movie_batches.append(movie)
            
            # 批量保存
            if len(movie_batches) >= batch_size:
                try:
                    Movie.objects.bulk_create(movie_batches, ignore_conflicts=True)
                    imported_count += len(movie_batches)
                    logger.info(f"[推荐系统] 已导入 {imported_count} 部电影")
                except Exception as e:
                    logger.error(f"[推荐系统] 批量导入电影出错: {str(e)}")
                movie_batches = []
                
        except Exception as e:
            logger.error(f"[推荐系统] 处理电影数据出错(ID={movie_data[0] if movie_data else 'unknown'}): {str(e)}")
            continue
    
    # 保存剩余的电影
    if movie_batches:
        try:
            Movie.objects.bulk_create(movie_batches, ignore_conflicts=True)
            imported_count += len(movie_batches)
        except Exception as e:
            logger.error(f"[推荐系统] 批量导入电影出错: {str(e)}")
    
    # 第二步：关联电影类型
    logger.info(f"[推荐系统] 开始关联电影类型...")
    
    # 获取所有成功导入的电影ID
    imported_movie_ids = Movie.objects.filter(id__in=[m.id for m in movie_batches]).values_list('id', flat=True)
    
    # 为这些电影关联类型
    for movie_data in movies_to_import:
        try:
            movie_id = movie_data[0]
            if movie_id not in imported_movie_ids:
                continue
                
            # 解析类型数据
            genres_str = movie_data[5]
            if not genres_str:
                continue
                
            # 将类型字符串转换为列表
            try:
                genres_list = genres_str.strip("[]").replace("'", "").split(", ")
                
                # 获取电影对象
                movie = Movie.objects.get(id=movie_id)
                
                # 清除现有关联
                movie.genres.clear()
                
                # 为每个类型创建关联
                for genre_name in genres_list:
                    if not genre_name:
                        continue
                        
                    # 获取或创建类型
                    genre, _ = Genre.objects.get_or_create(name=genre_name)
                    movie.genres.add(genre)
                
            except Exception as e:
                logger.error(f"[推荐系统] 关联电影类型出错(ID={movie_id}): {str(e)}")
                
        except Exception as e:
            logger.error(f"[推荐系统] 处理电影类型数据出错: {str(e)}")
    
    logger.info(f"[推荐系统] 电影导入完成，成功导入 {imported_count} 部电影")
    return imported_count 