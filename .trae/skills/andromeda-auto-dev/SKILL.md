---
name: "andromeda-auto-dev"
description: "仙女座自动开发: 往 smart_mount 建议池插新功能 → base64 预编码 → 自动 mount daemon → 真实产出代码文件. Invoke when user wants smart_mount to auto-develop new features (DarkMode/RAG/Agent/Celery/API Blueprint etc.)."
---

# 仙女座自动开发 (Andromeda Auto-Dev)

> **让 smart_mount engine 真正跑全栈开发**: 建议入库 → flow_id 路由 → base64 编码文件内容 → 自动生成 daemon 脚本 → 启动 → 写真实代码文件到 `flask-app/`。
> 
> **项目路径**: `flask-app/engines/ai_smart_mount_engine.py` | **建议库**: `database/app.db` (读) + `engines/app.db` (写)

---

## 一、核心架构（已验证 12/12 daemon）

```
mt_ai_suggestion_pool (建议池, source_name='sys_fullstack_sense', priority=10)
    ↓
_infer_work_body() ← flow_id 前缀路由 (auto_dark_mode → DEV_DARK_MODE_BODY)
    ↓
generate_daemon_script() ← 把 work_body 嵌入 daemon 循环
    ↓
mount_process() → subprocess.Popen 启动 daemon
    ↓
daemon 每 30s 循环: base64.b64decode(预编码内容).decode() → _f.write() → 真实文件落地
    ↓
Flask 重启时 try/except 注册 Blueprint
```

### 已验证的 12 种 DEV_* work_body 模式

| DEV Body | flow_id 前缀 | 目标产出 |
|----------|-------------|---------|
| DEV_DARK_MODE_BODY | `auto_dark_mode` | `static/css/auto_gen/*.css` |
| DEV_COMPONENT_LIB_BODY | `auto_component_library` | `static/js/auto_gen_components/*.js` |
| DEV_RESPONSIVE_BODY | `auto_responsive` | `static/css/auto_gen/*.css` |
| DEV_API_GATEWAY_BODY | `auto_api_gateway` | `routes/auto_gen_gateway/__init__.py` (Blueprint) |
| DEV_DB_MIGRATION_BODY | `auto_db_migration` | `migrations/alembic.ini` + `env.py` |
| DEV_CELERY_BODY | `auto_celery` | `auto_gen_celery/*.py` |
| DEV_RAG_BODY | `auto_rag` | `ai_engines/auto_gen_rag/*.py` |
| DEV_AGENT_ORCH_BODY | `auto_agent_orchestrator` | `ai_engines/auto_gen_orch/*.py` |
| DEV_METRICS_BODY | `auto_metrics` | `routes/auto_gen_metrics/__init__.py` + `templates/*.html` |
| DEV_LOG_AGG_BODY | `auto_log_aggregator` | `engines/auto_log_aggregator_engine.py` |
| DEV_ZERO_TRUST_BODY | `auto_zero_trust` | `engines/auto_gen_zero_trust/*.py` |
| DEV_DATA_CLASSIFY_BODY | `auto_data_classification` | `engines/auto_gen_classify/*.py` |

---

## 二、标准操作步骤（新增一个自动开发功能）

### STEP 1: 往建议池插入新建议

```python
import sqlite3, os, sys

sys.path.insert(0, "flask-app")
DB_10G = "flask-app/database/app.db"

conn = sqlite3.connect(DB_10G, timeout=5)
conn.execute("""
    INSERT INTO mt_ai_suggestion_pool
    (source_type, source_name, suggestion_text, priority,
     feasibility_score, value_score, cost_score, risk_score,
     status, flow_id)
    VALUES (?, ?, ?, ?, 0.85, 0.75, 0.20, 0.15, 'EVALUATED', ?)
""", (
    'FEATURE_EVOLUTION_AWAKE',
    'sys_fullstack_sense',
    '功能描述: 新增 XXX 模块, 产出 YYY 文件',
    10,
    'auto_xxx_feature_v1'  # ← 关键: 前缀必须匹配 DEV_XXX_BODY 的 flow_id 路由
))
conn.commit()
conn.close()
print("✅ 建议已入库")
```

### STEP 2: 在 `_infer_work_body()` 加新 DEV_XXX_BODY 路由

文件: `flask-app/engines/ai_smart_mount_engine.py`

在 `elif` 链里加（在 `generate_daemon_script` 调用前）:

```python
elif flow_id.startswith("auto_xxx_feature"):
    return DEV_XXX_BODY
```

### STEP 3: 定义 DEV_XXX_BODY（**严格模板**）

```python
# === DEV_XXX: XXX 模块 ===
DEV_XXX_BODY = """
import base64
# DEV_XXX: XXX 模块描述
try:
    _dir = os.path.join(_PROJECT_ROOT, 'flask-app', 'TARGET_DIR', 'auto_gen_xxx')
    os.makedirs(_dir, exist_ok=True)
    _fp = os.path.join(_dir, 'target_file.py')
    if not os.path.exists(_fp): _c1 = base64.b64decode('{BASE64_encoded_file_content}').decode('utf-8')
    if not os.path.exists(_fp):
        with open(_fp, 'w') as _f: _f.write(_c1)
        _log('DEV_XXX: target_file.py generated')
except Exception as e: _log(f'DEV_XXX err: {e}')
"""
```

### STEP 4: base64 预编码目标文件内容

```python
import base64

target_file_content = '''这里是你要生成的 Python/JS/CSS/HTML 文件内容
可以包含任何三引号、docstring、嵌套字符串 — 因为 base64 了
def hello():
    """这是一个 docstring, 包含 '单引号' 和 "双引号""""
    print("Hello, world!")
'''

encoded = base64.b64encode(target_file_content.encode("utf-8")).decode("ascii")
print(encoded)  # ← 把这个字符串贴到 STEP 3 的 {BASE64_encoded_file_content}
```

### STEP 5: 重启 smart_mount → 重新生成 daemon → 启动

```bash
cd flask-app/engines
pkill -f ai_smart_mount_engine.py
sleep 2
python3 ai_smart_mount_engine.py start
sleep 3
python3 ai_smart_mount_engine.py scan  # 消费新建议
```

或者用 Python 脚本精准触发（推荐）:

```python
import sys, os, subprocess, time, sqlite3
sys.path.insert(0, "flask-app/engines")
import ai_smart_mount_engine as sm

PROJECT = "/绝对路径/到/项目"
DB_10G = f"{PROJECT}/flask-app/database/app.db"

# 取刚插入的建议
c = sqlite3.connect(DB_10G, timeout=5)
row = c.execute("SELECT suggestion_id, flow_id, suggestion_text, feasibility_score, value_score, cost_score, risk_score FROM mt_ai_suggestion_pool WHERE flow_id='auto_xxx_feature_v1'").fetchone()
c.close()

sid, flow_id, text, feas, val, cost, risk = row
sug = {"suggestion_id": sid, "flow_id": flow_id, "suggestion_text": text, "direction": flow_id}

# 关键: 用已加载的 engine 里的 _infer_work_body
body = sm._infer_work_body(sug)

# compile 验证 (必经! 避免生成脚本后才发现语法错)
compile(body, f"<body_{flow_id}>", "exec")

# 生成 daemon 脚本
script = sm.generate_daemon_script(
    process_name=f"auto_gen_{sid}", duty=text[:40],
    suggestion_id=sid, mount_score=round((feas+val)/2, 2),
    work_body=body, inspect_cycle=30
)

# compile 验证生成的脚本
compile(open(script).read(), script, "exec")

# kill 旧的 + 启动
subprocess.run(["pkill", "-9", "-f", f"auto_gen_{sid}"], capture_output=True)
time.sleep(2)
log = open(f"{PROJECT}/_runtime/logs/auto_gen_{sid}.log", "a")
proc = subprocess.Popen([sys.executable, script], stdout=log, stderr=subprocess.STDOUT, cwd=f"{PROJECT}/flask-app")
print(f"✅ auto_gen_{sid} PID={proc.pid}")

# 等待产出 + 检查
time.sleep(60)
expected = f"{PROJECT}/flask-app/TARGET_DIR/auto_gen_xxx/target_file.py"
if os.path.exists(expected):
    print(f"✅ 产出: {expected} ({os.path.getsize(expected)}B)")
else:
    print(f"⏳ MISSING — 看日志: tail -3 _runtime/logs/auto_gen_{sid}.log")
```

### STEP 6: 注册 Blueprint（如果产出了 routes/）

在 `flask-app/modular_start.py` 的 Flask 启动前 try/except 注册：

```python
# 🆕 auto_gen_xxx Blueprint
try:
    from routes.auto_gen_xxx import bp as _xxx_bp
    app.register_blueprint(_xxx_bp)
    print(f'[BOOT] ✅ auto_gen_xxx 已注册 ({_xxx_bp.url_prefix})')
except Exception as _xxx_e:
    print(f'[BOOT] ⚠️ auto_gen_xxx 跳过: {_xxx_e}')
```

### STEP 7: 验证产出文件可运行

```bash
cd flask-app
python3 TARGET_DIR/auto_gen_xxx/target_file.py 2>&1 | head -3
python3 -c "
from flask import Flask
app = Flask(__name__)
from routes.auto_gen_xxx import bp
app.register_blueprint(bp)
with app.test_client() as c:
    r = c.get('/api/xxx/health')
    print(f'GET → {r.status_code} {r.get_json()}')
"
```

---

## 三、铁律清单（踩过的全部坑）

### 语法类
| # | 坑 | 解法 |
|---|---|---|
| 1 | 三引号嵌套冲突 | **所有文件内容 base64 预编码** — body 里只有 `base64.b64decode('...').decode('utf-8')` |
| 2 | work_body 缩进 IndentationError | **body 内容 0 缩进** — daemon 循环本身已有 12 空格，再叠加双重缩进 |
| 3 | `_os` vs `os` 别名 | 不用别名，直接用 `os.makedirs` / `os.path.join` |
| 4 | f-string 双花括号 `{{e}}` | 不用 f-string 嵌套在 work_body 里 — 用 `str(var)` 或普通拼接 |
| 5 | 闭合行不能挂 `.replace()` 链式调用 | `DEV_BODY = """\n...\n"""` 结束后直接换行，别加 `.replace(...)` |

### 架构类
| # | 坑 | 解法 |
|---|---|---|
| 6 | 读库 vs 写库分离 | **smart_mount 读 `database/app.db` (10GB)，daemon 写 `engines/app.db`** — 所有 schema 变更必须两边同步 |
| 7 | generate_daemon_script 有 format 调用 | body 里所有 `{var}` 会被 format 消费 — 要么用 `{{var}}` 要么干脆别用 f-string |
| 8 | 不要手动改 `_runtime/auto_daemons/auto_gen_N.py` | 下次 scan 会覆盖 — 改 `_infer_work_body()` 才是正道 |
| 9 | daemon 幂等性 | 所有写文件都 `if not os.path.exists(path)` — daemon 循环每 30s 跑一次 |

### 验证类
| # | 做法 | 命令 |
|---|------|------|
| 10 | 生成前先 compile work_body | `compile(body, '<body>', 'exec')` |
| 11 | 生成后再 compile daemon 脚本 | `compile(open(script).read(), script, 'exec')` |
| 12 | 启动后看真实产出文件 | `find flask-app -newer _runtime/logs/auto_gen_7.log -type f` |
| 13 | 看 daemon 执行日志 | `tail -5 _runtime/logs/auto_gen_{sid}.log` |

---

## 四、快速脚手架（新增功能 3 分钟走完全流程）

```bash
# 1. base64 预编码目标文件
python3 -c "
import base64
content = open('path/to/your/target_file.py').read()
print(base64.b64encode(content.encode()).decode())
" | pbcopy

# 2. 插建议 + 触发 mount
cd flask-app
python3 << 'PYEOF'
import sys, sqlite3
sys.path.insert(0, "engines")
import ai_smart_mount_engine as sm

# 插建议
c = sqlite3.connect("database/app.db", timeout=5)
c.execute("""INSERT INTO mt_ai_suggestion_pool
(source_type, source_name, suggestion_text, priority, feasibility_score, value_score, cost_score, risk_score, status, flow_id)
VALUES ('FEATURE_EVOLUTION_AWAKE','sys_fullstack_sense','新功能描述',10,0.85,0.75,0.2,0.15,'EVALUATED','auto_new_feature_v1')""")
c.commit(); c.close()
print("✅ 建议已入库, 现在去 _infer_work_body() 加 DEV_NEW_FEATURE_BODY")
PYEOF
```

---

## 五、Blueprint 注册模板（modular_start.py）

```python
# 放在 Flask app.run() 前, try/except 包裹, 失败不阻塞启动
try:
    from routes.auto_gen_xxx import bp as _xxx_bp
    app.register_blueprint(_xxx_bp)
    print(f'[BOOT] ✅ auto_gen_xxx 已注册 ({_xxx_bp.url_prefix})')
except Exception as _xxx_e:
    print(f'[BOOT] ⚠️ auto_gen_xxx 跳过: {_xxx_e}')
```

---

## 六、文件位置速查

| 文件 | 路径 | 作用 |
|------|------|------|
| smart_mount 引擎 | `flask-app/engines/ai_smart_mount_engine.py` | `_infer_work_body()` + `generate_daemon_script()` |
| 建议库 | `flask-app/database/app.db` | `mt_ai_suggestion_pool` (source_name='sys_fullstack_sense') |
| 活跃库 | `flask-app/engines/app.db` | daemon 心跳、注册状态 |
| daemon 脚本 | `flask-app/_runtime/auto_daemons/auto_gen_N.py` | 自动生成，**别手动改** |
| daemon 日志 | `flask-app/_runtime/logs/auto_gen_N.log` | 实时看 DEV_* 执行 |
| Flask 启动 | `flask-app/modular_start.py` | Blueprint try/except 注册 |
| 主入口 Flask | `flask-app/` 各目录 | daemon 产出的真实文件落地 |
