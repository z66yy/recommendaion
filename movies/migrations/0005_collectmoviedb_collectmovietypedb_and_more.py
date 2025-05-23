# Generated by Django 4.2.20 on 2025-04-12 17:09

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0004_movieimagecache_movie_movies_movi_rating_8fd49a_idx'),
    ]

    operations = [
        migrations.CreateModel(
            name='CollectMovieDB',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movie_id', models.IntegerField(unique=True, verbose_name='电影ID')),
                ('original_title', models.CharField(max_length=1000, verbose_name='原始标题')),
                ('title', models.CharField(max_length=1000, verbose_name='标题')),
                ('rating', models.TextField(verbose_name='评分')),
                ('ratings_count', models.IntegerField(verbose_name='评分数')),
                ('pubdate', models.CharField(max_length=1000, verbose_name='发布日期')),
                ('pubdates', models.CharField(max_length=1000, verbose_name='发布日期列表')),
                ('year', models.IntegerField(verbose_name='年份')),
                ('countries', models.CharField(max_length=1000, verbose_name='国家')),
                ('mainland_pubdate', models.CharField(max_length=1000, verbose_name='大陆发布日期')),
                ('aka', models.CharField(max_length=1000, verbose_name='别名')),
                ('tags', models.CharField(max_length=1000, verbose_name='标签')),
                ('durations', models.TextField(verbose_name='时长')),
                ('genres', models.CharField(max_length=1000, verbose_name='类型')),
                ('videos', models.TextField(verbose_name='视频')),
                ('wish_count', models.IntegerField(verbose_name='想看数')),
                ('reviews_count', models.IntegerField(verbose_name='评论数')),
                ('comments_count', models.IntegerField(verbose_name='短评数')),
                ('collect_count', models.IntegerField(verbose_name='收藏数')),
                ('images', models.TextField(verbose_name='图片')),
                ('photos', models.TextField(verbose_name='照片')),
                ('languages', models.CharField(max_length=1000, verbose_name='语言')),
                ('writers', models.TextField(verbose_name='编剧')),
                ('actor', models.TextField(verbose_name='演员')),
                ('summary', models.TextField(verbose_name='简介')),
                ('directors', models.TextField(verbose_name='导演')),
                ('record_time', models.DateTimeField(verbose_name='记录时间')),
            ],
            options={
                'verbose_name': '电影信息',
                'verbose_name_plural': '电影信息',
                'db_table': 'movie_collectmoviedb',
            },
        ),
        migrations.CreateModel(
            name='CollectMovieTypeDB',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movie_type', models.CharField(max_length=100, unique=True, verbose_name='电影类型')),
            ],
            options={
                'verbose_name': '电影类型',
                'verbose_name_plural': '电影类型',
                'db_table': 'movie_collectmovietypedb',
            },
        ),
        migrations.CreateModel(
            name='CollectTop250MovieDB',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movie_id', models.IntegerField(unique=True, verbose_name='电影ID')),
                ('movie_title', models.TextField(verbose_name='中文标题')),
                ('movie_original_title', models.TextField(verbose_name='原始标题')),
                ('movie_rating', models.TextField(verbose_name='评分')),
                ('movie_year', models.IntegerField(verbose_name='年份')),
                ('movie_pubdates', models.TextField(verbose_name='发布日期')),
                ('movie_directors', models.TextField(verbose_name='导演')),
                ('movie_genres', models.TextField(verbose_name='类型')),
                ('movie_actor', models.TextField(verbose_name='演员')),
                ('movie_durations', models.TextField(verbose_name='时长')),
                ('movie_collect_count', models.IntegerField(verbose_name='收藏数')),
                ('movie_mainland_pubdate', models.TextField(verbose_name='大陆发布日期')),
                ('movie_images', models.TextField(verbose_name='封面图片')),
                ('record_time', models.DateTimeField(verbose_name='记录时间')),
            ],
            options={
                'verbose_name': 'Top250电影',
                'verbose_name_plural': 'Top250电影',
                'db_table': 'movie_collecttop250moviedb',
            },
        ),
        migrations.CreateModel(
            name='MovieRatingDB',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.DecimalField(decimal_places=2, max_digits=4, verbose_name='评分')),
                ('movie_id', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='movies.collectmoviedb', to_field='movie_id', verbose_name='电影')),
            ],
            options={
                'verbose_name': '电影评分',
                'verbose_name_plural': '电影评分',
                'db_table': 'movie_movieratingdb',
            },
        ),
        migrations.CreateModel(
            name='MoviePubdateDB',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pubdate', models.DateField(null=True, verbose_name='发布日期')),
                ('movie_id', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='movies.collectmoviedb', to_field='movie_id', verbose_name='电影')),
            ],
            options={
                'verbose_name': '电影发布日期',
                'verbose_name_plural': '电影发布日期',
                'db_table': 'movie_moviepubdatedb',
            },
        ),
        migrations.CreateModel(
            name='MovieTagDB',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tag_type', models.CharField(max_length=100, verbose_name='标签类型')),
                ('tag_name', models.CharField(max_length=100, verbose_name='标签名')),
                ('movie_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='movies.collectmoviedb', to_field='movie_id', verbose_name='电影')),
            ],
            options={
                'verbose_name': '电影标签',
                'verbose_name_plural': '电影标签',
                'db_table': 'movie_movietagdb',
                'indexes': [models.Index(fields=['tag_type'], name='movie_movie_tag_typ_05b371_idx'), models.Index(fields=['tag_name'], name='movie_movie_tag_nam_aac407_idx')],
            },
        ),
    ]
