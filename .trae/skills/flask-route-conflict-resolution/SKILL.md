---
name: "flask-route-conflict-resolution"
description: "Flask 双路由冲突的诊断+解决模板 (authbp vs server_real_db.login). Invoke when two Flask routes handle the same URL, view_functions override, or before_request deadlock."
---

# Flask 双路由冲突解决模板

## 典型症状
```
同一 URL 被两个不同 route 函数处理：
  Flask 先注册 auth_bp.route('/login') → endpoint=auth.login
  后注册 app.route('/auth/login') → endpoint=login
  但 Flask url_map 里只会留一个 — 取决于注册顺序和规则表合并
```

## 本次仙女座修复的双保险模式

```python
# =================================================================
# 1️⃣ 根治: authbp 装饰器从 login 级改成 guest 级
#    routes/auth_routes.py
# =================================================================
@auth_bp.route('/login', methods=['GET', 'POST'])
@system_container(require_auth='guest')  # ← 原来是 'login' → 死锁!
def login():
    ...

# =================================================================
# 2️⃣ 双保险: view_functions 强制覆盖
#    server_real_db.py 末尾 (所有蓝图+路由注册完之后)
# =================================================================
try:
    _auth_login_fn = app.view_functions.get('auth.login')
    _our_login_fn = app.view_functions.get('login')
    if _auth_login_fn and _our_login_fn and _auth_login_fn != _our_login_fn:
        app.view_functions['auth.login'] = _our_login_fn
except Exception as _e:
    print(f"[FINAL 覆盖] ERROR: {_e}")

# =================================================================
# 3️⃣ before_request 终极拦截 (慎用 — 会跳过 CSRF!)
#    本次已删除, 保留作为应急方案
# =================================================================
# def _emergency_login_bypass():
#     if request.path == '/auth/login':
#         return login()
# app.before_request_funcs[None].insert(0, _emergency_login_bypass)
```

## 诊断清单

| 步骤 | 命令 | 看什么 |
|------|------|--------|
| 1 | 看 Flask 注册的 endpoint | `app.view_functions.keys()` 有没有 `auth.login` 和 `login` 两个 |
| 2 | 看 url_map | 同一个 `/auth/login` rule 对应几个 endpoint |
| 3 | 看 before_request 链 | `app.before_request_funcs[None]` 长度是否正常 (8-20) |
| 4 | 看 Flask log | 有没有 `[FINAL 覆盖]` 或 `before_request` 相关警告 |

## 三种解决方案对比

| 方案 | 侵入性 | 风险 | 适用 |
|------|--------|------|------|
| 根治 (改装饰器) | 低 | 无 | **首选** |
| view_functions 覆盖 | 中 | 需在所有注册之后 | 双保险 |
| before_request 拦截 | 高 | 跳过 CSRF / 防盗链 | 应急 |

## 预防铁律
1. **登录页必须是 guest 级** — `@system_container(require_auth='guest')`，不能是 `'login'`
2. **覆盖代码放文件末尾** — 在所有 Blueprint + route 注册完之后才能覆盖
3. **不要用 before_request 跳过中间件** — 会导致 CSRF、防盗链、VIKEY 检测全被绕过
4. **每次改完登录路由后重启 Flask** — `find . -name __pycache__ -exec rm -rf {} +` + kill 旧进程
