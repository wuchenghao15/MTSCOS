# MTSCOS_AI_Project 长期记忆

## 冰山（仙女座）AI 聊天系统
- 界面路由 `/local-chat`，模板 `flask-app/templates/local_chat.html`，蓝图 `flask-app/blueprints/chat_local_bp.py`，端口 8888。
- **公网入口 `/ai`（mtos.site/ai）**：v25.5 起强制登录（未登录 302→/auth/login，已登录直接进聊天页+每日 token 赠送）；防盗链白名单中的"直达放行"仅指隧道可达，非免登录。
- **权限约定（用户 2026-10-14 确认）**：聊天系统面向所有已注册用户开放（登录即可用，guest 403），不是 SA 专属功能。SA 专属路径仅限：`/sa/`、`/api/hardware/`、`/api/server/vikey-status`、`/admin_app/arduino_ide`。
- 技术栈：本地 Ollama（qwen2.5:7b / qwen2.5-coder:14b）+ SSE 流式；无 Ollama 时降级为冰山三视角发散模板回复；含认知画像适配、拐点检测、脑库投喂。
- 服务运维：8888 由 sys_flask_server 守护进程自动拉起（进程死后自动重启并重载代码）；入口 `flask-app/modular_start.py`；启动环境变量见 `launch_mtscos_flask.sh`（OLLAMA_HOST=11435、MTSCOS_SERVER_PORT=8888、MTSCOS_BIND_HOST=::）。
- 公网链路：www.mtos.site → Cloudflare → cloudflared（tunnel=iceberg，~/.cloudflared/config.yml）→ 127.0.0.1:8888。

## 已知存量缺口（截至 2026-10-14，均非本次回归、git 历史中也不存在）
- `templates/register.html` 缺失：GET /auth/register 被 except 兜底 302 回首页，首页「立即注册」链路空转（POST /auth/register 接口本身正常）。
- `/andromeda/persona_chat` 404：模板 `andromeda_persona_chat.html` 与多个导航页存在，但从未注册过路由。
