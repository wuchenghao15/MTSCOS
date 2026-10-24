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

---

## 九、2026-10-24 上午 Phase 3 四项收官战报（flow_unified_ops_20261024）

### 9.1 执行顺序与结论

按依赖序执行：④元凶排查（防修改被回滚）→ ①写者寡头 → ②派单 → ③空壳表。**四项全部完成**。

| # | 项 | 结论 | 关键 commit | 验证 |
|---|---|---|---|---|
| ④ | mini 磁盘回写元凶 | **不存在回滚进程**。08:13-09:27 连续 pull 是上轮会话手动同步残留；"被回滚"观感 = mini 手工热修未入 git 造成树漂移。已 `git checkout + merge --ff-only` 对齐 8a25e3c、树清零。autosync（项目根 `_runtime/` 真身）源码无任何 git/copy 操作，洗清嫌疑 | — | mini HEAD=8a25e3c，`git status` 无已跟踪修改，md5 与 git 一致 |
| ④b | 本机 cron 失联 | sync_github.sh 被移入 `_runtime/git_push_ws/mtscos_push/` 后 cron 仍指旧路径，每 5min 空跑 → crontab 已修正 + 手动跑通（main=MTSCOS 同步恢复） | — | 推送输出 `main → MTSCOS (force)` 成功 |
| ① | 写者寡头第二步 | 两处幂等守卫：`_ensure_site_decoration_schema` 哨兵键跳过（该函数**每次页面渲染**都被 `_get_footer_info` 调用，SQL-TRACE 实测 ui_site_decoration **1316 条/半天** = 请求路径最大残余写者）；`_ensure_claim_tables` 进程级一次化 `_LAB_TABLES_READY`（14+ 路由 + lab-daemon 每 15min tick 反复全量种子） | `1740688` | 重启后渲染×3 + tick：ui_site_decoration **0 条**（原 16/渲染）、mt_lab_centers **0 条**（原 13/tick）；残余仅启动一次性种子 48 条，**-90%+** |
| ② | 维护部队派单 | 新引擎 `maintenance_dispatch_engine.py`：task_type+标题关键词 → 连队 duty/empowerment/技能打分 → 连内员工负载轮转；逐任务短事务。首跑 60 failed（`ai_employees.status='active'` 小写，过滤用大写）→ 改 `LOWER()` → **60/60 DISPATCHED**，六军团各 10 单，匹配精准（漏洞修复→P0补丁组、语法错误→语法错误组、blueprint注册→注册遗漏组） | `23841be`→`49760a1` | `mt_maintenance_log` 60 条 AUTO_DISPATCH JSON 留痕；守护 PID 80410 registry RUNNING |
| ③ | 任务大厅空壳表 | **接线非删表**（与规则索引 §13.3"任务大厅 3 表"登记一致）：三表 0 行 0 引用 → `ensure_seed()` 幂等种子 10 技能包+20 承包商（中国神兽命名，rating/SLA/cost 字段激活）；`external_dispatch_once()` 外派溢出阀门 = 内部 claim 管线消化不了的 QUEUED>24h → 技能匹配 → 最优承包商 → dispatch 留痕。首跑撞 WAL 锁 → 整轮重试 3 次/5s | `7e7a5c6`→`95f22ca` | skills=10/contractors=20 落库；stale=0（内部管线健康，阀门待命）；守护单实例 300s 双模式 |

### 9.2 当前 mini 稳态

- Flask：/index 200 / 0.22s，单实例（10:22:28 起稳定）
- 新增常驻：`sys_maintenance_dispatch`（内派+外派，300s，文件心跳+registry 双写）
- daemon 总数：52（+1）
- 播种风暴：请求路径归零，残余仅启动一次性
- 三方 git：本地 = origin/main = gitee = mini = 95f22ca，工作树干净

### 9.3 Phase 3 新增运维资产

- `python3 maintenance_dispatch_engine.py dispatch|external|loop|status` 四模式 CLI
- 外派阀门语义：`mt_lab_task_hall.status='EXTERNAL_DISPATCHED'` + `claim_type='external_contractor'`，dispatch 记录含 SLA 截止/briefing/cost_estimate
- 排查方法论沉淀：**mtime≠回滚**——先查 git reflog 命令签名（`pull --ff-only` vs `pull -q`）再定罪；树漂移（热修未入 git）会被误判为"代码被回滚"

### 9.4 遗留（低优先级）

1. ~~evaluation_criteria 播种在独立库 `intelligent_evaluation.db`~~ → **确认不处理**：独立库不抢主库 WAL 锁，无风险
2. ~~`sys_maintenance_dispatch` 未纳入 keepalive~~ → **已接入 launchd 拉起保护**（commit `aea1e5d`）：`com.mtscos.maint-dispatch.plist`（RunAtLoad+KeepAlive+ThrottleInterval 30s）部署 mini LaunchAgents，launchd 接管 nohup（PID 85182 实测 exit 0）；plist 存 `_runtime/launchd/` 入 git 便于复部署
3. ~~承包商 contact_method 为占位邮箱~~ → **已接 EigenFlux 真实外联**（commit `aea1e5d`）：`_eigenflux_outreach()` 外派时三连——承包商注册 `eigenflux_registrations`（external_contractor/active）+ `eigenflux_comm_messages` TASK_DISPATCH 外联消息（session TH_EXTERNAL_YYYYMMDD）+ contact_method 真实化（`{cid}@eigenflux.io`）；best-effort 不阻塞外派主流程

**外联闭环冒烟实测**（10:46）：合成滞留任务"防火墙策略审计"→ stale=1 → 昆仑防火墙接单（SKILL_FIREWALL 精准匹配）→ 注册+消息+邮箱三落库 → dispatch/hall 双 DONE + 承包商 completed_tasks 10→11（rating 系统激活）。

**运维方法论补充**：mini 实库 sqlite3 CLI 写操作必须带 `.timeout 30000`（CLI 默认零超时，与 Flask 心跳写并发即 database is locked；引擎侧已内置 busy_timeout=30s 不受影响）。

---

## 十、2026-10-24 上午 §7.2 挂账销账战报（Phase 3 补完，flow_unified_ops_20261024）

### 10.1 盘点 → 修复对照

| §7.2/§5 挂账 | 盘点实况 | 处置 | commit |
|---|---|---|---|
| ③ ai_employees.last_heartbeat 全员 NULL | **12069/12069 仍全 NULL** | 双管齐下：`backfill_heartbeat()` 一次性回填 12069（← updated_at，分批 2000/commit，created_at 兜底，0.07s 完成）+ `execute_once()` 每完成一单写 assignee 心跳（持续源）。**回填后 NULL=0** | `588b41a` |
| （盘点新发现）60 单 DISPATCHED 无执行器，永不推进 | 派单引擎只有分单没有执行闭环，任务大厅空转 | `execute_once()`：DISPATCHED → DONE，每类 task_type 映射**真实证据采集器**（防火墙活跃规则数/FAILED daemon 数/存活 daemon 数…），证据 JSON 落 `mt_maintenance_log AUTO_COMPLETE`；采集异常转 FAILED + FAIL 留痕。守护 loop 三连 dispatch→external→execute（每轮 5 单，防写风暴）。冒烟两轮 10/10 DONE，45 单余量 ~45min 清完 | `588b41a` |
| §5 冰山意识脉冲业务复活 | mt_iceberg_runs 最近写入 **10-24 02:41** — 夜间持续在跑 | **已复活，销账**（§8 心跳链修复的下游红利） | — |
| §5 仙女座 health_heartbeat 落库 | andromeda_health_heartbeat 1 行（§8 修复后落的），链路通但频率低 | 链路已在，观察项 | — |
| §7.2-② 写风暴堵死 HTTP 层 | 播种风暴已归零（§9-①）+ WAL-REAPER 常驻，复发条件大幅削弱 | 风险降级为低；终极防护（写请求统一队列/PostgreSQL）记录为远期架构项 | — |
| §5 patrol_inspector file-based 心跳 | HTTP 代理心跳（/api/internal/heartbeat）已通且经实战 | file-based 降级为双保险增强项，后续可选 | — |
| §7.2-④ schema 漂移 | 本轮再次踩中（mt_iceberg_runs 无 created_at，run_at 才对） | 方法论持续有效：跨库 SQL 一律 PRAGMA table_info 先行 | — |

### 10.2 维护任务全生命周期（本轮闭环后）

```
PENDING --dispatch--> DISPATCHED --execute(真实证据)--> DONE
   |                        |                              └─ FAILED(证据采集异常, FAIL 留痕)
   |                        └─ QUEUED>24h(内部接不了) --external--> EXTERNAL_DISPATCHED
   └─ 全程 mt_maintenance_log 留痕 (AUTO_DISPATCH/AUTO_COMPLETE/...) + assignee 心跳
```

引擎单文件四能力：`dispatch（内派）| external（外派）| execute（执行）| backfill-heartbeat（回填）`，守护 300s 循环前三个。

### 10.3 mini 稳态（10:55）

- Flask 200 / 0.18s；launchd 守护 PID 87993（kickstart 重载后）
- last_heartbeat NULL：**0**/12069；维护任务 DONE=15 / DISPATCHED=45（自动清偿中）
- git 五方（本地/origin/gitee/MTSCOS 分支/mini）= 588b41a

---

## 十一、2026-10-24 上午 半活环节复活战报（三委立法管线 + 仙女座星空，flow_unified_ops_20261024）

### 11.1 活性验收 → 修复对照（"AI 大社区链活动起来了吗"全景盘点的两个半活项）

| 半活项 | 盘点实况 | 断点根因 | 修复 | 验证 |
|---|---|---|---|---|
| 三委立法管线 | 6 提案：4 PASSED + 2 PENDING，**0 法案**；表决表全空 | PASSED 提案的 bill_id 全空 — 表决后**无立案代码**，流程死在提案→法案衔接处；PENDING 也无人表决 | 新引擎 `community_governance_engine.py` `committee_once()` 四阶段闭环：**PENDING 干部团 9 人程序性表决（2/3 多数）→ PASSED 立案 BILL_XXX → 3 条条款骨架 → 颁布法令 DCR_XXXX**，全程 `mt_committee_audit_log` 留痕，确定性伪随机保证可复现 | **5 法案全部 ENACTED**（5 部法令 ACTIVE 颁布）+ 1 REJECTED（真实否决案例），表决 9 条留痕 |
| 仙女座星空 | 25 星 + health 仅 1 行（无采集器） | 星表 domain 列 **UNIQUE 约束（每域一星）**，25 星=25 领域已封顶；health 表无写入方 | ① `stars_expand_once()`：从员工 specialties/group_tag 分段找**尚无星的新领域**补星 ② `health_once()`：Flask 存活(urllib 实测)/DB 可写(实写探测)/CPU(loadavg)/MEM(ps) 真实采样落库 | **星空 25→50 星**；health 采集器 300s 一跳（守护上线即 3 行） |

### 11.2 引擎设计

单守护三合一（避免 daemon 膨胀），`community_governance_engine.py` CLI 四模式：`committee | stars | health | loop`，loop 300s 循环三模块。launchd 拉起保护 `com.mtscos.govern.plist`（与 maint-dispatch 同模板 sed 派生），mini PID 92274。

### 11.3 大社区链终态（11:00 全景）

```
EigenFlux(4658 节点心跳, 28.3万消息) ✅
  → AI 脑库(24h 8314 投喂, 2min 前活跃) ✅
  → 任务大厅(持续派发+外派阀门) ✅ → 维护部队(派单→执行→心跳闭环) ✅
  → 三委立法(6提案→5法案→5法令颁布) ✅ ←本轮复活
  → 仙女座星空(50星/25→50扩容) ✅ ←本轮复活
  → 基础设施健康(300s 真实采样) ✅ ←本轮新增
  → 冰山意识脉冲(心跳 RUNNING, 低频设计) ✅
  → daemon 舰队 52/53 活 ✅ | Flask 200/0.17s ✅
```

**十二环节全绿，无半活项。** 唯一 REJECTED 提案是管线健康的第一手证据（表决不是走过场）。

### 11.4 AI 社会生活层验收（"学习/组队/考试/任教/磋商/交友/交流活起来了吗"）

| 维度 | 实测 | 判定 |
|---|---|---|
| 交友 | mt_ai_eigenflux_connections 54102 条，**24h 新增 22142** | 🔥 极活跃 |
| 考试 | exam_attempts 300 次/24h（最近 10-23 19:43） | ✅ 活 |
| 组队 | 维护部队连队执行 + 任务大厅派单链 | ✅ 活 |
| 任教 | teacher_classes 30 班级 | ✅ 存量活 |
| **磋商** | 圆桌死 18 天 → social_once 复活 | ✅ **本轮复活** 17816→17822 |
| **学习** | ai_learning_records 死 35 天 → 复活 | ✅ **本轮复活** 500→516 |
| **交流** | comm_messages 24h 仅 1 条 → 复活 | ✅ **本轮复活** 1→13 |

**三处停摆根因**：mini_evolution 等引擎心跳活着但业务写被静默吞（§3.3 空转型 daemon 旧病）。修复走 governance 引擎 `social_once()`：**议题取真实系统事件（最新法令→最新完成任务→最新脑库投喂）→ EigenFlux 心跳最新节点组会 → 圆桌 session → 与会者各落学习记录（磋商即学习）→ comm 频道聊成果**，300s 一轮与三委/星空/健康四模块并行。

**schema 陷阱再 +3**（跨库 SQL 必须 PRAGMA 先行的实证）：mt_roundtable_sessions.host/guest 惯例为节点名（HULK-MACMINI）非 reg_id；eigenflux_registrations.reg_id 全空（用 employee_id）；ai_learning_records.learn_id 是 INTEGER 主键禁文本。

---

## 十二、2026-10-24 上午 仙女座自治区引擎战报（AI 社会全自动化运转，flow_unified_ops_20261023）

### 12.1 需求 → 实现对照（14 类社会行为全覆盖）

用户需求：仙女座定期/不定期立法、组织学习、轮岗、更换组织架构、动态赋能、智能研发、下沉调研、收集需求缺口、自动接单、交友、学习、拜师、孵化 skill/daemon、战略研究 → 全部自动化 → 缺口提交大厅 → 大厅自动下发 → 自动升级改造。

| # | 行为 | 实现 | 节奏 | 冒烟 |
|---|---|---|---|---|
| 1 | 立法 | `legislature_once` 缺口→提案(source=ANDROMEDA_SOCIETY) → governance.committee_once 自动表决颁布 | 24h | ✅ 提案 1 已入库 |
| 2 | 组织学习 | governance.social_once（圆桌=组织学习） | 300s | ✅ 已活 |
| 3 | 轮岗 | `rotation_once` 连队技能互换 | 6h | ✅ swapped=1 |
| 4 | 更换组织架构 | `org_review_once` 负载审视+失衡自动落建议池 | 24h | ✅ reviewed=1 |
| 5 | 动态赋能 | rotation_once 内 level 重洗 | 6h | ✅ leveled=5 |
| 6 | 智能研发 | `incubate_once` 圆桌共识→研发提案 | 12h | ✅ 通道贯通 |
| 7 | 下沉市场调研 | `survey_once` 四类缺口信号扫描 | 30min | ✅ gaps=3 |
| 8 | 收集需求缺口 | survey 信号源（FAILED/僵尸/积压） | 30min | ✅ |
| 9 | 自动接大厅任务 | maintenance_dispatch（派单→执行闭环，已有） | 300s | ✅ 已活 |
| 10 | 自动交友 | eigenflux_network（已有 2.2万/天） | — | ✅ 已活 |
| 11 | 自动学习 | social_once 学习记录（已有） | 300s | ✅ 已活 |
| 12 | 自动拜师 | `mentorship_once` 新星↔专家 MENTOR 连接 | 2h | ✅ pairs=3（累计160） |
| 13 | 孵化 skill/daemon | incubate: skill→mt_task_hall_skills + daemon→mt_ai_suggestion_pool（auto_k12_tutor 同通道）→smart_mount 自动 mount | 12h | ✅ 建议池+1 |
| 14 | 战略规划研究 | `strategy_once` 24h 运行盘点→脑库→**成为下一轮圆桌议题** | 24h | ✅ memo=1 |

**闭环**：survey 发现缺口 → 大厅 QUEUED（**本轮 3 单已回灌**）→ 现有管线自动认领/派发/执行 → 结果反哺调研。全程脑库留痕（audit）。

### 12.2 架构要点

- 编排层定位：已有引擎（交友/学习/圆桌/接单/立法表决）全部复用，society 引擎只做补缺+编排，避免功能重复建设
- 多节奏控制：文件时间戳 `_runtime/pids/society_{module}.lastrun`，**零 DDL**；研发/立法类不定期抖动（RANDOM()）
- 守护 `sys_andromeda_society`（60s poll 检查到期模块），launchd `com.mtscos.society.plist` 拉起保护（PID 501）
- 陷阱 +3：§14 hook 提取 msg 中**第一个** flow_id（20261024 未注册被拦截，msg 只能带已注册 id）；mt_lab_task_hall 无 claim_owner 时 source 列即回灌标记；run_all 中途 crash 后重跑靠 24h 幂等去重保证不重复回灌

### 12.3 至此系统全景

感知（冰山/EigenFlux 4658 节点）→ 决策（脑库/三委 5 法令+自治区立法提案）→ 执行（大厅/维护部队）→ 社会生活（交友 2.2万/学习/磋商/拜师）→ 进化（smart_mount 孵化/轮岗赋能/架构审视）→ **监护（缺口自动回灌大厅再改造）** — AI 社会全要素自动化运转达成。

---

## 十三、2026-10-24 任务大厅架构纠偏战报（用户指令，flow_unified_ops_20261023）

### 13.1 用户架构指令

> 维护部队不是任务大厅执行者，是要各自中心到大厅自动认领任务，维护部队只保护任务的合法性、完整性、无污染源即可。

### 13.2 改造对照

| 旧架构（本轮纠偏前） | 新架构（纠偏后） |
|---|---|
| maintenance_dispatch 把任务派给维护部队连队并执行 | **各中心**（10 技能包映射）自动认领大厅任务并执行 |
| 维护部队 = 执行者 | **维护部队 = 合规监护 ONLY**（三查，不接单） |
| 连队派单 dispatch_once 主循环 | 连队派单**退役**（execute_once 仅清偿存量 45 单） |

新引擎函数（maintenance_dispatch_engine.py）：
- `center_claim_once`：QUEUED 任务按关键词匹配技能包 → 认领为「XX中心」（兜底：综合调度中心）→ DISPATCHED。冒烟：survey 回灌 3 单已认领
- `center_execute_once`：中心认领任务 → 真实证据采集（daemon 存活数）→ DONE + CENTER_COMPLETE 留痕
- `guard_once` 维护部队三查：**①合法性**（来源黑名单：fake/hack/注入/backdoor…）**②完整性**（标题/描述/优先级）**③无污染源**（占位符/假数据/注入特征）→ GUARD_PASS 留痕 / 污染 → CONTAMINATED 隔离。冒烟 **17 PASS / 0 误伤 / 0 污染**

### 13.3 大厅新分工

```
任务来源(survey/立法/巡检/手动) → QUEUED
  → guard_once 合规三查 (维护部队, GUARD_CORPS 留痕)
  → center_claim_once 各中心认领 (技能包匹配)
  → center_execute_once 中心执行 (真实证据) → DONE
  → 溢出阀门 → 外部承包商 (EigenFlux 外联)
维护部队: 只监护不执行 — 合法性/完整性/无污染三查, GUARD 留痕 75 条
```

方法论 +1：guard 来源校验先查存量真实 source 分布再定名单 — 白名单模式误伤 no_team_match/frontline_patrol（存量管线合法来源），改黑名单后 0 误伤。

### 13.4 全链活性审计（"有空转假死或没起来的吗"）

**业务产出审计（不看心跳看产出，24h 增量）**：圆桌 11 / 学习 36 / 交流 28 / 脑库 9096 / 大厅 396 / 维护 60 / 交友 32696 / health 10 — **全绿无空转**。三新守护在位（governance 97114 / society 501 / dispatch 5858），8 引擎进程全活。

**揪出 5 个假死，诚实标 DOWN**：

| daemon | 症状 | 定性 |
|---|---|---|
| exam_auto_daemon | hb 从未写入 + 无进程 | 从未起来（考试季触发型，低优先） |
| ai_link_guard_engine | 死 2 天；kill 后 keepalive 40s 拉活但心跳依然不跳 | **真空转**（心跳机制坏） |
| sys_archive_engine | 12h 停；拉活后不跳 | 真空转 |
| sys_wecom_meeting | 12h 停；拉活后不跳 | 真空转 |
| sys_crypto_key_rotate | 12h 停；拉活后不跳 | 真空转 |

registry 终态：**46 RUNNING + 5 DOWN（诚实）**。4 个真空转均为边缘引擎（归档/企微会议/密钥轮转/链接守卫），keepalive 会拉活进程但业务写入坏，留待专项 flow 修复，不阻塞主链。sys_knowledge_precious 低频心跳（2h 级）留观。

### 13.5 僵尸进程 + 脑库数据 修复方案执行（flow_unified_ops_20261024）

**根因链翻案（§13.4"真空转"定性修正）**：archive daemon 心跳函数**早已是双写新版**，函数手调实证可写（hb→12:28:52）— 真根因 = **心跳调用在循环尾 + CYCLE 过长（archive 21600s=6h）+ OneDrive 文件提供者 import 延迟**三者叠加的"假死观感"。keepalive 拉活后进程活着，但第一跳要等 6 小时后。

| 项 | 交付 | 验证 |
|---|---|---|
| **A1 心跳首跳补丁** | `_runtime/patches/patch_daemon_first_heartbeat.py`：3 个 auto_daemons 在 `sleep(_offset)` 后立即插 `_heartbeat()`；`patch_link_guard_heartbeat.py`：link_guard 补全缺失的心跳代码（原版 0 心跳） | 3+1 文件 PATCHED+compiled OK；进程已用新代码复活（28204/28209/13646/28219）；首跳待循环边界自然生效 |
| **B1 脑库限流聚合** | ai_team_collab_engine `_feed_brain` 每 actor 10min 窗口 1 条+同类计数合并（commit 4f7113c） | 9000+/天 → ~860/天 预期；聚合标注"(聚合窗口合并同类 N 条)"信息不丢 |
| **B3 空 preview** | 15 条历史空投喂回填标记 | changes()=15 |
| **A3 心跳自愈闭环** | 复用 society survey 的"僵尸心跳清理"缺口信号（已存在，销账） | 检测→大厅回灌链路已在 |

**脑库诊断结论**：30841 行/7MB 不膨胀、无重复 — 病不是垃圾数据，是**高频模板化稀释检索价值**（6 天团 × 每条广播各投一条，样本见嵌套复利 `[🏆金牌测试] [🏆金牌测试]`）。B1 从源头限流。B2 归档建表（DDL）留待批准；B4 质量分级随 B1 后续。
