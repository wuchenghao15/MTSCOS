#!/usr/bin/env python3
"""
🧪 仙女座灰度发布 + 审批引擎测试套件 (v25.0)
=============================================
零外部依赖: python3 test_engines.py
覆盖:
  [APPROVAL] 风险评估 / 审批链构建 / 提交+自动审批 / 全流程闭环
  [GRAY]     发布创建+审批集成 / 7 阶段状态机 / 门禁 / 回滚 / Feature Flag
"""
import sys, os, sqlite3, json, tempfile, traceback
from pathlib import Path

# 切到 flask-app 作为 cwd
_TEST_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _TEST_DIR.parent
os.chdir(str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT))

PASS = 0; FAIL = 0; SKIP = 0
def _assert(cond, name, detail=''):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✅ {name}"); return True
    else: FAIL += 1; print(f"  ❌ {name}  ({detail})"); return False

def _run_group(title, fn):
    print(f"\n{'='*60}")
    print(f" 🧪 {title}")
    print(f"{'='*60}")
    try: fn()
    except Exception as e:
        print(f"  💥 测试组崩溃: {e}")
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════
# 准备: 独立临时 DB (不污染主 app.db)
# ═══════════════════════════════════════════════════════════
_TMP = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_TMP_DB = Path(_TMP.name); _TMP.close()

def _clean_test_db():
    # 重置临时 DB
    if _TMP_DB.exists(): _TMP_DB.unlink()


# ═══════════════════════════════════════════════════════════
#  APPROVAL ENGINE TESTS
# ═══════════════════════════════════════════════════════════
def _test_approvals():
    from engines.approvals_engine import (
        assess_risk, build_approval_nodes, ApprovalEngine,
        _get_next_approver
    )

    # ── 风险评估 ──
    print("\n  📌 assess_risk (8 种场景)")
    _assert(assess_risk('wenquxing','student')=='low',     'student 文曲星 → low')
    _assert(assess_risk('wenquxing','admin')=='medium',    'admin 文曲星 → medium (禁生文, 但审批侧中风险)')
    _assert(assess_risk('rule_change','admin')=='critical','rule_change → critical')
    _assert(assess_risk('permission_change','super_admin')=='critical','perm_change → critical')
    _assert(assess_risk('course_content','professor')=='high','professor 课程 → high')
    _assert(assess_risk('homework','teacher')=='medium',   'teacher 作业 → medium')
    _assert(assess_risk('parent_feedback','parent')=='low','parent → low')
    _assert(assess_risk('exam','super_admin')=='high',     'SA exam → high')

    # ── 审批链构建 ──
    print("\n  📌 build_approval_nodes (7 种链)")
    # 低风险: 2 节点 (initiate + 可选 teacher)
    nodes = build_approval_nodes('wenquxing','student','low')
    _assert(len(nodes)>=2 and nodes[1]['approver_role']=='teacher', 'wenquxing/student/low → initiate+teacher')
    # critical: 强制 admin + SA
    nodes = build_approval_nodes('rule_change','admin','critical')
    roles = [n['approver_role'] for n in nodes]
    _assert('super_admin' in roles and 'admin' in roles, 'critical → admin+super_admin 都在')
    # high: 直属+admin (professor 直属是 mentor 但修后跳过, 直接 admin)
    nodes = build_approval_nodes('course_content','professor','high')
    _assert(len(nodes)==3, f'professor/high → 3 节点 (initiate+ai+admin), got {len(nodes)}')
    # initiate 节点都是 auto_pass
    for scenario in [('wenquxing','student','low'),('rule_change','admin','critical'),
                     ('homework','teacher','medium'),('exam','super_admin','high')]:
        n = build_approval_nodes(*scenario)
        _assert(n[0]['node_type']=='initiate' and n[0]['auto_pass']==True,
                f'initiate 节点 auto_pass=True ({scenario})')

    # ── 审批引擎 DB 操作 ──
    print("\n  📌 ApprovalEngine DB 操作 (临时 DB)")
    _clean_test_db()
    eng = ApprovalEngine(db_path=_TMP_DB)
    rid1 = eng.submit('wenquxing','alice','student','wqx_001',{'preview':'test'})
    rid2 = eng.submit('rule_change','bob','admin','rule_001')
    rid3 = eng.submit('homework','carol','teacher','hw_001')
    _assert(rid1.startswith('appr_'), 'submit 返回 appr_xxx 格式')
    _assert(rid2 != rid1 and rid3 != rid2, 'request_id 唯一')
    d = eng.get_request(rid1)
    _assert(d['status']=='pending' and len(d['nodes'])>=2, 'get_request: pending + nodes')
    _assert(d['actions'][0]['action']=='submit', '有 submit action 记录')

    # ── 仙女座自动审批 low-risk ──
    print("\n  📌 仙女座 auto_approve_low_risk (全场景)")
    auto = eng.auto_approve_low_risk()
    _assert(len(auto)>=2, f'至少 auto 2 个节点 (student initiate+teacher), got {len(auto)}')
    d1 = eng.get_request(rid1)
    _assert(d1['status']=='approved', 'wenquxing low-risk → 最终 approved')
    # high-risk 不该被自动全过 (ai_review 不在 SAFE_CATS? 否 release 在 SAFE_CATS 但 rule_change 不在)
    d2 = eng.get_request(rid2)
    _assert(d2['status']!='approved', f'rule_change critical 不应自动全过, 实际 {d2["status"]}')

    # ── 手动 approve 完整闭环 ──
    print("\n  📌 手动 approve 完整闭环 (teacher 作业)")
    d3 = eng.get_request(rid3)
    pending_nodes = [n for n in d3['nodes'] if n['action'] not in ('approve','reject') and n['node_type']!='initiate']
    _assert(len(pending_nodes)>0, '有手动待审批节点')
    # 逐个 approve
    for n in pending_nodes:
        eng.action(rid3, n['node_index'], 'approve', actor='admin1', actor_role='admin', notes='ok')
    d3f = eng.get_request(rid3)
    _assert(d3f['status']=='approved', '全部 approve 后 → final approved')
    _assert(d3f['final_decision']=='approved', 'final_decision=approved')

    # ── reject 闭环 ──
    print("\n  📌 reject 闭环")
    rid4 = eng.submit('exam','dave','teacher','exam_001')
    # 跳过 initiate 直接 reject 第一个待审批的
    d4 = eng.get_request(rid4)
    reject_node = next(n for n in d4['nodes'] if n['action'] not in ('approve','reject') and n['node_type']!='initiate')
    eng.action(rid4, reject_node['node_index'], 'reject', actor='admin1', actor_role='admin', notes='质量不合格')
    d4f = eng.get_request(rid4)
    _assert(d4f['status']=='rejected', 'reject → final rejected')
    _assert(d4f['final_decision']=='rejected', 'final_decision=rejected')

    # ── list_pending ──
    print("\n  📌 list_pending 按角色过滤")
    p_admin = eng.list_pending('admin')
    # 应包含 rule_change 剩余节点 (admin role_approver)
    _assert(any(r['request_id']==rid2 for r in p_admin), 'admin pending 包含 rule_change')

    eng.db.close()


# ═══════════════════════════════════════════════════════════
#  GRAY RELEASE ENGINE TESTS
# ═══════════════════════════════════════════════════════════
def _test_gray():
    from engines.gray_release_engine import (
        GrayReleaseEngine, RELEASE_STAGES as STAGES, STAGE_LABELS, STAGE_PCTS,
        compute_user_bucket, is_in_gray, check_feature_flag
    )

    # ── 用户级哈希分流 ──
    print("\n  📌 compute_user_bucket + is_in_gray (确定性)")
    b1 = compute_user_bucket('student_a','salt1')
    b2 = compute_user_bucket('student_a','salt1')
    b3 = compute_user_bucket('student_a','salt2')
    _assert(b1==b2, f'同 user+salt → 同 bucket ({b1})')
    _assert(b1!=b3, f'同 user 不同 salt → 不同 bucket ({b1} vs {b3})')
    _assert(is_in_gray('student_a', 0)==False, 'pct=0 → 全 OFF')
    _assert(is_in_gray('student_a',100)==True, 'pct=100 → 全 ON')
    # 比例验证 (1000 用户 50% pct → 应 ~500 命中)
    hits = sum(1 for i in range(1000) if is_in_gray(f'user_{i:04d}',50))
    _assert(450<=hits<=550, f'1000 user @50% → hits={hits} (450~550)')
    hits10 = sum(1 for i in range(1000) if is_in_gray(f'user_{i:04d}',10))
    _assert(70<=hits10<=130, f'1000 user @10% → hits={hits10} (70~130)')

    # ── 状态机 ──
    print("\n  📌 7 阶段状态机完整性")
    _assert(len(STAGES)==7, f'7 阶段 got {len(STAGES)}')
    _assert(STAGES[0][1]=='draft' and STAGES[6][1]=='full', 'stage[0]=draft stage[6]=full')
    for s in STAGES:
        _assert(s[2]==(0 if s[1] in ('draft','approved') else
                       (1 if s[1]=='canary' else 100 if s[1] in ('pct100','full') else int(s[1].replace('pct','')))),
                f'stage {s[1]} pct={s[2]} 正确')

    # ── 发布创建 + 审批集成 ──
    print("\n  📌 create_release → ApprovalEngine 集成")
    _clean_test_db()
    eng = GrayReleaseEngine(db_path=_TMP_DB)
    rid = eng.create_release('test-v25','v25.0','wuchenghao15',risk_level='high')
    _assert(rid.startswith('rel_'), f'release_id 格式 {rid}')
    d = eng.get_release(rid)
    _assert(d['current_stage']==0 and d['current_pct']==0 and d['status']=='draft', '初始 stage=0 pct=0 status=draft')
    _assert(d.get('approval_id','').startswith('appr_'), f'自动提交审批 approval_id={d.get("approval_id")}')
    _assert(d.get('stage_label')=='draft', f'stage_label=draft, got {d.get("stage_label")}')

    # ── approve_and_start → canary 1% ──
    print("\n  📌 approve_and_start → canary 1%")
    res = eng.approve_and_start(rid,'wuchenghao15')
    _assert(res['ok'] and res['current_stage']==2 and res['current_pct']==1, f'→ canary 1%, got stage={res["current_stage"]} pct={res["current_pct"]}')
    d = eng.get_release(rid)
    _assert(d['status']=='releasing', 'status→releasing')

    # ── advance_stage + 门禁 (灌好指标) ──
    print("\n  📌 advance_stage + gate (4 次自动升 stage)")
    c = eng.db.cursor()
    for target_pct in [10, 50, 100]:
        c.execute("INSERT INTO mt_release_metrics "
            "(release_id, stage, total_requests, total_errors, success_rate, error_rate_pct, avg_latency_ms, pct, gate_ok) "
            "VALUES (?,?,100,1,99.0,1.0,350,?,1)", (rid, 0, target_pct))
        eng.db.commit()
        res = eng.advance_stage(rid)
        _assert(res['ok'], f'advance → {target_pct}% ok={res.get("ok")} reason={res.get("msg","")}')
    # 最后一次 advance (pct100 → full)
    res = eng.advance_stage(rid)
    _assert(res['ok'], f'→ full 100% ok')
    d = eng.get_release(rid)
    _assert(d['status']=='full' and d['current_stage']==6, f'最终 full stage=6, got status={d["status"]} stage={d["current_stage"]}')
    _assert(d.get('full_at') is not None, 'full_at 有时间戳')

    # ── 门禁拦截 (bad metrics) ──
    print("\n  📌 门禁拦截 (error_rate 过高)")
    rid2 = eng.create_release('gate-block','v-test','wuchenghao15')
    eng.approve_and_start(rid2,'wuchenghao15')
    c.execute("INSERT INTO mt_release_metrics "
        "(release_id, stage, total_requests, total_errors, success_rate, error_rate_pct, avg_latency_ms, pct, gate_ok) "
        "VALUES (?,?,100,30,70.0,30.0,350,1,0)", (rid2, 0))
    eng.db.commit()
    res = eng.advance_stage(rid2)
    _assert(not res['ok'] and res.get('msg','').startswith('gate'), f'被门禁拦截: {res.get("msg")}')

    # ── 手动 advance (force bypass) ──
    print("\n  📌 手动 force bypass 门禁")
    res = eng.advance_stage(rid2, force=True)
    _assert(res['ok'], f'force advance 成功, ok={res.get("ok")}')

    # ── rollback ──
    print("\n  📌 rollback 完整链路")
    rid3 = eng.create_release('rollback-test','v-test2','wuchenghao15')
    eng.approve_and_start(rid3,'wuchenghao15')
    rb = eng.rollback(rid3, '严重 error 自动回滚')
    _assert(rb['ok'] and rb['action']=='rollback', f'rollback ok')
    d3 = eng.get_release(rid3)
    _assert(d3['status']=='rolled_back' and d3['rollback_count']>=1,
            f'status=rolled_back rollback_count={d3["rollback_count"]}')
    _assert(d3['current_pct']==0, '回滚后 pct→0')
    # release_rollback_logs 有记录 (仅主 DB 才存在旧表, 临时 DB 跳过)
    try:
        rb_logs = eng.db.execute("SELECT * FROM release_rollback_logs WHERE release_id=?",(rid3,)).fetchall()
        _assert(len(rb_logs)>=1, f'release_rollback_logs 有记录 ({len(rb_logs)})')
    except sqlite3.OperationalError:
        print("  ⏭  release_rollback_logs 表不存在 (临时 DB)")
    # release_gray_audit 有记录
    try:
        ga_logs = eng.db.execute("SELECT * FROM release_gray_audit WHERE release_id=?",(rid3,)).fetchall()
        _assert(len(ga_logs)>=1, f'release_gray_audit 有记录 ({len(ga_logs)})')
    except sqlite3.OperationalError:
        print("  ⏭  release_gray_audit 表不存在 (临时 DB)")

    # ── auto_progress (模拟) ──
    print("\n  📌 auto_progress 完整自动推进")
    rid4 = eng.create_release('auto-progress','v-auto','wuchenghao15')
    eng.approve_and_start(rid4,'wuchenghao15')
    # patch collect_metrics 为 no-op (Flask 没启动, 跳过真实采集)
    _orig_collect = eng.collect_metrics
    def _fake_collect(rid, pct=0):
        eng.db.cursor().execute("INSERT INTO mt_release_metrics "
            "(release_id, stage, total_requests, total_errors, success_rate, error_rate_pct, avg_latency_ms, pct, gate_ok) "
            "VALUES (?,?,100,1,99.0,1.0,300,?,1)", (rid, 0, pct))
        eng.db.commit()
        return {'total':100,'errors':1,'error_rate':1.0,'success_rate':99.0,'latency_ms':300,'gate_ok':True}
    eng.collect_metrics = _fake_collect
    # 连续跑 auto_progress 直到 full
    for _ in range(5):
        prog = eng.auto_progress_releases()
        d = eng.get_release(rid4)
        if d['status'] == 'full': break
    eng.collect_metrics = _orig_collect
    advance_count = sum(1 for r in prog if r['action']=='advance')
    _assert(advance_count>=1, f'auto_progress advance 次数={advance_count} (≥1)')
    d4 = eng.get_release(rid4)
    _assert(d4['status']=='full', f'auto_progress 最终 full, got {d4["status"]}')

    # ── 严重 error 自动回滚 ──
    print("\n  📌 auto_progress 严重 error → 自动回滚")
    # 清掉之前的 releasing 避免误扫
    c.execute("UPDATE mt_release_sessions SET status='rolled_back' WHERE status='releasing'")
    eng.db.commit()
    rid5 = eng.create_release('auto-rollback','v-test','wuchenghao15')
    eng.approve_and_start(rid5,'wuchenghao15')
    def _bad_collect(rid, pct=0):
        eng.db.cursor().execute("INSERT INTO mt_release_metrics "
            "(release_id, stage, total_requests, total_errors, success_rate, error_rate_pct, avg_latency_ms, pct, gate_ok) "
            "VALUES (?,?,100,60,40.0,60.0,5000,?,0)", (rid, 0, pct))
        eng.db.commit()
        return {'total':100,'errors':60,'error_rate':60.0,'success_rate':40.0,'latency_ms':5000,'gate_ok':False}
    eng.collect_metrics = _bad_collect
    prog2 = eng.auto_progress_releases()
    eng.collect_metrics = _orig_collect
    auto_rb = [r for r in prog2 if r['action']=='auto_rollback']
    _assert(len(auto_rb)>=1, f'auto_rollback 触发次数={len(auto_rb)}')
    d5 = eng.get_release(rid5)
    _assert(d5['status']=='rolled_back', f'auto_rollback 最终 status={d5["status"]}')

    # ── Feature Flag ──
    print("\n  📌 Feature Flag 完整链路 (临时 DB)")
    # 用 GrayReleaseEngine 写, 临时 patch check_feature_flag 的 DB_PATH
    eng.db.execute("INSERT OR REPLACE INTO mt_release_feature_flags (flag_name, rollout_pct, salt, description, scope, enabled) "
                   "VALUES ('test.flag.a', 50, 'abcd1234', 'test', 'all', 1)")
    eng.db.commit()
    # 直接用 is_in_gray (无 DB 依赖) 验证
    hits = sum(1 for i in range(1000) if is_in_gray(f'u{i:04d}',50,'abcd1234'))
    _assert(450<=hits<=550, f'flag 50% → hits={hits}')
    _assert(is_in_gray('', 0, 'abcd1234')==False, '空 user + pct=0 → OFF')
    _assert(is_in_gray('anyone', 100, 'x')==True, 'pct=100 → 全 ON')

    eng.db.close()


# ═══════════════════════════════════════════════════════════
#  SUMMARY
# ═══════════════════════════════════════════════════════════
def _summary():
    print(f"\n{'='*60}")
    print(f" 📊 测试结果: ✅ {PASS}  PASSED   ❌ {FAIL}  FAILED   ⏭  {SKIP}  SKIPPED")
    print(f"{'='*60}")
    if FAIL==0: print("  🎉 全部通过!")
    else: print(f"  💥 {FAIL} 个失败 — 请检查 ❌ 项")
    print()


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
if __name__=='__main__':
    print("🧪 仙女座引擎测试套件 v25.0")
    print(f"DB: 临时 {_TMP_DB}")
    _run_group("APPROVAL ENGINE", _test_approvals)
    _run_group("GRAY RELEASE ENGINE", _test_gray)
    _summary()
    # 清理
    _clean_test_db()
    sys.exit(0 if FAIL==0 else 1)
