#!/usr/bin/env python3
"""离线验证：使用 Flask test_client
   1. GET /auth/check_username?username=caopw → 必须 exists=true, is_active=true
   2. GET /auth/check_username?username=notexist12345 → 必须 exists=false（非 db_error）
   3. POST /auth/login caopw/xuxu4pipo/合法ssl_fp → 必须 success=true
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importlib.util
spec = importlib.util.spec_from_file_location("srv", os.path.join(os.path.dirname(__file__), "server_real_db.py"))
srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)

SSL_FP = '0' * 64

app = srv.app
app.config['TESTING'] = True
app.secret_key = 'test-secret-xxx'
client = app.test_client()

def run(label, fn, expect_ok):
    print(f"\n=== {label} ===")
    try:
        ok, info = fn()
        status = "PASS" if (bool(ok) == bool(expect_ok)) else "FAIL"
        print(f"  [{status}] expected={bool(expect_ok)} got={bool(ok)} :: {info}")
        return status == "PASS"
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  [FAIL] 异常: {e}")
        return False

results = []

# 1. check_username caopw 存在
def t1():
    r = client.get('/auth/check_username?username=caopw')
    body = r.get_json(silent=True) or {}
    info = f"status={r.status_code} exists={body.get('exists')} role={body.get('role')} is_active={body.get('is_active')} user_id={body.get('user_id')} db={body.get('db_source')}"
    return (body.get('success') is True and body.get('exists') is True and body.get('is_active') is True), info

results.append(run("1. check_username(caopw) → exists=true active=true", t1, True))

# 2. check_username 不存在用户名 → success=true, exists=false（不能是 db_error）
def t2():
    r = client.get('/auth/check_username?username=nosuch_user_xyz_999')
    body = r.get_json(silent=True) or {}
    info = f"status={r.status_code} success={body.get('success')} exists={body.get('exists')} error={body.get('error')}"
    return (body.get('success') is True and body.get('exists') is False and not body.get('error')), info

results.append(run("2. check_username(nonexistent) → success=true exists=false", t2, True))

# 3. caopw / xuxu4pipo 登录成功
def t3():
    r = client.post('/auth/login', json={'username':'caopw','password':'xuxu4pipo','ssl_fingerprint': SSL_FP, 'remember_me': True})
    body = r.get_json(silent=True) or {}
    info = f"status={r.status_code} success={body.get('success')} message={body.get('message')} role={body.get('user',{}).get('role') if isinstance(body.get('user'),dict) else body.get('user')}"
    return (body.get('success') is True and (body.get('user') or {}).get('role') == 'student'), info

results.append(run("3. POST login caopw/xuxu4pipo → success=true role=student", t3, True))

# 4. 不存在的用户登录 → 401 "用户名或密码错误"（不应暴露存在性）
def t4():
    r = client.post('/auth/login', json={'username':'noone_xyz_888','password':'whatever@Pass123','ssl_fingerprint': SSL_FP})
    body = r.get_json(silent=True) or {}
    msg = body.get('message') or ''
    info = f"status={r.status_code} success={body.get('success')} msg={msg!r}"
    return (r.status_code == 401 and body.get('success') is False and ('密码错误' in msg or '用户名' in msg)), info

results.append(run("4. POST login 不存在用户 → 401 用户名或密码错误", t4, True))

# 5. caopw + 错误密码 → 401 "用户名或密码错误"
def t5():
    r = client.post('/auth/login', json={'username':'caopw','password':'WrongPass@1','ssl_fingerprint': SSL_FP})
    body = r.get_json(silent=True) or {}
    msg = body.get('message') or ''
    info = f"status={r.status_code} success={body.get('success')} msg={msg!r}"
    return (r.status_code == 401 and body.get('success') is False and ('密码错误' in msg or '用户名' in msg)), info

results.append(run("5. POST login caopw + 错误密码 → 401 用户名或密码错误", t5, True))

print("\n================ 汇总 ================")
pass_cnt = sum(1 for x in results if x)
print(f"  通过 {pass_cnt}/{len(results)}")
sys.exit(0 if all(results) else 1)
