---
name: "flask-sqlite-column-compat"
description: "多 SQLite DB 列名不兼容的分层 SELECT 模板 (password vs password_hash). Invoke when Flask logs 'no such column', multi-db deployments, or table schema drift between environments."
---

# SQLite 多 DB 列名兼容模板

## 仙女座已踩的坑
```
Flask 启动警告: [认证] 加载用户失败: no such column: password

根因: 两套 DB schema
  Database/auth.db → users.password ✅ (SA 主库, authbp 用)
  database/app.db  → users.password_hash ❌ (仙女座用, 缺 password 列!)
```

## 分层 SELECT 兼容方案

```python
# server_real_db.py _find_user_and_verify_password()
# 核心思路: 尝试 N 种列组合, 找到能跑的那条
col_candidates = [
    # 方案 A: password 直接列 (auth.db)
    ("id, username, email, password, role, is_active",
     ["id", "username", "email", "password", "role", "is_active"]),
    
    # 方案 B: password_hash 列 AS password (app.db)
    ("id, username, email, password_hash as password, role, enabled as is_active",
     ["id", "username", "email", "password", "role", "is_active"]),
    
    # 方案 C: 通配 (兜底)
    ("*", None),
]

for cols, expected_keys in col_candidates:
    try:
        row = c.execute(
            f"SELECT {cols} FROM users WHERE username=?", (uname,)
        ).fetchone()
        if row and expected_keys:
            return dict(zip(expected_keys, row)), user_db, False
        elif row:  # 通配 "*" 结果
            return dict(row), user_db, False
    except sqlite3.OperationalError:
        continue  # 换下一套列组合
```

## admin 用户数据错位修复

```sql
-- database/app.db users 表 admin 行原始错误数据:
-- id=1, user_id=admin, username=admin, role=admin@mtscos.com, enabled=admin
--                                          ↑ 角色填成了 email!   ↑ 启用填成了字符串!

-- 修复 (SQLite):
UPDATE users 
SET role='admin', enabled=1,
    password_hash=?, password=?, user_id=username
WHERE username='admin';
```

## Flask 启动警告清单（已消除的）

| 警告 | 根因 | 修复 |
|------|------|------|
| `no such column: password` | col_candidates 缺 password_hash 兼容 | 加 `password_hash AS password` 方案 |
| `no such column: is_active` | app.db 用 enabled 代替 is_active | 加 `enabled AS is_active` |
| `no such column: rule_code` | system_rules 表缺此列 | 待修 (非本次范围) |
| `no such column: error_message` | AutoRepair 引擎扫描字段不存在 | 待修 |

## 多 DB 环境的 schema 对齐策略

```bash
# 1. 列出所有 DB 里的 users 表结构
python3 -c "
import sqlite3, os
for db in ['database/app.db', '../Database/auth.db']:
    if not os.path.exists(db): continue
    c = sqlite3.connect(db)
    cols = c.execute('PRAGMA table_info(users)').fetchall()
    print(f'{db}:')
    for col in cols:
        print(f'  {col[1]:25} {col[2]:10} NOT NULL={col[3]}')
    c.close()
"

# 2. 补齐缺失列 (SQLite ALTER TABLE)
ALTER TABLE users ADD COLUMN password TEXT DEFAULT NULL;
ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1;

# 3. 数据修复
UPDATE users SET role='admin', enabled=1 WHERE username='admin';
UPDATE users SET password_hash=?, password=? WHERE username='admin';
```

## 预防铁律
1. **新 DB 首次启动就补齐列** — `if 'password' not in cols: ALTER TABLE ADD`
2. **col_candidates 至少两种方案** — 覆盖不同 schema 版本
3. **user_id 必须 NOT NULL** — users.user_id 列，INSERT 必须显式写入
4. **role/enabled 数据类型正确** — role=TEXT 存角色字符串，enabled=INTEGER 存 0/1
5. **每次改 DB schema 后重跑 Flask 看启动警告** — 还有没有 `no such column`
