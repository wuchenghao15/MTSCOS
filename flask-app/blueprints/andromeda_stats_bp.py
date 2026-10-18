# -*- coding: utf-8 -*-
"""仙女座工作全景统计系统 — v1.0 (flow_andromeda_stats_20261016)

聚合仙女座自激活以来全部智能操作拐点事件:
  自研发(§14 flow) / 自拉活(雇佣+建议池) / 自维护(挂载决策+进程)
  自修复(铁律违反+告警+CHAT-HEAL) / 自升级 / 自学习(规则+脑库+本地推理) / 自巡逻(Arduino扫描)
输出: 概览KPI + 分类柱状图数据 + 月度趋势 + 事件明细表 + 缺口分析 + 研发联动派发
"""
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from blueprints.chat_local_bp import _login_required, _resolve_db_path

andromeda_stats_bp = Blueprint('andromeda_stats', __name__)

FLOW_ID = "flow_andromeda_stats_20261016"

# ── 事件源注册表: (分类, 表, 时间列, 标题表达式, 详情表达式, 行为者表达式) ──
# 全部防御式查询: 表缺失/列漂移自动跳过, 不阻塞整页
EVENT_SOURCES = [
    ("自研发", "mt_dev_flow_session", "created_at",
     "COALESCE(proposal_title, flow_id)", "current_step || ' / ' || COALESCE(final_status,'')",
     "COALESCE(created_by,'system')", "flow_id"),
    ("自研发", "mt_dev_flow_events", "triggered_at",
     "event_kind || ' ' || COALESCE(flow_id,'')", "COALESCE(from_step,'') || '→' || COALESCE(to_step,'')",
     "COALESCE(triggered_by,'AI')", "COALESCE(event_payload_json,'')"),
    ("自拉活", "mt_ai_auto_hire_log", "hired_at",
     "COALESCE(hire_type,'hire') || ' ' || COALESCE(employee_name,'')", "COALESCE(employee_role,'')",
     "COALESCE(source,'auto_hire')", "hire_id"),
    ("自拉活", "mt_ai_suggestion_pool", "created_at",
     "COALESCE(suggestion_text,'')", "status || ' priority=' || COALESCE(priority,0)",
     "COALESCE(source_name, source_type, 'suggestion')", "suggestion_id"),
    ("自维护", "mt_ai_mount_decisions", "created_at",
     "COALESCE(suggestion_text,'(挂载决策)')", "COALESCE(decision,'') || ' score=' || COALESCE(final_score,0)",
     "smart_mount", "decision_id"),
    ("自维护", "mt_ai_smart_mount_processes", "created_at",
     "COALESCE(process_name,'') || ' 挂载'", "'state=' || COALESCE(current_state,'') || ' restarts=' || COALESCE(restart_count,0)",
     "COALESCE(mount_source,'smart_mount')", "process_id"),
    ("自修复", "mt_iron_rule_violations", "created_at",
     "COALESCE(viol_rule,'') || ' ' || COALESCE(viol_stage,'')", "COALESCE(viol_action,'')",
     "iron_rule", "viol_id"),
    ("自修复", "mt_rule_violation_alert", "created_at",
     "COALESCE(violation_code, alert_type, 'violation_alert')",
     "COALESCE(severity,'') || ' ' || COALESCE(description,'')", "alert_feed", "alert_id"),
    ("自修复", "mt_ai_rule_enforcement_log", "created_at",
     "COALESCE(rule_id, violation_code, 'enforcement')", "COALESCE(action_taken,'')",
     "COALESCE(operator,'rule_enforcer')", "enforcement_id"),
    ("自修复", "mt_chat_heal_flow_binding", "bound_at",
     "'CHAT-HEAL ' || COALESCE(heal_type,'')", "'flow=' || COALESCE(flow_id,'') || ' alert=' || COALESCE(alert_id,'')",
     "chat_heal", "binding_id"),
    ("自学习", "mt_ai_rule_learning_log", "learned_at",
     "'规则学习 ' || COALESCE(rule_id,'') || ' ' || COALESCE(rule_version,'')", "COALESCE(learn_summary,'')",
     "COALESCE(learned_by,'ai')", "learn_id"),
    ("自学习", "mt_ai_brain_feed_log", "fed_at",
     "'脑库投喂 ' || COALESCE(feed_target,'')", "COALESCE(payload_preview,'')",
     "COALESCE(fed_by,'ai')", "feed_id"),
    ("自学习", "mt_local_ai_inference_log", "triggered_at",
     "'本地推理 ' || COALESCE(inference_kind,'')",
     "COALESCE(model_name,'') || ' tokens_saved=' || COALESCE(tokens_saved,0)",
     "COALESCE(source,'local_ai')", "id"),
    ("自巡逻", "mt_arduino_detect_log", "scanned_at",
     "'Arduino设备扫描 found=' || COALESCE(devices_found,0)", "COALESCE(scan_status,'')",
     "arduino_detect", "scan_id"),
]

# 升级关键词: 命中则从"自研发"重分类为"自升级"
_UPGRADE_KEYWORDS = ("升级", "upgrade", "REBUILD", "重建", "版本", "version", "v22", "v23", "v24", "v25")

# ── 缺口清单: 应存在但缺失/空置的能力面 ──
GAP_REGISTRY = [
    ("mt_file_organize_log", "智能文件整理日志", "补建表并接入 sys_file_organizer 落库"),
    ("mt_file_organize_stats", "文件整理日汇总", "补建表并启用日汇总写入"),
    ("mt_edu_sync_log", "教辅同步日志", "补建表并接入 sys_edu_sync 落库"),
    ("mt_edu_sync_content", "教辅内容库(K12/高等/成人/文科)", "补建表并触发教辅内容同步"),
    ("mt_arduino_sync_log", "Arduino教程同步日志", "补建表并接入 sys_arduino_sync 落库"),
    ("mt_ai_eigenflux_invite_log", "EigenFlux邀请记录", "激活 sys_auto_hire 邀请写入"),
    ("mt_ai_eigenflux_messages", "EigenFlux专家交流消息", "补建表并接入 sys_eigenflux_network 落库"),
    ("mt_local_ai_token_savings", "本地推理token节省日汇总", "补建表并启用 sys_local_inference 日汇总"),
    ("mt_arduino_detected_devices", "Arduino设备清单", "插入已检测设备快照或触发一次真实扫描"),
]

UPPER_BAND_ON = True  # 柱状图上限标记(防止单类长尾压缩其他类可读性) — 预留


def _cols(c, table):
    try:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _table_exists(c, table):
    return bool(c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _collect_events(c):
    """归一化全部事件源 → [{time, category, source_table, title, detail, actor, ref}]"""
    events = []
    for cat, table, time_col, title_e, detail_e, actor_e, ref_e in EVENT_SOURCES:
        if not _table_exists(c, table):
            continue
        cols = _cols(c, table)
        if not cols or time_col not in cols:
            continue
        sql = (f"SELECT {title_e} AS t, {detail_e} AS d, {actor_e} AS a, {ref_e} AS r, "
               f"{time_col} AS ts FROM {table} ORDER BY {time_col} DESC")
        try:
            cur = c.execute(sql)
            t_idx = [desc[0] for desc in cur.description]
            for row in cur.fetchall():
                rec = dict(zip(t_idx, row))
                title = str(rec.get("t") or "(空)")
                category = cat
                if category == "自研发" and any(k in title for k in _UPGRADE_KEYWORDS):
                    category = "自升级"
                events.append({
                    "time": rec.get("ts") or "",
                    "category": category,
                    "source_table": table,
                    "title": title[:160],
                    "detail": str(rec.get("d") or "")[:200],
                    "actor": str(rec.get("a") or "")[:60],
                    "ref": str(rec.get("r") or ""),
                })
        except Exception:
            continue  # 表达式列漂移 → 跳过该源, 不阻塞
    events.sort(key=lambda e: e["time"] or "", reverse=True)
    return events


def _collect_gaps(c):
    gaps = []
    for table, capability, action in GAP_REGISTRY:
        if not _table_exists(c, table):
            gaps.append({"gap_id": f"gap_missing_{table}", "capability": capability,
                         "table": table, "status": "MISSING", "rows": 0, "action": action})
            continue
        try:
            n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            n = -1
        if n <= 0:
            gaps.append({"gap_id": f"gap_empty_{table}", "capability": capability,
                         "table": table, "status": "EMPTY", "rows": n, "action": action})
    # daemon 异常也算缺口 — 有因停用(config 带 reason/note)不算
    if _table_exists(c, "mt_daemon_registry"):
        try:
            for name, status, cfg in c.execute(
                    "SELECT process_name, status, COALESCE(config_json,'') FROM mt_daemon_registry").fetchall():
                if str(status or "").upper() in ("RUNNING", "OK", "ACTIVE"):
                    continue
                justified = ('"reason"' in cfg or '"note"' in cfg
                             or 'obsolete' in cfg or 'no_arduino' in cfg or 'graceful' in cfg)
                if justified:
                    continue
                gaps.append({
                    "gap_id": f"gap_daemon_{name}", "capability": f"daemon {name}",
                    "table": "mt_daemon_registry", "status": f"ABNORMAL({status})",
                    "rows": 0, "action": "触发 sys_auto_repair 自动修复或人工排查"})
        except Exception:
            pass
    return gaps


def _collect_teams(c):
    teams = {"ai_employees_total": 0, "ai_employees_by_dept": [],
             "eigenflux_experts": [], "daemons": [], "daemons_running": 0}
    if _table_exists(c, "mt_ai_employees"):
        try:
            teams["ai_employees_total"] = c.execute("SELECT COUNT(*) FROM mt_ai_employees").fetchone()[0]
            teams["ai_employees_by_dept"] = [
                {"dept": r[0] or "未分组", "n": r[1]} for r in c.execute(
                    "SELECT department, COUNT(*) FROM mt_ai_employees GROUP BY department ORDER BY 2 DESC")]
        except Exception:
            pass
    if _table_exists(c, "mt_eigenflux_registrations"):
        try:
            cur = c.execute("SELECT name, expertise, status, is_member, role, score "
                            "FROM mt_eigenflux_registrations ORDER BY score DESC")
            teams["eigenflux_experts"] = [
                {"name": r[0], "expertise": r[1], "status": r[2],
                 "is_member": r[3], "role": r[4], "score": r[5]} for r in cur.fetchall()]
        except Exception:
            pass
    if _table_exists(c, "mt_daemon_registry"):
        try:
            # schema 自适应: source/stop_reason 列部分库缺失, 缺则不查 (flow_gap_fill_20261018)
            _dcols = _cols(c, "mt_daemon_registry")
            _src_sel = ", source" if "source" in _dcols else ""
            _reason_sel = ", stop_reason" if "stop_reason" in _dcols else ""
            cur = c.execute("SELECT process_name, duty, status, restart_count, last_heartbeat"
                            + _src_sel + _reason_sel + " FROM mt_daemon_registry ORDER BY process_name")
            for r in cur.fetchall():
                teams["daemons"].append({"name": r[0], "duty": r[1], "status": r[2],
                                         "restart_count": r[3], "last_heartbeat": r[4],
                                         "source": r[5] if _src_sel else "",
                                         "stop_reason": r[6] if _reason_sel else ""})
                if str(r[2] or "").upper() in ("RUNNING", "OK", "ACTIVE", "ALIVE"):
                    teams["daemons_running"] += 1
        except Exception:
            pass
    return teams


def _build_overview(c):
    events = _collect_events(c)
    by_cat = Counter(e["category"] for e in events)
    by_month = Counter((e["time"] or "")[:7] for e in events if len(e["time"] or "") >= 7)
    by_actor = Counter(e["actor"] for e in events)
    return {
        "flow_id": FLOW_ID,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_events": len(events),
        "categories": dict(by_cat.most_common()),
        "by_month": dict(sorted(by_month.items())),
        "top_actors": [{"actor": a, "n": n} for a, n in by_actor.most_common(10)],
        "teams": _collect_teams(c),
        "gaps": _collect_gaps(c),
    }


@andromeda_stats_bp.route('/andromeda/stats')
@_login_required
def stats_page():
    from flask import session
    csrf = session.get('csrf_token', '')
    if not csrf:
        import hashlib
        import os as _os
        import time as _tm
        csrf = hashlib.sha256(f'mtscos-csrf-sess-{_tm.time()}-{_os.urandom(16)}'.encode()).hexdigest()
        session['csrf_token'] = csrf
    return render_template('andromeda_stats.html', flow_id=FLOW_ID, csrf_token=csrf)


@andromeda_stats_bp.route('/api/andromeda/stats/overview')
@_login_required
def stats_overview():
    conn = sqlite3.connect(_resolve_db_path(), timeout=10)
    try:
        return jsonify({"success": True, "data": _build_overview(conn)})
    finally:
        conn.close()


@andromeda_stats_bp.route('/api/andromeda/stats/events')
@_login_required
def stats_events():
    category = (request.args.get('category') or '').strip()
    q = (request.args.get('q') or '').strip()
    try:
        limit = max(1, min(int(request.args.get('limit', 200)), 1000))
    except ValueError:
        limit = 200
    try:
        offset = max(0, int(request.args.get('offset', 0)))
    except ValueError:
        offset = 0

    conn = sqlite3.connect(_resolve_db_path(), timeout=10)
    try:
        events = _collect_events(conn)
    finally:
        conn.close()
    if category:
        events = [e for e in events if e["category"] == category]
    if q:
        ql = q.lower()
        events = [e for e in events if ql in e["title"].lower()
                  or ql in e["detail"].lower() or ql in e["actor"].lower()]
    return jsonify({"success": True, "total": len(events),
                    "events": events[offset:offset + limit]})


@andromeda_stats_bp.route('/api/andromeda/stats/dispatch', methods=['POST'])
@_login_required
def stats_dispatch():
    """缺口 → 研发联动: 写入 smart_mount 建议池(mt_ai_suggestion_pool), 引擎自动扫走并 mount 开发。"""
    payload = request.get_json(silent=True) or {}
    gap_id = str(payload.get('gap_id') or '').strip()
    note = str(payload.get('note') or '').strip()
    if not gap_id.startswith('gap_'):
        return jsonify({"success": False, "error": "invalid_gap_id"}), 400

    conn = sqlite3.connect(_resolve_db_path(), timeout=10)
    try:
        # 从缺口定义还原语义
        target = gap_id
        action = "按缺口定义补齐能力"
        capability = gap_id
        for table, cap, act in GAP_REGISTRY:
            if gap_id in (f"gap_missing_{table}", f"gap_empty_{table}"):
                target, capability, action = table, cap, act
                break
        else:
            if gap_id.startswith('gap_daemon_'):
                target = gap_id[len('gap_daemon_'):]
                capability = f"daemon {target}"
                action = "触发 sys_auto_repair 自动修复或人工排查"
        text = f"[STATS_GAP] {capability}: {action}" + (f" | 备注: {note}" if note else "")
        cols = _cols(conn, "mt_ai_suggestion_pool")
        if not cols or "suggestion_text" not in cols:
            return jsonify({"success": False, "error": "suggestion_pool_missing"}), 500
        now = datetime.now().isoformat(timespec='seconds')
        # status='EVALUATED': 统计系统缺口自带评估结论, 引擎 collect_suggestions 直接按
        # status='EVALUATED' AND priority>=5 收集 (CHECK 约束无 'NEW', 见表 DDL)
        if "suggestion_id" in cols:
            conn.execute(
                "INSERT INTO mt_ai_suggestion_pool (source_type, source_name, suggestion_text, "
                "priority, status, created_at) VALUES ('STATS_GAP','andromeda_stats',?,8,'EVALUATED',?)",
                (text, now))
        else:
            conn.execute(
                "INSERT INTO mt_ai_suggestion_pool (suggestion_text, priority, status, created_at) "
                "VALUES (?,8,'EVALUATED',?)", (text, now))
        conn.commit()
        sid = conn.execute("SELECT suggestion_id FROM mt_ai_suggestion_pool "
                           "WHERE source_type='STATS_GAP' ORDER BY created_at DESC, rowid DESC LIMIT 1"
                           ).fetchone()[0]
        return jsonify({"success": True, "suggestion_id": sid, "text": text,
                        "message": "已派发至 smart_mount 建议池, 引擎将在下轮扫描自动 mount"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()
