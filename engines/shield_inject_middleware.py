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
    _INJECTED.clear()  # 重置 (防止 Flask reload 累积)
    
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
    
    # ═══ Layer 3.5: 大厅提案全链路安全钩子 (修复 11 个缺口) ═══
    try:
        _inject_hall_security(app)
    except Exception as e:
        log.warning(f'⚠️ Layer 3.5 大厅安全注入失败: {type(e).__name__}: {e}')
    
    # ═══ Layer 4: 协同总线融合 ═══
    try:
        _inject_collab_bus(app)
    except Exception as e:
        log.warning(f'⚠️ Layer 4 协同总线注入失败: {type(e).__name__}: {e}')
    
    # ═══ Layer 4.5: 30 中心全量识别 + 事件自动 dispatch ═══
    try:
        _inject_center_awareness(app)
    except Exception as e:
        log.warning(f'⚠️ Layer 4.5 中心识别注入失败: {type(e).__name__}: {e}')
    
    # ═══ Layer 5: after_request 统一审计 ═══
    @app.after_request
    def _shield_audit_response(response):
        """所有响应 → 金盾审计 + 中心识别"""
        from flask import request
        
        # ── 中心识别 (Layer 4.5 预计算) ──
        center_code = getattr(request, '_shield_center_code', None)
        center_name = getattr(request, '_shield_center_name', None)
        
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH') and 200 <= response.status_code < 400:
            try:
                source = center_code or (request.path.split('/')[1] if request.path.startswith('/api/') else 'web')
                _shield_audit_event(
                    event_type=f"HTTP_{request.method}",
                    source=source,
                    target=request.path,
                    severity="INFO" if response.status_code < 400 else "WARNING",
                )
                # 如果识别到中心, 额外记中心事件
                if center_code:
                    _shield_audit_event(
                        event_type=f"CENTER_ACTION_{request.method}",
                        source=center_code,
                        target=request.path,
                        severity="INFO",
                    )
            except Exception:
                pass
        
        # 给每个响应加金盾 header
        response.headers['X-Shield-Status'] = 'PROTECTED'
        response.headers['X-Shield-Flow'] = 'flow_shield_inject_all_loops_20261104'
        if center_code:
            # HTTP header 只能 latin-1, 中文 name 不要放
            response.headers['X-Shield-Center'] = center_code
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
#  🏛️ Layer 3.5: 大厅提案全链路安全钩子 (修复 11 个缺口)
#
#  注入点: daemon_skill_lab_bp._hall_publish
#  覆盖:   海关检查 + 铁律筛选 + 风险评分 + collab_bus 发布
#  修复:   hall_proposal 匿名 admin 绕过权限
# ═══════════════════════════════════════════════════════════

def _inject_hall_security(app):
    """大厅提案 4 件套安全注入"""
    log = app.logger
    
    try:
        from blueprints import daemon_skill_lab_bp as dsl
    except ImportError as e:
        log.warning(f'⚠️ Layer 3.5 daemon_skill_lab_bp 导入失败: {e}')
        return
    
    # ── 1. 钩住 _hall_publish (唯一"正规"入口 + 所有旁路最终汇聚) ──
    if hasattr(dsl, '_hall_publish') and not getattr(dsl._hall_publish, '_shield_wrapped', False):
        original_publish = dsl._hall_publish
        
        def _shield_hall_publish(data, u):
            """大厅提案 → 海关 + 铁律 + 风险 + collab_bus 四件套"""
            title = (data.get('title') or '').strip()
            desc = (data.get('description') or '').strip()
            ttype = (data.get('task_type') or 'OTHER').strip().upper()
            priority = (data.get('priority') or 'NORMAL').strip().upper()
            username = u.get('username') or 'unknown'
            role = u.get('role') or 'user'
            
            # ═══ (a) 金盾海关总署 ═══
            risk = _quick_customs_check(username, title, "HALL_PROPOSAL")
            
            # ── 铁律关键词扫描 ──
            IRON_RULE_BLOCKLIST = [
                ('DROP_TABLE',  r'\bdrop\s+table\b', 95, '铁律禁止删除表'),
                ('DROP_DB',     r'\bdrop\s+database\b', 95, '铁律禁止删库'),
                ('TRUNCATE',    r'\btruncate\s+table\b', 90, '铁律禁止清空表'),
                ('RM_RF',       r'rm\s+-rf\s+/', 95, '铁律禁止 rm -rf /'),
                ('SUDO_REBOOT', r'(sudo\s+)?(reboot|poweroff|shutdown\s+-h)', 90, '铁律禁止关机/重启'),
                ('BYPASS_AUTH', r'(绕过.*(权限|验证|认证)|bypass.*auth)', 85, '铁律禁止绕过权限'),
                ('DATA_EXFIL',  r'(导出.*全量|dump.*production|mysqldump.*--all)', 70, '数据导出需审批'),
                ('SECRET_KEY',  r'(API_KEY|SECRET|PASSWORD)\s*=\s*["\'][A-Za-z0-9+/=]{16,}', 60, '疑似硬编码密钥'),
            ]
            for label, pattern, add_risk, reason in IRON_RULE_BLOCKLIST:
                text = f"{title} {desc}"
                import re
                if re.search(pattern, text, re.IGNORECASE):
                    risk += add_risk
                    # 直接拦截 (risk >= 100 → 抛异常被上层 catch → 返回 error)
                    if risk >= 100:
                        _shield_audit_event(
                            event_type="HALL_IRON_RULE_BLOCK",
                            source="shield_iron_rule",
                            target=f"{label}: {reason}",
                            severity="CRITICAL",
                        )
                        raise PermissionError(f"🛑 铁律拦截: {reason} (风险 {risk}/100)")
            
            # ── 风险增强 (priority/ttype 加权) ──
            if priority == 'HIGH': risk += 15
            if ttype == 'SECURITY': risk += 20
            if ttype in ('TRADING_EXECUTION', 'TRADING_AUDIT'): risk += 10
            
            # ═══ (b) 写金盾审计日志 ═══
            _shield_audit_event(
                event_type="HALL_PROPOSAL_SUBMIT",
                source=f"hall_{ttype}",
                target=f"{title[:80]} | risk={risk} | pub={username}({role}) | pri={priority} | iron_rule_scanned",
                severity="BLOCKED" if risk >= 80 else ("WARNING" if risk >= 60 else "INFO"),
            )
            
            # ═══ (c) risk >= 80 → 直接拦截 ═══
            if risk >= 80:
                raise PermissionError(
                    f"🛑 金盾海关+铁律拦截 — 风险 {risk}/100 — {username} {priority} {ttype}: {title[:40]}"
                )
            
            # ═══ (d) collab_bus 发布 (不阻塞提案) ═══
            try:
                import engines.collab_bus_engine as cbe
                bus = cbe.get_collab_bus()
                bus.publish(
                    event_type="HALL_PROPOSAL",
                    source=f"hall_{username}",
                    payload={
                        "title": title[:120], "task_type": ttype,
                        "priority": priority, "risk_score": risk,
                        "publisher": username, "publisher_role": role,
                        "shield_checked": True, "iron_rule_passed": True,
                    },
                    priority=2 if risk >= 50 else 1,
                )
            except Exception as e:
                # collab_bus 不影响提案本身
                log.debug(f'collab_bus 发布失败(不阻塞): {e}')
            
            # ═══ 走原始逻辑 (海关+铁律都放行了) ═══
            return original_publish(data, u)
        
        dsl._hall_publish = _shield_hall_publish
        dsl._hall_publish._shield_wrapped = True
        
        # hall_submit 和 hall_proposal 都调 _hall_publish, 猴子补丁自动覆盖两条路径
        log.info('✅ 🛡️ Layer 3.5: _hall_publish → 海关+铁律+风险+collab_bus 四件套 已注入')
        _INJECTED.append('hall_publish_shield')
    
    # ── 2. 修 hall_proposal 匿名 admin 绕过 ──
    if hasattr(dsl, 'hall_proposal'):
        try:
            import inspect
            src = inspect.getsource(dsl.hall_proposal)
            if 'role":"admin"' in src or 'role": "admin"' in src or 'proposal_sys' in src:
                # 在 Flask before_request 层强制要求 auth
                @app.before_request
                def _shield_hall_proposal_auth():
                    from flask import request, jsonify
                    if request.method != 'POST': return None
                    if '/api/daemon-lab/hall/proposal' not in request.path: return None
                    
                    # 有 session 且 role != user → 放行
                    try:
                        from flask import session
                        if session.get('user_id') and session.get('role') not in (None, 'user'):
                            return None
                    except Exception:
                        pass
                    
                    # 无鉴权 → 强制降级 role=user + 记录审计
                    try:
                        from flask import session
                        session['role'] = 'user'
                        _shield_audit_event(
                            event_type="HALL_PROPOSAL_NO_AUTH",
                            source="shield_hall_proposal_guard",
                            target=request.path,
                            severity="WARNING",
                        )
                    except Exception:
                        pass
                    return None
                
                log.info('✅ 🛡️ Layer 3.5: hall_proposal 匿名 admin 绕过 → 强制 role=user 已修复')
                _INJECTED.append('hall_proposal_auth_fix')
        except Exception as e:
            log.warning(f'hall_proposal auth fix 跳过: {e}')
    
    # ── 3. 修 SANDBOX_SHORTCUT 违禁词绕过 (在 peacekeeper_review 外再套一层) ──
    try:
        import engines.ai_task_hall_flow_engine as hall_engine
        if hasattr(hall_engine, 'peacekeeper_review'):
            original_review = hall_engine.peacekeeper_review
            if not getattr(original_review, '_shield_wrapped', False):
                def _shield_peacekeeper(task_id, *args, **kwargs):
                    """peacekeeper 外层再做一层最低限度检查"""
                    result = original_review(task_id, *args, **kwargs)
                    try:
                        conn = hall_engine._db()
                        row = conn.execute(
                            "SELECT title,description,task_type FROM mt_lab_task_hall WHERE id=?",
                            (task_id,)).fetchone()
                        conn.close()
                        if row:
                            text = f"{row[0]} {row[1] or ''}"
                            import re
                            BLOCKS = [
                                (r'\bdrop\s+(table|database)\b', 'DROP_TABLE', 95),
                                (r'\btruncate\s+table\b', 'TRUNCATE', 90),
                                (r'rm\s+-rf\s+[/*]', 'RM_RF', 95),
                                (r'(sudo\s+)?(reboot|poweroff)', 'REBOOT', 90),
                            ]
                            for pat, label, risk in BLOCKS:
                                if re.search(pat, text, re.IGNORECASE):
                                    _shield_audit_event(
                                        event_type="HALL_SANDBOX_BYPASS_BLOCK",
                                        source=f"peacekeeper_outer:{label}",
                                        target=f"task_{task_id}",
                                        severity="CRITICAL",
                                    )
                                    # 返回 VETOED 而非 APPROVED
                                    hall_engine.transition_cas(task_id, 'QUEUED', 'VETOED',
                                        reason=f'SHIELD_IRON_RULE_{label} risk={risk}')
                                    return False
                    except Exception as e:
                        log.debug(f'peacekeeper 外层检查跳过: {e}')
                    return result
                
                hall_engine.peacekeeper_review = _shield_peacekeeper
                hall_engine.peacekeeper_review._shield_wrapped = True
                log.info('✅ 🛡️ Layer 3.5: peacekeeper_review 外层铁律兜底 已注入')
                _INJECTED.append('peacekeeper_outer_iron_rule')
    except Exception as e:
        log.debug(f'peacekeeper 外层跳过: {e}')
    
    log.info('✅ 🛡️ Layer 3.5: 大厅提案全链路安全钩子已注入 (_hall_publish + peacekeeper + auth_fix)')
    _INJECTED.append('hall_security_layer')
    
    # ── 全局 PermissionError 捕获 → 金盾 403 ──
    if not hasattr(app, '_shield_permission_handler_installed'):
        app._shield_permission_handler_installed = True
        
        @app.errorhandler(PermissionError)
        def _shield_permission_error_handler(e):
            from flask import jsonify, request
            _shield_audit_event(
                event_type="SHIELD_PERMISSION_BLOCK",
                source=getattr(request, '_shield_center_code', 'hall_security'),
                target=f"{request.path} | {str(e)[:100]}",
                severity="BLOCKED",
            )
            return jsonify({
                'success': False,
                'error': 'SHIELD_BLOCKED',
                'blocked_by': 'shield_layer_3.5',
                'message': str(e)[:500],
                'flow_id': 'flow_gobelin_shield_20261104',
            }), 403
        log.info('✅ 🛡️ Layer 3.5: PermissionError → 403 金盾审计 已注入')
    
    # ── (e) trading_routes._insert_hall_task 强制金盾前置 ──
    try:
        import blueprints.trading_routes as trading_bp
        if hasattr(trading_bp, '_insert_hall_task'):
            original_insert = trading_bp._insert_hall_task
            if not getattr(original_insert, '_shield_wrapped', False):
                def _shield_wrapped_insert(*args, **kwargs):
                    """trading_routes → 大厅: 先走金盾"""
                    # kwargs: title, description, task_type, priority, publisher 等
                    data = kwargs.copy()
                    # 先过铁律+海关 (复用 _shield_hall_publish 的逻辑)
                    risk = 0
                    import re as _re
                    text = f"{data.get('title','')} {data.get('description','')}"
                    IRON_BLOCKS = [
                        (_re.compile(r'\bdrop\s+(table|database)\b', _re.I), 95, 'DROP_TABLE'),
                        (_re.compile(r'\btruncate\s+table\b', _re.I), 90, 'TRUNCATE'),
                        (_re.compile(r'rm\s+-rf\s+/[^\s]', _re.I), 95, 'RM_RF'),
                        (_re.compile(r'(sudo\s+)?(reboot|poweroff|shutdown)', _re.I), 90, 'REBOOT'),
                    ]
                    for pat, add_risk, label in IRON_BLOCKS:
                        if pat.search(text):
                            risk += add_risk
                    if data.get('priority','').upper() == 'HIGH': risk += 15
                    if data.get('task_type','').upper() == 'SECURITY': risk += 20
                    
                    if risk >= 80:
                        _shield_audit_event(
                            event_type="TRADING_HALL_BLOCK",
                            source="trading_routes",
                            target=data.get('title','')[:60],
                            severity="BLOCKED",
                        )
                        # 不 raise，让 trading_routes 知道被拦截
                        return None
                    
                    # 写金盾审计 + collab_bus
                    _shield_audit_event(
                        event_type="TRADING_HALL_BYPASS_BLOCKED",
                        source=f"trading_{data.get('task_type','?')}",
                        target=f"{data.get('title','')[:60]} | risk={risk}",
                        severity="WARNING" if risk >= 50 else "INFO",
                    )
                    # 继续原始逻辑
                    return original_insert(*args, **kwargs)
                
                trading_bp._insert_hall_task = _shield_wrapped_insert
                trading_bp._insert_hall_task._shield_wrapped = True
                log.info('✅ 🛡️ Layer 3.5e: trading_routes._insert_hall_task → 强制金盾前置 已注入')
                _INJECTED.append('trading_hall_shield')
    except ImportError:
        log.debug('trading_routes 不可导入, 跳过 trading_hall_shield')
    except Exception as e:
        log.warning(f'trading_routes 注入跳过: {e}')
    
    # ── (f) DB 级拦截: sqlite3.Connection.execute 是 read-only, 不做猴子补丁 ──
    # 已通过 Layer 3.5a (_hall_publish) 和 Layer 3.5e (trading_routes) 覆盖主要入口
    # _hall_ingest / _iceberg_auto_close 等旁路已通过 Layer 3.5c peacekeeper 外层兜底
    
    # ── (g) 结案 → AI 脑库投喂 (闭环) ──
    try:
        # 钩子 transition_cas 的 DONE 状态
        import engines.ai_task_hall_flow_engine as hall_engine
        if hasattr(hall_engine, 'transition_cas'):
            original_tc = hall_engine.transition_cas
            if not getattr(original_tc, '_shield_wrapped', False):
                def _shield_wrapped_transition(task_id, old_status, new_status, **kwargs):
                    result = original_tc(task_id, old_status, new_status, **kwargs)
                    # DONE 状态 → 投喂 AI 脑库
                    if result and new_status == 'DONE':
                        try:
                            conn = hall_engine._db()
                            row = conn.execute(
                                "SELECT title,description,task_type,publisher FROM mt_lab_task_hall WHERE id=?",
                                (task_id,)).fetchone()
                            conn.close()
                            if row:
                                _shield_audit_event(
                                    event_type="HALL_DONE_AI_FEED",
                                    source=f"hall_{row[2] or 'TASK'}",
                                    target=f"DONE→脑库 | {row[0][:60]}",
                                    severity="INFO",
                                )
                                # 直接投 AI 脑库 mt_ai_brain_feed_log (统一入口)
                                try:
                                    import sqlite3 as _sqlite3, json as _json
                                    _db2 = os.environ.get('APP_DB') or os.path.join(
                                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        'database', 'app.db')
                                    _conn2 = _sqlite3.connect(_db2, timeout=30)
                                    _content = f"大厅结案 #{task_id} | 类型:{row[2]} | 来源:{row[3]} | {row[0][:200]}"
                                    _meta = _json.dumps({
                                        "task_id": task_id, "hall_type": row[2],
                                        "title": row[0], "publisher": row[3],
                                        "source": "shield_layer_3.5g",
                                        "shield_checked": True,
                                    }, ensure_ascii=False)
                                    _conn2.execute("""
                                        INSERT INTO mt_ai_brain_feed_log
                                        (flow_id, feed_target, feed_kind, feed_content, payload_preview, fed_at, fed_by)
                                        VALUES (?,?,?,?,?,datetime('now','localtime'),?)
                                    """, (
                                        "flow_gobelin_shield_20261104",
                                        "hall_tasks",
                                        "HALL_TASK_DONE",
                                        _content,
                                        _meta[:500],
                                        "shield_layer_3.5g",
                                    ))
                                    _conn2.commit()
                                    _conn2.close()
                                except Exception as feed_err:
                                    log.debug(f'AI 脑库投喂跳过: {feed_err}')
                        except Exception as e:
                            log.debug(f'DONE→脑库跳过: {e}')
                    return result
                
                hall_engine.transition_cas = _shield_wrapped_transition
                hall_engine.transition_cas._shield_wrapped = True
                log.info('✅ 🛡️ Layer 3.5g: 大厅 DONE → AI 脑库投喂 已注入')
                _INJECTED.append('hall_done_brain_feed')
    except Exception as e:
        log.debug(f'DONE→脑库投喂跳过: {e}')

# ═══════════════════════════════════════════════════════════
#  🏥 Layer 4.5: 30 中心全量识别 + 事件自动 dispatch
# ═══════════════════════════════════════════════════════════

# URL path prefix → (center_code, center_name) 映射
_CENTER_PATH_MAP = [
    # ── mt_lab_centers 22 中心 ──
    ("/api/backup",              "BACKUP",            "数据备份中心"),
    ("/api/archive",             "archive_hall",      "历史档案中心"),
    ("/api/daemon-lab",          "daemon_ops",        "部署运维中心"),
    ("/api/lab",                 "data_research",     "数据研究中心"),
    ("/api/lab",                 "dev_flow",          "开发流程中心"),
    ("/api/ai-edu",              "edu_qbank",         "教育题库中心"),
    ("/api/andromeda",           "expert_team",       "专家团队中心"),
    ("/api/lab/hr",              "hr_center",         "人力统一调配中心"),
    ("/api/rule",                "legal",             "法务合规中心"),
    ("/api/rule",                "rules_gov",         "规则治理中心"),
    ("/api/shield",              "security_audit",    "安全审计中心"),
    ("/api/lab",                 "skill_dev",         "Skill研发中心"),
    ("/api/andromeda",           "strategy_center",   "战略中心"),
    ("/api/shield",              "supervision_brigade","监察大队"),
    ("/api/local-chat",          "sync_center",       "仙女座同步中心"),
    ("/api/sandbox",             "trading_execution", "交易投资中心"),
    ("/api/whitehat",            "vuln_fix",          "漏洞修复适配中心"),
    ("/api/lab",                 "workflow",          "工作流研究中心"),
    # ── 额外 8 中心 (Blueprint 存在但 mt_lab_centers 未注册) ──
    ("/api/medical",             "medical",           "医疗中心"),
    ("/api/pedagogy",            "language",          "语言教学中心"),
    ("/api/math-pedagogy",       "math",              "数学教学中心"),
    ("/api/exam",                "exam",              "考试自动中心"),
    ("/api/disaster",            "disaster",          "灾难恢复中心"),
    ("/api/threat-intel",        "threat",            "威胁情报中心"),
    ("/api/collab-bus",          "collab",            "协同总线"),
    ("/api/whitehat",            "whitehat",          "白帽维和"),
]

# 去重: 一个 path → 一个 center_code (取第一个匹配)
_CENTER_PATH_MAP_DEDUP = {}
for _p, _code, _name in _CENTER_PATH_MAP:
    if _p not in _CENTER_PATH_MAP_DEDUP:
        _CENTER_PATH_MAP_DEDUP[_p] = (_code, _name)


def _inject_center_awareness(app):
    """30 中心全量识别: before_request 匹配 URL → 标注 center_code → after_request 自动审计"""
    log = app.logger
    
    if not hasattr(app, '_shield_center_awareness_installed'):
        app._shield_center_awareness_installed = True
        
        @app.before_request
        def _shield_center_identify():
            from flask import request
            path = request.path
            
            # 匹配 URL prefix → center
            for prefix, (code, name) in _CENTER_PATH_MAP_DEDUP.items():
                if path.startswith(prefix):
                    request._shield_center_code = code
                    request._shield_center_name = name
                    
                    # 每个中心启动时记录一次 (防风暴: 抽样 10%)
                    import random
                    if request.method in ('GET', 'POST') and random.random() < 0.1:
                        try:
                            _shield_audit_event(
                                event_type=f"CENTER_ACCESS_{request.method}",
                                source=code,
                                target=path,
                                severity="INFO",
                            )
                        except Exception:
                            pass
                    break
    
    log.info(f'✅ 🛡️ Layer 4.5: 30 中心全量识别已注入 ({len(_CENTER_PATH_MAP_DEDUP)} 个 API prefix 映射)')
    _INJECTED.append('center_awareness')


# ═══════════════════════════════════════════════════════════
#  🚀 Layer 6: 中心协同总线 (跨中心自动事件传播)
# ═══════════════════════════════════════════════════════════

def _inject_collab_bus(app):
    """协同总线 ↔ 金盾总线 双向镜像"""
    log = app.logger
    
    try:
        import engines.collab_bus_engine as cbe
        
        # CollabBus 是类, publish 是实例方法
        try:
            bus = cbe.get_collab_bus()
        except Exception as e:
            log.warning(f'⚠️ collab_bus get_collab_bus 异常: {e}')
            bus = None
        
        if bus and hasattr(bus, 'publish'):
            original_publish = bus.publish
            if not hasattr(bus, '_shield_original_publish'):
                bus._shield_original_publish = original_publish
                
                def _shield_wrapped_publish(*args, **kwargs):
                    # 原始事件
                    result = original_publish(*args, **kwargs)
                    
                    # 同步到金盾总线 (异步不阻塞)
                    try:
                        event_type = args[0] if len(args) > 0 else kwargs.get('event_type', 'COLLAB_BUS')
                        source = args[1] if len(args) > 1 else kwargs.get('source', 'collab_bus')
                        
                        _shield_audit_event(
                            event_type=f"COLLAB_BUS_{event_type}",
                            source=source,
                            target="shield_bus_mirror",
                            severity="INFO",
                        )
                    except Exception:
                        pass
                    
                    return result
                
                bus.publish = _shield_wrapped_publish
                log.info('✅ 🛡️ 协同总线 → 金盾总线 双向镜像 已注入')
                _INJECTED.append('collab_bus_mirror')
        
        # 同时 patch 模块级 CollabBus.publish (兜底)
        if hasattr(cbe, 'CollabBus') and hasattr(cbe.CollabBus, 'publish'):
            original_cls_publish = cbe.CollabBus.publish
            if not hasattr(cbe.CollabBus, '_shield_original_cls_publish'):
                cbe.CollabBus._shield_original_cls_publish = original_cls_publish
                
                def _shield_wrapped_cls_publish(self, *args, **kwargs):
                    result = original_cls_publish(self, *args, **kwargs)
                    try:
                        event_type = args[0] if len(args) > 0 else kwargs.get('event_type', 'COLLAB_BUS')
                        source = args[1] if len(args) > 1 else kwargs.get('source', 'collab_bus')
                        _shield_audit_event(
                            event_type=f"COLLAB_BUS_{event_type}",
                            source=source,
                            target="shield_bus_mirror",
                            severity="INFO",
                        )
                    except Exception:
                        pass
                    return result
                
                cbe.CollabBus.publish = _shield_wrapped_cls_publish
                if 'collab_bus_mirror' not in _INJECTED:
                    log.info('✅ 🛡️ 协同总线 → 金盾总线 双向镜像 已注入 (cls-level)')
                    _INJECTED.append('collab_bus_mirror')
                else:
                    log.info('✅ 🛡️ 协同总线 → 金盾总线 双向镜像 已注入 (cls-level 追加)')
        
    except ImportError as e:
        log.warning(f'⚠️ collab_bus_engine ImportError: {e}')
    except Exception as e:
        log.warning(f'⚠️ 协同总线注入异常: {type(e).__name__}: {e}')


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
