"""v1/teams — AI 天团 + AI 员工 + 仙女座员工库"""
from flask import Blueprint, jsonify
from .._helpers import _db_conn, _api_success, _api_error

bp = Blueprint("andromeda_v1_teams", __name__, url_prefix="/teams")


@bp.route("/all", methods=["GET"])
def teams_all():
    """全部 AI 天团全景 (SVG 银河用)."""
    try:
        conn = _db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT team_id, team_name, member_count, skill_keywords, color_tag, auto_formed_at
            FROM mt_team_registry ORDER BY member_count DESC""")
        registry = [dict(r) for r in cur.fetchall()]

        teams, core_mask = [], [
            'GRAND_MASTER','UI_MASTER','ARCHITECT','COMPLIANCE','DBA','AUTO_EVOLUTION',
            'SYSTEM_ENGINEERING_PIONEER','SECURITY']
        for reg in registry:
            cur.execute("""
                SELECT member_name, skill_level, source, capabilities FROM mt_team_members
                WHERE team_name=? ORDER BY
                    CASE UPPER(skill_level) WHEN 'NATIONAL_GRAND_MASTER' THEN 0
                    WHEN 'GRAND_MASTER' THEN 1 WHEN 'ARCHITECT' THEN 2
                    WHEN 'UI_MASTER' THEN 3 WHEN 'COMPLIANCE' THEN 4
                    WHEN 'DBA' THEN 5 WHEN 'AUTO_EVOLUTION' THEN 6 ELSE 50 END,
                    member_name LIMIT 8""", (reg['team_name'],))
            members = [dict(r) for r in cur.fetchall()]
            teams.append({
                "team_id": reg["team_id"], "team_name": reg["team_name"],
                "member_count": reg["member_count"],
                "color": reg["color_tag"] or "#95A5A6",
                "skill_keywords": reg["skill_keywords"] or "",
                "has_core_expert": any(m["skill_level"] in core_mask for m in members),
                "core_members": members,
            })
        conn.close()
        total = sum(t["member_count"] for t in teams)
        tech = {"🎨 前端艺术天团","🏛️ 架构天团","⚙️ 后端工程天团","🗄️ DBA 天团",
                "🤖 AI 引擎天团","⚖️ 合规安全天团","🧪 测试巡检天团","📚 题库教育天团",
                "🛠️ DevOps 天团","🧠 知识脑库天团","💬 产品交互天团","🔧 运维修复天团"}
        return jsonify(_api_success(
            total_members=total, total_teams=len(teams),
            tech_members=sum(t["member_count"] for t in teams if t["team_name"] in tech),
            culture_members=sum(t["member_count"] for t in teams if t["team_name"] not in tech),
            teams=teams,
        ))
    except Exception as e:
        return _api_error(str(e))


@bp.route("/employees", methods=["GET"])
def teams_employees():
    """AI 员工全景 + 来源分布 + EigenFlux 注册状态."""
    try:
        conn = _db_conn()
        cur = conn.cursor()
        total_ai = cur.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]
        total_mtscos = cur.execute("SELECT COUNT(*) FROM mtscos_ai_employees").fetchone()[0]
        total_reg = cur.execute("SELECT COUNT(*) FROM eigenflux_registrations").fetchone()[0]
        pending_invite = 0
        try:
            pending_invite = cur.execute(
                "SELECT COUNT(*) FROM eigenflux_registrations WHERE registration_status='pending_invite'"
            ).fetchone()[0]
        except Exception:
            pass
        source_dist = {}
        try:
            for r in cur.execute(
                "SELECT source, COUNT(*) FROM mt_ai_auto_hire_log GROUP BY source ORDER BY COUNT(*) DESC"):
                source_dist[r[0]] = r[1]
        except Exception:
            pass
        recent = []
        try:
            cur.execute("""
                SELECT a.name, a.description, a.status, a.specialties, a.created_at, a.model_version,
                       r.registration_status as ef_status
                FROM ai_employees a LEFT JOIN eigenflux_registrations r ON r.employee_name=a.name
                ORDER BY a.created_at DESC LIMIT 20""")
            recent = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass
        conn.close()
        return jsonify(_api_success(
            totals={"ai_employees": total_ai, "mtscos_ai_employees": total_mtscos,
                    "eigenflux_registrations": total_reg, "pending_eigenflux_invite": pending_invite},
            source_distribution=source_dist, recent=recent,
        ))
    except Exception as e:
        return _api_error(str(e))


@bp.route("/registry", methods=["GET"])
def teams_registry():
    """仙女座 33K+ 员工库统计 (level/source 分布 + 高等级样本)."""
    try:
        conn = _db_conn()
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) FROM mt_andromeda_employee_registry").fetchone()[0]
        level_dist = {}
        for r in cur.execute("SELECT level, COUNT(*) FROM mt_andromeda_employee_registry GROUP BY level ORDER BY level"):
            level_dist[f"L{r[0]}"] = r[1]
        source_dist = {}
        try:
            for r in cur.execute("""
                SELECT employee_source, COUNT(*) FROM mt_andromeda_employee_registry
                GROUP BY employee_source ORDER BY COUNT(*) DESC LIMIT 10"""):
                source_dist[r[0]] = r[1]
        except Exception:
            pass
        high_level = cur.execute(
            "SELECT COUNT(*) FROM mt_andromeda_employee_registry WHERE level >= 7").fetchone()[0]
        bridged = 0
        try:
            bridged = cur.execute(
                "SELECT COUNT(*) FROM mt_ai_auto_hire_log WHERE source='ANDROMEDA_REGISTRY'"
            ).fetchone()[0]
        except Exception:
            pass
        samples = []
        try:
            cur.execute("""
                SELECT employee_id, name, employee_type, level, employee_source,
                       neuralhub_task, route_priority, enabled
                FROM mt_andromeda_employee_registry
                WHERE level >= 8 AND enabled=1 ORDER BY level DESC, call_count DESC LIMIT 15""")
            samples = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass
        conn.close()
        return jsonify(_api_success(
            total_registry=total, level_distribution=level_dist,
            source_distribution=source_dist, high_level_total=high_level,
            already_bridged=bridged, available_to_bridge=high_level - bridged,
            high_level_samples=samples,
        ))
    except Exception as e:
        return _api_error(str(e))
