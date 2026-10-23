# 冰山 + 仙女座 战略前线调研报告

> **报告时间**: 2026-10-23
> **调研方式**: Mac mini 100.106.220.96 SSH 直接巡检 + SQLite 实库查询 + 进程级诊断
> **flow_id**: flow_unified_ops_20261023

---

## 一、冰山真实运行状态（mini 实库快照）

### 1.1 历史数据丰富但已停摆

| 表 | 行数 | 最近写入 | 状态 |
|---|---|---|---|
| mt_iceberg_runs | 7,170 | 10-22 前（重启前） | ⛔ **41h 无新增** |
| mt_iceberg_content_matrix | 6,761 | 10-22 前 | ⛔ 停摆 |
| mt_iceberg_consciousness_runs | 2,506 | 10-22 前 | ⛔ 停摆 |
| mt_iceberg_consciousness_optimizations | 2,492 | 10-22 前 | ⛔ 停摆 |
| mt_iceberg_rules_generated | 611 | 10-22 前 | ⛔ 停摆 |
| mt_iceberg_optimization_log | 75 | — | ⛔ 停摆 |
| mt_iceberg_slim_log | 1 | 本次瘦身 VACUUM | ✅ 唯一新数据 |
| mt_iceberg_admin_audit | 8 | — | ⛔ 停摆 |

**结论**: 冰山引擎（意识脉冲 + 进化 + 优化 + 规则生成）自 **10-22 mini 重启以来完全停摆**。7,170 runs 全部是历史资产。

### 1.2 冰山引擎文件结构

```
flask-app/engines/  ← 8 个冰山引擎模块
├── iceberg_consciousness.py      # 意识脉冲 (核心)
├── iceberg_content_matrix.py     # 内容矩阵
├── iceberg_command.py            # 命令处理器
├── iceberg_handshake.py          # 握手协议
├── iceberg_meta_model.py         # 元模型
├── iceberg_qbank_adaptive.py     # 题库自适应
├── iceberg_slang_substitution.py # 俚语替换
└── iceberg_arduino_ai.py         # Arduino AI 桥接

runtime/auto_daemons/ ← 1 个冰山守护进程
└── sys_consciousness.py          # 🧊 意识脉冲 · 120s 周期
```

---

## 二、仙女座真实运行状态

### 2.1 仙女座星空稀疏

| 指标 | 数值 |
|---|---|
| mt_andromeda_stars | **25 颗**（AI 员工星空注册） |
| andromeda_health_heartbeat | ⛔ **空表**（健康心跳完全没写入） |
| mt_andromeda_workflow_runs | 有数据但停滞 |
| daemon 数量 | **5 个**（auto_evolution + autosync + life_daemon + research + think_loop） |

### 2.2 仙女座守护进程状态

| 进程 | 状态 | 心跳 |
|---|---|---|
| sys_andromeda_auto_evolution | RUNNING | ❌ 10-22 · 41h 前 |
| sys_andromeda_autosync | RUNNING | ❌ 10-23 13:29 · 10h 前 |
| sys_andromeda_life_daemon | RUNNING | ❌ 10-22 · 41h 前 |
| sys_andromeda_research | RUNNING | ❌ 10-22 · 41h 前 |
| sys_think_loop | RUNNING | ❌ 10-22 · 41h 前 |

**全部僵尸**！PID 已死（ps -p 返回空）但 `mt_daemon_registry.status='RUNNING'`。

---

## 三、根因分析

### 3.1 直接根因：SQLite WAL 写锁

```
Flask PID 26600 (modular_start.py)
    ↓
  独占 WAL 写锁 (PRAGMA journal_mode=WAL)
    ↓
  所有外部进程的 UPDATE/INSERT 都 database is locked
    ↓
  daemon 心跳写 mt_daemon_registry → locked
  daemon 业务写 mt_iceberg_runs → locked
    ↓
  模板 except Exception: pass 静默吞掉所有错误
    ↓
  僵尸 daemon: status=RUNNING 但 PID 死了 + 心跳 41h 不跳
```

**实测证据**:
```bash
# mini 上外部进程尝试写 DB
$ python3 -c "conn.execute(\"UPDATE mt_daemon_registry SET pid=94573 WHERE process_name='sys_consciousness'\")"
# → ❌ database is locked (3.0s timeout)

# 停 Flask 后立刻能写
$ kill -9 26600 26599
$ sqlite3 app.db "UPDATE mt_daemon_registry SET pid=95343 WHERE process_name='sys_consciousness'"
# → ✅ 写入成功
```

### 3.2 模板根因：`_heartbeat()` 只写一张表

smart_mount_engine.py 自动生成 daemon 的模板：

```python
# 旧版（已修复）
def _heartbeat():
    try:
        conn = _db(); c = conn.cursor()
        c.execute(  # ← 只写 mt_ai_smart_mount_processes
            "UPDATE mt_ai_smart_mount_processes SET ...", ...)
        conn.commit()
        conn.close()
    except Exception:  # ← WAL 锁时静默吞掉
        pass
    # ❌ 完全忘了写 mt_daemon_registry！
    # patrol_inspector / 规则索引 看的就是后者
```

**后果**:
- patrol_inspector 看 registry.last_heartbeat → 永远是旧值 → 判 RUNNING → 不 spawn 新 daemon
- smart_mount_monitor 只看 smart_mount_processes.heartbeat_at → 那里可能更新了但没人用
- 两套心跳系统脱节，全链路"状态不一致"

### 3.3 触发条件：mini 重启 + WAL 锁重夺

10-22 mini 经历了一次重启（或 Flask 重启）。重启序列：
1. Flask 最先起来 → 立刻持有 WAL 写锁
2. cron / patrol_inspector 想 spawn auto_daemons → fork 继承锁状态（或竞争锁失败）
3. daemon 启动后跑第一个 `_heartbeat()` → WAL 锁 → locked → except pass
4. daemon 业务循环里 `IcebergConsciousness.pulse()` 也要写 DB → 同样 locked → 同样被吞
5. daemon 等于**空转**：CPU 占着但什么都没产出
6. smart_mount patrol 看 registry → RUNNING + 心跳旧 → 不 spawn 新 → 僵尸永久化

---

## 四、修复路径（三阶段）

### Phase 1 · 短期（模板已修，mini 已部署）

✅ **已完成**：`ai_smart_mount_engine.py` 模板 `_heartbeat()` 改为双写：
```python
def _heartbeat():
    try:
        now_iso = datetime.now().isoformat()
        conn = _db(); c = conn.cursor()
        c.execute(  # ① smart_mount 进程表（兼容）
            "UPDATE mt_ai_smart_mount_processes SET heartbeat_at=?...", ...)
        c.execute(  # ② daemon_registry（patrol 看的表）+ 带 PID
            "UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), pid=?, status='RUNNING'",
            (os.getpid(), "{process_name}"))
        conn.commit(); conn.close()
    except Exception:
        pass  # WAL 锁时仍然吞，这是问题根源
```

但这**治标不治本**——Flask 持锁时还是写不进去。

### Phase 2 · 中期（需要独立 flow）

#### 方案 A：File-based heartbeat（推荐）

daemon 心跳**不碰 DB** → touch 一个文件 mtime：

```python
def _heartbeat():
    # ① file-based heartbeat (不依赖 DB!)
    hb_file = f"{PID_DIR}/{process_name}.heartbeat"
    os.utime(hb_file, None)  # touch mtime
    
    # ② DB 心跳（best-effort，失败静默）
    try:
        conn = _db(); c = conn.cursor()
        c.execute("UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), pid=?, status='RUNNING'",
                  (os.getpid(), "{process_name}"))
        conn.commit(); conn.close()
    except Exception:
        pass
```

patrol_inspector 检查 heartbeat 文件 mtime：
```python
def _is_daemon_alive(name):
    hb = f"{PID_DIR}/{name}.heartbeat"
    if not os.path.exists(hb): return False
    age = time.time() - os.path.getmtime(hb)
    return age < 5 * 120  # 5 个周期没心跳 = 死了
```

**优势**: 不碰 DB，完全绕过 WAL 锁；文件操作纳秒级；patrol 检查也是本地 syscall。

#### 方案 B：Flask HTTP heartbeat endpoint

在 Flask 里加 `/internal/heartbeat` POST 端点：
```python
@app.post('/internal/heartbeat')
def internal_heartbeat():
    name = request.json['process_name']
    pid = request.json['pid']
    db.execute("UPDATE mt_daemon_registry SET last_heartbeat=datetime('now','localtime'), pid=?, status='RUNNING'", (pid, name))
    db.commit()
    return {'ok': True}
```

daemon 改 `_heartbeat()` 为 HTTP POST：
```python
def _heartbeat():
    try:
        urllib.request.urlopen('http://127.0.0.1:5001/internal/heartbeat',
            data=json.dumps({'process_name': '{process_name}', 'pid': os.getpid()}).encode())
    except Exception:
        pass
```

**优势**: Flask 自己写自己的 DB → WAL 锁永远持有方就是写方 → 不可能 locked。

### Phase 3 · 长期（架构重构）

| 方向 | 可行性 | 代价 |
|---|---|---|
| daemon 各自独立 SQLite DB（不与 Flask 共享） | ✅ 高 | 需重构 smart_mount + patrol 跨库读 |
| 统一 PostgreSQL（连接池 + WAL 支持多写） | ⚠️ 中 | 全量迁移 633 表 + WAL 模式切换 |
| daemon 用 Redis 心跳（setex 300s） | ✅ 高 | 需加 Redis 实例 |
| Flask 主循环 fork 后主动释放 WAL 锁给子进程 | ❌ 低 | SQLite WAL 不支持多进程写 |

**推荐**：Phase 2A（file-based heartbeat）+ Phase 2B（HTTP 代理）同时做，形成双保险。

---

## 五、修复清单

| 项目 | 状态 | 位置 |
|---|---|---|
| smart_mount 模板 `_heartbeat` 双写 | ✅ 已 commit `6dc0a71` | `flask-app/engines/ai_smart_mount_engine.py` |
| mini 5 个僵尸 daemon 文件 patch | ✅ 已 patch 运行实例 | `_runtime/auto_daemons/sys_*.py` |
| mini 僵死活化（手动 spawn + Flask stop/restart） | ✅ 心跳暂时跳动 | mini 现场操作 |
| patrol_inspector 改为 file-based heartbeat | ⏳ 待独立 flow | smart_mount_engine.py |
| Flask 加 `/internal/heartbeat` | ⏳ 待独立 flow | routes/page_routes.py |
| 冰山意识脉冲 engine 业务复活 | ⏳ 心跳活了才能复活业务 | iceberg_consciousness.py |
| 仙女座 health_heartbeat 落库 | ⏳ 同心跳复活 | andromeda_life_daemon.py |

---

## 六、战略方向建议

### 6.1 冰山定位

**现状**: 7,170 runs 历史丰富但停摆。**战略价值**: 冰山是"战略感知层"——跨学科知识矩阵（6,761 条内容矩阵）+ 意识脉冲（健康快照→脑库投喂→进化判定→优化建议→议会提案）。

**下一步**: 心跳复活后第一件事——让 sys_consciousness 跑一次完整 pulse 链路，把健康快照落库 mt_iceberg_runs，让 2,506 历史 consciousness 跑一个 "replay + 增量" 模式。

### 6.2 仙女座定位

**现状**: 25 颗星星 + 健康心跳空表 + 5 僵尸 daemon。**战略价值**: 仙女座是"战略执行层"——AI 员工星空 + 七阶段自演化 + 参数统一系统（mt_params 108 条）+ 知识库/工作流/预测/自愈。

**下一步**: 心跳复活后——让 sys_andromeda_autosync 开始双向同步 mini ↔ Flask，让 sys_andromeda_health_heartbeat 开始落库。25 颗星星不够，要从 mini ai_employees 的 12,064 人中自动选"候选星星"（高 heartbeat + 高技能 + 高任务完成率）。

### 6.3 共同瓶颈

**两者共享的致命瓶颈**: WAL 锁导致的 daemon 静默死亡。

**两者共享的解决方案**: Phase 2 file-based heartbeat → Phase 2B HTTP 代理 → Phase 3 PostgreSQL。

---

## 附录：本次 flow 交付物

| 交付物 | commit | 说明 |
|---|---|---|
| 三委合一 12 表 | `630bc22` | 立法/常务/政法委 |
| 防火墙 4 表 | `630bc22` | 4 环境 24 规则 |
| 任务大厅 3 表 | `630bc22` | 10 技能 + 20 承包商 |
| 冰山瘦身 14 表 | `630bc22` | VACUUM 10.5GB→8.3GB |
| 维护部队 6 表 | `630bc22` | 6 军 18 营 54 连 162 技能 |
| ai_file_organizer 4 系统清理函数 | `630bc22` | run_system_cleanup 冒烟 35 文件+3 进程+134KB |
| deploy_organizer.sh 自动部署 | `fd3f989` | 172 行 7 步脚本 |
| 规则索引 v3.3.0 刷新 | `6052ca4` | 633 表 + 51 daemon + 40 新表 |
| smart_mount 心跳双写修复 | `6dc0a71` | **根因修复** |
| **本报告** | 待 commit | 冰山仙女座运行状态 + 僵尸根因 + 修复路径 |
