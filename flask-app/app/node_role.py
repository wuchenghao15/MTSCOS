#!/usr/bin/env python3
"""
三环境职责分离管控
================

三种角色 (NODE_ROLE 环境变量):
  DEV      — 开发机 (MacBook Pro)
             全量加载: 所有 blueprint + render_template + engines + static
             开发人员可以开任何环境任意部署
             
  SERVER   — 服务器 (Mac mini SLAVE)
             只加载:   纯 JSON API blueprint + engines daemon
             排除:     render_template blueprint + static 文件服务
             效果:     服务器只有后端接口, 看不到前端
             
  CLIENT   — 客户机 (iPhone / 浏览器 / Apple Vision)
             只加载:   static 文件服务 + 极简健康检查 + passport 蓝牙
             排除:     engines daemon + 后端 blueprint (API 由远端 SERVER 提供)
             效果:     客户机只用前端, 看不到后端代码/DB

用法:
  import os
  from app.node_role import NODE_ROLE, is_server, is_client, is_dev, ALLOW_TEMPLATE, ALLOW_ENGINES
  
  # blueprint 注册条件
  if ALLOW_TEMPLATE:
      app.register_blueprint(dev_dashboard_bp)  # render_template, 只 DEV
  
  # engines daemon 启动条件
  if ALLOW_ENGINES:
      start_smart_mount()  # 只 SERVER/DEV

环境变量设置:
  export NODE_ROLE=server   # Mac mini
  export NODE_ROLE=client   # iPhone / 浏览器代理
  export NODE_ROLE=dev      # MacBook Pro (默认)
"""
import os
from pathlib import Path

# ── 三角色定义 ──────────────────────────────────────────────────
_NODE_ROLES = {"DEV", "SERVER", "CLIENT"}

_RAW = os.environ.get("NODE_ROLE", os.environ.get("MTSCOS_NODE_ROLE", "dev"))
NODE_ROLE = _RAW.strip().upper()
if NODE_ROLE not in _NODE_ROLES:
    print(f"[NODE_ROLE] ⚠️ 未知值 '{_RAW}', fallback to DEV")
    NODE_ROLE = "DEV"

# ── 三角色判定 (统一入口) ────────────────────────────────────────
is_dev      = NODE_ROLE == "DEV"
is_server   = NODE_ROLE == "SERVER"
is_client   = NODE_ROLE == "CLIENT"

# ── 能力矩阵 (谁能做什么) ─────────────────────────────────────────
#                    DEV   SERVER   CLIENT
ALLOW_TEMPLATE      = is_dev                    # render_template / 前端页面
ALLOW_STATIC        = is_dev or is_client       # static 静态文件 (SERVER 纯 API 不需要)
ALLOW_ENGINES       = is_dev or is_server       # ai_engines / smart_mount / eigenflux daemon
ALLOW_DEV_PANEL     = is_dev                    # dev_dashboard / debug 路由
ALLOW_SYNC          = is_dev or is_server       # handshake 双向同步
ALLOW_LOCAL_AI      = is_dev or is_server       # 本地推理引擎
ALLOW_ADMIN         = is_dev or is_server       # admin 管理接口
ALLOW_PASSPORT      = True                      # BLE/蓝牙 passport (全角色)
ALLOW_I18N          = True                      # t() 国际化 (全角色)
ALLOW_DB_WRITE      = is_dev or is_server       # 数据库写 (CLIENT 只读或写远端)
ALLOW_HEALTH_CHECK  = True                      # /api/health (全角色)

# ── SERVER 模式需要排除的 render_template blueprint ────────────────
# 这 2 个在 Flask app 工厂里需要条件注册
EXCLUDED_BLUEPRINTS_SERVER = [
    "dev_dashboard",   # dev_dashboard_api.py — 开发面板
    "history",         # history_api.py       — 历史画廊 (render_template)
]

# ── 环境元信息 (给前端/health API 读取) ────────────────────────────
NODE_INFO = {
    "node_role": NODE_ROLE,
    "node_name": os.environ.get("NODE_NAME", "MTSCOS-Node"),
    "node_host": os.environ.get("NODE_HOST", "127.0.0.1"),
    "node_port": int(os.environ.get("NODE_PORT", "8888")),
    "allow_template": ALLOW_TEMPLATE,
    "allow_engines": ALLOW_ENGINES,
    "allow_sync": ALLOW_SYNC,
    "allow_local_ai": ALLOW_LOCAL_AI,
    "is_dev": is_dev,
    "is_server": is_server,
    "is_client": is_client,
}


# ── 启动时打印 (方便在日志里确认) ────────────────────────────────
def _startup_banner():
    role_cn = {"DEV": "开发机", "SERVER": "服务器", "CLIENT": "客户机"}[NODE_ROLE]
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║  MTSCOS AI · 三环境职责分离                                 ║
║  NODE_ROLE = {NODE_ROLE} ({role_cn})
╠═══════════════════════════════════════════════════════════╣
║  ✅ 纯 JSON API:       38 blueprint  (全角色)
║  {'✅' if ALLOW_TEMPLATE else '🚫'} 前端模板渲染:   2 blueprint    (DEV only)
║  {'✅' if ALLOW_ENGINES else '🚫'} AI engines daemon:   15 个          (DEV/SERVER)
║  {'✅' if ALLOW_SYNC else '🚫'} 双向握手同步:       Mac mini SSH    (DEV/SERVER)
║  {'✅' if ALLOW_LOCAL_AI else '🚫'} 本地推理零 token:        qwen2.5          (DEV/SERVER)
║  {'✅' if ALLOW_STATIC else '🚫'} static 静态文件:    21MB           (DEV/CLIENT)
║  ✅ BLE Passport:      TRAECARD UUID  (全角色)
╚═══════════════════════════════════════════════════════════╝
""")

_startup_banner()
