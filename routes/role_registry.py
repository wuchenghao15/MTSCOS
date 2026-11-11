#!/usr/bin/env python3
"""
仙女座角色注册表 (v25.0 — 单点权威源)
====================================

所有角色定义集中在此处 — 路由权限/菜单可见性/功能开关/冰山绑定 全部从此读取.
改角色 → 改这个文件 → 全链路自动同步.

注册: routes/__init__.py 自动扫描 ROLE_REGISTRY 注册蓝图
权限: app/middlewares/system_container.py ROLE_TO_PERM 同步更新
"""
from __future__ import annotations
from typing import Dict, List, Any


# ═══════════════════════════════════════════════════════════
# 权限矩阵定义
# ═══════════════════════════════════════════════════════════
# 键名 → 含义:
#   write_wenquxing   — 文曲星生文
#   view_iceberg      — 冰山控制中心(只读)
#   view_ai_workbench — 仙女座 AI 工作台
#   view_daemon       — daemon 活率/心跳
#   view_employee     — AI 员工/天团
#   view_brain        — 知识脑库
#   view_budget       — 算力/Token 预算
#   view_audit        — 权限审计日志
#   manage_user       — 用户增删改
#   manage_course     — 课程/考试管理
#   manage_content    — 内容审批/发布
#   manage_daemon     — daemon 启停
#   view_exam_result  — 考试结果查看权限
#   view_student_list — 学生名单可见
# ═══════════════════════════════════════════════════════════

ROLE_REGISTRY: Dict[str, Dict[str, Any]] = {

    # ── 核心 3 角色 ──
    "super_admin": {
        "label": "超级管理员", "label_en": "Super Admin",
        "icon": "👑", "perm_level": "super_admin",
        "desc": "全权限不受约束. 7要素双钥认证.",
        "can": {
            "write_wenquxing": True, "view_iceberg": True,
            "view_ai_workbench": True, "view_daemon": True,
            "view_employee": True, "view_brain": True,
            "view_budget": True, "view_audit": True,
            "manage_user": True, "manage_course": True,
            "manage_content": True, "manage_daemon": True,
            "view_exam_result": True, "view_student_list": True,
        },
        "pages": ["/andromeda/iceberg_center", "/andromeda/health_board",
                  "/andromeda/eigenflux_council", "/andromeda/upgrade_board"],
        "iceberg_domain": "ALL",
    },
    "admin": {
        "label": "管理员", "label_en": "Administrator",
        "icon": "🛡️", "perm_level": "admin",
        "desc": "后台审批+管理, 不可生文.",
        "can": {
            "write_wenquxing": False,  # 被禁! 文曲星学生专属
            "view_iceberg": True, "view_ai_workbench": False,
            "view_daemon": True, "view_employee": False,
            "view_brain": False, "view_budget": False,
            "view_audit": True, "manage_user": True,
            "manage_course": True, "manage_content": True,
            "manage_daemon": False, "view_exam_result": True,
            "view_student_list": True,
        },
        "pages": ["/andromeda/iceberg_center"],
        "iceberg_domain": "iceberg_admin",
    },
    "student": {
        "label": "学生", "label_en": "Student",
        "icon": "🎓", "perm_level": "login",
        "desc": "文曲星生文+学习+冰山浏览.",
        "can": {
            "write_wenquxing": True, "view_iceberg": True,
            "view_ai_workbench": False, "view_daemon": False,
            "view_employee": True, "view_brain": True,
            "view_budget": False, "view_audit": False,
            "manage_user": False, "manage_course": False,
            "manage_content": False, "manage_daemon": False,
            "view_exam_result": True, "view_student_list": False,
        },
        "pages": ["/andromeda/wenquxing", "/andromeda/iceberg_center",
                  "/andromeda/iceberg_evolution"],
        "iceberg_domain": "wenquxing",
    },

    # ── 🆕 5 大教育角色 (v25.0) ──
    "teacher": {
        "label": "教师", "label_en": "Teacher",
        "icon": "📚", "perm_level": "login",
        "desc": "带班级+布置作业+批改+查看学生考试成绩. 不可生文.",
        "can": {
            "write_wenquxing": False,  # 被禁
            "view_iceberg": True, "view_ai_workbench": False,
            "view_daemon": False, "view_employee": True,
            "view_brain": True, "view_budget": False,
            "view_audit": False, "manage_user": False,
            "manage_course": True, "manage_content": False,
            "manage_daemon": False, "view_exam_result": True,
            "view_student_list": True,
        },
        "pages": ["/andromeda/iceberg_center"],
        "iceberg_domain": "education",
        "features": {
            "teacher_workbench": True,
            "homework_assign": True,
            "exam_create": True,
            "exam_grade": True,
            "student_progress_view": True,
        },
    },
    "professor": {
        "label": "教授", "label_en": "Professor",
        "icon": "🎓", "perm_level": "login",
        "desc": "科研+长课程+论文指导+多班级. 不可生文.",
        "can": {
            "write_wenquxing": False,  # 被禁
            "view_iceberg": True, "view_ai_workbench": True,  # 唯一除 SA 外能看 AI 工作台
            "view_daemon": False, "view_employee": True,
            "view_brain": True, "view_budget": False,
            "view_audit": False, "manage_user": False,
            "manage_course": True, "manage_content": True,   # 审批自己的内容
            "manage_daemon": False, "view_exam_result": True,
            "view_student_list": True,
        },
        "pages": ["/andromeda/iceberg_center", "/andromeda/eigenflux_council"],
        "iceberg_domain": "education_research",
        "features": {
            "professor_workbench": True,
            "course_create": True,
            "research_dashboard": True,
            "thesis_advise": True,
            "ai_workbench_view": True,  # 教授可看 AI 工作台
        },
    },
    "counselor": {
        "label": "导员", "label_en": "Counselor",
        "icon": "💬", "perm_level": "login",
        "desc": "心理辅导+考勤+班级通知+家校沟通. 不可生文.",
        "can": {
            "write_wenquxing": False,  # 被禁
            "view_iceberg": True, "view_ai_workbench": False,
            "view_daemon": False, "view_employee": True,
            "view_brain": False, "view_budget": False,
            "view_audit": False, "manage_user": False,
            "manage_course": False, "manage_content": False,
            "manage_daemon": False, "view_exam_result": False,  # 导员不看成绩
            "view_student_list": True,
        },
        "pages": ["/andromeda/iceberg_center"],
        "iceberg_domain": "education_wellness",
        "features": {
            "counselor_workbench": True,
            "attendance_view": True,
            "class_notice": True,
            "parent_comm": True,
            "student_wellness": True,
        },
    },
    "mentor": {
        "label": "导师", "label_en": "Mentor",
        "icon": "🌟", "perm_level": "login",
        "desc": "一对一带徒+职业规划+项目指导. 不可生文.",
        "can": {
            "write_wenquxing": False,  # 被禁
            "view_iceberg": True, "view_ai_workbench": False,
            "view_daemon": False, "view_employee": True,
            "view_brain": True, "view_budget": False,
            "view_audit": False, "manage_user": False,
            "manage_course": False, "manage_content": False,
            "manage_daemon": False, "view_exam_result": True,
            "view_student_list": True,
        },
        "pages": ["/andromeda/iceberg_center"],
        "iceberg_domain": "education_mentorship",
        "features": {
            "mentor_workbench": True,
            "mentee_tracker": True,
            "career_planning": True,
            "project_review": True,
        },
    },
    "parent": {
        "label": "家长", "label_en": "Parent",
        "icon": "👨‍👩‍👧", "perm_level": "login",
        "desc": "只看自己孩子的成绩+考勤+作业. 不可生文.",
        "can": {
            "write_wenquxing": False,  # 被禁
            "view_iceberg": False, "view_ai_workbench": False,
            "view_daemon": False, "view_employee": False,
            "view_brain": False, "view_budget": False,
            "view_audit": False, "manage_user": False,
            "manage_course": False, "manage_content": False,
            "manage_daemon": False, "view_exam_result": True,  # 只看自己孩子
            "view_student_list": False,
        },
        "pages": [],  # 家长不看冰山
        "iceberg_domain": "education_parent",
        "features": {
            "parent_portal": True,
            "my_child_grade": True,
            "homework_view": True,
            "attendance_view": True,
        },
    },
}


# ── 便捷查询 ──
def get_role(key: str) -> Dict | None:
    return ROLE_REGISTRY.get((key or '').strip().lower())

def get_perm_level(key: str) -> str:
    return (get_role(key) or {}).get('perm_level', 'guest')

def can_do(key: str, action: str) -> bool:
    r = get_role(key)
    return bool(r and r.get('can', {}).get(action, False))

def list_roles_by_perm() -> Dict[str, List[str]]:
    """按权限级分组列出所有角色"""
    groups: Dict[str, List[str]] = {}
    for k, v in ROLE_REGISTRY.items():
        groups.setdefault(v['perm_level'], []).append(k)
    return groups

def list_all_role_keys() -> List[str]:
    return list(ROLE_REGISTRY.keys())


# ── Flask Blueprint 自动注册钩子 ──
# 每个教育角色有专属子蓝图, 挂载到 /role/<key>/...
# routes/__init__.py 会扫描 ROLE_REGISTRY 自动注册
def build_role_blueprints(app=None) -> Dict[str, Any]:
    """为每个角色构建专属蓝图 (自动注册到 Flask app 后可直接访问)
    返回: {role_key: Blueprint_instance}
    """
    from flask import Blueprint

    bps = {}
    for role_key, info in ROLE_REGISTRY.items():
        bp_name = f"role_{role_key}"
        bp = Blueprint(bp_name, __name__, url_prefix=f"/role/{role_key}")

        @bp.route("/")
        def _role_dashboard(role_key=role_key, info=info):
            """角色专属工作台"""
            from flask import render_template, session as _sess
            sess_role = (_sess.get('role') or '').lower()
            # 权限校验: 只有对应角色 + SA 能看自己的工作台
            if sess_role not in (role_key, 'super_admin', 'sa'):
                return ("<h1>🔒 403 无权限</h1>", 403)
            return render_template(
                "role_dashboard.html",
                role_key=role_key, role_info=info,
                iceberg_domain=info.get('iceberg_domain', 'general'),
            )

        # 角色专属 API 前缀
        @bp.route("/api/me")
        def _role_me(role_key=role_key, info=info):
            from flask import jsonify, session as _sess
            return jsonify({
                "role": role_key,
                "label": info['label'],
                "icon": info['icon'],
                "can": info['can'],
                "features": info.get('features', {}),
            })

        bps[role_key] = bp

    return bps


if __name__ == "__main__":
    import json
    print("📊 仙女座角色注册表 (v25.0)")
    print("=" * 60)
    groups = list_roles_by_perm()
    for level, roles in sorted(groups.items(), key=lambda x: ['guest', 'login', 'admin', 'super_admin'].index(x[0]) if x[0] in ['guest','login','admin','super_admin'] else 99):
        print(f"\n  [{level.upper()}] — {len(roles)} 个角色")
        for r in roles:
            info = ROLE_REGISTRY[r]
            print(f"    {info['icon']} {r:20s} {info['label']:8s} → {info.get('iceberg_domain', '-')}")
    print(f"\n✅ 总计 {len(ROLE_REGISTRY)} 个角色")
