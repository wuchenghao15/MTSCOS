[Flask 应用 — 主启动点]
服务器主入口。启动命令：cd flask-app && python server_real_db.py
- server_real_db.py : Flask 主应用（8000+ 行 · 300+ 路由）
- engines/ : 55+ AI 引擎文件（核心）
- ai_engines/ : Neural Hub rules_engine 等
- static/ : 前端静态资源（CSS/JS/图片）
- templates/ : Jinja2 HTML 模板
- app/ : Blueprint（32 文件 · 新增 405 路由）
- Database/ : 主数据库（7.2GB）
- logs/ : 运行日志
- venv/ : Python 虚拟环境
详见 flask-app/README.txt
