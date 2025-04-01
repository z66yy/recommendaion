from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from movies.models import Movie
from .recommendation import get_movie_recommendations, get_user_recommendations, get_recommendation_system_status

# Create your views here.

@login_required
def user_recommendations(request):
    """用户个性化推荐页面"""
    print(f"[用户推荐] 开始为用户 ID:{request.user.id} 用户名:{request.user.username} 生成个性化推荐页面")
    
    # 获取推荐系统状态
    print(f"[用户推荐] 检查推荐系统状态")
    system_status = get_recommendation_system_status()
    
    # 如果推荐系统没有就绪，显示提示信息
    if not system_status['recommendation_ready']:
        print(f"[用户推荐] 警告：推荐系统未就绪，推荐质量可能受到影响")
    
    # 获取用户推荐的电影
    print(f"[用户推荐] 调用推荐系统API获取个性化推荐")
    recommended_movies = get_user_recommendations(request.user)
    print(f"[用户推荐] 获取到 {len(recommended_movies)} 部推荐电影")
    
    # 记录推荐电影的标题和评分
    for i, movie in enumerate(recommended_movies[:5]):  # 只记录前5部，避免日志过长
        print(f"[用户推荐] 推荐电影 {i+1}: ID={movie.id} 标题={movie.title} 评分={getattr(movie, 'avg_rating', 0)}")
    
    if len(recommended_movies) > 5:
        print(f"[用户推荐] 更多推荐电影: {len(recommended_movies) - 5}部")
    
    context = {
        'recommended_movies': recommended_movies,
        'system_status': system_status,
    }
    print(f"[用户推荐] 用户推荐页面渲染完成")
    return render(request, 'recommender/user_recommendations.html', context)

def movie_recommendations(request, movie_id):
    """获取相似电影推荐API"""
    print(f"[电影推荐API] 收到电影 ID:{movie_id} 的相似电影推荐请求")
    
    try:
        print(f"[电影推荐API] 查询电影数据")
        movie = Movie.objects.get(id=movie_id)
        print(f"[电影推荐API] 找到电影: {movie.title}")
        
        print(f"[电影推荐API] 调用推荐系统获取相似电影")
        similar_movies = get_movie_recommendations(movie)
        print(f"[电影推荐API] 获取到 {len(similar_movies)} 部相似电影")
        
        # 提取推荐电影的信息
        recommendations = []
        for i, m in enumerate(similar_movies):
            movie_data = {
                'id': m.id,
                'title': m.title,
                'poster_url': m.poster.url if hasattr(m, 'poster') and m.poster else None,
                'rating': getattr(m, 'rating', 0),
                'rating_count': getattr(m, 'rating_count', 0),
            }
            recommendations.append(movie_data)
            print(f"[电影推荐API] 推荐电影 {i+1}: ID={m.id} 标题={m.title}")
        
        print(f"[电影推荐API] 成功返回 {len(recommendations)} 部推荐电影")
        return JsonResponse({
            'success': True,
            'recommendations': recommendations
        })
    except Movie.DoesNotExist:
        print(f"[电影推荐API] 电影不存在: ID={movie_id}")
        return JsonResponse({
            'success': False,
            'error': '电影不存在'
        })
    except Exception as e:
        print(f"[电影推荐API] 推荐生成失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
