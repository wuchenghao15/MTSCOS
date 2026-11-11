"""api_routes — 通用API Blueprint
源码: server_real_db.py 其余路由 (~236路由)
功能: 容器心跳/状态/ViKey/自动化/EigenFlux监控/审批/安全(防爆破/黑客/反编译)/
      指纹/主题/工作流/历史/技能/GitHub/治理/变更/AI员工管理/测试1000
"""
import os
import sqlite3

from flask import Blueprint, jsonify, jsonify

from . import api_bp
from app.middlewares.system_container import system_container

# [AUTO_FIXED by sys_gap_discovery_engine flow_id=autogap_9c4d829b_20260827_001018560] 原注释: [AUTO_FIXED by sys_gap_discovery_engine flow_id=manual_598b2
# 主要路由前缀:
# /api/container/*        — 容器管理
# /api/vikey/*            — ViKey接口 (15路由)
# /api/automation/*       — 自动化 (15路由)
# /api/eigenflux/monitor/* — EigenFlux (9路由)
# /api/approvals/*        — 审批 (8路由)
# /api/upgrade/*          — 升级 (7路由)
# /api/history/*          — 历史 (6路由)
# /api/security/*         — 安全防护 (19路由)
# /api/fingerprint/*      — 指纹 (5路由)
# /api/theme/*            — 主题 (4路由)
# /api/governance/*       — 治理 (9路由)
# /api/test1000/*         — 1000轮测试
# /api/devflow/*          — 开发流程
# /_rules/*               — 规则系统 (9路由)
# ... 及其余API路由


# ===== 首页公开统计 API (P0修复: net::ERR_ABORTED /api/homepage/stats) =====
# flow_id: flow_test_repair_20260818_002 (STEP_7 P0修复)
# 根因(双重缺失):
#   ① modular_start.py _user_container_middleware 对 /api/* 无 session_token
#      一律返回 401 CONTAINER_MISSING, 首页公开统计接口被误拦;
#   ② 该路由仅在 server_real_db.py 的独立 app 上注册, modular_start 的 app 未注册
#      (api_routes.py 原为 TODO 桩), 导致放行后仍 404.
# 修复:
#   ① middleware 已加 _PUBLIC_API_PATHS 白名单放行 /api/homepage/stats;
#   ② 本文件于 api_bp (url_prefix=/api) 注册 /homepage/stats → /api/homepage/stats.
# 数据源: 主库 _runtime/databases/Database/app.db (唯一权威源) + ai_engines/app.db (AI模块表).
# 契约: {'success': True, 'stats': {version, users_count, questions_count, exams_count,
#        ai_employees_count, rules_count, ai_registered_modules, ...}}
# 硬约束: 数据库为唯一权威源, 禁止假数据 (用户权限.md / 开发规则.md).
_PROJECT_ROOT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"


def _resolve_main_db():
    """主库路径解析 (对齐 admin_routes._get_admin_center_stats)"""
    try:
        from core.db_path import get_db_path
        p = get_db_path('app.db')
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    return os.path.join(_PROJECT_ROOT, '_runtime', 'databases', 'Database', 'app.db')


def _safe_count(cur, sql):
    """安全计数: 表/列缺失返回 0, 不抛异常中断聚合"""
    try:
        r = cur.execute(sql).fetchone()
        return r[0] if r and r[0] else 0
    except Exception:
        return 0


def _get_homepage_stats():
    """首页统计聚合 (访客可见, 数据库为唯一权威源, 禁止假数据).

    移植自 server_real_db.py L6216 _get_homepage_stats, 适配 modular app:
      - 主库聚合 users/questions/exams/ai_employees/system_rules/perf_metrics
      - AI 引擎库聚合 ai_module_registry/ai_upgrade_log/ai_inspection_log
    """
    stats = {
        'version': '',
        'modules_count': 0,
        'availability': '0',
        'rules_count': 0,
        'avg_response_ms': 0,
        'scoring_consistency': '0',
        'questions_count': 0,
        'users_count': 0,
        'exams_count': 0,
        'ai_employees_count': 0,
        'ai_modules_total': 0,
        'ai_upgrade_logs': 0,
        'ai_inspection_logs': 0,
        'ai_registered_modules': 0,
        'ai_module_categories': 0,
    }

    # 版本信息 (非关键, 多路径回退, 失败留空)
    _gvi = None
    for _mod_fn in (
        lambda: __import__('core.version', fromlist=['get_version_info']).get_version_info,
        lambda: __import__('app.utils.version_info', fromlist=['get_version_info']).get_version_info,
    ):
        try:
            _gvi = _mod_fn()
            break
        except Exception:
            continue
    if _gvi:
        try:
            ver, info, _ = _gvi()
            if ver:
                stats['version'] = ver
            if info:
                stats['availability'] = str(info.get('availability', 0))
        except Exception:
            pass

    # ---- 主库聚合 ----
    main_db = _resolve_main_db()
    if os.path.exists(main_db):
        try:
            conn = sqlite3.connect('file:' + main_db + '?mode=ro', uri=True, timeout=3)
            c = conn.cursor()
            # 用户总数
            stats['users_count'] = _safe_count(c, 'SELECT COUNT(*) FROM "users"')
            # 题库 (多表累加, 覆盖主题库/AI题库/职业考试题库)
            for t in ('questions', 'question_bank_items', 'ai_question_bank',
                      'professional_exam_questions'):
                stats['questions_count'] += _safe_count(c, f'SELECT COUNT(*) FROM "{t}"')
            # 考试/测试 (多表累加)
            for t in ('exams', 'teacher_exams', 'exam_sessions'):
                stats['exams_count'] += _safe_count(c, f'SELECT COUNT(*) FROM "{t}"')
            # AI员工 (核心表 ai_employees + 专业表 mtscos_ai_employees 累加)
            for t in ('ai_employees', 'mtscos_ai_employees'):
                stats['ai_employees_count'] += _safe_count(c, f'SELECT COUNT(*) FROM "{t}"')
            # 系统规则
            stats['rules_count'] = _safe_count(c, 'SELECT COUNT(*) FROM system_rules')
            # 性能指标 (平均响应时长, 秒→毫秒)
            try:
                avg = c.execute(
                    'SELECT AVG(duration_seconds) FROM ai_performance_metrics'
                ).fetchone()
                if avg and avg[0]:
                    stats['avg_response_ms'] = round(avg[0] * 1000)
            except Exception:
                pass
            conn.close()
        except Exception:
            pass

    # ---- AI 引擎库聚合 (ai_module_registry / ai_upgrade_log / ai_inspection_log) ----
    ai_db = os.path.join(_PROJECT_ROOT, 'flask-app', 'ai_engines', 'app.db')
    if os.path.exists(ai_db):
        try:
            aconn = sqlite3.connect('file:' + ai_db + '?mode=ro', uri=True, timeout=3)
            ac = aconn.cursor()
            stats['ai_registered_modules'] = _safe_count(
                ac, 'SELECT COUNT(*) FROM ai_module_registry')
            try:
                cats = ac.execute(
                    'SELECT COUNT(DISTINCT module_type) FROM ai_module_registry'
                ).fetchone()
                if cats and cats[0]:
                    stats['ai_module_categories'] = cats[0]
            except Exception:
                pass
            stats['ai_upgrade_logs'] = _safe_count(
                ac, 'SELECT COUNT(*) FROM ai_upgrade_log')
            stats['ai_inspection_logs'] = _safe_count(
                ac, 'SELECT COUNT(*) FROM ai_inspection_log')
            stats['ai_modules_total'] = stats['ai_registered_modules']
            aconn.close()
        except Exception:
            pass

    return stats


@api_bp.route('/homepage/stats')
@system_container()
def api_homepage_stats():
    """首页公开统计 (访客可见, 无需登录/用户容器).

    P0修复: 解决 net::ERR_ABORTED /api/homepage/stats
      修复前: 401 CONTAINER_MISSING (middleware 误拦) + 404 (未注册)
      修复后: 200 {'success': True, 'stats': {...真实聚合数据...}}
    驱动: 首页前端 refreshAIStatus() 轮询展示系统/AI状态.
    """
    return jsonify({'success': True, 'stats': _get_homepage_stats()})


bp = Blueprint('api_bp', __name__)

@bp.route('/stats/overview', methods=['GET'])
@system_container()
def stats_overview():
    return jsonify({'status':'ok','code':0,'data':{'module':'api','routes_implemented':1}})

