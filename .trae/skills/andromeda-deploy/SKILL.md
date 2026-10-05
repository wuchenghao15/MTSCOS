---
name: "andromeda-deploy"
description: "MTSCOS AI 仙女座 daemon 修复 + 双机部署 + 三重保活。Invoke when user asks to fix daemon, deploy to Mac mini, sync DB, or set up keepalive."
---

# 🪐 Andromeda Deploy — 仙女座双机部署与自愈

MTSCOS AI 项目的仙女座（smart_mount daemon）完整修复、远程部署、数据库同步、三重保活一站式流程。

## 触发条件

- daemon 全停 / daemon 心跳无更新
- Mac mini 或其他节点需要部署仙女座
- 两端 DB 需要完全同步
- 需要搭建三重保活（launchd + keepalive.sh + 内置心跳）
- "仙女座修复"、"Mac mini 部署"、"双机同步"、"保活"

## 已知根因库（按概率排序）

| # | 根因 | 现象 | 修复 |
|---|------|------|------|
| 1 | **daemon 模板局部 import 污染函数作用域** | `UnboundLocalError: os` at main_loop 第一行 | 模板顶部全局 import + 清除 work_body 里的所有 `import` 行 |
| 2 | macOS AirPlay 占 5000 端口 | `smart_mount start` 后 daemon 秒挂 | 全局替换 `:5000` → `:8888`（项目设计端口） |
| 3 | APP_DB 指向损坏的 `Database/app.db` (10G) | `database disk image is malformed` | 优先 `engines/app.db`（768M 活跃库） |
| 4 | Mac mini 缺 smart_mount 相关表 | `mt_ai_smart_mount_processes NOT NULL constraint` | 手动 CREATE TABLE（rsync 过来的空表 IF NOT EXISTS 不重建） |
| 5 | Python 3.14 pyc rsync 到 Python 3.9 节点 | 语法错误或 silent crash | 清所有 `__pycache__` 目录（跨 Python 大版本不兼容） |
| 6 | work_body 硬编码过期 DB 路径 | daemon 启动但读错库 | 统一替换为模板变量 `APP_DB` |

## 部署流程（6 步）

### Step 1: 诊断 — 先搞清楚现状

```bash
# 本机端口
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/

# daemon 进程
pgrep -fl "auto_daemons/sys_" | wc -l

# 心跳表（mt_daemon_registry 是旧版，mt_ai_smart_mount_processes 是新版）
python3 -c "
import sqlite3; c=sqlite3.connect('engines/app.db')
for r in c.execute(\"SELECT daemon_name, last_heartbeat FROM mt_daemon_registry ORDER BY last_heartbeat DESC LIMIT 5\"):
    print(r)
"

# Mac mini 现状
ssh andromeda 'python3 ai_smart_mount_engine.py status 2>&1 | head -12'
```

### Step 2: 修复本机 smart_mount_engine 模板

**文件**: `flask-app/engines/ai_smart_mount_engine.py`

```python
# 模板顶部 import 行（~L1062）— 必须全局导入，不能在 main_loop 里局部 import
import os, sys, time, signal, sqlite3, json, glob, subprocess, random as _rand, tempfile as _tf2

# APP_DB 路径（~L1017-1023）— 优先 engines/app.db
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINES_DIR = os.path.join(_PROJECT_ROOT, "flask-app", "engines")
AI_ENGINES_DIR = os.path.join(_PROJECT_ROOT, "flask-app", "ai_engines")
APP_DB = os.path.join(ENGINES_DIR, "app.db")
if not os.path.exists(APP_DB):
    APP_DB = os.path.join(AI_ENGINES_DIR, "app.db")
```

**work_body 批量清洗**: 29 个 SYSTEM_REQUIRED_DAEMONS 的 work_body 里的所有 `import xxx` 行 + `DB = os.environ.get(...)` 行必须删除。

### Step 3: 启动本机守护进程

```bash
cd flask-app/engines
python3 ai_smart_mount_engine.py start    # 后台守护模式
# 验证
python3 ai_smart_mount_engine.py status   # Daemon State: RUNNING
tail -5 ../_runtime/logs/sys_heartbeat_writer.log  # 应看到连续 [heartbeat] written
```

### Step 4: rsync 到远程节点（Mac mini）

```bash
# 代码
rsync -avz --delete \
  flask-app/engines/ \
  andromeda:/Users/wuchenghao/mtscos/flask-app/engines/

# DB（先 WAL checkpoint）
python3 -c "import sqlite3; c=sqlite3.connect('engines/app.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)')"
rsync -avz engines/app.db* andromeda:/Users/wuchenghao/mtscos/flask-app/engines/
```

### Step 5: 远程建表 + 启动

```bash
ssh andromeda '
# 清 3.14 pyc（Mac mini 是 Python 3.9）
find /Users/wuchenghao/mtscos -name "__pycache__" -type d -exec rm -rf {} +

# 建 smart_mount 表（rsync 空表不会触发 IF NOT EXISTS）
cd /Users/wuchenghao/mtscos/flask-app && python3 -c "
import sqlite3
c = sqlite3.connect(\"engines/app.db\", timeout=10)
c.execute(\"CREATE TABLE IF NOT EXISTS mt_ai_smart_mount_processes (...)\")
c.execute(\"CREATE TABLE IF NOT EXISTS mt_ai_mount_decisions (...)\")
c.commit()
"

# 启动守护
cd engines && python3 ai_smart_mount_engine.py start
python3 ai_smart_mount_engine.py status 2>&1 | head -12
'
```

### Step 6: 三重保活（Mac mini 端）

**keepalive.sh** — 每分钟巡检关键 daemon：

```bash
#!/bin/bash
# 放到 ~/mtscos/keepalive.sh，chmod +x
DAEMONS=(sys_heartbeat_writer sys_patrol_inspector sys_eigenflux_network
         sys_auto_repair sys_local_inference sys_rule_enforcer
         sys_auto_patrol sys_auto_hire sys_deep_inspection)
for name in "${DAEMONS[@]}"; do
    pid=$(pgrep -f "_runtime/auto_daemons/${name}\.py" | head -1)
    [ -z "$pid" ] && python3 "$HOME/mtscos/_runtime/auto_daemons/${name}.py" &
done
```

**launchd plist** — `~/Library/LaunchAgents/com.mtscos.andromeda.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>com.mtscos.andromeda</string>
    <key>ProgramArguments</key><array><string>/bin/bash</string><string>/Users/wuchenghao/mtscos/keepalive.sh</string></array>
    <key>RunAtLoad</key><true/>
    <key>StartInterval</key><integer>60</integer>
    <key>KeepAlive</key><true/>
</dict></plist>
```

**crontab** 兜底（macOS 新版可能受限）：
```
* * * * * /bin/bash /Users/wuchenghao/mtscos/keepalive.sh
```

## 双向同步链路

```
本机 engines/ ──rsync──→ Mac mini engines/    (增量代码)
本机 engines/app.db ──WAL checkpoint+rsync──→ Mac mini engines/app.db  (完全同步)
Mac mini _runtime/logs/ ──rsync──→ 本机 /tmp/mtscos_sync/logs/macmini/  (状态回传)
```

## Mac mini 连接信息

```
Host: andromeda (SSH config ~/.ssh/config)
IP:   192.168.31.9
User: wuchenghao
Project: /Users/wuchenghao/mtscos/
Flask: 8888
Python: 3.9.6
```

## 本机信息

```
Project: ~/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/
Flask: 8888 (macOS AirPlay 占 5000, 不可用)
Python: 3.14
DB: flask-app/engines/app.db (768M, WAL mode)
Rule: 00-规则总索引.md — 端口契约统一 8888
```

## 成功标志

| 检查项 | 命令 | 预期 |
|--------|------|------|
| 本机守护 | `status \| head -8` | `Daemon State: RUNNING` |
| Mac mini 守护 | SSH status | 同上 |
| 心跳 | `tail -5 heartbeat_writer.log` | 连续 `[heartbeat] written` |
| Flask | `curl -s -o /dev/null -w "%{http_code}"` | HTTP 200/302 |
| DB 一致 | `ls -lh engines/app.db` 两端对比 | 大小相同 |
| launchd | `launchctl list \| grep mtscos` | `com.mtscos.andromeda` 在线 |
