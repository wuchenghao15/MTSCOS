#!/usr/bin/env python3
"""快速探查：数据库中 wuchenghao15 用户是否存在（含 password 哈希，对应真实密码如果是已知的则直接用），
   同时查 vikey_device_bindings 看已有的绑定；再检查 wuchenghao15 在 users 表里的权限/角色"""
import sys, os, sqlite3, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
spec = importlib.util.spec_from_file_location("srv", os.path.join(os.path.dirname(__file__), "server_real_db.py"))
srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)

TARGETS = ['wuchenghao15', 'WuChenghao15', 'WuChenghao', 'wuchenghao', 'WUCHENGHAO15']

print("=== 1. 跨库查找目标用户（case-insensitive） ===")
user_info = None
for uname in TARGETS:
    row, db = srv._find_user_across_dbs(uname)
    if row:
        print(f"  ✅ 找到用户: {row.get('username')!r} @ db={os.path.basename(db)}")
        user_info = {'row': dict(row), 'db': db}
        keys_show = ['id','username','email','role','is_active','super_admin_approved','hardware_admin_approved',
                     'created_at','updated_at','last_login','failed_login_count','locked_until']
        for k in keys_show:
            if k in row: print(f"     {k:<22s}: {row[k]}")
        print(f"     password hash (len={len(row.get('password') or '')}) 前缀: {(row.get('password') or '')[:20]!r}…")
        break
if not user_info:
    print("  ❌ 没找到！列出所有 users 表中 role=super_admin 或包含 'admin' 的记录：")
    for dbp in srv._all_user_db_candidates():
        try:
            with sqlite3.connect(dbp) as c:
                tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users')").fetchall()]
                if not tables: continue
                cols = [r[1] for r in c.execute(f"PRAGMA table_info(\"users\")").fetchall()]
                # 找所有 admin 相关用户
                q = f"SELECT * FROM users WHERE (role LIKE '%admin%' OR username LIKE '%wuchenghao%' OR username LIKE '%admin%') LIMIT 20"
                rows = c.execute(q).fetchall()
                print(f"  - db {os.path.basename(dbp)} 命中 {len(rows)} 条")
                for r in rows:
                    d = dict(zip(cols, r))
                    for k in ['id','username','email','role','is_active','super_admin_approved']:
                        if k in d: print(f"     {k:<22s}: {d[k]}")
                    print("     ---")
        except Exception as e:
            pass

print("\n=== 2. 查 vikey_device_bindings 表（已有绑定） ===")
db_candidates = srv._all_user_db_candidates()
v_existing = []
for dbp in [srv.APP_DB] + db_candidates:
    try:
        with sqlite3.connect(dbp) as c:
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vikey_device_bindings'").fetchall()]
            if not tables: continue
            cols = [r[1] for r in c.execute(f"PRAGMA table_info(vikey_device_bindings)").fetchall()]
            rows = c.execute("SELECT * FROM vikey_device_bindings ORDER BY id DESC LIMIT 10").fetchall()
            print(f"  ✅ 在 {os.path.basename(dbp)} 找到 vikey_device_bindings {len(rows)} 条")
            for r in rows:
                d = dict(zip(cols, r))
                print(f"    id={d.get('id')} serial={d.get('serial')!r} username={d.get('username')!r} role={d.get('role')!r} auth_token_prefix={str(d.get('auth_token') or '')[:16]!r} bound_at={d.get('bound_at')}")
                v_existing.append(d)
    except Exception as e:
        print(f"  - {os.path.basename(dbp)}: err {e}")
