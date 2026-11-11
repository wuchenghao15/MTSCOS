"""🏛️ 全体中心咨询引擎 (flow_all_center_consult_20261027)

所有提案发布后, mt_lab_centers 全部 14 个中心必须介入咨询 —
每个中心从自己的领域视角, 自动生成对该提案的:
  ① requirements  (中心的硬性要求 — 哪些必须满足, 哪些绝对不能碰)
  ② expectations (中心的期盼 — 希望看到什么效果, 期待什么产出)
  ③ outlook      (中心的展望 — 如果做好了, 这个提案能给本中心带来什么长期价值)

设计:
  - 零 token: 文本由规则模板 + 中心 keywords 自动生成, 不调 LLM
  - 落库: mt_center_proposal_consultations 新表
  - 挂点: _hall_dispatch_one 派单成功后 → 自动触发
  - 立法委: 法案第 9 条 (全体中心必须介入咨询)

CLI:
  python3 engines/ai_center_consultation_engine.py --once <hall_task_id>   # 生成单任务全中心咨询
  python3 engines/ai_center_consultation_engine.py --all                     # 对所有 ACTIVE 任务补生成
  python3 engines/ai_center_consultation_engine.py --status <hall_task_id>   # 查看咨询结果 JSON
  python3 engines/ai_center_consultation_engine.py --demo                   # 对 TH-20261027-0011 数学任务演示
"""
import os, sys, json, sqlite3, re
from datetime import datetime

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path: sys.path.insert(0, _APP_DIR)
DB_PATH = os.path.join(_APP_DIR, "Database", "app.db")  # 权威库
FLOW = "flow_all_center_consult_20261027"

# ═══════════════════════════════════════════════════════════
# ① 中心领域画像 — 每个中心的 keywords + 典型关切 + 模板
# ═══════════════════════════════════════════════════════════

CENTER_PROFILES = {
    1:  {"code": "daemon_ops",   "name": "部署运维中心",
         "focus": "daemon/挂载/keepalive/巡检/修复",
         "kw": re.compile(r"(daemon|挂载|keepalive|巡检|修复|部署|ops|云|docker|容器|进程|端口)", re.I),
         "req": "必须有 daemon 守护进程启动脚本 + 挂载配置 + keepalive 心跳 + 端口健康检查; 禁止硬编码路径, 必须走 get_db_path 权威库",
         "exp": "新系统启动后 15min 内自动纳入巡检体系, 异常告警直达钉钉; 挂载点迁移零停机",
         "out": "形成可复用的部署模板, 降低后续新系统部署成本 60%"},
    2:  {"code": "security_audit","name": "安全审计中心",
         "focus": "安全/审计/漏洞/加密/风险/红线",
         "kw": re.compile(r"(漏洞|注入|加密|风险|红线|审计|安全|shell|硬编码|凭证|密码|token)", re.I),
         "req": "必须过白帽猎捕 SAST 扫描 (SQL 注入/命令执行/硬编码/凭证泄露); 敏感数据 AES-256 加密; 禁止 print 调试敏感信息",
         "exp": "上线前 7 天内完成全量安全审计 + 漏洞修复 + 回归验证, 零 CRITICAL/HIGH 漏洞",
         "out": "形成安全基线库, 新系统自动过守卫拦截, 数据库 is locked 等常见问题减少 80%"},
    3:  {"code": "dev_flow",      "name": "开发流程中心",
         "focus": "dev/git/flask/commit/代码/规则",
         "kw": re.compile(r"(dev|git|flask|commit|代码|merge|review|ci|开发|流程|flow|branch)", re.I),
         "req": "必须 12 步开发流程 (STEP_1~STEP_12) + 合法 flow_id; 禁止无 flow_id 直接写代码; PR 必须 2 人 review + SA 终审",
         "exp": "每个 PR 都有完整 checklist 闭环, 零 SKIP 记录; daemon tick 自动推进状态机",
         "out": "开发流程铁律覆盖率 100%, MT_IR_STEP_SKIP 违规为 0, 代码质量趋势向上"},
    4:  {"code": "ai_engine",     "name": "AI 引擎中心",
         "focus": "ai/推理/脑库/ollama/向量/eigenflux/embedding",
         "kw": re.compile(r"(ollama|向量|embedding|推理|eigenflux|脑库|llm|模型|ai|引擎|专家|雇佣|群智)", re.I),
         "req": "必须三轨 LLM (星火→volc→local) 接入, 本地兜底不可少; EigenFlux 专家雇佣走 hire_batch + form_team + hr_registry; 禁止单轨依赖",
         "exp": "新引擎上线后 1 周内脑库知识块同步, 仙女座能感知新能力; 专家团队 72h 内 form_team 完成",
         "out": "AI 引擎矩阵能力覆盖度从 60%→95%, 三轨融合率 100%, EigenFlux 专家团队响应时间 < 30s"},
    5:  {"code": "workflow",      "name": "工作流研究中心",
         "focus": "工作流/workflow/流水线/调度/协同/编排",
         "kw": re.compile(r"(工作流|workflow|流水线|调度|编排|任务链|协作|daemon|tick)", re.I),
         "req": "必须挂入现有 daemon tick (15min 推进), 禁止写独立 cron; 任务状态机必须 transition_cas 并发安全",
         "exp": "新能力 3 天内被 daemon 接管, 自动状态推进 + 异常自动回滚",
         "out": "工作流流水线复用率 85%, 新能力上线时间从 3 天→1 天, 并发冲突减少 90%"},
    6:  {"code": "data_research", "name": "数据研究中心",
         "focus": "数据/分析/报告/统计/研究/画像",
         "kw": re.compile(r"(数据|分析|报告|统计|画像|etl|报表|学情|正确率|趋势|指标|kpi)", re.I),
         "req": "必须有学情画像自动更新 + 正确率统计 + 趋势分析; 数据落地走权威库 Database/app.db, 禁止创建新 DB 文件",
         "exp": "上线后 7 天内有完整数据看板 + 学情诊断报告, 每 1h 自动刷新",
         "out": "数据研究中心能复用新数据, 形成跨学科学情画像体系, 诊断覆盖率提升 40%"},
    7:  {"code": "frontend_design","name": "前端设计中心",
         "focus": "前端/设计/ui/页面/视觉/交互/冰山",
         "kw": re.compile(r"(前端|ui|页面|交互|设计token|渲染|组件|html|css|js|冰山|web|响应式|移动端)", re.I),
         "req": "必须对齐三套设计系统 (admin ins #4F46E5 / iceberg 教育风 / whitehat 终端风); 禁止内联样式/硬编码色值; 响应式断点 768/1024/1440",
         "exp": "新页面上线后 3 天内通过设计中心验收 (设计 token 合规 + 无渲染污染 + 移动端可访问)",
         "out": "前端设计系统统一率 100%, 冰山教育风覆盖率 95%, 渲染污染消除, 移动端体验提升"},
    106:{"code": "edu_qbank",    "name": "教育题库中心",
         "focus": "教育/题库/考试/备课/教学/讲解/试题",
         "kw": re.compile(r"(教育|题库|考试|教学|备课|试题|学情|组卷|批改|讲解|考点|学生|数学|物理|语文|化学)", re.I),
         "req": "必须与 mt_edu_sync_question_types 母题库联动; 造题走 create_questions + 母题变式模板; 组卷覆盖考点 ≥ 80%; 批改联动学情画像更新",
         "exp": "上线后 7 天内完成 3 个知识点造题 + 1 套试卷组卷 + 批改闭环; 学情画像 24h 内有新数据",
         "out": "教育题库中心题型覆盖度从 40%→85%, 学生画像数据密度翻倍, 个性化讲解命中率提升 50%"},
    467:{"code": "rules_gov",     "name": "规则治理中心",
         "focus": "规则/rule/变更/changelog/弱约束/违反/铁律/治理",
         "kw": re.compile(r"(规则|rule|变更|changelog|铁律|治理|违反|审计|合规|slc|lawyer|律师|法规|条例|条文|法案|法令|立法|法条)", re.I),
         "req": "必须走立法委 7 步流程 (提案→法案→法条→法令→AI 分身讨论→常委会表决→审计); 法条必须精确到操作级别, 禁止模糊表述",
         "exp": "新规则 3 天内走完立法流程 + 写入 mt_andromeda_rule_knowledge, 仙女座能感知; 立法委 AI 分身讨论 ≥ 5 角色",
         "out": "规则治理四轨落地率 100%, MT_IR_D1 STEP_1 缺失违规为 0, 立法效率提升 3x"},
    468:{"code": "legal",        "name": "法务合规中心",
         "focus": "法务/合规/legal/评审/风险/个保法/网安法/消保法",
         "kw": re.compile(r"(法务|合规|legal|风险|个保法|网安法|消保法|数据|隐私|脱敏|审计|合同|责任|赔偿|法律|条例|监管)", re.I),
         "req": "敏感数据 (姓名/手机号/IP/chat 内容) 必须脱敏; 禁止明文存储密码/token; 必须符合个保法/网安法/消保法三法合规",
         "exp": "上线前完成三法合规评审 + 脱敏审计 + 风险评估, 零 HIGH 风险项",
         "out": "法务合规审计效率提升 40%, 风险预警提前 7 天, 零合规事故"},
    469:{"code": "hr_center",    "name": "人事人力中心",
         "focus": "人事/人力/员工/雇佣/绩效/名册/roster",
         "kw": re.compile(r"(人力|人事|员工|雇佣|绩效|培训|认证|roster|注册|名册|考勤|薪酬|考核|eigenflux_expert|专家)", re.I),
         "req": "EigenFlux hire_batch 后必须 mt_hr_center_registry 注册 + mt_hr_training_log 培训 + mt_hr_certification 认证; 每提案 mt_lab_hr_log 必须有 DISPATCH 记录",
         "exp": "新专家 72h 内完成注册+培训+认证; 未入厅提案 < 总提案 5%; 周度人力报告自动生成",
         "out": "HR 中心数据密度从 0→N, 专家响应时间 < 30s, 合规培训覆盖率 100%"},
    470:{"code": "expert_team",  "name": "专家团队中心",
         "focus": "专家/eigenflux/磋商/表决/连线/心跳",
         "kw": re.compile(r"(专家|eigenflux|磋商|表决|连线|心跳|群智|多专家|团队|expert|hire|form_team)", re.I),
         "req": "EigenFlux 专家必须 form_team + 定期 heartbeat; 群智决策走 mt_expert_team_consultation_log 投票; 禁止单专家决定关键决策",
         "exp": "新团队 72h 内 form_team 完成, 每 24h heartbeat; 关键决策 3 专家≥2 通过",
         "out": "专家团队响应时间 < 30s, 群智决策覆盖率 100%, 专家利用率提升 60%"},
    471:{"code": "skill_dev",    "name": "Skill研发中心",
         "focus": "skill/技能/衍生/SKILL.md/能力库",
         "kw": re.compile(r"(skill|技能|衍生|SKILL.md|能力库|skill-creator|封装|模板|可复用|流水线|pipeline)", re.I),
         "req": "新能力必须封装为可复用 Skill (SKILL.md + frontmatter); 触发关键词必须覆盖中英双语; 禁止一次性硬编码不可复用逻辑",
         "exp": "新系统 3 天内封装为 Skill, 下次同类需求自动触发",
         "out": "Skill 复用率 85%, 新领域建设时间从 3 天→1 天, 重复代码减少 70%"},
    1421:{"code": "strategy_center","name": "战略中心",
         "focus": "战略/strategy/策略/规划/plan/决策/decision/进化",
         "kw": re.compile(r"(战略|strategy|策略|规划|plan|决策|decision|进化|evolution|方向|愿景|路线图|里程碑|ROI|收益|成本)", re.I),
         "req": "必须对齐战略路线图; 新系统必须有成本-收益分析 (ROI ≥ 2x); 禁止无战略对齐的孤立建设",
         "exp": "战略中心对每个新系统给出对齐评分 (1-10), 评分 < 5 需 SA 特批; 季度战略复盘自动关联新系统贡献",
         "out": "战略对齐率 95%, ROI 平均 3x, 资源浪费减少 60%"},
    1526:{"code": "vuln_fix",    "name": "漏洞修复适配中心",
         "focus": "漏洞/修复/安全/补丁/加固/适配",
         "kw": re.compile(r"(漏洞|修复|补丁|加固|适配|patch|fix|security|vuln|hardcode|shell|sql注入|命令执行|凭证泄露)", re.I),
         "req": "所有硬编码/凭证泄露/SQL 注入必须立即修复; 白帽猎捕 SAST 扫描零 CRITICAL/HIGH; 修复必须走 PR + 2 人 review",
         "exp": "漏洞发现后 24h 内修复 + 回归验证; SAST 扫描零 CRITICAL/HIGH; 修复 PR 全量 review",
         "out": "漏洞修复 SLA 从 72h→24h, 白帽猎捕告警 100% 响应, 系统安全水位提升"},
    1532:{"code": "supervision_brigade","name": "监察大队",
         "focus": "监察/督办/跟进/研究/完善/备案/回档/巡检/审计/复盘",
         "kw": re.compile(r"(监察|督办|跟进|研究|完善|备案|回档|巡检|审计|复盘|合规|violation|违反|MT_IR)", re.I),
         "req": "所有新系统上线后 7 天内监察大队巡检一次; 铁律违反必须立即告警 + 整改 + 回档; 禁止事后补录",
         "exp": "上线后 7 天内监察报告 + 问题清单; MT_IR_D1 STEP_1 缺失违规 24h 内整改; 周度巡检自动生成",
         "out": "监察覆盖率 100%, 铁律违反响应时间 < 24h, 系统健康度趋势向上"},
}


# ═══════════════════════════════════════════════════════════
# ② DDL
# ═══════════════════════════════════════════════════════════

CONSULT_DDL = """CREATE TABLE IF NOT EXISTS mt_center_proposal_consultations (
    consult_id INTEGER PRIMARY KEY AUTOINCREMENT,
    hall_task_id INTEGER NOT NULL,
    center_id INTEGER NOT NULL,
    center_code TEXT NOT NULL,
    center_name TEXT NOT NULL,
    perspective_type TEXT NOT NULL,       -- requirements / expectations / outlook
    perspective_text TEXT NOT NULL,
    match_score REAL DEFAULT 0,           -- 中心对提案的关键词匹配分
    created_at TEXT DEFAULT (datetime('now','localtime')),
    flow_id TEXT DEFAULT 'flow_all_center_consult_20261027',
    UNIQUE(hall_task_id, center_id, perspective_type)
)"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables():
    c = get_conn()
    c.execute(CONSULT_DDL)
    c.commit()
    c.close()


def _load_center_halls(conn, hall_code=None, hall_id=None):
    """加载待咨询的任务大厅记录"""
    if hall_id:
        return conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (hall_id,)).fetchone()
    if hall_code:
        return conn.execute("SELECT * FROM mt_lab_task_hall WHERE hall_code=?", (hall_code,)).fetchone()
    return conn.execute(
        "SELECT * FROM mt_lab_task_hall WHERE status IN ('QUEUED','DISPATCHED','IN_PROGRESS') "
        "ORDER BY id DESC LIMIT 20").fetchall()


def _compute_match_score(center_kw_re, proposal_text):
    """中心关键词与提案文本的匹配分 (0-1)"""
    if not proposal_text or not center_kw_re:
        return 0.0
    hits = center_kw_re.findall(proposal_text)
    unique_hits = set(h.lower() for h in hits)
    return min(1.0, len(unique_hits) / 8.0)  # 8 个 unique 词 = 100%


def generate_consultations(hall_task_id: int) -> int:
    """为单个任务生成所有中心的三方咨询, 返回写入条数"""
    conn = get_conn()
    task = conn.execute("SELECT * FROM mt_lab_task_hall WHERE id=?", (hall_task_id,)).fetchone()
    if not task:
        conn.close()
        print(f"[CONSULT] 任务 {hall_task_id} 不存在")
        return 0

    proposal_text = f"{task['title']} {task['description'] or ''}"
    hall_code = task['hall_code']

    written = 0
    for cid, profile in CENTER_PROFILES.items():
        score = _compute_match_score(profile["kw"], proposal_text)
        # 生成三方文本
        texts = {
            "requirements": f"[{profile['name']}] 针对《{task['title']}》的硬性要求: {profile['req']}",
            "expectations": f"[{profile['name']}] 针对《{task['title']}》的期盼: {profile['exp']}",
            "outlook": f"[{profile['name']}] 针对《{task['title']}》的展望: {profile['out']}",
        }
        for ptype, ptext in texts.items():
            conn.execute("""INSERT OR IGNORE INTO mt_center_proposal_consultations
(hall_task_id, center_id, center_code, center_name, perspective_type, perspective_text, match_score)
VALUES (?,?,?,?,?,?,?)""",
                         (hall_task_id, cid, profile["code"], profile["name"],
                          ptype, ptext, round(score, 3)))
            written += 1

    # 写跨中心协作记录 (复用 mt_lab_collab)
    centers_list = sorted(CENTER_PROFILES.keys())
    collab_existing = conn.execute(
        "SELECT id FROM mt_lab_collab WHERE hall_task_id=? AND mode='ALL_CENTER_CONSULT'",
        (hall_task_id,)).fetchone()
    if not collab_existing:
        conn.execute("""INSERT INTO mt_lab_collab
(hall_task_id, mode, primary_center_id, collab_center_ids, status, created_at)
VALUES (?,'ALL_CENTER_CONSULT',?,'[]','ACTIVE',datetime('now','localtime'))""",
                     (hall_task_id, task['center_id'] or 0))

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print(f"[CONSULT] ✅ {hall_code} 全 {len(CENTER_PROFILES)} 中心 × 3 视角 = {written} 条")
    return written


def generate_all_active():
    """对所有 ACTIVE 任务补生成"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, hall_code, title FROM mt_lab_task_hall "
        "WHERE status IN ('QUEUED','DISPATCHED','IN_PROGRESS')").fetchall()
    conn.close()
    total = 0
    for r in rows:
        try:
            n = generate_consultations(r["id"])
            total += n
        except Exception as e:
            print(f"[CONSULT] ⚠️ {r['hall_code']} 失败: {e}")
    print(f"\n[CONSULT] 全量完成: {total} 条写入")


def status(hall_task_id: int):
    conn = get_conn()
    rows = conn.execute("""SELECT center_id, center_name, perspective_type, perspective_text, match_score
FROM mt_center_proposal_consultations WHERE hall_task_id=? ORDER BY center_id, perspective_type""",
                         (hall_task_id,)).fetchall()
    print(f"\n=== 任务 {hall_task_id} 全中心咨询结果 ({len(rows)} 条) ===")
    current_center = None
    for r in rows:
        if r['center_id'] != current_center:
            current_center = r['center_id']
            print(f"\n── {r['center_name']} (id={r['center_id']}, score={r['match_score']}) ──")
        label = {"requirements": "① 要求", "expectations": "② 期盼", "outlook": "③ 展望"}[r['perspective_type']]
        print(f"  {label}: {r['perspective_text']}")
    conn.close()


if __name__ == "__main__":
    ensure_tables()
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", type=int, help="hall_task_id")
    ap.add_argument("--all", action="store_true", help="全量补生成")
    ap.add_argument("--status", type=int, help="查看结果")
    ap.add_argument("--demo", action="store_true", help="对数学任务演示")
    args = ap.parse_args()
    if args.once:
        generate_consultations(args.once)
    elif args.all:
        generate_all_active()
    elif args.status:
        status(args.status)
    elif args.demo:
        conn = get_conn()
        r = conn.execute("SELECT id FROM mt_lab_task_hall WHERE hall_code='TH-20261027-0011'").fetchone()
        conn.close()
        if r:
            generate_consultations(r['id'])
            status(r['id'])
        else:
            print("TH-20261027-0011 不存在")
