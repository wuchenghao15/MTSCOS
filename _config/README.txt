[配置模板目录]
存放项目级配置模板和部署相关文件。
- requirements.txt : Python 依赖清单（pip install -r 用）
- Dockerfile / docker-compose.yml : Docker 部署
- Makefile : 构建命令
- nginx.conf : 生产反向代理配置
- tailwind.config.js / postcss.config.js : 前端样式构建
- pyrightconfig.json : Python 类型检查
- ViKey/ : VIKEY USB 加密狗驱动文件（.CAB/.Dll/.h/.js）
- security/ : SSL/TLS 证书模板（cert.pem / key_main.key / key_vikey.key）
