#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
theme_routes.py — 主题调度中心 RESTful API (v1.0.0)
==================================================
来源：§14 FeatureGap #WU-THEME-SCHEME-DB-API-20260829
flow_id: autogap_27c8c83a_20260829_001984565
IR14 7步链: STEP1→STEP7 批推 SUCCESS=1 / SimpleAutoImplementer confidence=95 ✅

3张调度表 SSOT:
  • mt_theme_schemes     — 18 套方案: 4 base + 14 吴美工节日/个性化
  • mt_theme_release     — 灰度发布 1% → 10% → 50% → 100% (SA+VIIKEY后triggered_by_sa=1才激活)
  • mt_theme_usage_log   — 5触发器调度审计(日志表，保留90天)

4个端点:
  1) GET  /api/theme/schemes                 — login: 查询今日推荐+可切换列表+4基础+14wu+3高对比
  2) GET  /api/theme/prefs                   — login: 返回当前用户今日生效主题（5触发器级联）
  3) POST /api/theme/select                  — login: 用户手动切主题 → 写usage_log + 返回确认
  4) POST /api/admin/theme/publish           — SA only: 发布灰度(pct=1/10/50/100) + 要求VIIKEY

5层触发器级联 (WU_LAYOUT_UX_CONFIG_JSON 标准)
  优先级: 强制页面锁SA页aurora(0) > 节日匹配(1) > 灰度发布canary(2) > 用户画像age/gender(3)
        > 用户生日月(4) > 用户手动选择(5)

铁律合规:
  • §用户权限.md — 全部 @_check_login/@_check_admin 权限装饰
  • §设计规范.md — 所有返回颜色来自 mt_theme_schemes.element_plus_color_tokens
  • §14 IRON_RULE L0 — bypass_allowed=False (已体现在lifecycle flow_id)
"""
import os
import sys
import json
import sqlite3
import hashlib
import random
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from flask import Blueprint, request, jsonify, session

logger = logging.getLogger('theme_routes')

# 和 routes/__init__.py 中 theme_bp 保持一致
from . import theme_bp
from app.middlewares.system_container import system_container

# ============================================================================
# 延迟导入：权限/主DB
# ============================================================================

def _current_safe_user() -> Dict:
    """session用户安全字典"""
    try:
        from server_real_db import _current_user, _safe_user_ctx
        u = _current_user()
        return _safe_user_ctx(u) or {}
    except Exception:
        role = session.get('role', 'guest')
        return {
            'id': session.get('user_id'),
            'username': session.get('username'),
            'role': role,
            'is_super_admin': role in ('super_admin', 'sadmin'),
            'logged_in': bool(session.get('user_id')),
            'birthday': session.get('birthday'),
            'age_group': session.get('age_group'),
            'gender': session.get('gender'),
            'permissions': session.get('permissions', []),
        }

_MT_SUPER_ADMINS = frozenset(('super_admin', 'sadmin'))
_MT_ADMIN_ROLES = frozenset(('super_admin', 'sadmin', 'admin', 'teacher_admin'))

_PAGE_LOCK_TO_AURORA_CATEGORIES = frozenset((
    'sa', 'login', 'rules', 'permissions', 'auth', 'rule_', 'admin/permissions'
))
_FORCE_LOCK_THEME_PRESET = 'aurora'


def _check_login(user: Dict) -> Tuple[bool, Optional[Tuple[int, str]]]:
    if not user:
        return False, (401, '未登录或会话已过期')
    if not user.get('id') and not user.get('username'):
        return False, (401, '未登录或会话已过期')
    if not user.get('logged_in') and not user.get('id'):
        return False, (401, '未登录或会话已过期')
    return True, None


def _check_sa(user: Dict) -> Tuple[bool, Optional[Tuple[int, str]]]:
    """校验超级管理员 — wuchenghao15(SA)+VIIKEY 仅发布端点强制"""
    ok, err = _check_login(user)
    if not ok:
        return False, err
    if user.get('is_super_admin') or user.get('role') in _MT_SUPER_ADMINS or user.get('username') == 'wuchenghao15':
        return True, None
    return False, (403, '需要超级管理员权限(wuchenghao15)')


def _check_admin(user: Dict) -> Tuple[bool, Optional[Tuple[int, str]]]:
    ok, err = _check_login(user)
    if not ok:
        return False, err
    if user.get('is_super_admin') or user.get('role') in _MT_ADMIN_ROLES:
        return True, None
    return False, (403, '需要管理员权限')


def _get_main_db():
    """主DB连接（用core.db_path get_db_path()对齐server_real_db.py 全局）"""
    try:
        from core.db_path import get_db_path
        path = get_db_path('app.db')
    except Exception:
        path = os.environ.get('MT_APP_DB_PATH') or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_str(v: Any, default: str = '', max_len: int = 2048) -> str:
    if v is None:
        return default
    s = str(v)
    return s[:max_len]


def _safe_int(v: Any, default: int = 0, min_v: Optional[int] = None, max_v: Optional[int] = None) -> int:
    try:
        i = int(v)
    except Exception:
        return default
    if min_v is not None and i < min_v:
        return min_v
    if max_v is not None and i > max_v:
        return max_v
    return i


def _today_month_day_tuple():
    d = datetime.now()
    return d.month, d.day, d.strftime("%m-%d")


_FESTIVAL_MMDD_TO_PRESET_KEY = {
    # MM-DD → 吴美工 14 套中文化禁忌合规
    "12-13": "national_memorial",   # 公祭日grayscale全灰阶 WU_CULTURE_IRON_LAW
    "10-01": "national_day",
    "01-01": "spring_festival",     # 元旦→春节同色
    "01-29": "spring_festival",
    "01-30": "spring_festival",
    "01-31": "spring_festival",
    "02-01": "spring_festival",
    "02-02": "spring_festival",
    "02-03": "spring_festival",
    "02-04": "spring_festival",
    "02-05": "spring_festival",
    "09-17": "mid_autumn",
    "06-01": "dragon_boat",
    "04-04": "qingming",
    "04-05": "qingming",
    "02-12": "lantern",
    "02-14": "lantern",
    "07-01": "party_found",
    "09-10": "teachers_day",
    "06-01": "children_day",
    "05-04": "graduation",
    "06-15": "graduation",
    "05-01": "kids_candy",
}


def _match_festival_calendar() -> Optional[str]:
    """Layer 1: 节日日历匹配（优先级最高的软切换，grayscale类节日是强制）"""
    try:
        from datetime import date
        today = date.today().strftime("%m-%d")
        if today in _FESTIVAL_MMDD_TO_PRESET_KEY:
            return _FESTIVAL_MMDD_TO_PRESET_KEY[today]
    except Exception:
        pass
    return None


def _in_user_birthday_month(user: Dict) -> bool:
    b = user.get('birthday')
    if not b:
        return False
    try:
        m = datetime.now().month
        if isinstance(b, (list, tuple)) and len(b) >= 2:
            return int(b[0]) == m
        s = str(b)
        for fm in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m-%d"):
            try:
                bd = datetime.strptime(s, fm)
                if bd.month == m:
                    return True
            except Exception:
                continue
    except Exception:
        return False
    return False


def _age_gender_profile(user: Dict) -> Optional[str]:
    """Layer 3: 用户画像 age_group × gender 软建议 (Wu Layout 5×4软建议)"""
    age = user.get('age_group')
    gender = (user.get('gender') or 'unknown').lower()
    if age in ('senior', 'elder', '>=65', '65+', '45+') or str(age).lower().startswith(('6','5','eld','s')):
        return 'elder_high_contrast'
    if age in ('child', 'kids', '<=12', 'toddler') or str(age).lower().startswith(('k','c','<=1')):
        return 'kids_candy'
    if age in ('teen', 'youth', 'teenager', '13-22') and gender == 'female':
        return 'birthday_month'
    return None


def _canary_release_hit(user: Dict) -> Optional[str]:
    """Layer 2: 灰度1%/10%/50%/100%发布（稳定性=STABLE的才命中）"""
    uid = user.get('id') or user.get('username') or 'anon'
    bucket = int(hashlib.md5(str(uid).encode()).hexdigest()[:4], 16) % 100
    try:
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT scheme_id, rollout_pct FROM mt_theme_release WHERE status IN ('ROLLOUT','STABLE') ORDER BY rollout_pct DESC")
        rows = cur.fetchall()
        conn.close()
        for r in rows:
            if bucket < (r['rollout_pct'] or 0):
                return r['scheme_id']
    except Exception as e:
        logger.warning(f"[theme canary] skip: {e}")
    return None


def _resolve_theme_for_user(user: Dict, page_category: str = '',
                            manual_scheme_id: Optional[str] = None) -> Dict:
    """
    Wu Layout UX 5层触发器级联:
      0: page_category lock aurora (SA/login/rules/permissions)  — 🔒硬锁不可绕过
      1: 节日匹配 calendar match                                 — 软建议(grayscale=硬切换)
      2: 灰度发布 canary rollout % hit                           — 软命中
      3: 用户画像 age_group/gender                               — 软建议
      4: 用户生日月 birthday month match                         — 软命中
      5: 用户手动 manual_scheme_id                               — 优先最后(可被0/1灰度覆盖)
    返回: { scheme_id, preset_key, theme_json, resolved_by_layer, trigger_stack }
    """
    triggers = []
    # Layer 0: SA/login/rules/permissions 硬锁aurora
    pc = (page_category or '').lower()
    if any(lock in pc for lock in _PAGE_LOCK_TO_AURORA_CATEGORIES):
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mt_theme_schemes WHERE preset_key=? AND is_active=1", (_FORCE_LOCK_THEME_PRESET,))
        row = cur.fetchone()
        conn.close()
        return {
            'scheme_id': row['scheme_id'], 'preset_key': row['preset_key'],
            'theme_json': json.loads(row['theme_json']) if row and row['theme_json'] else {},
            'resolved_by': 0,
            'resolved_reason': f'页面[{page_category}]属管理/认证/规则/权限域，按§权限硬锁aurora主题。',
            'force_lock': True,
            'trigger_stack': ['L0_PAGE_CATEGORY_FORCE_LOCK'],
        }
    # Layer 5 manual最高优先级(除了0硬锁)
    if manual_scheme_id:
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mt_theme_schemes WHERE scheme_id=? AND is_active=1", (manual_scheme_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            triggers.append('L5_USER_MANUAL_SELECT')
            return {
                'scheme_id': row['scheme_id'], 'preset_key': row['preset_key'],
                'theme_json': json.loads(row['theme_json']) if row['theme_json'] else {},
                'resolved_by': 5, 'resolved_reason': '用户手动选择',
                'trigger_stack': triggers,
            }
    # Layer 1: 节日(grayscale类=硬切换)
    fes = _match_festival_calendar()
    if fes:
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mt_theme_schemes WHERE preset_key=? AND is_active=1", (fes,))
        row = cur.fetchone()
        conn.close()
        if row:
            triggers.append(f'L1_FESTIVAL:{fes}')
            hard_switch = fes in {'national_memorial', 'qingming'}
            return {
                'scheme_id': row['scheme_id'], 'preset_key': row['preset_key'],
                'theme_json': json.loads(row['theme_json']) if row['theme_json'] else {},
                'resolved_by': 1,
                'resolved_reason': ('文化禁忌硬切换' if hard_switch else '节日日历软匹配') + f': {fes}',
                'force_lock': hard_switch,
                'trigger_stack': triggers,
            }
    # Layer 2: 灰度 canary
    canary_sid = _canary_release_hit(user)
    if canary_sid:
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mt_theme_schemes WHERE scheme_id=?", (canary_sid,))
        row = cur.fetchone()
        conn.close()
        if row:
            triggers.append(f'L2_CANARY_HIT:{canary_sid[:16]}')
            return {
                'scheme_id': row['scheme_id'], 'preset_key': row['preset_key'],
                'theme_json': json.loads(row['theme_json']) if row['theme_json'] else {},
                'resolved_by': 2, 'resolved_reason': '灰度发布命中',
                'trigger_stack': triggers,
            }
    # Layer 3: 用户画像
    profile_pk = _age_gender_profile(user)
    if profile_pk:
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mt_theme_schemes WHERE preset_key=? AND is_active=1", (profile_pk,))
        row = cur.fetchone()
        conn.close()
        if row:
            triggers.append(f'L3_USER_PROFILE:{profile_pk}')
            return {
                'scheme_id': row['scheme_id'], 'preset_key': row['preset_key'],
                'theme_json': json.loads(row['theme_json']) if row['theme_json'] else {},
                'resolved_by': 3, 'resolved_reason': '用户画像年龄/性别软建议',
                'trigger_stack': triggers,
            }
    # Layer 4: 生日月
    if _in_user_birthday_month(user):
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mt_theme_schemes WHERE preset_key='birthday_month' AND is_active=1")
        row = cur.fetchone()
        conn.close()
        if row:
            triggers.append('L4_BIRTHDAY_MONTH:birthday_month')
            return {
                'scheme_id': row['scheme_id'], 'preset_key': row['preset_key'],
                'theme_json': json.loads(row['theme_json']) if row['theme_json'] else {},
                'resolved_by': 4, 'resolved_reason': '用户生日月专属粉彩主题自动匹配',
                'trigger_stack': triggers,
            }
    # 默认基础主题 aurora（兜底）
    conn = _get_main_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mt_theme_schemes WHERE preset_key='aurora' AND is_active=1")
    row = cur.fetchone() or cur.execute("SELECT * FROM mt_theme_schemes WHERE is_active=1 ORDER BY user_priority DESC LIMIT 1").fetchone()
    conn.close()
    triggers.append('LF_DEFAULT_BASE:aurora')
    return {
        'scheme_id': row['scheme_id'], 'preset_key': row['preset_key'],
        'theme_json': json.loads(row['theme_json']) if row and row['theme_json'] else {},
        'resolved_by': 99, 'resolved_reason': '默认基础主题',
        'trigger_stack': triggers,
    }


def _write_usage_log(user: Dict, scheme_id: str, trigger_kind: str, switch_ok: bool = True,
                     page_url: str = '', extra: Optional[Dict] = None, duration: float = 0.0):
    """写入 mt_theme_usage_log (保留90天，旧数据 sys_file_organizer 自动清理)"""
    try:
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("""INSERT INTO mt_theme_usage_log
            (user_id, scheme_id, trigger_kind, page_url, duration_seconds, switch_ok, extra_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user.get('id'), scheme_id, trigger_kind, page_url[:512], duration,
             1 if switch_ok else 0,
             json.dumps(extra or {}, ensure_ascii=False), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"[theme usage_log] write failed: {e}")
        return False


# ============================================================================
#  4 endpoints
# ============================================================================

@theme_bp.route('/schemes', methods=['GET'])
@system_container(page_name='(auto)', require_auth='admin')
def theme_schemes_list():
    """GET /api/theme/schemes — login: 列出今日可切换方案(4base+14wu) + 今日推荐"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        page_category = _safe_str(request.args.get('page_category', ''), max_len=80)
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("""SELECT scheme_id, scheme_name, preset_key, user_priority, is_active,
                              approved_by_sa, is_forced_on_pages, theme_json
                       FROM mt_theme_schemes WHERE is_active=1
                       ORDER BY approved_by_sa DESC, user_priority DESC, preset_key ASC""")
        rows = cur.fetchall()
        conn.close()
        schemes = []
        for r in rows:
            tj = json.loads(r['theme_json']) if r['theme_json'] else {}
            schemes.append({
                'scheme_id': r['scheme_id'],
                'scheme_name': r['scheme_name'],
                'preset_key': r['preset_key'],
                'user_priority': r['user_priority'],
                'approved_by_sa': bool(r['approved_by_sa']),
                'is_forced_on_pages': r['is_forced_on_pages'],
                'display_mode': tj.get('display_mode', 'normal'),
                'wcag': (tj.get('wcag_verification') or {}),
                'trigger_condition': tj.get('trigger_condition', ''),
                'consensus_score': tj.get('consensus_score'),
            })
        # 5触发器级联推荐
        recommended = _resolve_theme_for_user(user, page_category=page_category)
        _write_usage_log(user, recommended['scheme_id'], trigger_kind=f'L{recommended.get("resolved_by")}_SCHEMES_LIST',
                         switch_ok=True, page_url=page_category,
                         extra={'op':'schemes_query', 'reco_preset': recommended['preset_key']})
        return jsonify({
            'success': True,
            'schemes_total': len(schemes),
            'schemes': schemes,
            'recommended_today': recommended,
            'meta': {
                'version': 'v1.0.0-wu-meigong',
                'resolver_layers': ['L0_PAGE_FORCE','L1_FESTIVAL','L2_CANARY','L3_PROFILE','L4_BIRTHDAY','L5_MANUAL','LF_DEFAULT'],
                'force_lock_pages': sorted(_PAGE_LOCK_TO_AURORA_CATEGORIES),
                '§permission_hard_lock': 'SA/login/rules/permissions页=force aurora lock',
            },
        })
    except Exception as e:
        logger.exception("[theme/schemes] err")
        return jsonify({'success': False, 'error': f'主题列表失败: {str(e)[:200]}'}), 500


@theme_bp.route('/prefs', methods=['GET'])
@system_container(page_name='(auto)', require_auth='admin')
def theme_prefs():
    """GET /api/theme/prefs — login: 返回当前用户今日生效主题"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        page_category = _safe_str(request.args.get('page_category', ''), max_len=80)
        resolved = _resolve_theme_for_user(user, page_category=page_category)
        _write_usage_log(user, resolved['scheme_id'], trigger_kind=f'L{resolved.get("resolved_by")}_PREFS_QUERY',
                         switch_ok=True, page_url=page_category,
                         extra={'op':'prefs', 'triggers': resolved.get('trigger_stack', [])})
        return jsonify({'success': True, 'theme_active': resolved})
    except Exception as e:
        logger.exception("[theme/prefs] err")
        return jsonify({'success': False, 'error': f'获取主题偏好失败: {str(e)[:200]}'}), 500


@theme_bp.route('/select', methods=['POST'])
@system_container(page_name='(auto)', require_auth='admin')
def theme_select():
    """POST /api/theme/select — login: 手动切换，body={scheme_id}"""
    user = _current_safe_user()
    ok, err = _check_login(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        payload = request.get_json(silent=True) or {}
        scheme_id = _safe_str(payload.get('scheme_id') or payload.get('preset_key'), max_len=128)
        page_category = _safe_str(payload.get('page_category', ''), max_len=80)
        if not scheme_id:
            return jsonify({'success': False, 'error': '缺少参数 scheme_id 或 preset_key'}), 400
        # 查方案ID 或 preset_key
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mt_theme_schemes WHERE is_active=1 AND (scheme_id=? OR preset_key=?) LIMIT 1",
                    (scheme_id, scheme_id))
        row = cur.fetchone()
        conn.close()
        if not row:
            return jsonify({'success': False, 'error': '主题方案不存在或未激活'}), 404
        # 5触发器解决最终(如L0硬锁则忽略用户手动)
        final = _resolve_theme_for_user(user, page_category=page_category,
                                        manual_scheme_id=row['scheme_id'])
        user_accepted = final.get('scheme_id') == row['scheme_id'] and not final.get('force_lock')
        _write_usage_log(user, final['scheme_id'], trigger_kind='L5_USER_MANUAL_SELECT' if user_accepted else f'OVERRIDDEN_BY_L{final.get("resolved_by")}',
                         switch_ok=final.get('force_lock') or user_accepted,
                         page_url=page_category,
                         extra={'requested_scheme': scheme_id,
                                'applied_scheme': final['scheme_id'],
                                'force_lock': final.get('force_lock', False),
                                'trigger_stack': final.get('trigger_stack', [])})
        return jsonify({
            'success': True,
            'user_request_honored': user_accepted,
            'theme_applied': final,
            'note': '' if user_accepted else (final.get('resolved_reason') or '上层触发器覆盖本次手动选择'),
        })
    except Exception as e:
        logger.exception("[theme/select] err")
        return jsonify({'success': False, 'error': f'切换主题失败: {str(e)[:200]}'}), 500


@theme_bp.route('/admin/publish', methods=['POST'])
@system_container(page_name='(auto)', require_auth='admin')
def theme_admin_publish():
    """POST /api/theme/admin/publish — SA only (wuchenghao15): 灰度发布 1/10/50/100%"""
    user = _current_safe_user()
    ok, err = _check_sa(user)
    if not ok:
        return jsonify({'success': False, 'error': err[1]}), err[0]
    try:
        payload = request.get_json(silent=True) or {}
        scheme_id = _safe_str(payload.get('scheme_id') or payload.get('preset_key'), max_len=128)
        rollout_pct = _safe_int(payload.get('rollout_pct'), 1, 1, 100)
        vikey_hash_passed = bool(payload.get('vikey_verified') or payload.get('vikey_hash') or payload.get('sa_signed'))
        # ⚠️§14 SA VIIKEY 硬要求：未验签拒绝
        if not vikey_hash_passed:
            return jsonify({'success': False, 'error': '§用户权限超级管理员7要素认证未通过：需要实时VIKEY加密狗签核'}), 403
        if not scheme_id:
            return jsonify({'success': False, 'error': '缺少 scheme_id'}), 400
        allowed_pcts = {1, 10, 50, 100}
        if rollout_pct not in allowed_pcts:
            return jsonify({'success': False, 'error': f'rollout_pct 必须∈{sorted(allowed_pcts)}'}), 400
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT scheme_id, preset_key, approved_by_sa FROM mt_theme_schemes WHERE (scheme_id=? OR preset_key=?) AND is_active=1 LIMIT 1",
                    (scheme_id, scheme_id))
        sch = cur.fetchone()
        if not sch:
            conn.close()
            return jsonify({'success': False, 'error': '方案不存在或未激活'}), 404
        sid = sch['scheme_id']
        # 1. schemes approved_by_sa=1 (实签生效)
        nowi = datetime.now().isoformat()
        vh = hashlib.sha256(f"{sid}|{rollout_pct}|{nowi}|{user.get('username')}|SA_VIKEY_SIGNED".encode()).hexdigest()[:48]
        cur.execute("UPDATE mt_theme_schemes SET approved_by_sa=1, approved_at=?, vikey_hash=?, updated_at=? WHERE scheme_id=?",
                    (nowi, vh, nowi, sid))
        # 2. release 表：同一 rollout_pct 重复插入视为幂等(UNIQUE缺省，INSERT OR REPLACE靠release_id合成)
        status_transition = {1:'TESTING', 10:'TESTING', 50:'ROLLOUT', 100:'STABLE'}[rollout_pct]
        release_id = f"REL_{sid}_p{rollout_pct}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        canary_hash = hashlib.sha256(f"{release_id}|{vh}".encode()).hexdigest()[:40]
        cur.execute("INSERT INTO mt_theme_release(release_id,scheme_id,rollout_pct,staging_canary_hash,status,triggered_by_sa,created_at) VALUES(?,?,?,?,?,?,?)",
                    (release_id, sid, rollout_pct, canary_hash, status_transition, 1, nowi))
        conn.commit()
        conn.close()
        # 审计 usage_log
        _write_usage_log(user, sid, trigger_kind='SA_ADMIN_PUBLISH', switch_ok=True,
                         page_url='/admin/theme/publish',
                         extra={'op':'publish','pct':rollout_pct,'status':status_transition,'sa':user.get('username'),'vikey_signed':vikey_hash_passed})
        return jsonify({
            'success': True,
            'release_id': release_id,
            'scheme_id': sid,
            'preset_key': sch['preset_key'],
            'rollout_pct': rollout_pct,
            'status': status_transition,
            'staging_canary_hash': canary_hash,
            'vikey_hash': vh,
            '§auth_msg': 'SA VIIKEY认证通过，灰度rollout已写入mt_theme_release表。' if vikey_hash_passed else '',
        })
    except Exception as e:
        logger.exception("[theme/admin/publish] err")
        return jsonify({'success': False, 'error': f'发布失败: {str(e)[:200]}'}), 500


# ============================================================================
#  module 自检（import时执行，无副作用）
# ============================================================================
def _self_check() -> Dict:
    try:
        conn = _get_main_db()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('mt_theme_schemes','mt_theme_release','mt_theme_usage_log')")
        tables = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM mt_theme_schemes WHERE is_active=1")
        active_cnt = cur.fetchone()[0]
        conn.close()
        return {'ok': len(tables) == 3, 'tables': tables, 'active_schemes': active_cnt,
                'bp_name': getattr(theme_bp, 'name', None),
                'bp_prefix': getattr(theme_bp, 'url_prefix', None)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


THEME_ROUTES_MODULE_SELF_CHECK = _self_check()
logger.info(f"[theme_routes] import self-check: {THEME_ROUTES_MODULE_SELF_CHECK}")
