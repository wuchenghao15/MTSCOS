"""
🤝💡 Collab + R&D Blueprint — 协作团结 + 研发放大器 API
====================================================================

所有端点位于 /api/collab-rd/ 前缀下, 已添加 CSRF 豁免 + 海关白名单.

=== 协作团结 (CollabSolidarityEngine) ===
  GET  /api/collab-rd/network           完整协作网络 (含孤立中心)
  GET  /api/collab-rd/pacts             已签署协作契约
  POST /api/collab-rd/rebuild           用 evolution_log 重建矩阵
  POST /api/collab-rd/suggest           AI 推荐新协作对
  POST /api/collab-rd/pact              签署协作契约 (body: {center_a, center_b, pact_type})
  POST /api/collab-rd/hub-network       建立星系 hub 网络

=== 研发放大器 (RDAmplifierEngine) ===
  GET  /api/collab-rd/rd/pipeline       研发流水线状态
  GET  /api/collab-rd/rd/derivatives    研发衍生池 (分页)
  POST /api/collab-rd/rd/derive         从中心职责衍生新方向
  POST /api/collab-rd/rd/compose        技能链组合
  POST /api/collab-rd/rd/sprint         周末研发冲刺
  POST /api/collab-rd/rd/feedback       研发反馈闭环
  POST /api/collab-rd/rd/full-cycle     完整研发放大周期
"""

from __future__ import annotations

import json
import os
import sqlite3
import traceback

from flask import Blueprint, jsonify, request

collab_rd_bp = Blueprint('collab_rd', __name__, url_prefix='/api/collab-rd')

_DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', 'database', 'app.db'
))


def _db_conn(readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        return sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    return sqlite3.connect(_DB_PATH)


# ═══════════════════════════════════════════════════════════════
# 协作团结 Engine 懒加载
# ═══════════════════════════════════════════════════════════════

def _collab_engine():
    from engines.collab_solidarity_engine import CollabSolidarityEngine
    return CollabSolidarityEngine(_DB_PATH)


def _rd_engine():
    from engines.rd_amplifier_engine import RDAmplifierEngine
    return RDAmplifierEngine(_DB_PATH)


# ═══════════════════════════════════════════════════════════════
# ── 协作团结: Network ──
# ═══════════════════════════════════════════════════════════════

@collab_rd_bp.route('/network', methods=['GET'])
def api_network():
    """完整协作网络 — 含孤立中心 + hub 分组 + 统计."""
    try:
        conn = _db_conn(readonly=True)

        # 全部中心
        centers = conn.execute("""
            SELECT center_name, galaxy, primary_duty, health_score
            FROM mt_center_cognition_portrait
            ORDER BY galaxy, center_name
        """).fetchall()

        # 协作矩阵
        pairs = conn.execute("""
            SELECT source_center, target_center, event_count, relationship, suggested_upgrade
            FROM mt_center_collab_matrix
        """).fetchall()

        # Hub 网络
        hubs = conn.execute("""
            SELECT hub_id, galaxy, hub_center, member_centers, coverage_pct
            FROM mt_collab_hub_network
        """).fetchall()

        # 连接状态
        connected_centers = set()
        for p in pairs:
            connected_centers.add(p[0])
            connected_centers.add(p[1])

        center_list = []
        for c in centers:
            center_list.append({
                'center_name': c[0], 'galaxy': c[1],
                'primary_duty': (c[2] or '')[:60],
                'health_score': c[3],
                'connected': c[0] in connected_centers,
            })

        pair_list = []
        for p in pairs:
            pair_list.append({
                'source': p[0], 'target': p[1],
                'event_count': p[2], 'relationship': p[3],
                'suggestion': (p[4] or '')[:80],
            })

        hub_list = []
        for h in hubs:
            members = []
            try:
                members = json.loads(h[3]) if h[3] else []
            except Exception:
                pass
            hub_list.append({
                'galaxy': h[1], 'hub_center': h[2],
                'members': members, 'coverage_pct': h[4],
            })

        summary = {
            'total_centers': len(centers),
            'connected': len(connected_centers),
            'isolated': len(centers) - len(connected_centers),
            'collab_pairs': len(pairs),
            'hub_networks': len(hubs),
            'connectivity_pct': round(
                len(connected_centers) / max(len(centers), 1) * 100, 1
            ),
        }

        conn.close()
        return jsonify({
            'success': True, 'summary': summary,
            'centers': center_list, 'pairs': pair_list, 'hubs': hub_list,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/pacts', methods=['GET'])
def api_pacts():
    """已签署的协作契约列表."""
    try:
        conn = _db_conn(readonly=True)
        rows = conn.execute("""
            SELECT pact_id, center_a, center_b, pact_type,
                   formed_by, confidence, active, formed_at, obligations
            FROM mt_collab_pact
            ORDER BY formed_at DESC
        """).fetchall()
        pacts = []
        for r in rows:
            pacts.append({
                'pact_id': r[0], 'center_a': r[1], 'center_b': r[2],
                'pact_type': r[3], 'formed_by': r[4], 'confidence': r[5],
                'active': bool(r[6]), 'formed_at': r[7],
                'obligations': r[8][:200] if r[8] else None,
            })
        conn.close()
        return jsonify({'success': True, 'total': len(pacts), 'pacts': pacts})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# ── 协作团结: Rebuild / Suggest / Pact / Hub ──
# ═══════════════════════════════════════════════════════════════

@collab_rd_bp.route('/rebuild', methods=['POST'])
def api_rebuild():
    """POST /api/collab-rd/rebuild — 用 evolution_log 5s 因果窗口重建矩阵."""
    try:
        engine = _collab_engine()
        result = engine.rebuild_full_collab_matrix()
        engine.close()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/suggest', methods=['POST'])
def api_suggest():
    """POST /api/collab-rd/suggest — AI 推荐新协作对."""
    try:
        engine = _collab_engine()
        result = engine.ai_suggest_collab_pairs()
        engine.close()
        return jsonify({'success': True, 'count': len(result), 'pairs': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/pact', methods=['POST'])
def api_pact():
    """POST /api/collab-rd/pact — 签署协作契约.
    body: {center_a, center_b, pact_type}
    """
    try:
        data = request.get_json(silent=True) or {}
        center_a = data.get('center_a')
        center_b = data.get('center_b')
        pact_type = data.get('pact_type', 'PEER')
        formed_by = data.get('formed_by', 'api')
        confidence = float(data.get('confidence', 0.7))

        if not center_a or not center_b:
            return jsonify({'success': False, 'error': 'center_a / center_b 必填'}), 400

        engine = _collab_engine()
        result = engine.form_collab_pact(center_a, center_b, pact_type, formed_by, confidence)
        engine.close()
        ok = result.get('status') == 'OK'
        return jsonify({'success': ok, 'result': result}), (200 if ok else 400)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/hub-network', methods=['POST'])
def api_hub_network():
    """POST /api/collab-rd/hub-network — 建立星系 hub 分层网络."""
    try:
        engine = _collab_engine()
        result = engine.ai_broadcast_hub_network()
        engine.close()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# ── 研发放大器: Pipeline 状态 + Derivatives ──
# ═══════════════════════════════════════════════════════════════

@collab_rd_bp.route('/rd/pipeline', methods=['GET'])
def api_rd_pipeline():
    """研发流水线总览状态."""
    try:
        conn = _db_conn(readonly=True)

        # derivatives 状态分布
        status_counts = dict(conn.execute("""
            SELECT status, COUNT(*) FROM mt_autodev_derivatives
            GROUP BY status
        """).fetchall())

        # 类型分布
        type_counts = dict(conn.execute("""
            SELECT deriv_type, COUNT(*) FROM mt_autodev_derivatives
            GROUP BY deriv_type ORDER BY COUNT(*) DESC LIMIT 15
        """).fetchall())

        # auto triggers 数
        trigger_count = conn.execute("""
            SELECT COUNT(*) FROM mt_trigger_handler
            WHERE handler_key LIKE 'auto_deriv_%'
        """).fetchone()[0]

        # 最新 derivatives
        latest = conn.execute("""
            SELECT deriv_id, deriv_type, confidence, status, created_at, content
            FROM mt_autodev_derivatives
            ORDER BY created_at DESC LIMIT 10
        """).fetchall()

        latest_list = [
            {
                'deriv_id': r[0], 'deriv_type': r[1], 'confidence': r[2],
                'status': r[3], 'created_at': r[4],
                'content_preview': (r[5] or '')[:80],
            }
            for r in latest
        ]

        # 质量指标
        quality = conn.execute("""
            SELECT
                COUNT(*) as total,
                ROUND(AVG(confidence), 3) as avg_conf,
                ROUND(AVG(ic), 4) as avg_ic,
                ROUND(AVG(backtest_sharpe), 3) as avg_sharpe
            FROM mt_autodev_derivatives
        """).fetchone()

        conn.close()
        return jsonify({
            'success': True,
            'pipeline': {
                'status_distribution': status_counts,
                'type_distribution': type_counts,
                'auto_triggers': trigger_count,
                'quality': {
                    'total': quality[0] if quality else 0,
                    'avg_confidence': quality[1] if quality else 0,
                    'avg_ic': quality[2] if quality else 0,
                    'avg_backtest_sharpe': quality[3] if quality else 0,
                },
                'latest_10': latest_list,
            },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/rd/derivatives', methods=['GET'])
def api_rd_derivatives():
    """研发衍生池列表 (分页 + 筛选)."""
    try:
        status_filter = request.args.get('status', '')
        type_filter = request.args.get('deriv_type', '')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        conn = _db_conn(readonly=True)
        clauses = []
        params = []
        if status_filter:
            clauses.append("status = ?")
            params.append(status_filter)
        if type_filter:
            clauses.append("deriv_type = ?")
            params.append(type_filter)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        base_sql = f"""
            SELECT deriv_id, deriv_type, source_ids, content, confidence,
                   ic, backtest_sharpe, status, registered_at, performance, created_at
            FROM mt_autodev_derivatives
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(base_sql, params + [limit, offset]).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM mt_autodev_derivatives {where}", params
        ).fetchone()[0]

        results = []
        for r in rows:
            results.append({
                'deriv_id': r[0], 'deriv_type': r[1],
                'source_ids': (r[2] or '')[:100],
                'content': (r[3] or '')[:200],
                'confidence': r[4], 'ic': r[5],
                'backtest_sharpe': r[6], 'status': r[7],
                'registered_at': r[8], 'performance': (r[9] or '')[:150],
                'created_at': r[10],
            })
        conn.close()
        return jsonify({
            'success': True, 'total': total, 'limit': limit, 'offset': offset,
            'derivatives': results,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# ── 研发放大器: Derive / Compose / Sprint / Feedback / Full ──
# ═══════════════════════════════════════════════════════════════

@collab_rd_bp.route('/rd/derive', methods=['POST'])
def api_rd_derive():
    """POST /api/collab-rd/rd/derive — 从中心职责衍生研发方向."""
    try:
        data = request.get_json(silent=True) or {}
        max_per = int(data.get('max_per_center', 3))
        engine = _rd_engine()
        result = engine.derive_from_center_duties(max_per_center=max_per)
        engine.close()
        return jsonify({'success': True, 'count': len(result), 'samples': result[:15]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/rd/compose', methods=['POST'])
def api_rd_compose():
    """POST /api/collab-rd/rd/compose — 技能链组合."""
    try:
        engine = _rd_engine()
        result = engine.skill_chain_composition()
        engine.close()
        return jsonify({'success': True, 'count': len(result), 'samples': result[:10]})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/rd/sprint', methods=['POST'])
def api_rd_sprint():
    """POST /api/collab-rd/rd/sprint — 周末研发冲刺."""
    try:
        engine = _rd_engine()
        result = engine.weekend_rd_sprint()
        engine.close()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/rd/feedback', methods=['POST'])
def api_rd_feedback():
    """POST /api/collab-rd/rd/feedback — 研发反馈闭环."""
    try:
        engine = _rd_engine()
        result = engine.rd_feedback_loop()
        engine.close()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/rd/full-cycle', methods=['POST'])
def api_rd_full_cycle():
    """POST /api/collab-rd/rd/full-cycle — 完整研发放大周期."""
    try:
        engine = _rd_engine()
        result = engine.run_rd_cycle()
        engine.close()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# ★★★ REAL-TIME DASHBOARD ENDPOINTS ★★★
# ═══════════════════════════════════════════════════════════════

@collab_rd_bp.route('/dashboard/overview', methods=['GET'])
def api_dashboard_overview():
    """GET /api/collab-rd/dashboard/overview — 一句话仪表盘."""
    try:
        conn = _db_conn(readonly=True)

        # 核心计数
        total_centers = conn.execute(
            "SELECT COUNT(*) FROM mt_center_cognition_portrait"
        ).fetchone()[0]

        connected_pairs = conn.execute(
            "SELECT COUNT(*) FROM mt_center_collab_matrix"
        ).fetchone()[0]

        hub_networks = conn.execute(
            "SELECT COUNT(*) FROM mt_collab_hub_network"
        ).fetchone()[0]

        pacts = conn.execute(
            "SELECT COUNT(*) FROM mt_collab_pact WHERE active=1"
        ).fetchone()[0]

        deriv_total = conn.execute(
            "SELECT COUNT(*) FROM mt_autodev_derivatives"
        ).fetchone()[0]

        deriv_status = dict(conn.execute(
            "SELECT status, COUNT(*) FROM mt_autodev_derivatives GROUP BY status"
        ).fetchall())

        handler_count = conn.execute(
            "SELECT COUNT(*) FROM mt_trigger_handler WHERE enabled=1"
        ).fetchone()[0]

        deriv_handlers = conn.execute(
            "SELECT COUNT(*) FROM mt_trigger_handler WHERE handler_key LIKE 'DERIV_%' AND enabled=1"
        ).fetchone()[0]

        registry_events = conn.execute(
            "SELECT COUNT(*) FROM mt_trigger_registry WHERE enabled=1"
        ).fetchone()[0]

        # 健康分 (简单 0-100)
        portrait_health = conn.execute(
            "SELECT AVG(health_score) FROM mt_center_cognition_portrait"
        ).fetchone()[0] or 50

        # 孤立中心
        conn_list = set()
        for row in conn.execute(
            "SELECT source_center, target_center FROM mt_center_collab_matrix"
        ).fetchall():
            conn_list.add(row[0])
            conn_list.add(row[1])
        isolated = total_centers - len(conn_list)

        # 近 24h 事件数
        try:
            events_24h = conn.execute(
                "SELECT COUNT(*) FROM mt_collab_bus_events "
                "WHERE created_at >= datetime('now','-24 hours')"
            ).fetchone()[0]
        except Exception:
            events_24h = 0

        conn.close()

        # 构建一句话
        total_score = round(portrait_health, 1)
        summary = (
            f"🤝 {total_centers} 中心 | 🔗 {connected_pairs} 协作对 | "
            f"🛡 {hub_networks} Hub | 📜 {pacts} 契约\n"
            f"💡 {deriv_total} 衍生 ({deriv_status.get('live', 0)} 上线 / "
            f"{deriv_status.get('pending', 0)} 待推进)\n"
            f"⚡ {handler_count} handlers ({deriv_handlers} 衍生自动) | "
            f"📝 {registry_events} event types\n"
            f"🏥 综合健康: {total_score}/100"
        )

        return jsonify({
            'success': True,
            'summary': summary,
            'numbers': {
                'centers': total_centers,
                'collab_pairs': connected_pairs,
                'hub_networks': hub_networks,
                'active_pacts': pacts,
                'isolated_centers': isolated,
                'derivatives_total': deriv_total,
                'derivatives_status': deriv_status,
                'trigger_handlers': handler_count,
                'deriv_trigger_handlers': deriv_handlers,
                'registry_events': registry_events,
                'events_24h': events_24h,
            },
            'health_score': total_score,
            'timestamp': __import__('datetime').datetime.now().isoformat(),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/dashboard/network-graph', methods=['GET'])
def api_dashboard_network_graph():
    """GET /api/collab-rd/dashboard/network-graph — 协作网络图 (节点+边 JSON)."""
    try:
        conn = _db_conn(readonly=True)

        # 节点 (全部中心)
        centers = conn.execute("""
            SELECT center_name, galaxy, primary_duty, health_score
            FROM mt_center_cognition_portrait
            ORDER BY health_score DESC
        """).fetchall()

        nodes = []
        for c in centers:
            nodes.append({
                'id': c[0],
                'galaxy': c[1] or 'unknown',
                'duty': (c[2] or '')[:40],
                'health': round(c[3] or 50, 1),
            })

        # 边 (协作对)
        pairs = conn.execute("""
            SELECT source_center, target_center, event_count, relationship
            FROM mt_center_collab_matrix
            WHERE event_count > 0
        """).fetchall()

        edges = []
        for p in pairs:
            edges.append({
                'source': p[0],
                'target': p[1],
                'weight': p[2],
                'relationship': p[3] or 'PEER',
            })

        # Hub 分组
        hubs = conn.execute("""
            SELECT hub_center, member_centers, galaxy
            FROM mt_collab_hub_network
        """).fetchall()

        hub_groups = {}
        for h in hubs:
            members = []
            try:
                members = json.loads(h[1]) if h[1] else []
            except Exception:
                pass
            hub_groups[h[0]] = {
                'galaxy': h[2] or '',
                'members': members,
            }

        conn.close()

        return jsonify({
            'success': True,
            'nodes': nodes,
            'edges': edges,
            'hubs': hub_groups,
            'stats': {
                'nodes': len(nodes),
                'edges': len(edges),
                'hubs': len(hub_groups),
                'isolated_nodes': len(nodes) - len(
                    set(e['source'] for e in edges) | set(e['target'] for e in edges)
                ),
            },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/dashboard/rd-pipeline', methods=['GET'])
def api_dashboard_rd_pipeline():
    """GET /api/collab-rd/dashboard/rd-pipeline — 研发流水线状态."""
    try:
        conn = _db_conn(readonly=True)

        # derivatives 状态分布
        status_counts = dict(conn.execute("""
            SELECT status, COUNT(*) FROM mt_autodev_derivatives GROUP BY status
        """).fetchall())

        # 类型分布 Top 10
        type_top = dict(conn.execute("""
            SELECT deriv_type, COUNT(*) FROM mt_autodev_derivatives
            GROUP BY deriv_type ORDER BY COUNT(*) DESC LIMIT 10
        """).fetchall())

        # 质量指标
        quality = conn.execute("""
            SELECT
                COUNT(*) as total,
                ROUND(AVG(confidence), 3) as avg_conf,
                MIN(confidence) as min_conf,
                MAX(confidence) as max_conf
            FROM mt_autodev_derivatives
        """).fetchone()

        # trigger handlers from derivatives
        deriv_handlers = conn.execute("""
            SELECT handler_key, trigger_event_type, target_engine,
                   enabled, exec_count, avg_duration_ms
            FROM mt_trigger_handler
            WHERE handler_key LIKE 'DERIV_%'
            ORDER BY enabled DESC, exec_count DESC
        """).fetchall()

        handlers_list = []
        for h in deriv_handlers:
            handlers_list.append({
                'handler_key': h[0],
                'event_type': h[1],
                'target': f"{h[2]}.{h[2]}",
                'enabled': bool(h[3]),
                'exec_count': h[4],
                'avg_ms': round(h[5] or 0, 1),
            })

        # 流水线进度
        total = sum(status_counts.values())
        stages = ['pending', 'backtest_pending', 'ready_for_trigger', 'live', 'ACTIVE']
        stage_data = {}
        for s in stages:
            stage_data[s] = status_counts.get(s, 0)
        stage_data['total'] = total

        # 如果存在 derivatives → triggers 的 handler, 显示它们
        registry_new = conn.execute("""
            SELECT event_type, handler_count FROM mt_trigger_registry
            WHERE event_type LIKE 'DERIV_%' OR event_type LIKE 'BRAIN_%'
                   OR event_type LIKE 'QUESTION_%' OR event_type LIKE 'SYSTEM_%'
                   OR event_type LIKE 'CENTER_%' OR event_type LIKE 'EMPLOYEE_%'
            ORDER BY handler_count DESC
        """).fetchall()

        new_events = [{'event_type': r[0], 'handler_count': r[1]} for r in registry_new]

        conn.close()

        return jsonify({
            'success': True,
            'pipeline': {
                'status_distribution': status_counts,
                'stage_progress': stage_data,
                'type_top10': type_top,
                'quality': {
                    'total': quality[0] if quality else 0,
                    'avg_confidence': quality[1] if quality else 0,
                    'min_confidence': quality[2] if quality else 0,
                    'max_confidence': quality[3] if quality else 0,
                },
                'deriv_trigger_handlers': handlers_list,
                'new_trigger_events': new_events,
            },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/dashboard/feedback', methods=['GET'])
def api_dashboard_feedback():
    """GET /api/collab-rd/dashboard/feedback — 反馈闭环最近 24h."""
    try:
        conn = _db_conn(readonly=True)

        # 最近 24h collab bus events
        events_24h = conn.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM mt_collab_bus_events
            WHERE created_at >= datetime('now','-24 hours')
            GROUP BY event_type
            ORDER BY cnt DESC
        """).fetchall()

        events_list = [{'event_type': r[0], 'count': r[1]} for r in events_24h]

        # trigger execution log
        try:
            exec_24h = conn.execute("""
                SELECT result, COUNT(*) as cnt
                FROM mt_trigger_execution_log
                WHERE started_at >= datetime('now','-24 hours')
                GROUP BY result
            """).fetchall()
            exec_dist = {r[0]: r[1] for r in exec_24h}
        except Exception:
            exec_dist = {}

        # derivatives performance / feedback
        feedback_derivs = conn.execute("""
            SELECT deriv_id, deriv_type, status, confidence, registered_at, performance
            FROM mt_autodev_derivatives
            WHERE status IN ('live', 'ready_for_trigger', 'backtest_pending')
            ORDER BY registered_at DESC NULLS LAST
            LIMIT 15
        """).fetchall()

        feedback_list = []
        for d in feedback_derivs:
            perf = {}
            try:
                perf = json.loads(d[5]) if d[5] else {}
            except Exception:
                pass
            feedback_list.append({
                'deriv_id': d[0],
                'deriv_type': d[1],
                'status': d[2],
                'confidence': d[3],
                'loop_at': perf.get('feedback_loop_at', None),
                'success_rate': perf.get('success_rate', None),
                'live_now': perf.get('live_now', None),
            })

        # 最近的 evolution events (协作因果证据)
        try:
            evol_24h = conn.execute("""
                SELECT event_type, COUNT(*) as cnt
                FROM mt_center_evolution_log
                WHERE created_at >= datetime('now','-24 hours')
                GROUP BY event_type
                ORDER BY cnt DESC
                LIMIT 10
            """).fetchall()
            evol_list = [{'event_type': r[0], 'count': r[1]} for r in evol_24h]
        except Exception:
            evol_list = []

        # Ollama 连通性
        ollama_ok = True
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:11434/api/tags")
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            ollama_ok = False

        conn.close()

        return jsonify({
            'success': True,
            'feedback_24h': {
                'collab_bus_events': events_list,
                'execution_result_distribution': exec_dist,
                'derivatives_feedback': feedback_list,
                'evolution_events': evol_list,
                'ollama_available': ollama_ok,
            },
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@collab_rd_bp.route('/dashboard/health', methods=['GET'])
def api_dashboard_health():
    """GET /api/collab-rd/dashboard/health — 综合健康分."""
    try:
        conn = _db_conn(readonly=True)

        scores = {}
        details = {}

        # 1. 中心画像覆盖率 (应接近 100%)
        total = conn.execute(
            "SELECT COUNT(*) FROM mt_center_cognition_portrait"
        ).fetchone()[0]
        covered = conn.execute("""
            SELECT COUNT(*) FROM mt_center_cognition_portrait
            WHERE health_score IS NOT NULL AND health_score > 0
        """).fetchone()[0]
        portrait_score = round(covered / max(total, 1) * 100, 1)
        scores['portrait'] = portrait_score
        details['portrait'] = f"{covered}/{total} centers have portrait"

        # 2. 协作连通率
        conn_pairs = conn.execute(
            "SELECT COUNT(*) FROM mt_center_collab_matrix"
        ).fetchone()[0]
        if total > 1:
            connectivity = round(min(conn_pairs / (total * (total - 1)) * 200, 100), 1)
        else:
            connectivity = 50
        scores['connectivity'] = connectivity
        details['connectivity'] = f"{conn_pairs} collab pairs for {total} centers"

        # 3. 研发衍生产能
        deriv_total = conn.execute(
            "SELECT COUNT(*) FROM mt_autodev_derivatives"
        ).fetchone()[0]
        deriv_live = conn.execute(
            "SELECT COUNT(*) FROM mt_autodev_derivatives WHERE status='live'"
        ).fetchone()[0]
        deriv_health = round(min(deriv_live / max(deriv_total, 1) * 100 + 30, 100), 1)
        scores['rd_amplifier'] = deriv_health
        details['rd_amplifier'] = f"{deriv_live}/{deriv_total} derivatives live"

        # 4. Trigger 自动化
        handlers = conn.execute(
            "SELECT COUNT(*) FROM mt_trigger_handler WHERE enabled=1"
        ).fetchone()[0]
        deriv_handlers = conn.execute("""
            SELECT COUNT(*) FROM mt_trigger_handler
            WHERE handler_key LIKE 'DERIV_%' AND enabled=1
        """).fetchone()[0]
        auto_ratio = round(deriv_handlers / max(handlers, 1) * 100, 1)
        scores['trigger_auto'] = min(auto_ratio + 30, 100)
        details['trigger_auto'] = f"{deriv_handlers}/{handlers} handlers from derivatives"

        # 5. Ollama AI 可用
        ollama_score = 0
        ollama_ok = False
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:11434/api/tags")
            urllib.request.urlopen(req, timeout=2)
            ollama_ok = True
            ollama_score = 100
        except Exception:
            ollama_score = 10
        scores['ollama_ai'] = ollama_score
        details['ollama_ai'] = '✅ available' if ollama_ok else '❌ unavailable'

        # 6. Event 流活跃度 (24h)
        try:
            events_24h = conn.execute("""
                SELECT COUNT(*) FROM mt_collab_bus_events
                WHERE created_at >= datetime('now','-24 hours')
            """).fetchone()[0]
            event_score = round(min(events_24h / 50 * 100, 100), 1)
        except Exception:
            events_24h = 0
            event_score = 50
        scores['event_flow'] = event_score
        details['event_flow'] = f"{events_24h} events in last 24h"

        conn.close()

        # 综合分 (加权平均)
        weights = {
            'portrait': 0.2, 'connectivity': 0.2, 'rd_amplifier': 0.25,
            'trigger_auto': 0.15, 'ollama_ai': 0.1, 'event_flow': 0.1,
        }
        total_score = round(
            sum(scores[k] * weights[k] for k in weights), 1
        )

        # 状态
        if total_score >= 80:
            status = 'GREEN'
            emoji = '🟢'
        elif total_score >= 60:
            status = 'YELLOW'
            emoji = '🟡'
        else:
            status = 'RED'
            emoji = '🔴'

        return jsonify({
            'success': True,
            'overall_score': total_score,
            'status': status,
            'emoji': emoji,
            'component_scores': scores,
            'details': details,
            'recommendations': _health_recommendations(scores, total_score),
            'timestamp': __import__('datetime').datetime.now().isoformat(),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


def _health_recommendations(scores: dict, total: float) -> list:
    """基于各项分数给出建议."""
    recs = []
    if scores.get('connectivity', 0) < 70:
        recs.append("🔗 协作连通率偏低 — 建议重建 collab matrix (POST /rebuild)")
    if scores.get('rd_amplifier', 0) < 70:
        recs.append("💡 研发放大器产能不足 — 建议 promote 更多 derivatives (POST /rd/full-cycle)")
    if scores.get('trigger_auto', 0) < 50:
        recs.append("⚡ 自动触发占比偏低 — 建议运行 derivative→trigger pipeline")
    if scores.get('ollama_ai', 0) < 50:
        recs.append("🧠 Ollama 不可用 — event_type 推理质量下降")
    if scores.get('event_flow', 0) < 50:
        recs.append("📡 Event 流不活跃 — 检查 cron / autopilot 是否在跑")
    if not recs:
        recs.append("✅ 全系统运行良好, 继续保持!")
    return recs
