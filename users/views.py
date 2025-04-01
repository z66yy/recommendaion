from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from .forms import UserRegistrationForm, UserProfileForm
from .models import User, UserFavorite, UserHistory
from movies.models import Movie
from django.db import connection
from datetime import datetime

def login_view(request):
    """用户登录视图"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', '/')
            return redirect(next_url)
        else:
            messages.error(request, '用户名或密码错误')
    
    return render(request, 'users/login.html')

def logout_view(request):
    """用户登出视图"""
    logout(request)
    return redirect('home')

def register_view(request):
    """用户注册视图"""
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = ''  # 设置空邮箱
            user.save()
            login(request, user)
            messages.success(request, '注册成功！')
            return redirect('home')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'users/register.html', {'form': form})

@login_required
def profile_view(request):
    """用户个人资料视图"""
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, '个人资料更新成功')
            return redirect('users:profile')
    else:
        form = UserProfileForm(instance=request.user)
    
    # 使用原生SQL查询获取用户数据
    user_id = request.user.id
    
    with connection.cursor() as cursor:
        # 获取最近评分记录
        cursor.execute("""
            SELECT r.id, r.rating, r.comment, r.created_time, r.updated_time, 
                   m.movie_id, m.title as movie_title
            FROM users_userrating r
            JOIN movie_collectmoviedb m ON r.movie_id = m.movie_id
            WHERE r.user_id = %s
            ORDER BY r.updated_time DESC
            LIMIT 5
        """, [user_id])
        recent_ratings = []
        for row in cursor.fetchall():
            recent_ratings.append({
                'id': row[0],
                'rating_value': row[1],
                'comment': row[2],
                'created_time': row[3],
                'updated_time': row[4],
                'movie_id': row[5],
                'movie_title': row[6]
            })
        
        # 获取最近收藏的电影
        cursor.execute("""
            SELECT f.id, f.created_time, 
                   m.movie_id, m.title as movie_title
            FROM users_userfavorite f
            JOIN movie_collectmoviedb m ON f.movie_id = m.movie_id
            WHERE f.user_id = %s
            ORDER BY f.created_time DESC
            LIMIT 8
        """, [user_id])
        recent_favorites = []
        for row in cursor.fetchall():
            recent_favorites.append({
                'id': row[0],
                'created_time': row[1],
                'movie_id': row[2],
                'movie_title': row[3]
            })
        
        # 获取最近观看记录
        cursor.execute("""
            SELECT h.id, h.watch_time, h.watch_duration,
                   m.movie_id, m.title as movie_title
            FROM users_userhistory h
            JOIN movie_collectmoviedb m ON h.movie_id = m.movie_id
            WHERE h.user_id = %s
            ORDER BY h.watch_time DESC
            LIMIT 5
        """, [user_id])
        recent_history = []
        for row in cursor.fetchall():
            recent_history.append({
                'id': row[0],
                'watch_time': row[1],
                'watch_duration': row[2],
                'movie_id': row[3],
                'movie_title': row[4]
            })
    
    context = {
        'form': form,
        'recent_ratings': recent_ratings,
        'recent_favorites': recent_favorites,
        'recent_history': recent_history,
    }
    return render(request, 'users/profile.html', context)

@login_required
def favorites_view(request):
    """用户收藏列表视图"""
    user_id = request.user.id
    
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT f.id, f.created_time, 
                   m.movie_id, m.title as movie_title, m.rating, m.genres, m.year
            FROM users_userfavorite f
            JOIN movie_collectmoviedb m ON f.movie_id = m.movie_id
            WHERE f.user_id = %s
            ORDER BY f.created_time DESC
        """, [user_id])
        favorites = []
        for row in cursor.fetchall():
            import json
            # 解析电影评分JSON
            rating_data = json.loads(row[4].replace("'", "\"")) if row[4] else {"average": 0}
            avg_rating = rating_data.get("average", 0)
            
            favorites.append({
                'id': row[0],
                'created_time': row[1],
                'movie_id': row[2],
                'movie_title': row[3],
                'rating': avg_rating,
                'genres': row[5].strip("[]").replace("'", "").split(", ") if row[5] else [],
                'year': row[6]
            })
    
    return render(request, 'users/favorites.html', {'favorites': favorites})

@login_required
def history_view(request):
    """用户观看历史视图"""
    user_id = request.user.id
    
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT h.id, h.watch_time, h.watch_duration,
                   m.movie_id, m.title as movie_title, m.rating, m.genres, m.year
            FROM users_userhistory h
            JOIN movie_collectmoviedb m ON h.movie_id = m.movie_id
            WHERE h.user_id = %s
            ORDER BY h.watch_time DESC
        """, [user_id])
        history_list = []
        for row in cursor.fetchall():
            import json
            # 解析电影评分JSON
            rating_data = json.loads(row[5].replace("'", "\"")) if row[5] else {"average": 0}
            avg_rating = rating_data.get("average", 0)
            
            history_list.append({
                'id': row[0],
                'watch_time': row[1],
                'watch_duration': row[2],
                'movie_id': row[3],
                'movie_title': row[4],
                'rating': avg_rating,
                'genres': row[6].strip("[]").replace("'", "").split(", ") if row[6] else [],
                'year': row[7]
            })
    
    # 分页，每页12条记录
    paginator = Paginator(history_list, 12)
    page = request.GET.get('page', 1)
    history = paginator.get_page(page)
    
    return render(request, 'users/history.html', {'history': history})

@login_required
@require_POST
def toggle_favorite(request, movie_id):
    """切换电影收藏状态"""
    try:
        user_id = request.user.id
        print(f"Processing favorite toggle for user_id: {user_id}, movie_id: {movie_id}")
        
        # 检查电影是否存在
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT movie_id FROM movie_collectmoviedb
                WHERE movie_id = %s
            """, [movie_id])
            movie = cursor.fetchone()
            
            if not movie:
                print(f"Movie with ID {movie_id} not found")
                return JsonResponse({
                    'success': False,
                    'error': '电影不存在'
                })
            
            # 暂时禁用外键检查
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            
            try:
                # 检查收藏是否存在
                cursor.execute("""
                    SELECT id FROM users_userfavorite
                    WHERE user_id = %s AND movie_id = %s
                """, [user_id, movie_id])
                favorite = cursor.fetchone()
                
                if favorite:
                    # 已收藏，删除收藏
                    print(f"Removing favorite for user_id: {user_id}, movie_id: {movie_id}")
                    cursor.execute("""
                        DELETE FROM users_userfavorite
                        WHERE user_id = %s AND movie_id = %s
                    """, [user_id, movie_id])
                    is_favorite = False
                else:
                    # 未收藏，添加收藏
                    print(f"Adding favorite for user_id: {user_id}, movie_id: {movie_id}")
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute("""
                        INSERT INTO users_userfavorite (user_id, movie_id, created_time)
                        VALUES (%s, %s, %s)
                    """, [user_id, movie_id, current_time])
                    is_favorite = True
            finally:
                # 恢复外键检查
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        return JsonResponse({
            'success': True,
            'is_favorite': is_favorite
        })
    except Exception as e:
        print(f"收藏操作出错: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def check_favorite(request, movie_id):
    """检查电影是否被当前用户收藏"""
    try:
        user_id = request.user.id
        
        # 检查收藏是否存在
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id FROM users_userfavorite
                WHERE user_id = %s AND movie_id = %s
            """, [user_id, movie_id])
            favorite = cursor.fetchone()
            
            is_favorite = favorite is not None
        
        return JsonResponse({
            'success': True,
            'is_favorite': is_favorite
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
