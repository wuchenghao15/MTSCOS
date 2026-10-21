# MTSCOS AI 项目安全级别完整体系
---

> ## 🔐 2026-10-21 · v22.25.16 安全更新
> 敏感数据收口: 手机号金库 + email 金库 + password 三列金库 (`mt_user_password_vault`, Fernet, 复用 phone_vault 泛化
> store_field/load_field; 读取列值优先→空/墓碑→金库回读, 写路径金库成功才清列零丢失)。
> 第四列评估完成: users 表 18 列盘点, 三金库已覆盖全部敏感列, 剩余列均非敏感, 无需新增。
> 双库迁移 5/5+5/5 对账全过, 明文残留 0。合规: 法务评审 5 项通过 (个保法/网安法), 2 项 P2 整改已落 (投喂明示+计费明示)。


> **版本**: v21.6.0 | **最后更新**: 2026-08-14 | **文档状态**: 正式版

---

## 目录

1. [安全级别概述](#1-安全级别概述)
2. [五级安全分类体系 (L0-L4)](#2-五级安全分类体系-l0-l4)
3. [加密策略与安全级别对应](#3-加密策略与安全级别对应)
4. [用户角色与安全级别映射](#4-用户角色与安全级别映射)
5. [页面安全级别对应](#5-页面安全级别对应)
6. [API路由安全级别分布](#6-api路由安全级别分布)
7. [数据库信息安全级别](#7-数据库信息安全级别)
8. [端口与协议安全级别](#8-端口与协议安全级别)
9. [参数安全级别对应](#9-参数安全级别对应)
10. [通讯安全级别](#10-通讯安全级别)
11. [5级规则体系权限等级](#11-5级规则体系权限等级)
12. [4合1安全防护体系](#12-4合1安全防护体系)
13. [认证加密体系](#13-认证加密体系)
14. [安全测试与质量保证](#14-安全测试与质量保证)

---

## 1. 安全级别概述

MTSCOS AI 项目采用**五级安全分类体系**（L0-L4），从极密到公开，每个级别都有对应的加密策略、访问控制和数据保护措施。

### 1.1 安全架构层级

```
安全架构
├── 第1层: 网络层安全
│   ├── SSL/TLS加密
│   ├── 防火墙规则
│   └── DDoS防护
├── 第2层: 应用层安全
│   ├── 请求过滤
│   ├── 输入验证
│   ├── 安全中间件
│   └── 白名单控制
├── 第3层: 数据层安全
│   ├── 数据加密存储
│   ├── 敏感数据脱敏
│   └── 访问日志记录
├── 第4层: 权限层安全
│   ├── RBAC权限模型
│   ├── 16+角色定义
│   ├── 6级访问控制
│   └── 审计日志
└── 第5层: AI安全
    ├── 漏洞扫描引擎
    ├── 异常检测引擎
    ├── 安全防护引擎
    └── 自动修复引擎
```

---

## 2. 五级安全分类体系 (L0-L4)

### 2.1 安全级别定义表

| 级别 | 名称 | 加密方式 | 访问控制 | 示例数据 |
|------|------|---------|---------|---------|
| **L0** | 极密 | VIKEY绑定 + AES-256-GCM | 仅超级管理员 | root_users, vikey_devices |
| **L1** | 机密 | AES-256-GCM | 管理员+ | user_sessions, password_hashes |
| **L2** | 秘密 | AES-256-GCM | 登录用户+ | question_bank, ai_employees |
| **L3** | 内部 | 访问控制(无加密) | 登录用户 | system_config, logs |
| **L4** | 公开 | 明文(无加密) | 游客 | public_docs, static_resources |

### 2.2 各级别详细说明

#### L0 极密级别
- **数据范围**: 超级管理员账户、VIKEY硬件设备、根用户表
- **加密强度**: 最高级别，VIKEY硬件绑定 + AES-256-GCM
- **访问权限**: 仅 wuchenghao15 唯一超级管理员
- **密钥来源**: VIKEY硬件加密狗实时生成
- **密钥轮换**: 每日自动轮换
- **备份方式**: 加密离线备份
- **典型表**: `root_users`, `vikey_devices`, `vikey_heartbeat`

#### L1 机密级别
- **数据范围**: 用户会话、密码哈希、审计日志、安全事件
- **加密强度**: AES-256-GCM 加密
- **访问权限**: 管理员及以上角色
- **密钥来源**: HKDF(master_key) 派生
- **密钥轮换**: 每周轮换
- **备份方式**: 加密数据库备份
- **典型表**: `user_sessions`, `password_hashes`, `security_events_log`, `audit_log`, `user_containers`

#### L2 秘密级别
- **数据范围**: 题库、AI员工、角色权限、访问控制
- **加密强度**: AES-256-GCM 加密
- **访问权限**: 登录用户及以上
- **密钥来源**: HKDF(master_key) 派生
- **密钥轮换**: 每月轮换
- **备份方式**: 数据库备份
- **典型表**: `question_bank`, `ai_employees`, `role_permissions`, `access_control`

#### L3 内部级别
- **数据范围**: 系统配置、操作日志、内部参数
- **加密强度**: 无加密，仅访问控制
- **访问权限**: 登录用户
- **密钥来源**: N/A
- **密钥轮换**: N/A
- **备份方式**: 数据库备份
- **典型表**: `system_config`, `logs`, `operation_logs`

#### L4 公开级别
- **数据范围**: 公开文档、静态资源、公开信息
- **加密强度**: 明文存储
- **访问权限**: 游客及以上
- **密钥来源**: N/A
- **密钥轮换**: N/A
- **备份方式**: 无备份
- **典型表**: `public_docs`, `static_resources`

---

## 3. 加密策略与安全级别对应

### 3.1 加密策略配置

```python
ENCRYPTION_POLICY = {
    'L0': {
        'algorithm': 'AES-256-GCM',
        'key_source': 'VIKEY',
        'key_rotation': 'daily',
        'backup': 'encrypted_offline'
    },
    'L1': {
        'algorithm': 'AES-256-GCM',
        'key_source': 'HKDF(master_key)',
        'key_rotation': 'weekly',
        'backup': 'encrypted_database'
    },
    'L2': {
        'algorithm': 'AES-256-GCM',
        'key_source': 'HKDF(master_key)',
        'key_rotation': 'monthly',
        'backup': 'database'
    },
    'L3': {
        'algorithm': 'none',
        'key_source': 'N/A',
        'key_rotation': 'N/A',
        'backup': 'database'
    },
    'L4': {
        'algorithm': 'none',
        'key_source': 'N/A',
        'key_rotation': 'N/A',
        'backup': 'none'
    }
}
```

### 3.2 加密算法说明

| 算法 | 密钥长度 | 模式 | 适用级别 | 说明 |
|------|---------|------|---------|------|
| AES-256-GCM | 256位 | GCM认证加密 | L0/L1/L2 | 提供机密性和完整性 |
| PBKDF2-HMAC-SHA256 | 256位 | 密码派生 | 密码存储 | 100,000轮迭代 |
| bcrypt | 60位 | 密码哈希 | 用户密码 | 自动盐值 |
| HKDF | 可变 | 密钥派生 | L1/L2 | 从主密钥派生 |

---

## 4. 用户角色与安全级别映射

### 4.1 16+角色完整列表

| 序号 | 角色代码 | 角色名称 | 6级级别 | 100点级别 | 安全级别访问权限 |
|------|----------|----------|----------|-----------|----------------|
| 1 | super_admin | 超级管理员 | 6 | 100 | L0-L4全部 |
| 2 | system_admin | 系统管理员 | 5 | 90 | L1-L4 |
| 3 | admin | 管理员 | 5 | 80 | L1-L4 |
| 4 | sysadmin | 系统运维管理员 | 5 | 85 | L1-L4 |
| 5 | school_admin | 学校管理员 | 5 | 75 | L1-L4 |
| 6 | teacher_admin | 教师管理员 | 5 | 65 | L1-L4 |
| 7 | hardware_admin | 硬件管理员 | 5 | 75 | L1-L4 |
| 8 | hardware_vikey_admin | 硬件Vikey管理员 | 5 | 75 | L0-L4 |
| 9 | cluster_manager | 集群管理员 | 5 | 85 | L1-L4 |
| 10 | ai_manager | AI管理员 | 5 | 75 | L1-L4 |
| 11 | question_manager | 题库管理员 | 5 | 65 | L2-L4 |
| 12 | exam_proctor | 监考员 | 5 | 55 | L2-L4 |
| 13 | designer | 设计师 | 4 | 70 | L2-L4 |
| 14 | teacher | 教师 | 4 | 60 | L2-L4 |
| 15 | student_vip | VIP学生 | 3.5 | 50 | L2-L4 |
| 16 | student | 普通学生 | 3 | 40 | L2-L4 |
| 17 | parent_vip | VIP家长 | 2.5 | 35 | L3-L4 |
| 18 | parent | 家长 | 2 | 30 | L3-L4 |
| 19 | user | 普通用户 | 1.5 | 20 | L3-L4 |
| 20 | guest | 访客 | 1 | 0 | L4仅 |

### 4.2 角色权限矩阵

| 权限 | super_admin | system_admin | admin | teacher | student | guest |
|------|------------|-------------|-------|---------|---------|-------|
| * (全部) | ✓ | | | | | |
| manage_users | ✓ | ✓ | ✓ | | | |
| manage_exams | ✓ | ✓ | ✓ | ✓ | | |
| view_exams | ✓ | ✓ | ✓ | ✓ | ✓ | |
| view_courses | ✓ | ✓ | ✓ | ✓ | ✓ | |
| view_profile | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| hardware_manage | ✓ | | | | | |
| vikey_manage | ✓ | | | | | |

---

## 5. 页面安全级别对应

### 5.1 权限控制装饰器

所有页面路由必须使用 `@system_container` 装饰器进行权限控制。

```python
@system_container(require_auth='login', allowed_roles=None)
```

**参数说明**:
- `require_auth`: 认证级别 ('guest'/'login'/'admin'/'super_admin')
- `allowed_roles`: 允许的角色列表

### 5.2 页面安全级别映射

| 认证级别 | 安全级别 | 页面对应 | 装饰器参数 |
|---------|---------|---------|-----------|
| `super_admin` | L0 | 超级管理员专属页面 | `require_auth='super_admin'` |
| `admin` | L1 | 管理员页面(仪表盘、用户管理、系统设置) | `require_auth='admin'` |
| `login` | L2-L3 | 登录用户页面(学习、考试、个人中心) | `require_auth='login'` |
| `guest` | L4 | 公开页面(公开文档、静态资源) | `require_auth='guest'` |

### 5.3 用户容器6字段强制验证

```python
user_container = {
    'user_group': 'super_admin',       # 用户组别
    'permission_code': 'SA001',        # 权限识别码
    'login_status': 'active',          # 登录状态
    'is_abnormal': False,              # 是否异常
    'is_legal': True,                  # 是否合法
    'login_timestamp': 1723600000.0    # 登录时间戳
}
```

---

## 6. API路由安全级别分布

### 6.1 安全级别分布表

| 安全级别 | API路由示例 | 权限要求 | 说明 |
|---------|-----------|---------|------|
| L0 | `/api/auth/sa_activity_log`<br>`/api/auth/sa_permission_snapshot`<br>`/api/auth/sa_heartbeat` | 仅super_admin | 非SA返回403 |
| L1 | `/api/admin/*`<br>`/api/permissions/*`<br>`/api/users/*` | admin+ | 管理员专属 |
| L2 | `/api/exam/*`<br>`/api/course/*`<br>`/api/question/*`<br>`/api/ai/*` | login+ | 登录用户可访问 |
| L3 | `/api/profile/*`<br>`/api/notification/*` | login+ | 个人相关 |
| L4 | `/api/public/*`<br>`/api/docs/*`<br>`/api/health` | 无需认证 | 公开接口 |

### 6.2 API权限控制示例

```python
# L0 - 超级管理员专属
@app.route('/api/auth/sa_activity_log')
@system_container(require_auth='super_admin')
def sa_activity_log():
    """超级管理员活动日志 - 极密L0"""
    pass

# L1 - 管理员权限
@app.route('/api/admin/users')
@system_container(require_auth='admin', allowed_roles=['admin', 'super_admin'])
def admin_users():
    """用户管理 - 机密L1"""
    pass

# L2 - 登录用户
@app.route('/api/exam/list')
@system_container(require_auth='login')
def exam_list():
    """考试列表 - 秘密L2"""
    pass

# L4 - 公开访问
@app.route('/api/public/docs')
@system_container(require_auth='guest')
def public_docs():
    """公开文档 - 公开L4"""
    pass
```

---

## 7. 数据库信息安全级别

### 7.1 8分片数据库系统

| 分片 | 安全级别 | 表数量 | 容量限制 | 加密策略 |
|------|---------|--------|---------|---------|
| L0 | 极密 | 2 | ≤1GB | VIKEY绑定 + AES-256-GCM |
| L1 | 机密 | 71 | ≤1GB | AES-256-GCM |
| L2 | 秘密 | 206 | ≤1GB | AES-256-GCM |
| L3 | 内部 | 970 | ≤1GB | 访问控制 |
| L4 | 公开 | - | ≤1GB | 明文 |
| L5 | 归档 | - | ≤1GB | 访问控制 |
| L6 | 临时 | - | ≤1GB | 明文 |
| L7 | 分析 | - | ≤1GB | 访问控制 |

### 7.2 数据库表安全级别分布

#### L0 极密表
| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `root_users` | 根用户表 | username, password_hash, password_salt |
| `vikey_devices` | VIKEY设备 | serial, chip_id, status, whitelist |
| `vikey_heartbeat` | VIKEY心跳 | session_id, vikey_serial, last_heartbeat, status |

#### L1 机密表
| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `user_sessions` | 用户会话 | session_id, username, vikey_serial, created_at |
| `password_hashes` | 密码哈希 | username, hash_value, salt, iterations |
| `security_events_log` | 安全事件 | event_id, event_type, severity, ip_address |
| `audit_log` | 审计日志 | log_id, operator, action, timestamp |
| `user_containers` | 用户容器 | username, user_group, permission_code, login_status |

#### L2 秘密表
| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `question_bank` | 题库 | question_id, content, answer, difficulty |
| `ai_employees` | AI员工 | employee_id, name, role, status |
| `role_permissions` | 角色权限 | role, permission, allowed |
| `access_control` | 访问控制 | resource, role, access_level |

#### L3 内部表
| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `system_config` | 系统配置 | config_key, config_value, updated_at |
| `logs` | 操作日志 | log_id, action, timestamp, user |

#### L4 公开表
| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `public_docs` | 公开文档 | doc_id, title, content |
| `static_resources` | 静态资源 | resource_id, path, type |

---

## 8. 端口与协议安全级别

### 8.1 端口安全级别对应

| 安全级别 | 端口/协议 | 说明 | 访问控制 |
|---------|---------|------|---------|
| L0 | HTTPS(443) + VIKEY USB通道 | 超级管理员专用加密通道 | 仅SA |
| L1 | HTTPS(443) | 管理员加密通讯 | admin+ |
| L2 | HTTPS(443) / WSS | 登录用户加密通讯 | login+ |
| L3 | HTTP(5000) 内网 | 内部服务通讯 | 内网IP |
| L4 | HTTP(5000) 公开 | 公开静态资源 | 无限制 |

### 8.2 协议安全要求

| 协议 | 加密方式 | 适用级别 | 说明 |
|------|---------|---------|------|
| HTTPS | TLS 1.3 | L0-L2 | 强制加密传输 |
| WSS | WebSocket Secure | L2 | 实时通讯加密 |
| HTTP | 明文 | L3-L4 | 内网/公开资源 |
| USB | VIKEY硬件加密 | L0 | 硬件级加密通道 |

---

## 9. 参数安全级别对应

### 9.1 参数分类与安全级别

| 参数类别 | 安全级别 | 存储方式 | 示例 |
|---------|---------|---------|------|
| 密码/密钥 | L0 | VIKEY绑定AES-256-GCM加密 | password_hash, encryption_key |
| 会话Token | L1 | AES-256-GCM加密 | session_id, auth_token |
| 用户个人信息 | L2 | AES-256-GCM加密 | email, phone, address |
| 系统配置 | L3 | 明文+访问控制 | system_settings, feature_flags |
| 公开数据 | L4 | 明文 | public_docs, static_resources |

### 9.2 参数验证规则

```python
# L0 参数验证 - 超级管理员专属
def validate_l0_param(param):
    """验证L0级参数 - VIKEY绑定"""
    if not verify_vikey():
        raise PermissionError("VIKEY required for L0 params")
    return decrypt_aes256_gcm(param, vikey_key)

# L1 参数验证 - 管理员权限
def validate_l1_param(param, user_role):
    """验证L1级参数 - 管理员权限"""
    if user_role not in ['admin', 'super_admin']:
        raise PermissionError("Admin role required")
    return decrypt_aes256_gcm(param, hkdf_key)

# L2 参数验证 - 登录用户
def validate_l2_param(param, user_container):
    """验证L2级参数 - 登录用户"""
    if not user_container['is_legal']:
        raise PermissionError("Legal user required")
    return decrypt_aes256_gcm(param, hkdf_key)
```

---

## 10. 通讯安全级别

### 10.1 通讯类型与安全级别

| 通讯类型 | 安全级别 | 加密方式 | 说明 |
|---------|---------|---------|------|
| SA认证通讯 | L0 | VIKEY + AES-256-GCM + TLS | 双钥匙+传输加密 |
| 管理员API | L1 | AES-256-GCM + TLS | 数据加密+传输加密 |
| 用户API | L2 | TLS | 传输加密 |
| 内部服务间 | L3 | 内网隔离 | 无外部访问 |
| 公开资源 | L4 | 无 | 明文传输 |

### 10.2 通讯加密流程

```
L0 通讯流程:
客户端 → VIKEY认证 → TLS加密 → AES-256-GCM加密数据 → 服务端
服务端 → AES-256-GCM解密 → TLS解密 → VIKEY验证 → 客户端

L1 通讯流程:
客户端 → TLS加密 → AES-256-GCM加密数据 → 服务端
服务端 → AES-256-GCM解密 → TLS解密 → 客户端

L2 通讯流程:
客户端 → TLS加密 → 服务端
服务端 → TLS解密 → 客户端
```

---

## 11. 5级规则体系权限等级

### 11.1 规则层级定义

| 规则层级 | 等级代码 | 需对应角色等级 | 审批要求 | 违例后果 |
|---------|---------|--------------|---------|---------|
| IRON_RULE (铁规) | L0 | super_admin 100级 | SA终审+VIKEY+保密撤回 | 零容忍，立即阻断+审计 |
| RED_LINE (红线) | L1 | system_admin 90级 | 7步全流程审批 | 强制阻断，记录违例 |
| RED_WALL (红墙) | L2 | admin 80级 | 5步审批 | 默认阻断，可申请跳过 |
| CONSTRAINT (制约) | L3 | hardware_admin 75级 | 3步审批 | 强制告警，可继续操作 |
| WARNING (提示) | L4 | teacher 60级 | AI自动审核 | 仅提示，不阻断 |

### 11.2 7步审批流程

```
Step 1: 管理员提议 (admin+)
    ↓
Step 2: ≥2名非提议管理员同意 (admin+)
    ↓
Step 3: EigenFlux AI 5人磋商 (≥4/5通过)
    ↓
Step 4: AI防火墙复审 (system_admin+)
    ↓
Step 5: 超级管理员终审 (wuchenghao15 + VIKEY)
    ↓
Step 6: 适配期生效 (系统自动)
    ↓
Step 7: 保密撤回 (仅SA，无痕操作)
```

---

## 12. 4合1安全防护体系

### 12.1 4大安全威胁模块

| 模块 | 威胁类别 | 核心DB表 | 5级规则默认层级 |
|------|---------|---------|---------------|
| 防黑客 | Hacking | sec_hacking_events + sec_rate_limit_buckets | IRON_RULE(L0) |
| 防暴力破解 | BruteForce | sec_bruteforce_locks + login_attempts | RED_LINE(L1) |
| 防撞库 | CredentialStuffing | sec_credential_stuffing_logs + sec_known_weak_password_hashes | RED_LINE(L1) |
| 防反编译 | DecompileProtect | sec_decompile_watermarks | RED_WALL(L2) |

### 12.2 16类安全事件码

| event_code | 触发场景 | 主导AI员工角色 | 典型修复建议 |
|---|---|---|---|
| hack_sqlmap_detected | 请求UA含sqlmap/nmap特征 | 安全审计员CISO | IP封禁24h |
| hack_xss_payload | 请求参数含`<script>`特征 | 安全审计员CISO | 参数过滤+封锁1h |
| hack_path_traversal | 路径含`../`特征 | 安全审计员+合规审计员 | 403阻断+路径规范化 |
| hack_ssrf_attempt | 内网IP段访问请求 | 安全审计员CISO | 请求拒绝+URL白名单 |
| brute_1min_5fail | 1分钟内≥5次失败 | 合规审计员 | LEVEL1锁定10分钟 |
| brute_1h_20fail | 1小时≥20次失败 | 合规审计员+SA | LEVEL3锁定6小时 |
| brute_perm_ban | 24小时≥100次失败 | CISO+SA VIKEY | LEVEL5永久锁定 |
| stuffing_multiaccount_1ip | 10分钟内同IP≥5账号 | 安全审计员CISO | IP锁定6小时 |
| stuffing_weak_password | 密码匹配弱密码库 | 合规审计员 | 强制修改密码 |
| decompile_debugger_ua | User-Agent含调试工具 | 升级分析师CTO | 返回404伪装页面 |

### 12.3 5级惩罚策略(防爆破)

| 惩罚层级 | 触发阈值 | 锁定时长 | 解锁权限 |
|---------|---------|---------|---------|
| LEVEL1 轻微 | 1min ≥5次失败 | 10分钟 | 自动超时解锁 |
| LEVEL2 中等 | 1h ≥20次失败 | 1小时 | admin+手动解锁 |
| LEVEL3 严重 | 24h ≥50次 | 6小时 | admin+手动解锁 |
| LEVEL4 高危 | 24h ≥80次或多账号协同爆破 | 24小时 | system_admin+解锁 |
| LEVEL5 永久封禁 | 24h ≥100次或EigenFlux 5/5全票 | 永久 | 仅super_admin+VIKEY |

---

## 13. 认证加密体系

### 13.1 超级管理员双钥匙认证 (L0)

**钥匙1**: 密码认证
- 算法: PBKDF2-HMAC-SHA256
- 迭代次数: 100,000轮
- 盐值: 32字节随机盐值
- 输出: 256位哈希值

**钥匙2**: VIKEY硬件加密狗
- USB序列号 + 芯片ID
- 移动端指纹认证
- 白名单校验

**7要素强认证**:
1. 用户名 (wuchenghao15唯一)
2. 密码 (已验证)
3. VIKEY序列号 (在线)
4. IP段 (内网白名单)
5. 设备指纹 (非空)
6. 时间窗口 (08:00-23:00)
7. 行为基线 (5s内≥4次=异常)

**30s心跳监控**:
- 每30秒检测VIKEY在线状态
- VIKEY拔出即销毁会话
- 触发审计告警

### 13.2 普通用户认证 (L1-L3)

- bcrypt密码哈希
- Session安全管理
- 权限容器验证
- 6字段强制验证

### 13.3 极密L0封锁矩阵

```
超级管理员存在性 → 极密L0
活动轨迹 → 极密L0
权限结构 → 极密L0
操作记录 → 不记录(无痕)
API访问 → 仅SA可访问
/api/auth/sa_activity_log → 403 (非SA)
/api/auth/sa_permission_snapshot → 403 (非SA)
/api/auth/sa_heartbeat → 403 (非SA)
```

---

## 14. 安全测试与质量保证

### 14.1 1000轮安全测试

所有安全模块都通过1000轮严格测试：

| 测试类型 | 轮次 | 覆盖内容 |
|---------|------|---------|
| 双钥匙认证 | 400 | 缺一即拒、VIKEY拔出≤30s销毁 |
| 7要素验证 | 300 | 不匹配即拒、时间窗口、行为基线 |
| 黑客攻击 | 300 | Token伪造、重放攻击、VIKEY绕过 |

### 14.2 测试成果

- **双钥匙认证**: 1000轮, 0漏洞
- **VIKEY检测**: 1000轮, 0漏洞
- **权限控制**: 1000轮, 0漏洞
- **§14铁律**: 1000轮, 0漏洞
- **深度巡检引擎**: 1000轮, 4880断言, 0漏洞
- **自动开发团队**: 1000轮, 5740断言, 99.5%通过
- **EigenFlux广播**: 1000轮, 5527断言, 0漏洞
- **自动巡逻队**: 1000轮, 14114断言, 0漏洞

---

## 附录

### A. 安全自查清单

#### 7步审批权限
- [ ] Step1提议权限：admin+角色均可
- [ ] Step2投票权限：≥2名非提议人admin+独立投票
- [ ] Step3 EigenFlux权限：AI员工5人组自动触发≥4/5通过
- [ ] Step5 SA终审权限：仅wuchenghao15 + VIKEY通过
- [ ] Step7保密撤回权限：仅SA(wuchenghao15)可执行，无痕日志

#### 5级规则权限对应
- [ ] IRON_RULE：仅SA+全票EigenFlux+VIKEY可变更
- [ ] RED_LINE：完整7步审批，≥4/5 AI磋商
- [ ] RED_WALL：Step1-2-3-4-5-6跳过保密撤回
- [ ] CONSTRAINT：Step1-2-6管理员同意即生效
- [ ] WARNING：AI自动审核即生效

#### SSOT与桥接函数
- [ ] unified_settings禁止直接写库，全部通过_mt_set_config_rule
- [ ] 桥接函数自动按规则层级触发对应审批步骤
- [ ] sa_rule_overrides仅SA+VIKEY可读写，其他角色不可见
- [ ] rule_violation_audit/settings_audit_log双表仅追加不删改

#### 4合1安全防护
- [ ] 4合1中间件已注册@app.before_request
- [ ] 6张sec_*表启动时创建
- [ ] 16类安全event_code已正确映射
- [ ] LEVEL5永久封禁仅wuchenghao15+VIKEY
- [ ] 撞库检测覆盖弱密码库校验
- [ ] 反编译水印token校验错误返回404

### B. 安全事件响应流程

```
1. 检测安全事件
   ↓
2. 记录到security_events_log
   ↓
3. 根据severity触发告警
   ↓
4. EigenFlux AI 5人磋商
   ↓
5. 执行修复建议
   ↓
6. 记录审计日志
   ↓
7. 更新安全策略
```

### C. 安全联系方式

- 漏洞报告: 通过GitHub Security标签页私密报告
- 响应时间: 48小时内
- 安全更新: 通过CHANGELOG.md发布

---

**文档版本**: v1.0.0  
**生效日期**: 2026-08-14  
**适用范围**: MTSCOS AI 项目所有安全相关功能  
**优先级**: 本规范优先级高于其他开发规范，安全管理必须优先遵循本规范
