---
name: "flask-smoke-tester"
description: "分层冒烟测试器: L1路由注册/L2页面HTTP/L3 API JSON/L4业务流程. Invoke when user asks to smoke test, 冒烟测试, verify pages/APIs, or check Flask health."
---

# Flask 分层冒烟测试器

## 触发条件
- 用户说"冒烟测试"、"测试所有页面"、"检查 Flask 健康"
- 完成开发后要验证功能是否正常
- Flask 重启后要确认路由注册完整性

## 四层设计

### L1 · 路由注册完整性（Flask test_client，不依赖 DB/网络）
```
✅ Flask app 创建 (has url_map)
✅ 路由总数 >= 100
✅ 关键 endpoint 存在 (login, auth.login 等)
✅ Blueprint 已注册 (检查 url_map 前缀)
✅ before_request 链长度正常 (8~20 个)
✅ view_functions 关键覆盖 (如果有路由冲突)
```

### L2 · 公开页面 HTTP 可达性（curl HTTP 状态码）
```
✅ /index → 200
✅ /iceberg → 302 → /andromeda/dashboard
✅ /andromeda → 302 → /andromeda/dashboard
✅ /andromeda/dashboard → 200
✅ /auth/login → 302 或 200 (登录页不应该 401!)
✅ 其他公开页面按需扩展
```

### L3 · API 端点 JSON 结构检查
```
✅ 每个 API 返回 status 200
✅ JSON 结构: success=True + 关键 data 字段
✅ 失败时记录: status=500 → 看 Flask log 定位
✅ Flask Blueprint 路径陷阱:
   Blueprint(url_prefix='/andromeda') + route('/api/xxx') → 实际 /andromeda/api/xxx
   不是 /api/andromeda/xxx ! 别写错路径！
```

### L4 · 登录完整流程（POST /auth/login + curl cookie jar）
```
✅ GET /index → 拿 CSRF cookie (curl -c jar)
✅ POST 假用户 → 401 + message 含"密码/不存在"
✅ POST SA 账号 → 401 + message 含"VIKEY/硬件/SZU100"
✅ POST 空用户名 → 400 + message 含"请输入"
✅ 不要用 Python urllib 读 Netscape cookie jar —— 格式不兼容
   统一用 curl -b jar -c jar 处理 cookie
```

## 关键工具链
```bash
# 1. 确认 Flask 活着
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/index

# 2. L3 API 快速 curl 测试
curl -s http://127.0.0.1:8888/andromeda/api/iceberg_structure | python3 -m json.tool | head -20

# 3. L4 完整流程 (curl cookie jar)
curl -s -c /tmp/c.txt http://127.0.0.1:8888/index -o /dev/null
CSRF=$(grep csrf_token /tmp/c.txt | awk '{print $NF}')
curl -s -o resp.json -w "%{http_code}\n" -b /tmp/c.txt -c /tmp/c.txt \
  -X POST http://127.0.0.1:8888/auth/login \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"username":"test","password":"xx"}'

# 4. Flask 日志定位问题
tail -50 /tmp/mtscos_8888.log | grep -iE "error|traceback|404|500"
```

## 常见坑（已踩过）

| 坑 | 症状 | 正确做法 |
|----|------|----------|
| 两个 `/auth/login` 路由 | POST 返回 E_AUTH_401 | 查 url_map 所有 `/auth/login` endpoint，authbp 的装饰器从 `login` 改 `guest` |
| Blueprint 路径写错 | 404 | `url_prefix=/andromeda` + `route=/api/xxx` = `/andromeda/api/xxx`，不是 `/api/andromeda/xxx` |
| CSRF cookie 读不到 | curl jar 里没 csrf_token | Flask 可能用 session 存 CSRF 或豁免了某些路径，看 `_mt_csrf_exempt_paths` |
| before_request 拦截顺序 | 钩子不生效 | 用 `app.before_request_funcs[None].insert(0, fn)` 插队到最前 |
| mt_users 缺 password 列 | 日志 `no such column: password` | 查所有 DB，`ALTER TABLE users ADD COLUMN password TEXT` |
| 临时文件不清理 | 污染项目 | 所有测试脚本和 cookie jar 放 `/tmp`，跑完 rm |

## 判定标准
```
通过率 >= 90% → 🟢 冒烟通过
通过率 70~90% → 🟡 有边缘问题 (API表未建/种子数据缺失)
通过率 < 70% → 🔴 核心故障 (路由冲突/装饰器死锁/Flask未启动)
```

## 输出格式
```
============================================================
🟢 L1  路由注册完整性          6/6 ✅
🟡 L2  公开页面 HTTP 可达性    5/5 ✅
🟠 L3  API 端点 JSON 结构      6/7 (stars 表未建)
🔴 L4  登录流程                3/4 (CSRF cookie 读取问题)
============================================================
📊 冒烟结果: ✅ 20 / ❌ 2 / 共 22 | 通过率 91%
============================================================
```
