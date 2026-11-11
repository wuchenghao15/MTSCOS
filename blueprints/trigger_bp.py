"""
trigger_bp.py — 🎛️ 触发器事件开关协调器 REST API
======================================================
Routes:
  ── 开关面板 ──
  GET    /panel                       全局开关面板
  GET    /panel/<name>                单个开关值
  POST   /panel/<name>/toggle         切换开关
  POST   /panel/batch                 批量设置 (JSON dict)

  ── 触发器注册表 ──
  GET    /triggers                    所有已注册触发器 + handler
  GET    /triggers/<event_type>       单个触发器详情 + 执行历史
  GET    /triggers/<event_type>/handlers 所有 handler 状态
  POST   /triggers/<event_type>/handlers/<key>/toggle   单个 handler 开关

  ── 事件触发 ──
  POST   /fire/<event_type>           手动触发事件
  GET    /events                      最近事件列表
  GET    /events/<event_id>           单个事件详情 + handler 执行状态

  ── 编排门 ──
  GET    /gates                       所有编排门
  POST   /gates                       新建编排门
  POST   /gates/<gate_id>/toggle      切换编排门开关

  ── 死信队列 ──
  GET    /dlq                         待处理死信
  POST   /dlq/<dlq_id>/retry          手动重试
  POST   /dlq/<dlq_id>/abandon        放弃
  POST   /dlq/process                 运行 retry+DLQ 循环

  ── 节流指标 ──
  GET    /throttle/metrics            节流统计 (近1小时)
  GET    /throttle/<event_type>       单个事件节流曲线

  ── 健康检查 ──
  GET    /health                      触发器综合健康分
  GET    /executions                  执行日志 (可过滤)

  ── 可视化 ──
  GET    /visualization/graph         事件流图 (节点=中心, 边=事件)
  GET    /visualization/timeline      实时事件时间线
"""

import json
import sqlite3
import traceback
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request


bp = Blueprint('trigger', __name__, url_prefix='/api/trigger')


def _get_tc():
    """延迟导入 TriggerCoordinator — 避免循环依赖."""
    from engines.trigger_coordinator import TriggerCoordinator
    return TriggerCoordinator()


def _db():
    from engines.trigger_coordinator import TriggerCoordinator
    tc = TriggerCoordinator()
    return tc._connect()


def _err(msg: str, code: int = 400) -> tuple:
    return jsonify({'success': False, 'error': msg}), code


# ═══════════════════════════════════════════════════════════════════
#  开关面板
# ═══════════════════════════════════════════════════════════════════

@bp.route('/panel', methods=['GET'])
def api_panel():
    """全局开关面板 — 所有开关当前值."""
    try:
        tc = _get_tc()
        switches = tc.list_switches()
        # 带类型信息
        typed = {}
        conn = _db()
        try:
            for r in conn.execute("SELECT switch_name, switch_type, category FROM mt_switch_panel").fetchall():
                typed[r['switch_name']] = switches.get(r['switch_name'])
        finally:
            conn.close()
        return jsonify({'success': True, 'switches': typed, 'count': len(switches)})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/panel/<name>', methods=['GET'])
def api_panel_get(name):
    """单个开关值."""
    try:
        tc = _get_tc()
        val = tc.get_switch(name)
        return jsonify({'success': True, 'switch': name, 'value': val})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/panel/<name>/toggle', methods=['POST'])
def api_panel_toggle(name):
    """切换开关 (POST JSON {value: true/false} 或空 body 自动 toggle)."""
    try:
        tc = _get_tc()
        body = request.get_json(silent=True) or {}
        if 'value' in body:
            val = body['value']
            r = tc.toggle_switch(name, val)
        else:
            r = tc.toggle_switch(name, None)  # auto toggle
        return jsonify({'success': True, **r})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/panel/batch', methods=['POST'])
def api_panel_batch():
    """批量设置 — POST JSON {NAME: value, ...}."""
    try:
        body = request.get_json(force=True)
        tc = _get_tc()
        results = []
        for name, val in body.items():
            r = tc.toggle_switch(name, val)
            results.append(r)
        return jsonify({'success': True, 'count': len(results), 'results': results})
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  触发器注册表
# ═══════════════════════════════════════════════════════════════════

@bp.route('/triggers', methods=['GET'])
def api_triggers_list():
    """所有已注册触发器 + handler 概况."""
    try:
        tc = _get_tc()
        conn = _db()
        try:
            rows = conn.execute("""
                SELECT r.trigger_id, r.event_type, r.priority, r.cooldown_ms,
                       r.handler_count, r.enabled, r.throttle_max_per_sec, r.throttle_burst,
                       r.description, r.updated_at
                FROM mt_trigger_registry r
                ORDER BY CASE r.priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'NORMAL' THEN 2 ELSE 3 END
            """).fetchall()
            triggers = []
            for r in rows:
                h_rows = conn.execute("""
                    SELECT handler_key, target_engine, target_method, enabled,
                           exec_count, last_success, avg_duration_ms, last_executed
                    FROM mt_trigger_handler WHERE trigger_event_type=?
                """, (r['event_type'],)).fetchall()
                triggers.append({
                    'event_type': r['event_type'], 'priority': r['priority'],
                    'cooldown_ms': r['cooldown_ms'], 'handler_count': r['handler_count'],
                    'enabled': bool(r['enabled']),
                    'throttle': {'max_per_sec': r['throttle_max_per_sec'], 'burst': r['throttle_burst']},
                    'description': r['description'], 'updated_at': r['updated_at'],
                    'handlers': [dict(h) for h in h_rows],
                })
            return jsonify({'success': True, 'triggers': triggers, 'count': len(triggers)})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/triggers/<event_type>', methods=['GET'])
def api_triggers_detail(event_type):
    """单个触发器详情 + 近 50 次执行历史."""
    try:
        conn = _db()
        try:
            r = conn.execute(
                "SELECT * FROM mt_trigger_registry WHERE event_type=?", (event_type,)
            ).fetchone()
            if not r:
                return _err(f'event_type {event_type} 未注册', 404)
            h_rows = conn.execute("""
                SELECT handler_key, target_engine, target_method, enabled,
                       exec_count, last_success, avg_duration_ms, last_executed
                FROM mt_trigger_handler WHERE trigger_event_type=?
            """, (event_type,)).fetchall()
            exec_logs = conn.execute("""
                SELECT event_id, handler_key, result, duration_ms, error_msg, retry_count, started_at
                FROM mt_trigger_execution_log
                WHERE event_type=? ORDER BY started_at DESC LIMIT 50
            """, (event_type,)).fetchall()
            return jsonify({
                'success': True,
                'trigger': dict(r),
                'handlers': [dict(h) for h in h_rows],
                'recent_executions': [dict(e) for e in exec_logs],
            })
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/triggers/<event_type>/handlers', methods=['GET'])
def api_triggers_handlers(event_type):
    """所有 handler 状态 (独立视图)."""
    try:
        conn = _db()
        try:
            rows = conn.execute("""
                SELECT handler_key, target_engine, target_method, enabled,
                       exec_count, last_success, avg_duration_ms, last_executed
                FROM mt_trigger_handler WHERE trigger_event_type=?
                ORDER BY handler_key
            """, (event_type,)).fetchall()
            return jsonify({'success': True, 'handlers': [dict(r) for r in rows]})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/triggers/<event_type>/handlers/<key>/toggle', methods=['POST'])
def api_trigger_handler_toggle(event_type, key):
    """单个 handler 开关 (POST JSON {enabled: true/false})."""
    try:
        body = request.get_json(silent=True) or {}
        enabled = body.get('enabled')
        if enabled is None:
            # 自动 toggle
            conn = _db()
            try:
                r = conn.execute(
                    "SELECT enabled FROM mt_trigger_handler WHERE trigger_event_type=? AND handler_key=?",
                    (event_type, key)
                ).fetchone()
                enabled = not bool(r['enabled']) if r else True
            finally:
                conn.close()
        conn = _db()
        try:
            conn.execute("""
                UPDATE mt_trigger_handler SET enabled=?
                WHERE trigger_event_type=? AND handler_key=?
            """, (1 if enabled else 0, event_type, key))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'success': True, 'event_type': event_type, 'handler_key': key, 'enabled': bool(enabled)})
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  事件触发
# ═══════════════════════════════════════════════════════════════════

@bp.route('/fire/<event_type>', methods=['POST'])
def api_fire(event_type):
    """手动触发事件 — POST JSON {source, payload, symbol, severity}."""
    try:
        body = request.get_json(force=True)
        tc = _get_tc()
        r = tc.fire(
            event_type,
            source=body.get('source', 'api_manual'),
            payload=body.get('payload'),
            symbol=body.get('symbol'),
            severity=body.get('severity', 'NORMAL'),
            skip_handlers=body.get('skip_handlers'),
        )
        return jsonify({'success': True, **r})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/events', methods=['GET'])
def api_events_list():
    """最近事件 — 从 mt_collab_bus_events 桥接."""
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        event_type = request.args.get('event_type')
        severity = request.args.get('severity')
        conn = _db()
        try:
            sql = "SELECT * FROM mt_collab_bus_events WHERE 1=1"
            params = []
            if event_type:
                sql += " AND event_type=?"; params.append(event_type)
            if severity:
                sql += " AND severity=?"; params.append(severity)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return jsonify({'success': True, 'events': [dict(r) for r in rows], 'count': len(rows)})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/events/<event_id>', methods=['GET'])
def api_event_detail(event_id):
    """单个事件详情 + handler 执行状态."""
    try:
        conn = _db()
        try:
            evt = conn.execute(
                "SELECT * FROM mt_collab_bus_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if not evt:
                return _err('event 不存在', 404)
            execs = conn.execute("""
                SELECT * FROM mt_trigger_execution_log WHERE event_id=?
                ORDER BY started_at ASC
            """, (event_id,)).fetchall()
            return jsonify({
                'success': True, 'event': dict(evt),
                'executions': [dict(e) for e in execs],
            })
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  编排门 (TRIGGER_GATEWAY)
# ═══════════════════════════════════════════════════════════════════

@bp.route('/gates', methods=['GET'])
def api_gates_list():
    """所有编排门."""
    try:
        conn = _db()
        try:
            rows = conn.execute("SELECT * FROM mt_trigger_gate ORDER BY created_at DESC").fetchall()
            return jsonify({'success': True, 'gates': [dict(r) for r in rows], 'count': len(rows)})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/gates', methods=['POST'])
def api_gates_create():
    """新建编排门 — POST JSON {gate_name, gate_type, condition_events:[], output_event, description}."""
    try:
        body = request.get_json(force=True)
        gid = f"GATE-{uuid.uuid4().hex[:10]}"
        conn = _db()
        try:
            conn.execute("""
                INSERT INTO mt_trigger_gate
                    (gate_id, gate_name, gate_type, condition_events, output_event, description)
                VALUES (?,?,?,?,?,?)
            """, (gid, body.get('gate_name', 'unnamed'), body.get('gate_type', 'AND'),
                  json.dumps(body.get('condition_events', []), ensure_ascii=False),
                  body.get('output_event'), body.get('description', '')))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'success': True, 'gate_id': gid})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/gates/<gate_id>/toggle', methods=['POST'])
def api_gate_toggle(gate_id):
    """切换编排门开关 — POST JSON {enabled: true/false}."""
    try:
        body = request.get_json(silent=True) or {}
        enabled = body.get('enabled')
        conn = _db()
        try:
            if enabled is None:
                r = conn.execute("SELECT enabled FROM mt_trigger_gate WHERE gate_id=?", (gate_id,)).fetchone()
                if not r: return _err('gate 不存在', 404)
                enabled = not bool(r['enabled'])
            conn.execute("UPDATE mt_trigger_gate SET enabled=? WHERE gate_id=?", (1 if enabled else 0, gate_id))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'success': True, 'gate_id': gate_id, 'enabled': bool(enabled)})
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  死信队列
# ═══════════════════════════════════════════════════════════════════

@bp.route('/dlq', methods=['GET'])
def api_dlq_list():
    """待处理死信 — 支持 resolution + event_type 过滤."""
    try:
        resolution = request.args.get('resolution', 'PENDING')
        event_type = request.args.get('event_type')
        limit = min(int(request.args.get('limit', 50)), 200)
        conn = _db()
        try:
            sql = "SELECT * FROM mt_dead_letter_queue WHERE resolution=?"
            params = [resolution]
            if event_type:
                sql += " AND event_type=?"; params.append(event_type)
            sql += " ORDER BY first_failed DESC LIMIT ?"; params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            # 汇总
            summary = {}
            for r in conn.execute("SELECT resolution, COUNT(*) as cnt FROM mt_dead_letter_queue GROUP BY resolution").fetchall():
                summary[r['resolution']] = r['cnt']
            return jsonify({'success': True, 'items': [dict(r) for r in rows], 'count': len(rows), 'summary': summary})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/dlq/<dlq_id>/retry', methods=['POST'])
def api_dlq_retry(dlq_id):
    """手动重试某条死信."""
    try:
        tc = _get_tc()
        conn = _db()
        try:
            r = conn.execute("SELECT * FROM mt_dead_letter_queue WHERE dlq_id=?", (dlq_id,)).fetchone()
            if not r: return _err('DLQ 记录不存在', 404)
            payload = {}
            try: payload = json.loads(r['payload']) if r['payload'] else {}
            except Exception: pass
            new_r = tc.fire(r['event_type'], r['source'] or 'dlq_manual_retry', payload, severity='NORMAL')
            if new_r.get('status') == 'ok':
                conn.execute("""
                    UPDATE mt_dead_letter_queue SET resolution='RESOLVED',
                        resolved_at=datetime('now','localtime') WHERE dlq_id=?
                """, (dlq_id,))
            else:
                conn.execute("""
                    UPDATE mt_dead_letter_queue SET retry_count=retry_count+1,
                        last_failed=datetime('now','localtime') WHERE dlq_id=?
                """, (dlq_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'success': True, 'fire_result': new_r})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/dlq/<dlq_id>/abandon', methods=['POST'])
def api_dlq_abandon(dlq_id):
    """放弃某条死信."""
    try:
        conn = _db()
        try:
            conn.execute("""
                UPDATE mt_dead_letter_queue SET resolution='ABANDONED',
                    resolved_at=datetime('now','localtime') WHERE dlq_id=?
            """, (dlq_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'success': True, 'dlq_id': dlq_id, 'resolution': 'ABANDONED'})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/dlq/process', methods=['POST'])
def api_dlq_process():
    """运行 retry+DLQ 循环 (协调器 5 分钟心跳的 API 入口)."""
    try:
        tc = _get_tc()
        body = request.get_json(silent=True) or {}
        dry_run = body.get('dry_run', False)
        r = tc.run_coordination_loop(dry_run=dry_run)
        return jsonify({'success': True, **r})
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  节流指标
# ═══════════════════════════════════════════════════════════════════

@bp.route('/throttle/metrics', methods=['GET'])
def api_throttle_metrics():
    """节流统计 (近 1 小时)."""
    try:
        conn = _db()
        try:
            rows = conn.execute("""
                SELECT * FROM mt_throttle_metrics
                WHERE window_start >= datetime('now','-1 hour')
                ORDER BY window_start DESC
            """).fetchall()
            # per-event 汇总
            agg = {}
            for r in rows:
                et = r['event_type']
                if et not in agg:
                    agg[et] = {'total_throttled': 0, 'windows': 0}
                agg[et]['total_throttled'] += r['throttled_count']
                agg[et]['windows'] += 1
            return jsonify({'success': True, 'windows': [dict(r) for r in rows], 'aggregate': agg})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/throttle/<event_type>', methods=['GET'])
def api_throttle_event(event_type):
    """单个事件节流曲线 (近 24 小时)."""
    try:
        conn = _db()
        try:
            rows = conn.execute("""
                SELECT * FROM mt_throttle_metrics
                WHERE event_type=? AND window_start >= datetime('now','-24 hours')
                ORDER BY window_start ASC
            """, (event_type,)).fetchall()
            return jsonify({'success': True, 'event_type': event_type, 'metrics': [dict(r) for r in rows]})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  健康检查 + 执行日志
# ═══════════════════════════════════════════════════════════════════

@bp.route('/health', methods=['GET'])
def api_health():
    """触发器综合健康分."""
    try:
        tc = _get_tc()
        h = tc.health_check()
        return jsonify({'success': True, 'health': h})
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/executions', methods=['GET'])
def api_executions():
    """执行日志 (可按 event_type/handler_key/result 过滤)."""
    try:
        event_type = request.args.get('event_type')
        handler_key = request.args.get('handler_key')
        result = request.args.get('result')   # SUCCESS/FAIL/SKIP/THROTTLED
        limit = min(int(request.args.get('limit', 100)), 500)
        conn = _db()
        try:
            sql = "SELECT * FROM mt_trigger_execution_log WHERE 1=1"
            params = []
            if event_type:
                sql += " AND event_type=?"; params.append(event_type)
            if handler_key:
                sql += " AND handler_key=?"; params.append(handler_key)
            if result:
                sql += " AND result=?"; params.append(result)
            sql += " ORDER BY started_at DESC LIMIT ?"; params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            # 汇总
            summary = {'SUCCESS': 0, 'FAIL': 0, 'SKIP': 0, 'THROTTLED': 0}
            for r in rows:
                key = r['result'] or 'UNKNOWN'
                summary[key] = summary.get(key, 0) + 1
            return jsonify({'success': True, 'executions': [dict(r) for r in rows], 'count': len(rows), 'summary': summary})
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  可视化
# ═══════════════════════════════════════════════════════════════════

@bp.route('/visualization/graph', methods=['GET'])
def api_visual_graph():
    """事件流图 — nodes=中心(engine), edges=事件."""
    try:
        conn = _db()
        try:
            # 从 mt_trigger_handler 提取所有 engine ↔ event_type 关系
            edges = conn.execute("""
                SELECT DISTINCT h.trigger_event_type as event,
                       h.target_engine as target_engine,
                       r.priority
                FROM mt_trigger_handler h
                JOIN mt_trigger_registry r ON r.event_type = h.trigger_event_type
                WHERE h.enabled=1
            """).fetchall()
            nodes = {}
            edge_list = []
            for e in edges:
                ev = e['event']
                tgt = e['target_engine']
                nodes.setdefault(tgt, {'id': tgt, 'group': 'engine'})
                nodes.setdefault(ev, {'id': ev, 'group': 'event', 'priority': e['priority']})
                edge_list.append({'source': ev, 'target': tgt, 'priority': e['priority']})
            # 也加上 db 里出现过的 source (事件发送方)
            for r in conn.execute("""
                SELECT DISTINCT source FROM mt_collab_bus_events WHERE source IS NOT NULL AND source != ''
                LIMIT 50
            """).fetchall():
                src = r['source']
                if src and src not in nodes:
                    nodes[src] = {'id': src, 'group': 'source'}
            return jsonify({
                'success': True,
                'nodes': list(nodes.values()),
                'edges': edge_list,
                'node_count': len(nodes),
                'edge_count': len(edge_list),
            })
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


@bp.route('/visualization/timeline', methods=['GET'])
def api_visual_timeline():
    """实时事件时间线 — 近 10 分钟."""
    try:
        minutes = int(request.args.get('minutes', 10))
        conn = _db()
        try:
            rows = conn.execute(f"""
                SELECT event_id, event_type, source, severity, symbol, created_at
                FROM mt_collab_bus_events
                WHERE created_at >= datetime('now','-{minutes} minutes')
                ORDER BY created_at DESC
                LIMIT 200
            """).fetchall()
            # 按分钟聚合
            buckets = {}
            for r in rows:
                minute = r['created_at'][:16] if r['created_at'] else '?'
                buckets.setdefault(minute, {'total': 0, 'by_severity': {}})
                buckets[minute]['total'] += 1
                sev = r['severity'] or 'INFO'
                buckets[minute]['by_severity'][sev] = buckets[minute]['by_severity'].get(sev, 0) + 1
            return jsonify({
                'success': True,
                'minutes': minutes,
                'events': [dict(r) for r in rows],
                'timeline': [{'minute': k, **v} for k, v in sorted(buckets.items())],
                'count': len(rows),
            })
        finally:
            conn.close()
    except Exception as e:
        return _err(str(e), 500)


# ═══════════════════════════════════════════════════════════════════
#  Daemon loop 工厂 — server_real_db.py 启动时注册
# ═══════════════════════════════════════════════════════════════════

def make_trigger_daemon_loop(interval_sec: int = 300):
    """构造后台协调循环 — 每 5 分钟 retry+DLQ+health."""
    import threading
    _TC = None
    _TC_LOCK = threading.Lock()

    def _get():
        nonlocal _TC
        if _TC is None:
            with _TC_LOCK:
                if _TC is None:
                    from engines.trigger_coordinator import TriggerCoordinator
                    _TC = TriggerCoordinator()
        return _TC

    def loop_fn():
        import time
        while True:
            try:
                tc = _get()
                tc.run_coordination_loop()
            except Exception as e:
                traceback.print_exc()
            time.sleep(interval_sec)

    return loop_fn


# 便捷导出 — server_real_db.py 可直接 import
run_trigger_coordination_loop = None  # 延迟初始化占位


def start_trigger_daemon(interval_sec: int = 300):
    """启动后台协调循环线程 (daemon=True)."""
    import threading
    global run_trigger_coordination_loop
    if run_trigger_coordination_loop is not None:
        return False
    run_trigger_coordination_loop = make_trigger_daemon_loop(interval_sec)
    t = threading.Thread(target=run_trigger_coordination_loop, name='trigger-coordinator-loop', daemon=True)
    t.start()
    return True
