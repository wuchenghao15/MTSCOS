# MTSCOS AI 部署指南

> 版本: v16.0.0
> 更新日期: 2026-07-22

---

## 📋 目录

- [1. 环境要求](#1-环境要求)
- [2. 原生部署（推荐）](#2-原生部署推荐)
  - [2.1 安装步骤](#21-安装步骤)
  - [2.2 配置说明](#22-配置说明)
  - [2.3 启动服务](#23-启动服务)
  - [2.4 服务管理](#24-服务管理)
- [3. Docker部署](#3-docker部署)
  - [3.1 完整部署（含Redis）](#31-完整部署含redis)
  - [3.2 快速部署（仅应用）](#32-快速部署仅应用)
  - [3.3 Docker Compose配置说明](#33-docker-compose配置说明)
- [4. 环境变量配置](#4-环境变量配置)
- [5. 数据库配置](#5-数据库配置)
- [6. 安全配置](#6-安全配置)
- [7. 性能优化](#7-性能优化)
- [8. 故障排查](#8-故障排查)
- [9. 部署对比](#9-部署对比)

---

## 1. 环境要求

| 组件 | 最低版本 | 推荐版本 | 说明 |
|------|---------|---------|------|
| Python | 3.9 | 3.10+ | 核心运行环境 |
| SQLite | 3.30 | 3.35+ | 默认数据库 |
| Redis | 7.0 | 7.2+ | 缓存服务（可选） |
| Git | 2.20 | 2.30+ | 版本控制 |
| pip | 20.0 | 23.0+ | 包管理器 |
| Docker | 20.10 | 24.0+ | 容器化部署 |
| Docker Compose | 2.0 | 2.20+ | 容器编排 |

---

## 2. 原生部署（推荐）

原生部署提供最佳性能和灵活性，适用于生产环境和开发环境。

### 2.1 安装步骤

#### 步骤1: 克隆仓库

```bash
git clone https://github.com/wuchenghao15/MTSCOS-AI-Project.git
cd MTSCOS-AI-Project
```

#### 步骤2: 创建虚拟环境

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
# macOS/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

#### 步骤3: 安装依赖

```bash
# 安装基础依赖
pip install -r requirements.txt

# 如果需要开发依赖
pip install -r requirements-dev.txt
```

#### 步骤4: 配置环境变量

```bash
# 创建.env文件
cp .env.example .env

# 编辑.env文件配置必要参数
vim .env
```

#### 步骤5: 初始化数据库

```bash
# 初始化所有数据库
python app.py --init

# 或者通过API初始化
curl -X POST http://localhost:8888/api/system/init
```

### 2.2 配置说明

#### 配置文件结构

```
MTSCOS-AI-Project/
├── .env                # 环境变量配置
├── config/             # 配置目录
│   ├── app.py          # 应用配置
│   ├── database.py     # 数据库配置
│   ├── security.py     # 安全配置
│   └── ai.py           # AI引擎配置
└── data/               # 数据目录（自动创建）
```

#### 主要配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| FLASK_ENV | 运行环境 | production |
| LOG_LEVEL | 日志级别 | INFO |
| DATABASE_URI | 数据库连接 | sqlite:///app.db |
| REDIS_HOST | Redis地址 | localhost |
| REDIS_PORT | Redis端口 | 6379 |
| SELF_LEARNING_ENABLED | AI自学习 | 1 |
| GIT_AUTO_SYNC_ENABLED | Git自动同步 | 1 |
| AUTO_BACKUP_ENABLED | 自动备份 | 1 |

### 2.3 启动服务

#### 开发模式

```bash
python app.py --debug --port 8888
```

#### 生产模式

```bash
# 使用gunicorn（推荐）
gunicorn -w 4 -b 0.0.0.0:8888 app:app

# 或者直接运行
python app.py --port 8888
```

#### 启动参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --port | 服务端口 | 8888 |
| --host | 绑定地址 | 0.0.0.0 |
| --debug | 调试模式 | False |
| --ssl | 启用SSL | False |
| --ssl-port | SSL端口 | 8443 |
| --init | 初始化数据库 | False |
| --migrate | 数据库迁移 | False |

### 2.4 服务管理

#### 使用systemd管理服务（Linux）

```bash
# 创建服务文件
sudo vim /etc/systemd/system/mtscos.service
```

服务文件内容：

```ini
[Unit]
Description=MTSCOS AI Service
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/MTSCOS-AI-Project
Environment="PATH=/var/www/MTSCOS-AI-Project/venv/bin"
ExecStart=/var/www/MTSCOS-AI-Project/venv/bin/python app.py --port 8888
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# 启动服务
sudo systemctl daemon-reload
sudo systemctl start mtscos
sudo systemctl enable mtscos

# 查看状态
sudo systemctl status mtscos

# 查看日志
sudo journalctl -u mtscos -f
```

---

## 3. Docker部署

### 3.1 完整部署（含Redis）

适用于生产环境，包含完整的依赖服务。

```bash
# 克隆仓库
git clone https://github.com/wuchenghao15/MTSCOS-AI-Project.git
cd MTSCOS-AI-Project

# 构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 更新服务
git pull
docker-compose up -d --build
```

### 3.2 快速部署（仅应用）

适用于开发和测试环境，无需Redis依赖。

```bash
# 快速启动
docker-compose -f docker-compose.quick.yml up -d

# 查看日志
docker-compose -f docker-compose.quick.yml logs -f

# 停止服务
docker-compose -f docker-compose.quick.yml down
```

### 3.3 Docker Compose配置说明

#### docker-compose.yml（完整部署）

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8888:8888"
    environment:
      - FLASK_ENV=production
      - LOG_LEVEL=INFO
      - DATABASE_URI=sqlite:///app.db
      - SELF_LEARNING_ENABLED=1
      - GIT_AUTO_SYNC_ENABLED=1
      - AUTO_BACKUP_ENABLED=1
    volumes:
      - .:/app
      - mtscos_data:/app/data
      - mtscos_logs:/app/logs
    depends_on:
      - redis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8888/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  mtscos_data:
  mtscos_logs:
  redis_data:
```

#### docker-compose.quick.yml（快速部署）

```yaml
version: '3.8'

services:
  web:
    image: python:3.9-slim
    ports:
      - "8888:8888"
    environment:
      - FLASK_ENV=production
      - LOG_LEVEL=INFO
      - DATABASE_URI=sqlite:///app.db
      - SELF_LEARNING_ENABLED=0
      - GIT_AUTO_SYNC_ENABLED=0
      - AUTO_BACKUP_ENABLED=0
    volumes:
      - .:/app
    working_dir: /app
    command: >
      bash -c "pip install --no-cache-dir -r requirements.txt && python app.py"
    restart: unless-stopped

volumes:
  mtscos_data:
```

---

## 4. 环境变量配置

### 基础配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| FLASK_ENV | 运行环境（development/production/test） | production |
| LOG_LEVEL | 日志级别（DEBUG/INFO/WARNING/ERROR） | INFO |
| SECRET_KEY | 加密密钥 | 自动生成 |
| PORT | 服务端口 | 8888 |
| HOST | 绑定地址 | 0.0.0.0 |

### 数据库配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| DATABASE_URI | SQLite数据库路径 | sqlite:///app.db |
| REDIS_HOST | Redis服务器地址 | localhost |
| REDIS_PORT | Redis端口 | 6379 |
| REDIS_PASSWORD | Redis密码 | 空 |
| REDIS_DB | Redis数据库编号 | 0 |

### AI引擎配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| OPENAI_API_KEY | OpenAI API密钥 | 空 |
| ANTHROPIC_API_KEY | Anthropic API密钥 | 空 |
| GOOGLE_API_KEY | Google API密钥 | 空 |
| SELF_LEARNING_ENABLED | 启用AI自学习 | 1 |
| AI_CLUSTER_ENABLED | 启用AI集群 | 1 |

### 功能开关

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| GIT_AUTO_SYNC_ENABLED | Git自动同步 | 1 |
| AUTO_BACKUP_ENABLED | 自动备份 | 1 |
| ENHANCEMENT_ENABLED | 增强管理器 | 1 |
| SECURITY_FIREWALL_ENABLED | 安全防火墙 | 1 |

### 安全配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| API_RATE_LIMIT | API限流（每秒请求数） | 100 |
| SESSION_TIMEOUT | 会话超时时间（秒） | 3600 |
| MAX_UPLOAD_SIZE | 最大上传大小（MB） | 50 |

---

## 5. 数据库配置

### SQLite配置（默认）

系统默认使用SQLite数据库，无需额外配置。数据库文件存储在`data/`目录下。

```python
# config/database.py
SQLALCHEMY_DATABASE_URI = 'sqlite:///data/app.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False
```

### 使用其他数据库

系统支持MySQL和PostgreSQL，但需要额外安装驱动。

#### MySQL配置

```bash
# 安装MySQL驱动
pip install mysql-connector-python
```

```python
# config/database.py
SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://user:password@host:port/database'
```

#### PostgreSQL配置

```bash
# 安装PostgreSQL驱动
pip install psycopg2-binary
```

```python
# config/database.py
SQLALCHEMY_DATABASE_URI = 'postgresql://user:password@host:port/database'
```

### 数据库初始化

```bash
# 初始化所有数据库
python app.py --init

# 迁移数据库
python app.py --migrate

# 重置数据库（危险操作）
python app.py --reset
```

---

## 6. 安全配置

### SSL/TLS配置

```bash
# 生成SSL证书（自签名）
openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365

# 启用SSL启动
python app.py --ssl --ssl-port 8443
```

### 防火墙规则

系统内置企业级防火墙，支持以下规则：

| 规则 | 说明 |
|------|------|
| SQL注入防护 | 检测并拦截SQL注入攻击 |
| XSS防护 | 检测并拦截跨站脚本攻击 |
| 命令注入防护 | 检测并拦截命令注入 |
| SSRF防护 | 检测并拦截服务端请求伪造 |
| 文件包含防护 | 检测并拦截文件包含攻击 |
| 路径遍历防护 | 检测并拦截路径遍历攻击 |
| 敏感文件防护 | 禁止访问敏感文件 |
| 暴力破解防护 | 检测并阻止暴力破解尝试 |
| 扫描器防护 | 检测并阻止自动化扫描 |
| API限流 | 限制API请求频率 |

### API密钥管理

```bash
# 生成新的API密钥
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 7. 性能优化

### 缓存配置

```python
# config/app.py
CACHE_TYPE = 'RedisCache'
CACHE_REDIS_URL = 'redis://localhost:6379/0'
CACHE_DEFAULT_TIMEOUT = 300
```

### 并发配置

```bash
# 使用gunicorn配置并发
gunicorn -w 4 -b 0.0.0.0:8888 --timeout 120 app:app

# 参数说明：
# -w: worker进程数（推荐为CPU核心数*2+1）
# --timeout: 请求超时时间
# --keep-alive: 长连接时间
```

### 数据库优化

```bash
# 优化SQLite数据库
sqlite3 data/app.db "VACUUM;"
sqlite3 data/app.db "ANALYZE;"
```

---

## 8. 故障排查

### 常见问题

#### 问题1: 端口被占用

```bash
# 查看端口占用
lsof -i :8888

# 杀死占用进程
kill -9 <PID>
```

#### 问题2: 依赖安装失败

```bash
# 更新pip
pip install --upgrade pip

# 清理缓存
pip cache purge

# 重新安装
pip install -r requirements.txt
```

#### 问题3: 数据库连接失败

```bash
# 检查数据库文件权限
ls -la data/

# 确保目录可写
chmod -R 755 data/
```

#### 问题4: Docker构建失败

```bash
# 清理缓存
docker-compose build --no-cache

# 查看详细日志
docker-compose up --build
```

#### 问题5: Git同步失败

```bash
# 检查Git配置
git config --list

# 检查远程仓库
git remote -v

# 测试连接
ssh -T git@github.com
```

### 日志查看

```bash
# 查看应用日志
tail -f logs/app.log

# 查看错误日志
tail -f logs/error.log

# 查看系统日志（Docker）
docker-compose logs -f

# 查看系统日志（systemd）
sudo journalctl -u mtscos -f
```

---

## 9. 部署对比

| 特性 | 原生部署 | Docker完整部署 | Docker快速部署 |
|------|---------|---------------|---------------|
| 性能 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 部署速度 | 中等 | 较慢 | 较快 |
| 环境一致性 | 依赖环境 | 完全一致 | 完全一致 |
| Redis支持 | ✅ | ✅ | ❌ |
| AI自学习 | ✅ | ✅ | ❌ |
| Git自动同步 | ✅ | ✅ | ❌ |
| 自动备份 | ✅ | ✅ | ❌ |
| 适合场景 | 生产/开发 | 生产环境 | 开发/测试 |
| 维护难度 | 较高 | 中等 | 较低 |

### 推荐部署方案

| 场景 | 推荐方案 |
|------|---------|
| 生产环境 | 原生部署 + systemd管理 |
| 开发环境 | 原生部署（调试模式） |
| 测试环境 | Docker快速部署 |
| 演示环境 | Docker完整部署 |
| CI/CD | Docker完整部署 |

---

**部署完成后，请访问 http://localhost:8888/ 查看系统状态。**
