# AI 轮巡新增「屎山代码 + 零散未归类文件」卫生巡检 — 实施方案

## Context（为什么做）

用户要求在现有 AI 轮巡中新增两类检测并完善闭环：
1. **屎山代码检测**：覆盖仙女座引擎（`engines/andromeda_*`、`engines/auto_*` 等）与冰山系统全站自研代码。
2. **零散/未归类文件检测**：扫描散落、错放、异常命名的文件与目录。

勘察发现三个半成品引擎均有结构性短板：
- 常驻主循环 [andromeda_auto_loop.py](../../flask-app/engines/andromeda_auto_loop.py)（launchd 每 5min，7 步）**完全没有**卫生检测步骤；`auto_sniff/auto_patrol/file_organizer` 未挂入。
- [auto_sniff_engine.py](../../flask-app/engines/auto_sniff_engine.py) 纯正则 7 规则，无真正复杂度/重复/长函数检测；`flow_id` 无 UNIQUE 致去重失效，已向 `mt_ai_suggestion_pool` 刷入 **6816 条 EVALUATED 噪音**；还跳过最大的 `server_real_db.py`。
- [auto_patrol_engine.py](../../flask-app/engines/auto_patrol_engine.py) `from mt_ir14_dev_flow import feed_brain` 断裂（模块在 `ai_engines/`，sys.path 只插 `engines/`）→ 走"假成功" fallback；[L35](../../flask-app/engines/auto_patrol_engine.py#L35) `defaultdict` import 被误注释但 [L261](../../flask-app/engines/auto_patrol_engine.py#L261) 仍用 → NameError。
- [ai_file_organizer.py](../../flask-app/engines/ai_file_organizer.py) 只扫项目根一层、不校验目录职责、不区分 git 状态、检测与 MOVE 耦合。

目标：**一个统一卫生引擎**，做检测→指纹去重落库→状态生命周期→节流接入主循环→HIGH 晋升建议池→投喂脑库；仅纯文本安全项自动修复，文件一律不自动移动。

## 用户已拍板（4 项决策）

| 决策点 | 选择 |
|---|---|
| 超大文件（server_real_db 1.34 万行 / arduino_ai_employees 1.2 万行） | **全量明细**（逐函数逐类，靠分批游标+预算兜底） |
| 自动处理边界 | **仅安全项自动修**（尾空白/缺末换行/未用 import）；屎山重构、文件移动只报告 |
| 扫描周期 | **代码 60min 一轮 / 文件 30min 一轮** |
| 6816 条历史 sniff 噪音 | **批量 DEFERRED 归档**（不删库，写原因 `sniff_dedup_legacy_20261012`） |

## 扫描作用域（排除依赖与融合代码）

- 仙女座 profile：`engines/andromeda_*.py`、`engines/auto_*.py`、`engines/ai_*andromeda*`
- 冰山自研 profile：`engines/`、`ai_engines/`（仅直接层 + management/rules_engine/brain/learning/security/monitoring）、`routes/`、`app/`、`core/`、`services/`、`scripts/`、flask-app 根 `*.py`
- 全局排除：`venv/.venv/site-packages`、`ai_engines/*_fusion/*`（外部融合源码 ~2700 个）、`auto_gen_*`、`__pycache__`、`_migration*`、`backups`、`node_modules`、`.git`。自研域约 1400 个 py。

## 1. 新模块

新建 `flask-app/engines/andromeda_code_hygiene_engine.py`（只检测/落库/晋升/投喂 + 安全修复，不移动文件）。公共函数：

```
ensure_tables()
scan_code_sweep_chunk(budget_files, budget_sec)   # 跨 tick 分批 AST 扫描
scan_file_health()                                # 文件卫生一轮(轻量)
_upsert_finding(category, rule_id, sev, ...)       # 指纹幂等
close_stale(sweep_id)                              # 本轮未再见 → FIXED
autofix_safe(limit)                                # 仅白名单 3 类纯文本项
promote_high_to_pool(limit)                        # HIGH 且 seen≥2 → 建议池(应用层判重)
feed(kind, content)                                # 复用 mt_ir14_dev_flow.feed_brain
run_once() / main(): CLI  dry-run | run | code | files | status
```

与旧引擎关系：
- sniff 的 7 规则并入新引擎 `REGEX_RULES`（id 加 `SNIFF_` 前缀）；`auto_sniff_engine.run_sniff_cycle()` 改为转调新引擎（保留 CLI 兼容），**停止直写建议池**。
- patrol 仍负责语法/py_compile 与安全修复；新引擎复用其 `ErrorItem` 思路但独立落库。
- organizer 继续负责"实际归档"，仅处理卫生表中 `status=ACK`（人工/SA 批准）的文件项；根一层旧扫描逻辑保留但不再作为检测来源。

## 2. 屎山规则集（AST；rule_id / 严重度 / 默认阈值）

| rule_id | sev | 阈值 | 检测 |
|---|---|---|---|
| `FILE_TOO_LARGE` | MED | 800 行 | 文件行数 |
| `FUNC_TOO_LONG` | MED | 80 行 | 函数/方法体行数（end_lineno-lineno） |
| `CYCLO_COMPLEX` | HIGH | 15 | If/For/While/And/Or/ExceptHandler/With/ comprehension-if/assert 计数+1 |
| `NEST_DEPTH` | MED | 5 | 函数内最大嵌套深度 |
| `ARG_COUNT` | MED | 7 | 参数个数（含 *args/**kwargs） |
| `GOD_CLASS` | HIGH | 方法≥25 或类体≥400 行 | ClassDef 统计 |
| `DUP_BLOCK` | HIGH | 归一化后连续 ≥8 行命中 | 函数体 stmt 归一化（空白/字面量/数字占位）取 5-gram sha1，单遍倒排索引；超大文件每文件最多取 400 个最大函数体参与，控内存 |
| `COMMENTED_CODE` | LOW | 连续 ≥12 注释行且 ≥60% 像代码 | 注释块启发式 |
| `BARE_EXCEPT` | LOW | — | ExceptHandler.type is None（复用 patrol） |
| `SWALLOW_PASS` | MED | — | except 块仅 `pass`/`...`/空 |
| `TODO_DENSITY` | LOW | 每百行 >3 | TODO/FIXME/HACK/XXX 密度 |
| `UNUSED_PRIVATE` | INFO | — | 单文件内 `_xxx` 函数/类零引用（保守仅提示） |
| `SNIFF_*` | 沿用 | 沿用 | 并入 auto_sniff 7 条（endpoint/missing_import/装饰器顺序/硬编码中文/legacy_kwargs/bare_except/todo） |

全量明细策略：超大文件逐函数产出，但**跨 chunk 分批**，单文件受 `BUDGET_SEC` 限制到点即停、下一 tick 续；不因体量大跳过。

## 3. 文件卫生规则集

| rule_id | sev | 判定 |
|---|---|---|
| `ROOT_LOOSE` | MED | 项目根一层不在 `ROOT_KEEP_FILES/ROOT_KEEP_DIRS`（复用 organizer 常量），区分文件/目录 |
| `DIR_MISPLACE` | MED | 目录→允许扩展名白名单（依据《开发规则.md》L183-215：engines=*.py、config=json/yaml/ini、templates=html/jinja、static=css/js/图片、flask-app 根仅入口白名单等） |
| `BAD_NAME` | LOW | 中文/空格/连续下划线/超长名 |
| `TEMP_LIKE` | LOW | tmp/bak/swp/~/.DS_Store/pyc/空目录 |
| `BIG_LOOSE_FILE` | INFO | >20MB 的散落文件（仅 `os.lstat`，不触发云下载） |

- git 维度：`git ls-files --cached` 与 `git status --porcelain -z`（cwd=项目根，timeout 10，只读），命中 tracked 的违规项 severity 升一档，meta 记 `tracked=1`；untracked 多为运行时产物，降一档。
- 忽略：pids/cache/keys/__pycache__/.git/node_modules/venv/auto_gen_/*_fusion/backups/OneDrive 占位；全程 `os.lstat` + SIGALRM 30s 看门狗。
- 所有文件项**只落库报告**，不 MOVE；治理需在表中置 ACK 后由 organizer 另行执行。

## 4. 落库（database/app.db）

```sql
CREATE TABLE mt_hygiene_findings (
  finding_id    INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint   TEXT NOT NULL UNIQUE,
  category      TEXT NOT NULL CHECK(category IN ('CODE','FILE')),
  rule_id       TEXT NOT NULL,
  severity      TEXT NOT NULL CHECK(severity IN ('CRITICAL','HIGH','MED','LOW','INFO')),
  file_path     TEXT NOT NULL,
  line          INTEGER DEFAULT 0,
  symbol        TEXT,
  metric_value  REAL,
  threshold_val REAL,
  status        TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN','ACK','FIXED','IGNORED')),
  seen_count    INTEGER DEFAULT 1,
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  last_sweep_id TEXT,
  auto_fixed    INTEGER DEFAULT 0,
  meta_json     TEXT
);
CREATE INDEX idx_hyg_status ON mt_hygiene_findings(status,severity);
CREATE INDEX idx_hyg_rule   ON mt_hygiene_findings(rule_id);
CREATE INDEX idx_hyg_file   ON mt_hygiene_findings(file_path);

CREATE TABLE mt_hygiene_runs (
  run_id TEXT PRIMARY KEY, kind TEXT, sweep_id TEXT,
  started_at TEXT, finished_at TEXT, duration_s REAL,
  scanned INTEGER, new_open INTEGER, still_open INTEGER,
  auto_closed INTEGER, auto_fixed INTEGER, promoted INTEGER,
  chunk INTEGER DEFAULT 0, phase TEXT,   -- phase=running/done
  note TEXT
);
-- 分批续扫游标
CREATE TABLE mt_hygiene_scan_state (
  kind TEXT PRIMARY KEY, phase TEXT, sweep_id TEXT,
  cursor_file TEXT, cursor_idx INTEGER,
  sweep_started_at TEXT, updated_at TEXT
);
```

- **指纹（行漂移稳定，不含行号）**：`sha1(category|rule_id|relpath|symbol|归一化ctx)`；CODE 的 ctx 取归一化函数体前 8 token，FILE 取 `小写文件名`（`DIR_MISPLACE` 用 目录+后缀）。
- **Upsert**：`ON CONFLICT(fingerprint) DO UPDATE SET seen_count=seen_count+1,last_seen_at,line,metric_value,last_sweep_id, status=CASE WHEN status='FIXED' THEN 'OPEN' ELSE status END`（问题回归自动重开）。
- **关单**：sweep 完成时，`category=CODE AND status IN('OPEN','ACK') AND last_sweep_id != :sweep` → `FIXED`（本轮没再见到即已修复/消失）；文件类同理每轮全量比对。
- **晋升建议池**：仅 HIGH 且 `seen_count>=2`，`flow_id='hygiene_'+fingerprint前12`，先 SELECT 应用层判重（该表 flow_id 无 UNIQUE），`PROMOTE_PER_LOOP=3 / PROMOTE_DAILY_MAX=10`，写 PENDING。

## 5. 接入 andromeda_auto_loop（节流 + 跨 tick 分批）

在 [run_self_loop()](../../flask-app/engines/andromeda_auto_loop.py#L83) 的 consume 之后追加两步：

```python
_safe("hygiene_code", _loop_hygiene_code)
_safe("hygiene_file", _loop_hygiene_file)
```

- 常量：`HYG_CODE_GAP_SEC=3600`、`HYG_FILE_GAP_SEC=1800`、`BUDGET_FILES_PER_CHUNK=120`、`BUDGET_SEC_PER_CHUNK=90`、`AUTO_FIX_PER_LOOP=10`、`AUTO_FIX_SAFE=True`、`HYG_AI_ENABLED=False`。
- 代码 sweep 状态机：上轮 sweep 未完成（phase=running）→ 按 cursor 续扫下一个 chunk；已完成且距今 < GAP → skip；否则开新 sweep。一个超大文件可独占一个 chunk。sweep 完成后执行 close_stale + promote + 写 runs。
- 文件卫生轻量，单 tick 一次扫完，按 GAP 节流。
- 步骤返回 `{skipped,scanned,new,open,closed,fixed,promoted}`，被 [_record_run](../../flask-app/engines/andromeda_auto_loop.py#L820) 汇总进 `mt_evolution_runs.notes`。每文件 try/except 隔离，DB `busy_timeout=30000`，复用 OneDrive 看门狗。

## 6. 安全项自动修（白名单）

仅 `trailing_whitespace` / `missing_newline` / `unused_import`（沿用 patrol 谨慎逻辑：跳过多行括号导入、每文件≤3）。流程：读原文→改→写临时文件→`py_compile` 验证→通过才 rename 落盘，失败回滚原文；每轮 ≤10 项、只对 OPEN；成功置 `status=FIXED,auto_fixed=1` 并 `feed_brain(...,'summary_success',...)`。**不 git add/commit，不碰 VERSION/.env**。

## 7. AI 增强（默认关）

`HYG_AI_ENABLED=False` 时不调用。开启后每 6h 取 Top3 HIGH 符号，用本文件 `ollama_chat(timeout=45)`（qwen2.5:14b-q5，零 token）生成重构建议并 `feed_brain(...,'anomaly',...)`；失败仅记 meta，不重试。调用 feed_brain 需将 `ai_engines/` 加入 sys.path。

## 8. 顺带修复 & 历史归档

- patrol：在 sys.path 补 `os.path.join(os.path.dirname(_BASE),'ai_engines')` 恢复真实 feed_brain；恢复 `from collections import defaultdict`（消 L261 NameError）。
- 6816 条归档（幂等迁移，放新引擎 ensure_tables 后一次性，或 scripts 下小脚本）：
  `UPDATE mt_ai_suggestion_pool SET status='DEFERRED', meta_json=json_set(COALESCE(meta_json,'{}'),'$.archived_reason','sniff_dedup_legacy_20261012') WHERE source_name='auto_sniff_engine' AND status='EVALUATED'`

## 9. 分阶段实施（每步独立可验证）

- **S0** §14：`python3 scripts/quick_start_flow.py '{"proposal_title":"feat(andromeda): 代码与文件卫生巡检引擎"}'` 拿 flow_id。
- **S1** 建引擎骨架 + 3 张表 + 文件卫生检测（`scan_file_health`/CLI dry-run）。
- **S2** AST 屎山规则（除 DUP_BLOCK）+ 超大文件分批 chunk + 游标状态机。
- **S3** DUP_BLOCK 倒排索引 + 指纹 upsert + close_stale。
- **S4** 接入 auto_loop 两步 + 节流/预算 + `_record_run` 汇总。
- **S5** 安全项自动修 + HIGH 晋升建议池（判重/限额）。
- **S6** sniff 规则并入并停直写池 + patrol 两 bug 修复 + 6816 归档；AI 增强留开关默认关。

## 10. 端到端验证

1. `python3 -m py_compile engines/andromeda_code_hygiene_engine.py engines/auto_patrol_engine.py engines/auto_sniff_engine.py engines/andromeda_auto_loop.py`
2. `python3 engines/andromeda_code_hygiene_engine.py dry-run`：不入库，打印规则命中；确认不含 venv/*_fusion。
3. 首轮 `run code`/`run files` → 查 `mt_hygiene_findings`/`mt_hygiene_runs` 计数与字段。
4. 下一 chunk/轮：`new_open=0`、存量 `seen_count+1`，验证指纹幂等。
5. 临时在测试文件造 90 行函数 → 出现 `FUNC_TOO_LONG` OPEN；删除后等下一 sweep 完成 → 自动转 FIXED。
6. 造尾随空白/缺末换行 → `autofix_safe` 后 py_compile 通过、status=FIXED、原文可从 git 还原。
7. launchd 下观察 auto_loop 日志与 `mt_evolution_runs.notes` 含 `hygiene_code/hygiene_file`；确认节流窗口内 skip、不与 DB 锁冲突。
8. 提交带 `[FLOW-...]` 过 pre-commit；VERSION 保持当前版本不被改动。

## 风险与约束

- 2.6GB OneDrive SQLite 锁：busy_timeout + SIGALRM + 与现有 daemon 错峰；写操作短事务。
- 全量首轮 ~1400 文件较久：分批游标跨 tick，单 chunk 预算硬上限，不阻塞其它步骤。
- DUP_BLOCK 误报：归一化 + ≥8 行阈值，标 HIGH 但只报告不自动改。
- OneDrive 文件写：临时文件+rename、py_compile 失败即回滚；自动修白名单极窄。
- 严格不触碰 `VERSION`、`.env`、`keys/`，不自动 git commit/tag、不 launchctl（SA 域）。
