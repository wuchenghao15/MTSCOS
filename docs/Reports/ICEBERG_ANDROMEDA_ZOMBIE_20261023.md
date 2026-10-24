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

---

## 七、2026-10-24 凌晨战报（P1 四项修复执行记录）

### 7.1 已交付（commit 链：a4c5b1a → c117722 → adca256）

| 项 | 交付 | 关键 commit | 验证 |
|---|---|---|---|
| **P1-3 表名对齐** | life_daemon 七阶段全部改指真实 schema：`ai_employees`(12064行)/`eigenflux_registrations`/`mt_ai_eigenflux_connections`(conn_uid/ACQUAINTANCE/MENTOR)/`mt_ai_brain_feed_log`(feed_target/fed_by/payload_preview)；GROW 改 knowledge_base_size 生长 | 模板+mini 实例同步 patch | DB_PATH 已指 database/app.db，DEBATE/GAME 等阶段可跑通查询 |
| **P1-3b 陷阱库隔离** | `flask-app/engines/app.db`（4KB 空库，10-19 误建）是"第二个宇宙"真身：无 env daemon 全连进去全表报错 → 已隔离改名 `.trap_quarantined_20261024`；`_paths` 候选顺序修正（database 优先、engines 降级、APP_DB 模块级优先） | 模板+mini | 无 env 启动 DB_PATH 正确 |
| **P1-1 心跳 HTTP 代理** | Flask 新增 `POST /api/internal/heartbeat`（loopback-only + X-Internal-Token 600权限文件 + fail-closed + CSRF 豁免前缀）；模板 `_heartbeat` 双路：HTTP 优先 → 直写兜底；mini 5 daemon 已改造 | `bc8cef3` | 三连测全绿（无token 403 / 有token 200 / 双表各 1 行）；sys_consciousness/autosync 心跳 HTTP 全链路通 |
| **P1-1b WAL 锁全案真凶** | `frontline_patrol` 的 `PRAGMA integrity_check`（8.3GB 全页扫数分钟）+ `wal_checkpoint(TRUNCATE)`（阻塞全部写者）= 全舰队锁死总根源（SQL-TRACE + faulthandler SIGUSR1 + SIGKILL 二分三重实证）；舰队级 22 文件替换 `quick_check`+`PASSIVE` | `0e4f006`→`c117722` | 多分钟级硬封锁消除 |
| **P1-1c 清道夫+取证** | sqlite3.connect monkey-patch（check_same_thread=False + weakref 注册表 + dbapi2 覆盖）→ 每 20s 代提交泄漏事务；SQL-TRACE 语句级+连接ID追踪；SIGUSR1 全线程栈取证 | `6cd9290`/`adca256` | reaper 已上线，取证设施常驻 |
| **P1-2 端口守卫** | modular_start 重导入前 health 探测：端口已有健康服务 → 安静退出（launchd KeepAlive / cron / 手动三拉起方竞争根治，EADDRINUSE 历史事故闭环） | 同日 | launchd 复活实例被守卫吸收，单实例稳定 |
| **P1-4 五自循环** | iceberg_command --daemon 已拉起（90s busy_timeout），five-cycles 代码就位 | — | daemon 运行中；业务写入受残余写竞争影响（见下） |

### 7.2 残余风险（Phase 3 待办，诚实记录）

1. **写者寡头问题（未根治）**：Flask 进程内 rules_engine 每 300s 重播种（legal_red_lines 等 INSERT OR IGNORE×数百，单事务数分钟）+ 启动播种风暴 3min → 写锁准连续占用；外部 daemon 即便 90s 耐心仍会在风暴峰值失败。SQL-TRACE 实证 08:39-41/08:45-48 两轮完整风暴。**根治方向**：播种幂等守卫（表非空跳过）/ 写请求统一队列 / PostgreSQL 迁移。
2. **一次写风暴曾把 Flask worker 全堵死**（health 000），权威重启恢复——写超载会演化成 HTTP 层瘫痪，Phase 3 必须处理。
3. `ai_employees.last_heartbeat` 全员 NULL、`successful_fixes` 全 0：life 生殖/社交池的"新鲜度"过滤已改 `updated_at`，心跳落库仍需 autosync 链路修复。
4. 本地/mini schema 漂移多处（ai_employees 列集、mt_iceberg_runs 列名 run_type 不存在等）——跨库 SQL 一律 PRAGMA table_info 先行。

### 7.3 运维资产（新增常驻）

- `POST /api/internal/heartbeat`：daemon 心跳标准通道（token 文件 `_runtime/.internal_token`，chmod 600，缺失即 fail-closed）
- `kill -USR1 <flask_pid>`：全线程栈转储（faulthandler 常驻）
- `[SQL-TRACE c<conn_id>]`：语句级追踪（flask_launchd.log），按连接聚合可定位长事务
- `[WAL-REAPER]`：泄漏事务清道夫日志（20s 周期）
- SIGKILL 二分定位法：SIGSTOP 不释放 fcntl 锁，必须 SIGKILL（今夜实证）

---

## 八、2026-10-24 上午全链启动战报（逐级盘点 + 逐级修复，flow_unified_ops_20261024）

> **方式**：L1 进程层 → L2 引擎层 → L3 数据层 → L4 Flask 层逐级体检，发现即修，修后即验。

### 8.1 L1 进程层 — Flask 假死根治（3 层修复，commit eaf5343）

**现象**：Flask 进程活、0% CPU 空转、curl 全超时（/api/health 45s 无响应）。
**取证**：`kill -USR1` 全线程栈转储 → 请求线程全部堵在两处请求路径 DB 写。
**修复**（commit eaf5343）：

| 层 | 病灶 | 修法 |
|---|---|---|
| ① | `_ensure_legal_redlines_schema` 被 `_mt_check_rules_on_request` **每请求**全量执行（4 表 CREATE/ALTER + 40 种子 + SRE 200+ 迁移），WAL 排队堵死 worker | 进程级一次性初始化（`_LEGAL_REDLINES_SCHEMA_READY` 幂等守卫） |
| ② | active 规则全表读每请求执行 | 15s TTL 进程内缓存 |
| ③ | `ai_firewall._log_event` before_request 同步 INSERT security_events_log + UPDATE hit_count | 内存队列（8000 上限丢最旧）+ 后台批量落库（≤2s 延迟，审计语义不变） |

**验证**：/index 45s 超时 → 200/0.14s；并发 20 全 200 最慢 67ms；3min 审计 101 条落库；flush fail=0。
**插曲**：mini 磁盘代码被某同步进程回写旧版（09:23）导致复发一次 → git checkout + pull eaf5343 后稳定。

### 8.2 L1 daemon 复活（9 个）

| daemon | 处置 |
|---|---|
| sys_arduino_detect / sys_arduino_sync / sys_auto_approval / sys_gray_release_progress / sys_think_loop | Popen + start_new_session 拉起（heredoc 后台管道挂起坑改用 Popen） |
| ai_eigenflux_network_engine | 见 8.3 五层修复链 |
| ai_link_guard_engine | registry 标 RETIRED（无脚本遗留注册） |
| sys_wendaemon | 实际存活（engines/ 目录，pgrep 模式修正后确认） |
| registry 终态 | 50 有效注册全部对应真实存活进程 |

### 8.3 L2/L3 — EigenFlux 心跳链五层修复（心跳停更 5 天 → 实时）

| # | 层 | 病灶 | 修法 |
|---|---|---|---|
| 1 | wrapper spawn 路径 | `TARGET="ai_eigenflux_network_engine.py"` 相对路径，cwd 不符 → Popen 立即失败 30s 冷却无限重试 | 改绝对路径 |
| 2 | wrapper spawn 参数 | 引擎无 `start` 参数默认打 STATUS 秒退（与 patrol 同款历史 bug） | `Popen([...TARGET, "start"])` |
| 3 | 引擎锁耐心 | busy_timeout 12s，启动期 ensure_eigenflux_registrations 撞 WAL 锁即崩 | 12s→60s |
| 4 | 心跳轮性能 | 兜底循环 244 次逐行 UPDATE × 全表扫 12080 行（OR 条件废索引）≈300 万行/轮，主线程卡死 10min+ | 单条 IN 批量 UPDATE + `idx_ae_reg_emp(employee_id, employee_type)` 复合索引 |
| 5 | wrapper/引擎 PID 文件冲突 | wrapper 把**自己的 PID** 写进共享 `ai_eigenflux_network_engine.pid` → 子引擎读文件发现 wrapper"在跑" → 永远 refuse 双启 | wrapper 改用 `.wrapper.pid` 独立文件 |

**验证**：子引擎 62813 稳定，心跳 R13→R15 每 5.7s 一轮，12068 节点全量，`eigenflux_registrations.last_heartbeat` 实时推进（09:54:45+）。

### 8.4 L2/L3 其余活性确认（健康，无需修复）

| 链 | 状态 |
|---|---|
| 冰山五自循环 | 凌晨 00:38 仍在跑（列名修正后确认）；iceberg_command daemon 运行中 |
| 脑库投喂 | mt_ai_brain_feed_log 最新 1 分钟前，实时投喂中 |
| 任务大厅 | 真实管线 = `mt_lab_task_hall`（250 任务，9 成 DONE），daemon_skill_lab_bp 驱动全生命周期；`mt_task_hall_skills/contractors` 为 630bc22 空壳目录表（无代码引用，遗留待清理决策） |
| 三委 | 提案有审议结果（PASSED 等），管线活 |
| 维护部队 | 60 任务全 PENDING 无执行者 — 业务空转（有任务无人接单），功能缺口非故障，待派单引擎接线 |
| ai_employees | 12068 节点已全量注册 EigenFlux（本次自动补注册 11824） |

### 8.5 L4 Flask 分层冒烟（全绿）

| 层 | 结果 |
|---|---|
| L1 路由 | /index /login /admin /eigenflux /andromeda /task_hall 全 200（99-252ms）；/api/health 200/2ms |
| L2 页面 | 全 200 ~100ms |
| L3 API | health 2ms；internal/heartbeat GET 405=POST-only 正常 |
| L4 业务流 | POST /api/internal/heartbeat 200/5ms（fail-closed 链路语义正确） |

### 8.6 L2 引擎层

48 个 `sys_*` wrapper 进程全活（47 脚本）；smart_mount 管辖 32 进程心跳新鲜（10min 内，仅 1 stale）；keepalive cron 周期脚本（keepalive_engines/ai_file_organizer）跑完即退为设计行为。

### 8.7 待办移交（Phase 3）

1. **写者寡头根治**（rules_engine 播种风暴）——本次 3 层修复已消掉请求路径大头，播种风暴仍是残余峰值源
2. **维护部队派单引擎接线**（60 PENDING 无人执行）
3. **mt_task_hall_skills/contractors 空壳表**处置决策（删表或接线）
4. mini 磁盘回写元凶排查（autosync 嫌疑，代码被回滚旧版一次）
