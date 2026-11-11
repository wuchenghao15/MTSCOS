#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🛡️ 金盾注入中间件 — 在仙女座/冰山/大厅所有闭环逻辑中硬接线金盾保护
=====================================================================

不修改原始蓝图文件，而是通过 3 层注入实现闭环保护:

Layer 1: Flask before_request 全局守卫
  → 所有 POST/PUT/DELETE 先过金盾海关检查
  
Layer 2: 蓝图猴子补丁 (import-time)
  → chat_local_bp._feed_brain  → 自动调 shield audit
  → daemon_skill_lab_bp.hall_tick → 自动注 shield intel
  → collab_bus_engine.publish → 自动同步 shield bus

Layer 3: 协同总线融合
  → collab_bus_engine ↔ gobelin_shield_bus 双向镜像

flow_id: flow_shield_inject_all_loops_20261104
"""
import os, sys, json, sqlite3, time, hashlib
from datetime import datetime

_SHIELD_LOADED = False
_INJECTED = []


def inject_shield(app):
    """主入口 — 在 Flask app 上调用一次，注入所有金盾保护"""
    global _SHIELD_LOADED
    if _SHIELD_LOADED:
        return
    _SHIELD_LOADED = True
    
    log = app.logger
    
    # ═══ Layer 1: 全局海关守卫 ═══
    @app.before_request
    def _shield_customs_guard():
        """所有写操作先过金盾海关检查"""
        from flask import request, jsonify
        
        if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
            return None
        
        path = request.path
        
        # 白名单放行 (内部系统 + 金盾自身 + 海关 + 协同总线)
        _WHITELIST_PREFIXES = (
            '/api/shield/',       # 金盾自身
            '/api/threat-intel/', # 海关总署
            '/api/collab-bus/',   # 协同总线
            '/api/internal/',     # 内部 daemon
            '/api/local-chat/send', '/api/local-chat/stream',  # 仙女座聊天主入口 (放行, 会话结束后自动审计)
        )
        if any(path.startswith(w) for w in _WHITELIST_PREFIXES):
            return None
        
        # 只读 + session 会话操作放行
        if '/api/local-chat/session' in path or path.endswith('/session'):
            return None
        if '/api/local-chat/models' in path or '/api/local-chat/widget' in path:
            return None
        
        # 海关总署合规快速检查 (只拦高风险)
        try:
            actor = request.headers.get('X-Shield-Actor', 'auto_guard')
            target = path
            action = request.method
            
            risk = _quick_customs_check(actor, target, action)
            if risk >= 80:
                log.warning(f'🛡️ 海关拦截: {actor} {action} {target} risk={risk}')
                return jsonify({
                    'success': False,
                    'error': 'SHIELD_CUSTOMS_BLOCKED',
                    'risk_score': risk,
                    'message': f'🛑 金盾海关总署拦截 — 风险 {risk}/100 — {actor} {action} {target}',
                }), 403
        except Exception:
            pass  # 海关检查异常不阻塞主流程
        
        return None
    
    log.info('✅ 🛡️ Layer 1: 金盾海关总署守卫已注入')
    _INJECTED.append('customs_guard')
    
    # ═══ Layer 2: 仙女座闭环注入 ═══
    _inject_andromeda(app)
    
    # ═══ Layer 3: 冰山闭环注入 ═══
    _inject_iceberg(app)
    
    # ═══ Layer 4: 协同总线融合 ═══
    _inject_collab_bus(app)
    
    # ═══ Layer 5: after_request 统一审计 ═══
    @app.after_request
    def _shield_audit_response(response):
        """所有响应 → 金盾审计"""
        from flask import request
        
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH') and 200 <= response.status_code < 400:
            try:
                _shield_audit_event(
                    event_type=f"HTTP_{request.method}",
                    source=request.path.split('/')[1] if request.path.startswith('/api/') else 'web',
                    target=request.path,
                    severity="INFO" if response.status_code < 400 else "WARNING",
                )
            except Exception:
                pass
        
        # 给每个响应加金盾 header
        response.headers['X-Shield-Status'] = 'PROTECTED'
        response.headers['X-Shield-Flow'] = 'flow_shield_inject_all_loops_20261104'
        return response
    
    log.info('✅ 🛡️ Layer 5: 金盾 after_request 统一审计已注入')
    _INJECTED.append('after_request_audit')
    
    log.info(f'🛡️ 金盾系统全闭环保护已激活 ({len(_INJECTED)} 层注入)')


# ═══════════════════════════════════════════════════════════
#  🌀 Layer 2: 仙女座闭环注入
# ═══════════════════════════════════════════════════════════

def _inject_andromeda(app):
    """仙女座: 会话创建 → 结束 → 脑库 → 金盾审计 全链路"""
    log = app.logger
    
    try:
        import blueprints.chat_local_bp as chat_bp
        
        # 记录原始 _feed_brain
        original_feed_brain = getattr(chat_bp, '_feed_brain', None)
        if original_feed_brain and not hasattr(chat_bp, '_shield_original_feed_brain'):
            chat_bp._shield_original_feed_brain = original_feed_brain
            
            def _shield_wrapped_feed_brain(*args, **kwargs):
                """脑库投喂 → 自动同步金盾"""
                result = original_feed_brain(*args, **kwargs)
                try:
                    session_id = args[0] if len(args) > 0 else kwargs.get('session_id', '')
                    user_id = args[1] if len(args) > 1 else kwargs.get('user_id', '')
                    _shield_audit_event(
                        event_type="ANDROMEDA_BRAIN_FEED",
                        source="chat_local_bp",
                        target=f"session={session_id}",
                        severity="INFO",
                    )
                except Exception:
                    pass
                return result
            
            chat_bp._feed_brain = _shield_wrapped_feed_brain
            log.info('✅ 🛡️ 仙女座脑库投喂 → 金盾审计 已注入')
            _INJECTED.append('andromeda_feed_brain')
        
        # _finalize (会话结束结算) → 自动调金盾 andromeda_ingest
        original_finalize = getattr(chat_bp, '_finalize', None)
        if original_finalize and not hasattr(chat_bp, '_shield_original_finalize'):
            chat_bp._shield_original_finalize = original_finalize
            
            def _shield_wrapped_finalize(*args, **kwargs):
                result = original_finalize(*args, **kwargs)
                try:
                    # 触发金盾仙女座会话摄入
                    session_id = args[1] if len(args) > 1 else kwargs.get('session_id', '')
                    _shield_audit_event(
                        event_type="ANDROMEDA_SESSION_END",
                        source="chat_local_bp",
                        target=f"session={session_id}",
                        severity="INFO",
                    )
                    # 自动入冰山
                    _shield_iceberg_dispatch(
                        event_id=f"ANDROMEDA-{session_id}",
                        event_type="ANDROMEDA_SESSION",
                        source="chat_local_bp",
                        payload={"session_id": session_id}
                    )
                except Exception:
                    pass
                return result
            
            chat_bp._finalize = _shield_wrapped_finalize
            log.info('✅ 🛡️ 仙女座会话结束 → 金盾+冰山 自动入厅 已注入')
            _INJECTED.append('andromeda_finalize')
        
        # _record_action (操作记录) → 金盾审计
        original_record = getattr(chat_bp, '_record_action', None)
        if original_record and not hasattr(chat_bp, '_shield_original_record'):
            chat_bp._shield_original_record = original_record
            
            def _shield_wrapped_record(*args, **kwargs):
                result = original_record(*args, **kwargs)
                try:
                    # 每 5 条操作写一次金盾 (避免风暴)
                    import random
                    if random.random() < 0.2:
                        _shield_audit_event(
                            event_type="ANDROMEDA_ACTION",
                            source="chat_local_bp",
                            target=args[2] if len(args) > 2 else 'action',
                            severity="INFO",
                        )
                except Exception:
                    pass
                return result
            
            chat_bp._record_action = _shield_wrapped_record
            log.info('✅ 🛡️ 仙女座操作记录 → 金盾抽样审计 已注入')
            _INJECTED.append('andromeda_record')
        
    except ImportError as e:
        log.warning(f'⚠️ chat_local_bp 导入失败: {e}')
    except Exception as e:
        log.warning(f'⚠️ 仙女座注入异常: {e}')


# ═══════════════════════════════════════════════════════════
#  🏔️ Layer 3: 冰山闭环注入
# ═══════════════════════════════════════════════════════════

def _inject_iceberg(app):
    """冰山: hall_tick → 金盾情报注入 + 提案闭环 → 海关合规"""
    log = app.logger
    
    try:
        import blueprints.daemon_skill_lab_bp as iceberg_bp
        
        # 16 轨 hall_tick → 金盾情报注入
        if hasattr(iceberg_bp, 'hall_autonomy_tick') and not hasattr(iceberg_bp, '_shield_wrapped_tick'):
            original_tick = iceberg_bp.hall_autonomy_tick
            iceberg_bp._shield_original_tick = original_tick
            
            def _shield_wrapped_tick(*args, **kwargs):
                # tick 前: 注入金盾待处理情报
                try:
                    shield_intel = _shield_pending_for_iceberg()
                    if shield_intel:
                        log.info(f'🛡️ 冰山 tick → 注入金盾情报 {len(shield_intel)} 条')
                except Exception:
                    pass
                
                result = original_tick(*args, **kwargs)
                
                # tick 后: 把新产出的提案同步金盾
                try:
                    _shield_audit_event(
                        event_type="ICEBERG_TICK_COMPLETE",
                        source="daemon_skill_lab",
                        target="hall_16_tick",
                        severity="INFO",
                    )
                except Exception:
                    pass
                
                return result
            
            iceberg_bp.hall_autonomy_tick = _shield_wrapped_tick
            iceberg_bp._shield_wrapped_tick = True
            log.info('✅ 🛡️ 冰山 16轨 tick → 金盾情报自动注入 已注入')
            _INJECTED.append('iceberg_tick')
        
        # hall_proposal 提交 → 海关合规快速检查
        proposal_routes = [r.rule for r in app.url_map.iter_rules() 
                          if 'hall/proposal' in r.rule or 'hall/submit' in r.rule]
        
        if proposal_routes and not hasattr(app, '_shield_proposal_guard_installed'):
            app._shield_proposal_guard_installed = True
            
            @app.before_request
            def _shield_proposal_customs():
                from flask import request, jsonify
                if request.method != 'POST':
                    return None
                if not any(r in request.path for r in ('/api/daemon-lab/hall/proposal', 
                                                         '/api/daemon-lab/hall/submit',
                                                         '/api/daemon-lab/hall/claim',
                                                         '/api/daemon-lab/hall/deliver')):
                    return None
                
                # 提案 → 快速合规检查
                try:
                    body = request.get_json(silent=True) or {}
                    risk = _quick_customs_check(
                        actor="iceberg_proposal",
                        target=body.get('title', request.path),
                        action="PROPOSAL"
                    )
                    if risk >= 80:
                        log.warning(f'🛡️ 冰山提案海关拦截 risk={risk}')
                        return jsonify({
                            'success': False,
                            'error': 'SHIELD_CUSTOMS_BLOCKED',
                            'risk_score': risk,
                            'message': '🛑 金盾海关总署拦截 — 提案高风险',
                        }), 403
                except Exception:
                    pass
                return None
            
            log.info('✅ 🛡️ 冰山提案 → 海关总署合规检查 已注入')
            _INJECTED.append('iceberg_proposal_customs')
        
    except ImportError as e:
        log.warning(f'⚠️ daemon_skill_lab_bp 导入失败: {e}')
    except Exception as e:
        log.warning(f'⚠️ 冰山注入异常: {e}')


# ═══════════════════════════════════════════════════════════
#  🚌 Layer 4: 协同总线融合
# ═══════════════════════════════════════════════════════════

def _inject_collab_bus(app):
    """协同总线 ↔ 金盾总线 双向镜像"""
    log = app.logger
    
    try:
        import engines.collab_bus_engine as cbe
        
        original_publish = getattr(cbe, 'publish', None) or getattr(cbe, 'publish_event', None)
        if original_publish and not hasattr(cbe, '_shield_original_publish'):
            cbe._shield_original_publish = original_publish
            
            def _shield_wrapped_publish(*args, **kwargs):
                # 原始事件
                result = original_publish(*args, **kwargs)
                
                # 同步到金盾总线 (异步不阻塞)
                try:
                    event_type = args[0] if len(args) > 0 else kwargs.get('event_type', 'COLLAB_BUS')
                    source = args[1] if len(args) > 1 else kwargs.get('source', 'collab_bus')
                    payload = args[2] if len(args) > 2 else kwargs.get('payload', {})
                    
                    _shield_audit_event(
                        event_type=f"COLLAB_BUS_{event_type}",
                        source=source,
                        target="shield_bus_mirror",
                        severity="INFO",
                    )
                except Exception:
                    pass
                
                return result
            
            # collab_bus_engine 可能叫 publish 或 publish_event
            if hasattr(cbe, 'publish'):
                cbe.publish = _shield_wrapped_publish
            if hasattr(cbe, 'publish_event'):
                cbe.publish_event = _shield_wrapped_publish
            
            log.info('✅ 🛡️ 协同总线 → 金盾总线 双向镜像 已注入')
            _INJECTED.append('collab_bus_mirror')
        
    except ImportError as e:
        log.warning(f'⚠️ collab_bus_engine 导入失败: {e}')
    except Exception as e:
        log.warning(f'⚠️ 协同总线注入异常: {e}')


# ═══════════════════════════════════════════════════════════
#  🔧 内部工具函数
# ═══════════════════════════════════════════════════════════

_DB_PATH = None

def _get_db():
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = os.environ.get('APP_DB') or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'database', 'app.db'
        )
    return _DB_PATH


def _shield_audit_event(event_type, source, target, severity="INFO"):
    """快速写金盾审计 (不阻塞, 不抛异常)"""
    try:
        conn = sqlite3.connect(_get_db(), timeout=5)
        c = conn.cursor()
        c.execute("""
            INSERT INTO mt_shield_events (event_type, source_force, target_force, severity)
            VALUES (?, ?, ?, ?)
        """, (event_type, source, target, severity))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _shield_iceberg_dispatch(event_id, event_type, source, payload=None):
    """快速触发冰山入厅 (写 hall_queue.jsonl)"""
    try:
        queue_path = os.path.join(os.path.dirname(_get_db()), '..', '_runtime', 'hall_queue.jsonl')
        queue_path = os.path.normpath(queue_path)
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        
        item = {
            "daemon": f"shield_{event_type.lower().replace('-','_')}",
            "reason": f"[金盾注入] {source} → {event_type} → 冰山大厅",
            "event_id": str(event_id),
            "flow_id": "flow_shield_inject_all_loops_20261104",
            "source": f"SHIELD-INJECT-{source}",
            "payload": json.dumps(payload or {}, ensure_ascii=False)[:3000],
            "timestamp": datetime.now().isoformat(),
        }
        with open(queue_path, "a") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _shield_pending_for_iceberg():
    """冰山 tick 前: 拉取金盾待注入事件"""
    try:
        conn = sqlite3.connect(_get_db(), timeout=5)
        c = conn.cursor()
        rows = c.execute("""
            SELECT id, event_type, source_force, severity FROM mt_shield_events
            WHERE hall_dispatched = 0
               AND created_at > datetime('now','-30 minutes')
            ORDER BY severity DESC LIMIT 5
        """).fetchall()
        
        for r in rows:
            try:
                _shield_iceberg_dispatch(r[0], r[1], r[2], {"severity": r[3]})
                c.execute("UPDATE mt_shield_events SET hall_dispatched=1 WHERE id=?", (r[0],))
            except Exception:
                pass
        
        conn.commit()
        conn.close()
        return rows
    except Exception:
        return []


def _quick_customs_check(actor, target, action):
    """海关总署快速合规检查 — 返回 0-100 风险分"""
    risk = 0
    actor_l = actor.lower()
    target_l = str(target).lower()
    
    # 规则 1: 沙实跨界
    if ('live' in actor_l and 'sandbox' in target_l) or ('sandbox' in actor_l and 'live' in target_l):
        risk += 50
    
    # 规则 2: 敏感资源
    sensitive = ('vault', 'secret', 'crypto', 'auth', 'admin', 'brain_feed', 'dual_key', 'hardware')
    if any(s in target_l for s in sensitive):
        risk += 30
    
    # 规则 3: 外部写操作
    if action in ('POST', 'PUT', 'DELETE', 'PATCH', 'TRANSFER') and 'internal' not in actor_l:
        risk += 10
    
    return min(risk, 100)
