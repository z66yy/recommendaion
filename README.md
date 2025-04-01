# 电影推荐系统

基于Django开发的电影推荐系统，使用协同过滤和基于内容的推荐算法，为用户提供个性化电影推荐服务。

## 数据
https://pan.baidu.com/s/14xd6SYCHKnFZx9piJKsHsw?pwd=figf 提取码: figf

## 功能特点

- 电影搜索与浏览
- 电影详情展示
- 个性化电影推荐
- 基于用户喜好的电影分类
- 基于标签、类型、导演和演员的相似电影推荐
- 一键在线观看电影
- 支持多平台视频源解析

## 技术栈

- **后端**: Django 4.2.20
- **数据库**: MySQL 9.2.0
- **推荐算法**: Spark MLlib (ALS 协同过滤)
- **前端**: Bootstrap, jQuery, AJAX

## 系统要求

- Python 3.8+
- Windows 10/11 或 Linux
- MySQL 9.2.0
- 至少2GB内存

## 快速开始

### 方法一：使用启动脚本（推荐）

1. 克隆或下载本项目到本地
2. 运行环境设置脚本:
   ```
   python setup_env.py
   ```
3. 启动项目:
   ```
   python start_project.py
   ```
4. 在浏览器中访问: http://localhost:8000

> **注意**: 使用`start_project.py`启动的服务会在后台持续运行，即使关闭命令行窗口。要停止服务，请运行`python start_project.py --stop-services`

### 方法二：手动设置

1. 克隆或下载本项目到本地
2. 确保MySQL 9.2.0已安装并位于`mysql-9.2.0-winx64`目录下
3. 启动MySQL服务:
   ```
   cd mysql-9.2.0-winx64/bin
   mysqld --console
   ```
4. 安装Python依赖:
   ```
   pip install -r requirements.txt
   ```
5. 设置环境变量:
   ```
   # Windows
   set DB_HOST=localhost
   set DB_PORT=3306
   set DB_USER=root
   set DB_PASSWORD=123
   set DB_NAME=movierecommendation
   
   # Linux/Mac
   export DB_HOST=localhost
   export DB_PORT=3306
   export DB_USER=root
   export DB_PASSWORD=123
   export DB_NAME=movierecommendation
   ```
6. 运行Django开发服务器:
   ```
   python manage.py runserver
   ```
7. 在浏览器中访问: http://localhost:8000

## 项目启动脚本使用说明

`start_project.py`脚本提供了多种项目启动和管理选项：

### 常用命令

1. **标准启动**（服务在后台运行）
   ```
   python start_project.py
   ```
   启动MySQL和Django服务。即使关闭命令行窗口，服务仍会在后台继续运行。

2. **停止所有服务**
   ```
   python start_project.py --stop-services
   ```
   或简写形式:
   ```
   python start_project.py -s
   ```
   停止在后台运行的MySQL和Django服务。

3. **仅启动MySQL服务**
   ```
   python start_project.py --mysql-only
   ```
   或简写形式:
   ```
   python start_project.py -m
   ```
   只启动MySQL服务，不启动Django。

4. **自定义Django参数**
   ```
   python start_project.py --django-args "0.0.0.0:8080 --insecure"
   ```
   或简写形式:
   ```
   python start_project.py -d "0.0.0.0:8080 --insecure"
   ```
   使用自定义参数启动Django服务器。

## 项目迁移说明

本项目设计为可移植的，所有路径都使用相对路径，可以轻松在不同环境中部署。迁移步骤：

1. 将整个项目文件夹复制到目标机器
2. 确保MySQL目录结构保持不变（位于项目根目录的`mysql-9.2.0-winx64`文件夹中）
3. 运行`setup_env.py`脚本检查环境并创建必要的目录
4. 使用`start_project.py`启动项目

## 项目结构

```
movierecommends/
├── manage.py              # Django命令行工具
├── setup_env.py           # 环境设置脚本
├── start_project.py       # 项目启动脚本
├── README.md              # 本文档
├── requirements.txt       # Python依赖列表
├── .env                   # 环境变量配置
├── mvrecommend/           # Django主项目目录
├── movies/                # 电影应用目录
├── templates/             # HTML模板目录
├── static/                # 静态文件目录
├── media/                 # 媒体文件目录
│   └── movie_posters/     # 电影海报目录
├── logs/                  # 日志目录
└── mysql-9.2.0-winx64/    # MySQL目录
    ├── bin/               # MySQL二进制文件
    ├── data/              # MySQL数据目录
    │   └── movierecommendation/  # 电影数据库
    └── my.ini             # MySQL配置文件
```

## 推荐算法说明

系统使用多维度相似度计算进行电影推荐，权重分配如下：

1. **类型相似度** (权重: 0.4)
   - 通过比较两部电影的类型（genres）计算
   - 计算方法：共同类型数量 / 两部电影类型的最大数量

2. **导演相似度** (权重: 0.1)
   - 通过比较两部电影的导演（directors）
   - 计算方法：共同导演数量 / 两部电影导演的最大数量

3. **演员相似度** (权重: 0.1)
   - 通过比较两部电影的演员（actors）
   - 计算方法：共同演员数量 / 两部电影演员的最大数量

4. **标签相似度** (权重: 0.4)
   - 通过比较两部电影的标签（tags）
   - 计算方法：共同标签数量 / 两部电影标签的最大数量

此外，系统还使用Spark MLlib的ALS算法进行协同过滤推荐。

## 在线观看功能

系统支持以下视频平台的一键播放：

- 爱奇艺
- 腾讯视频
- 优酷
- 芒果TV
- 1905电影网

注意：一键播放功能可能并不支持所有电影，如遇到问题，可使用快捷搜索功能手动搜索。

## 疑难解答

**Q: MySQL无法启动怎么办？**
A: 检查端口是否被占用，确认数据目录权限正确，查看MySQL日志文件获取详细错误信息。

**Q: 电影海报无法显示怎么办？**
A: 检查media/movie_posters目录是否存在并有正确权限，可以运行check_missing_posters.py和direct_poster_download.py下载缺失海报。

**Q: 推荐结果不准确怎么办？**
A: 系统需要足够的用户交互数据来提高推荐准确性。使用系统的用户越多，推荐越准确。

**Q: 如何确认服务是否在后台运行？**
A: 检查MySQL服务端口（3306）和Django服务端口（8000）是否被占用。Windows上可使用`netstat -ano | findstr 3306`和`netstat -ano | findstr 8000`命令检查。

**Q: 关闭程序窗口后服务仍在运行，如何停止？**
A: 运行`python start_project.py --stop-services`可以停止所有正在运行的服务。

## 许可证

MIT

## 联系方式

如有任何问题或建议，请联系项目维护者。 
