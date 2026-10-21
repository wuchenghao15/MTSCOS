# 机密等级规范执行层说明 (MT_RULE_CLASSIFICATION v1.2.0)
---

> ## 🔐 2026-10-21 · v22.25.16 安全更新
> 敏感数据收口: 手机号金库 + email 金库 + password 三列金库 (`mt_user_password_vault`, Fernet, 复用 phone_vault 泛化
> store_field/load_field; 读取列值优先→空/墓碑→金库回读, 写路径金库成功才清列零丢失)。
> 第四列评估完成: users 表 18 列盘点, 三金库已覆盖全部敏感列, 剩余列均非敏感, 无需新增。
> 双库迁移 5/5+5/5 对账全过, 明文残留 0。合规: 法务评审 5 项通过 (个保法/网安法), 2 项 P2 整改已落 (投喂明示+计费明示)。


> **规则文件**: .trae/rules/机密等级与访问控制规范.md
> **执行层文件**:
> - `flask-app/ai_engines/rules_engine/perm_manager.py` (PermissionManager 唯一入口)
> - `flask-app/ai_engines/rules_engine/classification_guard.py` (before_request 拦截)
> - `flask-app/engines/ai_smart_mount_engine.py` sys_rule_enforcer (5 项合规扫描)
> - `flask-app/app/utils/db_encryption.py` classify_table 默认值修复
> - `flask-app/server_real_db.py` L924-L932 (拦截器注册)
> **更新日期**: 2026-10-17

---

## 1. 三级密级体系

| 机器值 | 名称 | 访问要求 | 典型数据 |
|--------|------|---------|---------|
| L0_TOP_SECRET (0) | 极密 | 唯一 SA (wuchenghao15) + VIKEY 在线 + SZU100 实检 | VIKEY 状态、SA 活动、铁律违规记录 |
| L1_CONFIDENTIAL (1) | 机密 | admin+/security+ 角色 + 审计 | 用户容器、会话、权限识别码 |
| L2_SECRET (2) | 秘密 | 已认证用户 + 访问审计 | 考试、题库、AI 员工、脑库 |

> **禁止**: 按角色字符串自行判断密级; L0 不得仅凭 super_admin 字符串放行

---

## 2. PermissionManager 唯一入口

文件: `flask-app/ai_engines/rules_engine/perm_manager.py`

### 2.1 判定签名

```python
from ai_engines.rules_engine import PermissionManager

decision = PermissionManager.can_access_classification(
    level="L1_CONFIDENTIAL",        # 任意表示法: 0-4 / "L0_TOP_SECRET" / "极密" / "机密"
    username="wuchenghao15",
    role="super_admin",
    session=flask.session,
    op_type="read",                 # read/write/export/decrypt/grant
    resource="/api/admin/dashboard_stats",
    client_ip=request.remote_addr,
)

# decision:
# {
#   "allowed": True,
#   "reason_code": "OK",
#   "level": 0,
#   "classification": "L0_TOP_SECRET/极密",
#   "op_type": "read",
#   "operator": "wuchenghao15",
#   "operator_role": "super_admin",
#   "resource": "/api/admin/dashboard_stats",
#   "trace_id": "abc123..."
# }
```

### 2.2 403 响应码 (不含资源细节)

| reason_code | 触发 |
|-----------|------|
| CLASSIFIED_DENY_UNAUTHENTICATED | 未登录访问 L0/L1/L2 |
| CLASSIFIED_DENY_UNKNOWN_ROLE | 角色不在已知集合 |
| CLASSIFIED_DENY_ROLE | 角色不够 (如 teacher 访问 L1) |
| CLASSIFIED_DENY_HARDWARE | SA 但 VIKEY/SZU100 缺失 |
| CLASSIFIED_DENY_SESSION_INVALID | VIKEY 标志与身份不一致 |
| CLASSIFIED_DENY_UNCLASSIFIED | 无法识别密级 (fail-closed) |
| CLASSIFIED_DENY_COMPLIANCE_GATE | 合规门未打开 |

### 2.3 密级名称映射

```python
from ai_engines.rules_engine import normalize_classification_level

normalize_classification_level("极密")      # → 0
normalize_classification_level("L2_SECRET") # → 2
normalize_classification_level(0)           # → 0
normalize_classification_level("unknown")   # → None (fail-closed)
```

### 2.4 双硬件复核

```python
from ai_engines.rules_engine import check_sa_hardware

vikey_ok, szu100_ok = check_sa_hardware(session)
# - VIKEY: session["_sa_override_from_vikey"] (插入时注入, 拔出时清除) + 服务器侧 vikey_driver 实检
# - SZU100: 服务器侧 szu100_driver 实检 (仅本机客户端, 非本机 → False)
# - 结果缓存 30s (避免每秒 ioreg)
```

### 2.5 SA 会话残留清除

```python
from ai_engines.rules_engine import clear_sa_session_residue

clear_sa_session_residue(session)
# 清除: _sa_override_from_vikey / super_admin_approved / is_super_admin
# 触发时机: L0 硬件校验失败 / VIKEY 标志与身份不一致
```

### 2.6 审计落库

```python
PermissionManager.audit_access(decision, client_ip=request.remote_addr)
# 落库表: mt_classified_access_audit
# 字段: trace_id, op_type, operator, operator_role, resource,
#       resource_classification, access_level, result, deny_reason_code, client_ip, created_at
# L3/L4 不审计; 仅 L0/L1/L2
# 审计失败不阻断业务
```

### 2.7 脱敏输出

```python
PermissionManager.mask_output({"password": "abc123", "name": "张三"})
# → {"password": "****", "name": "张****"}
# 敏感键: password/passwd/token/secret/key/vikey/szu100/credential/auth_hash
```

---

## 3. classification_guard 拦截器

文件: `flask-app/ai_engines/rules_engine/classification_guard.py`

### 3.1 拦截路径 (v1.2.0 §B)

| 路径模式 | 密级 | 检查 | 失败处置 |
|---------|------|------|---------|
| `/api/admin/*` | L0 | SA 唯一用户 + 双硬件 | 403 + 销毁 SA 会话残留 |
| `/api/auth/vikey` | L0 | 匿名 GET 放行 (登录页轮询); 匿名 POST fail-closed | 403 |
| `/api/user/container` | L1 | admin+/security+ | 403 + 审计 |
| `/api/db/export/*` | L2 | 已认证用户 | 403 + 审计 |
| `/api/classified/*` | 注册表 | mt_classified_data.data_code → classification | 403 + 审计 |
| `/api/sa/vikey/export` | L0 | SA + 双硬件 | 403 + 销毁 |
| `/api/sa/firmware/export` | L0 | SA + 双硬件 | 403 + 销毁 |
| `/api/eigenflux/privkey` | L1 | admin+ | 403 + 审计 |

### 3.2 注册入口 (已写入 server_real_db.py L924-L932)

```python
# flask-app/server_real_db.py L924-L932
try:
    from ai_engines.rules_engine.classification_guard import register_interceptor
    register_interceptor(app)
    print("[RULES-ENGINE] classification_guard registered (MT_RULE_CLASSIFICATION v1.2.0 §B)")
except Exception as _mt_cg_err:
    print(f"[RULES-ENGINE] classification_guard register skip: {_mt_cg_err}")
```

### 3.3 合规门

```python
# PermissionManager.compliance_gate_open()
# 逻辑: 读取 mt_rule_integrity_scan 最新 classification_compliance 扫描
#       若 failed>0 → False (全部 403)
#       缓存 60s
# 触发: sys_rule_enforcer 每 300s 扫描, 若 failed>0 → 门关闭
```

### 3.4 403 响应格式 (不泄露)

```json
// 正确
{"error": "CLASSIFIED_ACCESS_DENIED", "code": "CLASSIFIED_DENY_ROLE"}

// 禁止
{"error": "user wuchenghao15 not found in mt_classified_data", "table": "mt_users"}
```

---

## 4. sys_rule_enforcer 五项合规扫描

文件: `flask-app/engines/ai_smart_mount_engine.py` (sys_rule_enforcer work_body)

| # | 扫描项 | 逻辑 | PASS 条件 |
|---|--------|------|----------|
| 1 | classify_table 分类覆盖 | 遍历所有 DB 表, 非日志/缓存表不得落入 L3/L4 | unprotected=0 |
| 2 | L0 VIKEY 门槛 | VIKEY 离线后 L0 DEK 必须锁定, L1 可缓存 | l0_locked=True, l1_cached=True |
| 3 | 审计表在位 | mt_classified_access_audit 六必需列 | missing=none |
| 4 | 密级注册一致 | mt_classified_data.classification 可归一化到受保护等级 | bad=[] |
| 5 | 日志脱敏 | 近 200 条审计/告警不得含 password/token/private_key/MTENC: | sensitive_hits=0 |

**扫描结果落库**: `mt_rule_integrity_scan` (scan_type='classification_compliance')

**验证命令**: `python3 flask-app/engines/ai_smart_mount_engine.py --probe classification`

---

## 5. classify_table 默认值修复

文件: `flask-app/app/utils/db_encryption.py` L498-L527

**修复前**: 无法识别的表默认 L3_INTERNAL (未受保护, §4 违反)
**修复后**: 无法识别的表默认 L2_SECRET (受保护, 完成显式分类前不得降级) + 密钥/凭证类命名强制 L0

```python
# 关键变化
def classify_table(table_name: str) -> EncryptionLevel:
    ...
    # 密钥/凭证类命名强制 L0 (§4 fail-closed)
    if any(k in tl for k in ("secret", "credential", "private_key", "apikey", "api_key")):
        return EncryptionLevel.L0_TOP_SECRET
    ...
    # 无法识别 → 默认 L2 秘密 (受保护, 完成显式分类前不得降级)
    return EncryptionLevel.L2_SECRET
```

---

## 6. mt_classified_access_audit 表结构

```sql
CREATE TABLE IF NOT EXISTS mt_classified_access_audit (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id                 TEXT NOT NULL,               -- 追踪 ID
    op_type                  TEXT NOT NULL,               -- read/write/export/decrypt/grant
    operator                 TEXT NOT NULL DEFAULT 'anonymous',
    operator_role            TEXT,
    resource                 TEXT,
    resource_classification TEXT,                        -- L0_TOP_SECRET/极密 等
    access_level             TEXT,                        -- 0/1/2
    result                   TEXT NOT NULL,               -- ALLOW/DENY
    deny_reason_code         TEXT,                        -- 失败时的 reason_code
    client_ip                TEXT,
    created_at               TEXT NOT NULL,
);
CREATE INDEX IF NOT EXISTS idx_mcaa_trace ON mt_classified_access_audit(trace_id);
CREATE INDEX IF NOT EXISTS idx_mcaa_created ON mt_classified_access_audit(created_at);
```

---

## 7. 运行验证清单

```bash
# 1. 分类合规扫描 (手动执行)
cd flask-app/engines && python3 -c "
import sys; sys.path.insert(0, '..')
from ai_smart_mount_engine import *
# 直接跑 work_body 里的五项扫描逻辑
"
# 预期: 5/5 PASS, score=100

# 2. Flask test client 模拟
# 见 /tmp/cls_test_20261017.py (18/18 PASS)
# 匿名 /api/admin → 403; SA + 双硬件 → 200; SA + 硬件离线 → 403 + 清残留

# 3. 审计落库
SELECT COUNT(*) FROM mt_classified_access_audit WHERE result='ALLOW';
SELECT COUNT(*) FROM mt_classified_access_audit WHERE result='DENY';
# 预期: 测试后 >10 条, 无密码/密钥明文

# 4. 合规门
SELECT score, failed FROM mt_rule_integrity_scan
WHERE scan_type='classification_compliance' ORDER BY created_at DESC LIMIT 1;
# 预期: score=100, failed=0
```

---

## 8. 关联规则执行层

| 规则 | 联动 |
|------|------|
| MT_IRON_RULE_12STEPS (§14) | L0 VIKEY 失效 → 触发 MT_IR_D8 (安全 fail-closed) |
| MT_RULE_PERM (用户权限) | PermissionManager.can_access_classification() 是唯一入口 |
| MT_RULE_GOVERNANCE (规则治理) | 弱约束词必须为 0 (auto_rule_strengthener 自动修复) |
| MT_RULE_VERSION (版本升级) | 安全事件 ≥ 3/24h → 强制 [SECURITY] patch bump |

---

## 9. 快速调用示例

```python
# Flask route 内调用 (标准模式)
from flask import request, session
from ai_engines.rules_engine import PermissionManager

@app.route("/api/my/classified/resource")
def my_resource():
    decision = PermissionManager.can_access_classification(
        level="L2_SECRET",
        username=session.get("username"),
        role=session.get("role"),
        session=session,
        op_type="read",
        resource="/api/my/classified/resource",
        client_ip=request.remote_addr,
    )
    PermissionManager.audit_access(decision, client_ip=request.remote_addr)
    if not decision["allowed"]:
        return jsonify({
            "error": "CLASSIFIED_ACCESS_DENIED",
            "code": decision["reason_code"],
        }), 403
    return jsonify({"data": get_my_data()})
```

---

**flow_id**: flow_docs_sync_20261017 | **STEP_7_EXECUTE**