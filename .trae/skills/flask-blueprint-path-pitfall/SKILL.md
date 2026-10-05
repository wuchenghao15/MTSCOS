---
name: "flask-blueprint-path-pitfall"
description: "Flask Blueprint url_prefix + route 路径陷阱速查. Invoke when writing Flask Blueprint routes, debugging 404s, or registering API endpoints with url_prefix."
---

# Flask Blueprint 路径陷阱速查

## 核心公式
```python
# Blueprint 注册
bp = Blueprint('andromeda', __name__, url_prefix='/andromeda')

# route 内部只写 /api/xxx — 不要重复 /andromeda
@bp.route('/api/iceberg_structure', methods=['GET'])  # ✅ 正确
# 实际 URL = /andromeda/api/iceberg_structure

@bp.route('/andromeda/api/iceberg_structure')  # ❌ 错误
# 实际 URL = /andromeda/andromeda/api/iceberg_structure → 404
```

## 已踩过的 4 次教训

| 次数 | 错误写法 | 实际 URL | 冒烟表现 |
|------|---------|---------|---------|
| 1 | `route('/api/iceberg_structure')` 冒烟脚本写 `/api/andromeda/iceberg_structure` | `/andromeda/api/iceberg_structure` | 冒烟脚本 5 个 API 全 404，改路径后全 200 |
| 2 | 登录路由 bp.route('/login') 冒烟脚本写 `/login` | `/auth/login` | Flask 先注册 auth bp → /auth/login 覆盖根级 → 装饰器死锁 |
| 3 | admin_routes 调 `server_real_db.student_portal_page()` | — | 函数不存在 → 500 |
| 4 | `/iceberg` + `/andromeda` 两个 redirect 路由没加防盗链白名单 | — | 302 → `/index?from=hotlink_blocked` |

## 发现路径冲突的快速方法
```bash
# 拿 Flask 启动后实际注册的所有路由
cd flask-app && python3 -c "
import sys; sys.path.insert(0,'.')
import server_real_db as srd
rules = sorted(srd.app.url_map.iter_rules(), key=lambda r: r.rule)
for r in rules:
    if 'andromeda' in r.rule or 'auth' in r.rule:
        print(f'  {r.rule:50} → {r.endpoint}')
"
# 检查两个关键:
# 1. url_map 里同一个 rule 是否有多个 endpoint (可能冲突)
# 2. 冒烟脚本用的 URL 是否和实际注册的一致
```

## 冒烟脚本路径模板
```python
# 写冒烟脚本前, 先跑上面的 url_map 导出, 再填入正确路径
BLUEPRINT_APIS = [
    # Blueprint(url_prefix='/andromeda') + route('/api/xxx') → 实际 /andromeda/api/xxx
    ("/andromeda/api/iceberg_structure", "冰山结构"),
    ("/andromeda/api/evolution_timeline", "演化时间线"),
    # 直接注册在 app 上的路由 (无 prefix)
    ("/api/andromeda/stars", "仙女座恒星"),
]
```

## 预防铁律
1. **写 route 时只写 suffix** — Blueprint 有 url_prefix，route 内部不要再写一遍
2. **冒烟脚本路径从 url_map 来** — 不要"猜"路径，先看 Flask 实际注册了什么
3. **redirect 路由也要加防盗链白名单** — `/iceberg` `/andromeda` 这些路径不能被 hotlink 拦截
4. **写新蓝图注册后立刻查 url_map** — 914 个路由里有没有重复的 rule + endpoint 对
