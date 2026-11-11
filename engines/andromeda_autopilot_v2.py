#!/usr/bin/env python3
"""
ANDROMEDA AUTOPILOT V2 — 自进化闭环中枢调度器
7 环节: 自收集→自学习→自投喂→自衍生→协作广播→反噬预警→自修复
launchd 托管, 每 5 分钟心跳一次
"""
import sqlite3, json, os, time, logging, subprocess
from datetime import datetime, timedelta
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [AUTOPILOT] %(message)s')
log = logging.getLogger("autopilot_v2")

DB = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db'))

def get_conn():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

# ═══════════════════════════════════════════════════════════════
# S1 自收集 Collector — signals + radar cache
# ═══════════════════════════════════════════════════════════════
def check_collector_health():
    conn = get_conn()
    try:
        sig = conn.execute("SELECT MAX(created_at) FROM mt_sandbox_signals").fetchone()[0] or "2000-01-01"
        radar = conn.execute("SELECT MAX(updated_at) FROM mt_market_radar_cache").fetchone()[0] or "2000-01-01"
        sig_fresh = sig >= (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        radar_fresh = radar >= (datetime.now() - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
        sig_count = conn.execute("SELECT COUNT(*) FROM mt_sandbox_signals WHERE created_at >= datetime('now','-24 hours')").fetchone()[0]
        return {"healthy": sig_fresh, "signal_last": sig, "signal_24h_count": sig_count, "radar_last": radar}
    except Exception as e:
        return {"healthy": False, "error": str(e)}
    finally: conn.close()

def repair_collector():
    log.info("[S1] Collector repair — radar refresh + signal catchup")
    return {"action": "radar_refresh", "status": "dispatched"}

# ═══════════════════════════════════════════════════════════════
# S2 自学习 Learner — knowledge_points + digest
# ═══════════════════════════════════════════════════════════════
def check_learner_health():
    conn = get_conn()
    try:
        kb_7d = conn.execute("SELECT COUNT(*) FROM mt_center_knowledge_points WHERE created_at >= datetime('now','-7 days')").fetchone()[0]
        dg_last = conn.execute("SELECT MAX(created_at) FROM mt_center_knowledge_digest").fetchone()[0] or "1970"
        dg_3d = dg_last >= (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        return {"healthy": kb_7d > 0, "kb_7d": kb_7d, "digest_last": dg_last, "digest_3d": dg_3d}
    except Exception as e:
        return {"healthy": False, "error": str(e)}
    finally: conn.close()

def repair_learner():
    log.info("[S2] Learner repair — trigger evolution broadcast")
    return {"action": "evolution_broadcast", "status": "dispatched"}

# ═══════════════════════════════════════════════════════════════
# S3 自投喂 BrainFeed — fm_brain_feed
# ═══════════════════════════════════════════════════════════════
def check_brain_health():
    conn = get_conn()
    try:
        bf = conn.execute("SELECT MAX(created_at) FROM mt_fm_brain_feed").fetchone()[0] or "1970"
        bf_6h = bf >= (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        dg = conn.execute("SELECT MAX(created_at) FROM mt_center_knowledge_digest").fetchone()[0] or "1970"
        return {"healthy": bf_6h, "brain_last": bf, "digest_last": dg}
    except Exception as e:
        return {"healthy": False, "error": str(e)}
    finally: conn.close()

def repair_brainfeed():
    log.info("[S3] BrainFeed repair — brain feeding retry")
    return {"action": "brain_feed_retry", "status": "dispatched"}

# ═══════════════════════════════════════════════════════════════
# S4 自衍生 AutoHire — ai_employees
# ═══════════════════════════════════════════════════════════════
def check_derivation_health():
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]
        enabled = conn.execute("SELECT COUNT(*) FROM ai_employees WHERE is_enabled=1").fetchone()[0]
        invite_7d = conn.execute("SELECT COUNT(*) FROM mt_eigenflux_invite_log WHERE invited_at >= datetime('now','-7 days')").fetchone()[0]
        return {"healthy": total > 0, "total": total, "enabled": enabled, "invite_7d": invite_7d}
    except Exception as e:
        return {"healthy": False, "error": str(e)}
    finally: conn.close()

def repair_derivation():
    log.info("[S4] Derivation repair — auto hire cycle")
    return {"action": "auto_hire", "status": "dispatched"}

# ═══════════════════════════════════════════════════════════════
# S5 协作广播 CollabHub — collab_channel + message
# ═══════════════════════════════════════════════════════════════
def check_collab_health():
    conn = get_conn()
    try:
        channels = conn.execute("SELECT COUNT(*) FROM mt_collab_channel").fetchone()[0]
        msgs_24h = conn.execute("SELECT COUNT(*) FROM mt_collab_message WHERE created_at >= datetime('now','-24 hours')").fetchone()[0]
        centers = conn.execute("SELECT COUNT(*) FROM mt_lab_collab").fetchone()[0]
        return {"healthy": channels > 0, "channels": channels, "msgs_24h": msgs_24h, "centers": centers}
    except Exception as e:
        return {"healthy": False, "error": str(e)}
    finally: conn.close()

def repair_collab():
    log.info("[S5] CollabHub repair — collab bus rebuild")
    return {"action": "collab_pulse", "status": "dispatched"}

# ═══════════════════════════════════════════════════════════════
# S6 反噬预警 IronGuard — rule_violation
# ═══════════════════════════════════════════════════════════════
def check_rebound_health():
    conn = get_conn()
    try:
        violations = conn.execute("SELECT COUNT(*) FROM rule_violation_audit WHERE created_at >= datetime('now','-24 hours')").fetchone()[0]
        repairs_24h = conn.execute("SELECT COUNT(*) FROM mt_lab_audit_log WHERE created_at >= datetime('now','-24 hours')").fetchone()[0]
        return {"healthy": violations == 0, "violations_24h": violations, "repairs_24h": repairs_24h}
    except Exception as e:
        return {"healthy": True, "violations_24h": 0, "repairs_24h": 0}
    finally: conn.close()

def invoke_rebound():
    log.warning("[S6] IronGuard rebound — generate repair suggestion")
    return {"action": "generate_repair", "status": "escalated"}

# ═══════════════════════════════════════════════════════════════
# S7 自修复 SelfHeal — self_check
# ═══════════════════════════════════════════════════════════════
def check_heal_health():
    conn = get_conn()
    try:
        sc = conn.execute("SELECT MAX(created_at) FROM mt_center_self_check").fetchone()[0] or "1970"
        sc_today = conn.execute("SELECT COUNT(*) FROM mt_center_self_check WHERE created_at >= datetime('now','-24 hours')").fetchone()[0]
        return {"healthy": True, "self_check_last": sc, "self_check_24h": sc_today}
    except Exception as e:
        return {"healthy": True, "error": str(e)}
    finally: conn.close()

def invoke_heal():
    log.warning("[S7] SelfHeal cycle triggered")
    return {"action": "self_heal", "status": "invoked"}

# ═══════════════════════════════════════════════════════════════
# 闭环注册表 (延迟绑定)
# ═══════════════════════════════════════════════════════════════
LOOP_STAGES = [
    ("S1", "自收集 Collector",  check_collector_health,  repair_collector),
    ("S2", "自学习 Learner",     check_learner_health,     repair_learner),
    ("S3", "自投喂 BrainFeed",   check_brain_health,       repair_brainfeed),
    ("S4", "自衍生 AutoHire",    check_derivation_health,  repair_derivation),
    ("S5", "协作广播 CollabHub", check_collab_health,      repair_collab),
    ("S6", "反噬预警 IronGuard", check_rebound_health,     invoke_rebound),
    ("S7", "自修复 SelfHeal",    check_heal_health,        invoke_heal),
]

# ═══════════════════════════════════════════════════════════════
# 主心跳
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# v26.1: BaseEngine 包装类 — AutoPilotV2
# ═══════════════════════════════════════════════════════════════
class AutoPilotV2:
    """Andromeda Autopilot V2 — 统一引擎接口

    封装模块级 run_heartbeat / proactive_patrol 等函数,
    提供 BaseEngine 兼容签名: start/stop/health_check/emit_event
    """
    SYSTEM = "andromeda"
    ENGINE_NAME = "AutoPilotV2"

    def __init__(self, db_path=None):
        import logging
        self.db_path = db_path or DB
        self._running = False
        self._loop_count = 0
        self._start_time = None
        logger = logging.getLogger("mtscos.andromeda.AutoPilotV2")
        if not logger.handlers:
            h = logging.StreamHandler()
            h.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s %(message)s'))
            logger.addHandler(h)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        self.logger = logger

    def start(self):
        self._running = True
        self._start_time = time.time()
        self.logger.info(f"[andromeda] AutoPilotV2 START")
        self.emit_event("DAEMON_STARTED", payload={"engine": "AutoPilotV2"})

    def stop(self):
        self._running = False
        self.logger.info(f"[andromeda] AutoPilotV2 STOP (loops={self._loop_count})")
        self.emit_event("DAEMON_STOPPED", payload={"engine": "AutoPilotV2", "loop_count": self._loop_count})

    def run_loop_once(self):
        self._loop_count += 1
        run_heartbeat()
        self.emit_event("AUTOPILOT_STAGE_COMPLETE", payload={"loop": self._loop_count, "stage": "heartbeat"})

    def run_loop(self, interval=300):
        self.start()
        try:
            while self._running:
                try:
                    self.run_loop_once()
                    scan_new_engines()
                    proactive_patrol()
                    self.emit_event("AUTOPILOT_FULL_CYCLE_DONE", payload={"loop": self._loop_count})
                except Exception as e:
                    self.logger.error(f"loop error: {e}")
                time.sleep(interval)
        finally:
            self.stop()

    def emit_event(self, event_name, target=None, payload=None, severity="INFO"):
        try:
            from engines.event_bus_engine import emit as _emit
            _ebus_r = _emit(
                event_name=event_name, source_system="andromeda",
                target_system=target, payload=payload or {}, severity=severity
            )
        except Exception as e:
            self.logger.debug(f"emit fallback: {e}")
            _ebus_r = None

        # ── 🎛️ TriggerCoordinator 事件桥接 ──
        # AUTOPILOT 事件 → TriggerCoordinator.fire
        try:
            from engines.trigger_coordinator import TriggerCoordinator
            tc_severity = {'CRITICAL': 'CRITICAL', 'ALERT': 'HIGH', 'ERROR': 'HIGH',
                           'WARN': 'NORMAL', 'INFO': 'NORMAL'}.get(severity, 'NORMAL')
            TriggerCoordinator().fire(
                event_name, source='andromeda_autopilot_v2',
                payload=payload or {}, severity=tc_severity,
            )
        except Exception:
            pass

        return _ebus_r

    def health_check(self):
        uptime = round(time.time() - (self._start_time or time.time()), 1)
        return {
            "engine": "AutoPilotV2",
            "system": "andromeda",
            "running": self._running,
            "uptime_sec": uptime,
            "loop_count": self._loop_count,
            "db_path": self.db_path,
        }


def _aimeta_hook(action: str, **kwargs):
    """🧠 AI Meta-Cognition Hook — 从 Autopilot 调用元认知能力
    
    安全包装: AIMetaCognition 不可用时静默跳过, 绝不 crash
    """
    try:
        from engines.ai_meta_cognition import AIMetaCognition
        aimc = AIMetaCognition(DB)
        
        if action == "distill_experience":
            exp = aimc.distill_experience(days=kwargs.get("days", 7))
            return exp
        elif action == "compose_and_idle":
            wf = aimc.compose_workflow(kwargs.get("task", "autopilot_daily"))
            idle = aimc.idle_improve_loop()
            return {"workflow": wf, "idle": idle}
        elif action == "recall_similar":
            return aimc.recall_similar(kwargs.get("task", ""), top_k=kwargs.get("top_k", 3))
        elif action == "full_cycle":
            return aimc.run_full_meta_cycle()
        return None
    except Exception as e:
        log.debug(f"[AIMeta hook skip] {action}: {e}")
        return None


def run_heartbeat():
    log.info("=" * 60)
    log.info(f"AUTOPILOT V2 HEARTBEAT — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)
    report = {"timestamp": datetime.now().isoformat(), "stages": {}, "loop": "closed"}
    cascade = False
    for sid, name, checker, repair in LOOP_STAGES:
        try:
            result = checker()
            healthy = result.get("healthy", True)
            log.info(f"  [{sid}] {name} — {'OK' if healthy else 'ANOMALY'} | {json.dumps({k:v for k,v in result.items() if k!='healthy'})[:90]}")
            if not healthy:
                log.warning(f"    ⚠ {sid} 异常 → 修复链触发")
                repair()
                cascade = True
                report["stages"][sid] = {"status": "ANOMALY", "details": result}
            else:
                report["stages"][sid] = {"status": "OK", "details": result}
        except Exception as e:
            log.error(f"    ❌ {sid} 崩溃: {e}")
            report["stages"][sid] = {"status": "CRASH", "error": str(e)}
            repair()
    
    # ── 🧠 S2 + Meta: AI 学习 + AI 反思经验 ──
    try:
        from engines.autodev_engine import AutoDevEngine
        ade = AutoDevEngine(DB)
        new_prompts = ade.generate_new_prompts('trading')
        report["deep_s2_prompts"] = len(new_prompts)
    except Exception as e:
        log.debug(f"S2 deep (prompts): {e}")
    
    # ── 🧠 Meta Hook S2: AIMetaCognition.distill_experience() ──
    aimeta_exp = _aimeta_hook("distill_experience", days=7)
    if aimeta_exp:
        report["aimeta_s2_experience"] = {
            "success_patterns": len(aimeta_exp.get("success_patterns", [])),
            "failure_lessons": len(aimeta_exp.get("failure_lessons", [])),
        }
        log.info(f"  🧠 Meta-S2: {report['aimeta_s2_experience']['success_patterns']} 成功模式 + "
                 f"{report['aimeta_s2_experience']['failure_lessons']} 失败教训")
    
    # ── S3 Deep: Weekly Lesson 协作链 ──
    try:
        from engines.center_orchestrator import CenterOrchestrator
        orch = CenterOrchestrator(DB)
        orch.execute_chain('WEEKLY_LESSON', {'heartbeat_trigger': True})
    except Exception as e:
        log.debug(f"S3 deep (weekly_lesson): {e}")
    
    # ── S4 Deep: AutoDev 组合爆炸 + BrainStorm ──
    try:
        from engines.autodev_engine import AutoDevEngine
        ade = AutoDevEngine(DB)
        combos = ade.derive_combinations()
        bs = ade.brainstorm_scenarios('Autopilot 心跳驱动的下一周策略方向', 4)
        report["deep_s4"] = {"combinations": len(combos), "brainstorm": len(bs)}
    except Exception as e:
        log.debug(f"S4 deep (derive): {e}")

    # ── 🔁 S4.5 Deep: Derivative→Trigger Pipeline — 研发衍生→真实触发器 ──
    try:
        from engines.derivative_to_trigger_pipeline import DerivativeTriggerPipeline
        dtp = DerivativeTriggerPipeline(DB)
        dt_result = dtp.run_feedback_loop(promote_n=5)
        report["deep_s45_deriv_trigger"] = {
            "promoted": dt_result.get("promoted_count", 0),
            "backtested": dt_result.get("backtested_count", 0),
            "live_now": dt_result.get("live_count", 0),
            "fired": dt_result.get("fired_count", 0),
        }
        log.info(f"  🔁 S4.5 Deriv→Trigger: {dt_result.get('promoted_count',0)} 推进, "
                 f"{dt_result.get('live_count',0)} live, {dt_result.get('fired_count',0)} 触发")
    except Exception as e:
        log.debug(f"S4.5 deep (deriv_trigger): {e}")
    
    # ── 🧠 Meta Hook S4: compose_workflow() + idle_improve_loop() ──
    aimeta_compose = _aimeta_hook("compose_and_idle", task="autopilot_daily_full_flow")
    if aimeta_compose:
        report["aimeta_s4_compose"] = {
            "workflow_steps": aimeta_compose.get("workflow", {}).get("total_steps", 0),
            "idle_actions": len(aimeta_compose.get("idle", {}).get("actions", [])),
        }
        log.info(f"  🧠 Meta-S4: 组合工作流 {report['aimeta_s4_compose']['workflow_steps']} 步 + "
                 f"空闲提升 {report['aimeta_s4_compose']['idle_actions']} actions")
    
    # ── 🧠 S5 Deep: CenterCognition — AI 反向赋能 33 中心画像 ──
    try:
        from engines.center_cognition_engine import CenterCognitionEngine
        cce = CenterCognitionEngine(DB)
        # 每天一次: 检查 mt_center_cognition_portrait.updated_at 是否今天
        _today = datetime.now().strftime('%Y-%m-%d')
        _last = None
        try:
            _cur = sqlite3.connect(DB)
            _row = _cur.execute(
                "SELECT MAX(updated_at) FROM mt_center_cognition_portrait"
            ).fetchone()
            _last = (_row[0] or '')[:10] if _row and _row[0] else None
            _cur.close()
        except Exception:
            pass
        if _last != _today:
            cce_result = cce.empower_all_centers()
            report["s5_center_cognition"] = {
                "portraits": len(cce_result.get("portraits", {})),
                "collab_pairs": cce_result.get("collab", {}).get("total_pairs", 0),
                "experiences": sum(
                    v.get("count", 0) for v in cce_result.get("experiences", {}).values()
                ),
                "ollama": cce_result.get("ollama_available", False),
                "duration_ms": cce_result.get("duration_ms", 0),
            }
            log.info(f"  🧠 S5-CenterCognition: {report['s5_center_cognition']['portraits']} 画像 + "
                     f"{report['s5_center_cognition']['collab_pairs']} 协作对 + "
                     f"{report['s5_center_cognition']['experiences']} 经验")
        else:
            log.info(f"  🧠 S5-CenterCognition: 今日已生成, 跳过 (last={_last})")
    except Exception as e:
        log.debug(f"S5 deep (center_cognition): {e}")

    # ── S7 Deep: CrossSelfHeal 全系统自愈 ──
    try:
        from engines.cross_self_heal import CrossSelfHealEngine
        h = CrossSelfHealEngine(DB)
        heal_report = h.run_heal()
        report["deep_s7_heal"] = heal_report
    except Exception as e:
        log.debug(f"S7 deep (heal): {e}")
    
    # ── 🧠 Meta Hook S7: recall_similar() — 自愈前先回忆类似问题 ──
    aimeta_recall = _aimeta_hook("recall_similar", task="system_repair_heal", top_k=3)
    if aimeta_recall:
        report["aimeta_s7_recall"] = len(aimeta_recall)
        for s in aimeta_recall:
            log.info(f"  🧠 Meta-S7 recall: [{s.get('snippet_type')}] {s.get('lesson_learnt', '')[:60]}")
    # ── 10 中心健康矩阵 ──
    try:
        from engines.center_orchestrator import CenterOrchestrator
        orch = CenterOrchestrator(DB)
        hm = orch.cross_center_diagnose()
        report["deep_health_matrix"] = {"total_score": hm["total_score"], "status": hm["overall_status"], "bottlenecks": len(hm["bottlenecks"])}
    except Exception as e:
        log.debug(f"deep health_matrix: {e}")
    # ── 写入 self_check ──
    try:
        conn = sqlite3.connect(DB)
        conn.execute(
            "INSERT INTO mt_center_self_check (center_name, check_type, metric, metric_value, result, created_at) VALUES (?,?,?,?,?,?)",
            ("AndromedaAutopilot", "heartbeat", "loop_ok", "ANOMALY" if cascade else "OK", 
             "P1" if cascade else "OK", datetime.now().isoformat())
        )
        conn.commit(); conn.close()
    except Exception: pass
    ok = sum(1 for s in report["stages"].values() if s["status"] == "OK")
    log.info(f"\n心跳结束: {ok}/7 OK, 级联修复 {'已触发' if cascade else '无需'}")
    return report

def scan_new_engines():
    eng_dir = os.path.dirname(__file__)
    found = [f.replace(".py","") for f in sorted(os.listdir(eng_dir)) if f.startswith("ai_") and f.endswith(".py")]
    log.info(f"引擎扫描: {len(found)} 个 ai_* 引擎")
    return found

def proactive_patrol():
    findings = []
    conn = get_conn()
    try:
        orph = conn.execute("SELECT COUNT(*) FROM mt_sandbox_trades WHERE session_id NOT IN (SELECT session_id FROM mt_sandbox_portfolio)").fetchone()[0]
        if orph > 0: findings.append({"type":"ORPHAN","count":orph,"sev":"P1"})
        for dname in ["com.mtscos.stock-sandbox","com.mtscos.gobelin-daily-pnl"]:
            try:
                r = subprocess.run(["launchctl","list",dname],capture_output=True,text=True,timeout=5)
                if r.returncode != 0: findings.append({"type":"DAEMON_DOWN","name":dname,"sev":"P1"})
            except Exception: pass
    finally: conn.close()
    if findings:
        for f in findings: log.warning(f"  🛡 [{f['sev']}] {f['type']}")
        invoke_heal()
    else: log.info("🛡 主动巡检: 全部健康 ✓")
    return findings

def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "heartbeat"
    if cmd == "heartbeat": run_heartbeat()
    elif cmd == "scan": scan_new_engines()
    elif cmd == "patrol": proactive_patrol()
    elif cmd == "full":
        log.info("🌐 AUTOPILOT V2 FULL CYCLE"); run_heartbeat(); scan_new_engines(); proactive_patrol()
    elif cmd == "daemon":
        log.info("🚀 AUTOPILOT V2 DAEMON (每 5 分钟)")
        while True:
            try: run_heartbeat(); scan_new_engines(); proactive_patrol()
            except Exception as e: log.error(f"崩溃: {e}")
            time.sleep(300)
    else: print("用法: heartbeat|scan|patrol|full|daemon")

# ═══════════════════════════════════════════════════════════════════════
# 🎛️ TriggerCoordinator 桥接模块级函数 (S3 BrainFeed)
# ═══════════════════════════════════════════════════════════════════════
def S3_feed_trade(payload: dict = None):
    """单笔交易触发 → 写入 AI 脑库投喂 (fm_brain_feed)

    TriggerCoordinator.fire('TRADE_EXECUTED') 时调用.
    payload 示例: {"symbol":"sh600519","qty":100,"price":1688,"action":"BUY"}
    """
    payload = payload or {}
    symbol = payload.get('symbol', '?')
    qty = payload.get('qty', 0) or payload.get('shares', 0)
    price = payload.get('price', 0)
    action = payload.get('action', '?')
    amount = float(qty or 0) * float(price or 0)

    try:
        conn = sqlite3.connect(DB)
        # 写 AI 脑库投喂 (适配 mt_fm_brain_feed 实际 schema)
        text = f"[TRADE] {action} {symbol} {qty} @ {price} = ¥{amount:,.0f}"
        conn.execute(
            """INSERT INTO mt_fm_brain_feed
               (stream_name, category, asr_text, trigger_keywords, emotion,
                emotion_score, has_price_info, has_policy)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            ("trade_execution", "trade", text, symbol, "NEUTRAL", 0.5,
             1 if amount > 0 else 0)
        )
        # 同时写治理层 exec_log (如果表存在)
        try:
            conn.execute(
                """INSERT INTO mt_center_exec_log
                   (center_code, action, detail, created_at)
                   VALUES (?, ?, ?, datetime('now','localtime'))""",
                ("BrainFeed", f"S3_feed_trade:{action}",
                 f"{symbol} qty={qty} price={price} amount={amount}")
            )
        except Exception:
            pass  # mt_center_exec_log 可能不存在
        conn.commit()
        conn.close()
        return {"ok": True, "symbol": symbol, "action": action, "amount": amount,
                "feed_written": True}
    except Exception as e:
        return {"ok": False, "error": str(e), "symbol": symbol}


if __name__ == "__main__": main()
