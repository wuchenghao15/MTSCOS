#!/usr/bin/env python3
"""
📱 移动端主应用蓝图 · Flask
==============================
给 templates/mobile/*.html 里写好的 20 个模板接上真正的路由。

之前的坑:
  - server_real_db._REDIRECT_MAP 把 /mobile/* 全重定向到 PC 端路由
  - 防盗链拦截器又把重定向后的请求挡回 /index

路由:
  GET  /mobile/              → 重定向 /mobile/home
  GET  /mobile/home          → 移动端首页 (home.html)
  GET  /mobile/exam          → 考试列表 (exam.html)
  GET  /mobile/exam/<id>     → 考试详情 (exam.html 内联)
  GET  /mobile/learn         → 学习中心 (learn.html)
  GET  /mobile/profile       → 个人中心 (profile.html)
  GET  /mobile/login         → 登录页 (login.html)
  POST /mobile/login         → 登录提交
  GET  /mobile/logout        → 退出登录
  GET  /mobile/notifications → 通知中心 (notifications.html)
  GET  /mobile/wrong_book    → 错题本 (暂重定向 /mobile/home)
"""

import os, sqlite3
from datetime import datetime
from flask import Blueprint, render_template, request, session, redirect, jsonify

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, 'database', 'app.db')

mobile_bp = Blueprint('mobile_app', __name__, url_prefix='/mobile')

# 移动端 APK WebView 无法携带跨域 CSRF cookie, 豁免整个蓝图
try:
    from flask_wtf.csrf import CSRFProtect
    mobile_bp.csrf.exempt(mobile_bp)
except Exception:
    try:
        # Flask-WTF 1.x API
        from flask_wtf.csrf import CSRFProtect
        CSRFProtect().exempt(mobile_bp)
    except Exception:
        pass


# ─── 工具函数 ──────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def _current_user():
    """从 session 取当前用户 ctx"""
    if not session.get('logged_in'):
        return None
    return {
        'user_id': session.get('user_id', 0),
        'username': session.get('username', '未知'),
        'role': session.get('role', 'student'),
        'role_canonical': session.get('role_canonical', 'user'),
        'grade': session.get('grade', ''),
        'auth_method': session.get('auth_method', 'password'),
    }

def _require_login():
    """未登录 → 跳 /mobile/login"""
    if not session.get('logged_in'):
        return redirect('/mobile/login')
    return None


# ─── 首页 /mobile/home ────────────────────────────────────

@mobile_bp.route('/', methods=['GET'])
@mobile_bp.route('/home', methods=['GET'])
def mobile_home():
    redir = _require_login()
    if redir: return redir

    user = _current_user()
    exam_count = 0
    test_count = 0
    streak_days = 0
    upcoming_exams = []

    try:
        db = _db()
        # 题库聚合 (给首页展示)
        bank_count = 0
        total_questions = 0
        bank_preview = []
        try:
            for tbl, display, subject, cat, icon, icontype in _QB_TABLES:
                try:
                    cnt = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    if cnt > 0:
                        bank_count += 1
                        total_questions += cnt
                        bank_preview.append({
                            'name': display, 'subject': subject, 'category': cat,
                            'count': cnt, 'icon': icon,
                        })
                except Exception:
                    continue
        except Exception:
            pass

        db.close()
    except Exception:
        pass

    return render_template(
        'mobile/home.html',
        user=user,
        grade=user.get('grade', '') if user else '',
        bank_count=bank_count,
        total_questions=total_questions,
        stats={'streak_days': streak_days},
        bank_preview=bank_preview,
        tabbar_active='home',
    )


# ─── 题库管理 /mobile/question_bank ───────────────────────

# 各题库表定义 (统一元信息: 表名 / 显示名 / 学科 / 分类 / 图标)
_QB_TABLES = [
    # (table_name, display_name, subject, category, fa_icon, icon_type)
    ('adult_education_questions', '成人教育题库', '成人教育', '成人教育', 'fa-graduation-cap', 'cool'),
    ('professional_exam_questions', '职业考试题库', '职业考试', '职业资格', 'fa-briefcase', 'warm'),
    ('mt_exam_questions_pool', 'MTSCOS 题库池', 'MTSCOS综合', '综合', 'fa-database', ''),
    ('mt_exam_australian_questions', '澳洲教材题库', '澳洲课程', '国际课程', 'fa-earth-asia', 'cool'),
    ('ai_maintenance_questions', 'AI 维护题库', 'AI系统维护', 'AI/系统', 'fa-robot', 'warm'),
    ('test_questions', '测试题库', '测试', '测试', 'fa-vial', ''),
]

# 分类映射 (给 /mobile/question_bank?category=xxx 用)
_QB_CATEGORY_MAP = {
    'all':   '全部',
    'k12':   'K12 教育',
    'adult': '成人教育',
    'exam':  '职业考试',
    'ai':    'AI / 科技',
    'intl':  '国际课程',
    'test':  '测试',
}

# 各表对应的 categories 归类 (用于筛选)
_QB_TABLE_CATEGORY = {
    'adult_education_questions': 'adult',
    'professional_exam_questions': 'exam',
    'mt_exam_questions_pool': 'k12',
    'mt_exam_australian_questions': 'intl',
    'ai_maintenance_questions': 'ai',
    'test_questions': 'test',
}

@mobile_bp.route('/question_bank', methods=['GET'])
def mobile_question_bank():
    redir = _require_login()
    if redir: return redir

    category = request.args.get('category', 'all')
    banks = []
    total_questions = 0
    subjects_set = set()

    try:
        db = _db()

        # 先查 question_bank_meta (如果有)
        meta_rows = []
        try:
            cur = db.execute("SELECT meta_id, subject, question_type, difficulty, total_questions, last_updated FROM question_bank_meta")
            meta_rows = cur.fetchall()
        except Exception:
            pass  # 表不存在，用 fallback

        if meta_rows:
            for r in meta_rows:
                if category != 'all':
                    # subject 或 question_type 包含分类关键词时才显示
                    cat_val = _QB_CATEGORY_MAP.get(category, '').lower()
                    if cat_val and cat_val not in (r['subject'] or '').lower():
                        continue
                dist = {'easy': 0, 'medium': 0, 'hard': 0}
                diff = r['difficulty'] or ''
                if '易' in diff or 'easy' in diff.lower(): dist['easy'] = 1
                if '中' in diff or 'medium' in diff.lower(): dist['medium'] = 1
                if '难' in diff or 'hard' in diff.lower(): dist['hard'] = 1
                bank = {
                    'name': r['subject'] or r['meta_id'] or '未命名题库',
                    'subject': r['subject'],
                    'category': r['question_type'] or '综合',
                    'count': r['total_questions'] or 0,
                    'last_updated': (r['last_updated'] or '')[:10],
                    'difficulty': r['difficulty'] or '',
                    'difficulty_dist': dist,
                    'maintenance': '巡检中',
                    'icon': 'fa-book-open',
                    'icon_type': '',
                }
                banks.append(bank)
                total_questions += bank['count']
                if bank['subject']: subjects_set.add(bank['subject'])
        else:
            # Fallback: 从分散表聚合
            for tbl, display, subject, cat, icon, icontype in _QB_TABLES:
                if category != 'all':
                    tbl_cat = _QB_TABLE_CATEGORY.get(tbl, '')
                    if tbl_cat != category:
                        continue
                try:
                    cnt = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    if cnt == 0:
                        continue
                    # 尝试取更新时间
                    updated = ''
                    try:
                        cols = [c[1] for c in db.execute(f"PRAGMA table_info({tbl})").fetchall()]
                        time_col = None
                        for tc in ['updated_at', 'last_updated', 'created_at', 'create_time']:
                            if tc in cols:
                                time_col = tc; break
                        if time_col:
                            row = db.execute(f"SELECT {time_col} FROM {tbl} ORDER BY {time_col} DESC LIMIT 1").fetchone()
                            if row: updated = str(row[0])[:10]
                    except Exception:
                        pass
                    bank = {
                        'name': display,
                        'subject': subject,
                        'category': cat,
                        'count': cnt,
                        'last_updated': updated,
                        'difficulty': '混合',
                        'difficulty_dist': {'easy': cnt // 3, 'medium': cnt // 3, 'hard': cnt - 2 * (cnt // 3)},
                        'maintenance': '就绪',
                        'icon': icon,
                        'icon_type': icontype,
                    }
                    banks.append(bank)
                    total_questions += cnt
                    subjects_set.add(subject)
                except Exception:
                    continue

        db.close()
    except Exception:
        pass

    # 分类列表 (全部 + 启用的分类)
    categories = [{'key': k, 'name': v} for k, v in _QB_CATEGORY_MAP.items() if k == 'all']
    for k, v in _QB_CATEGORY_MAP.items():
        if k != 'all' and any(_QB_TABLE_CATEGORY.get(t) == k for t, *_ in _QB_TABLES):
            categories.append({'key': k, 'name': v})

    return render_template(
        'mobile/question_bank.html',
        banks=banks,
        categories=categories,
        category=category,
        total_questions=total_questions,
        subjects=len(subjects_set),
        tabbar_active='bank',
    )


@mobile_bp.route('/exam', methods=['GET'])
def mobile_exam_redirect():
    """旧考试 Tab 链接 → 重定向到题库管理"""
    return redirect('/mobile/question_bank')


# ─── 学习中心 /mobile/learn ───────────────────────────────

@mobile_bp.route('/learn', methods=['GET'])
def mobile_learn():
    redir = _require_login()
    if redir: return redir

    courses = []
    learn_records = []
    user = _current_user()

    try:
        db = _db()
        # 推荐课程（简化：从题库/课程表取）
        for table in ('courses', 'learning_paths'):
            try:
                rows = db.execute(
                    f"SELECT id, title, lesson_count FROM {table} LIMIT 5"
                ).fetchall()
                courses = [dict(r) for r in rows]
                if courses: break
            except Exception:
                continue

        # 学习记录
        try:
            rows = db.execute(
                "SELECT id, title, progress, created_at FROM learning_records "
                "WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
                (user.get('user_id', 0),)
            ).fetchall()
            learn_records = [dict(r) for r in rows]
        except Exception:
            pass

        db.close()
    except Exception:
        pass

    return render_template(
        'mobile/learn.html',
        courses=courses,
        learn_records=learn_records,
        tabbar_active='learn',
    )


# ─── 个人中心 /mobile/profile ─────────────────────────────

@mobile_bp.route('/profile', methods=['GET'])
def mobile_profile():
    redir = _require_login()
    if redir: return redir

    user = _current_user()
    stats = {'points': 0, 'streak_days': 0, 'exams_completed': 0}
    unread_count = 0

    try:
        db = _db()
        uid = user.get('user_id', 0) if user else 0

        # 积分
        try:
            row = db.execute(
                "SELECT points FROM user_stats WHERE user_id=?", (uid,)
            ).fetchone()
            if row: stats['points'] = row['points'] or 0
        except Exception:
            pass

        # 连续学习
        try:
            row = db.execute(
                "SELECT COUNT(DISTINCT DATE(created_at)) as days FROM exam_attempts "
                "WHERE user_id=? AND created_at >= date('now','-30 days')",
                (uid,)
            ).fetchone()
            if row: stats['streak_days'] = row['days'] or 0
        except Exception:
            pass

        # 已完成考试
        try:
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM exam_attempts WHERE user_id=? AND status='completed'",
                (uid,)
            ).fetchone()
            if row: stats['exams_completed'] = row['cnt'] or 0
        except Exception:
            pass

        # 未读通知
        try:
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM notifications WHERE user_id=? AND read=0",
                (uid,)
            ).fetchone()
            if row: unread_count = row['cnt'] or 0
        except Exception:
            pass

        db.close()
    except Exception:
        pass

    role_map = {
        'super_admin': '超级管理员', 'admin': '管理员',
        'teacher': '教师', 'student': '学生', 'parent': '家长',
        'user': '用户',
    }

    return render_template(
        'mobile/profile.html',
        user=user,
        role_name=role_map.get(user.get('role', '') if user else '', '用户'),
        grade=user.get('grade', '') if user else '',
        stats=stats,
        unread_count=unread_count,
        tabbar_active='profile',
    )


# ─── 登录 / 登出 ─────────────────────────────────────────

@mobile_bp.route('/login', methods=['GET', 'POST'])
def mobile_login():
    error = ''
    msg = ''

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            error = '请输入用户名和密码'
        else:
            # 先跳转到 auth_bp 的完整登录路由（PC端已经实现所有密码格式兼容）
            # auth_bp /auth/login 支持 werkzeug scrypt / bcrypt / legacy SHA256
            # 并会正确设置 session + 重定向回来源
            return redirect(f'/auth/login?mobile=1&user={username}')

    return render_template(
        'mobile/login.html',
        error=error, msg=msg,
        tabbar_active=None,
    )


@mobile_bp.route('/logout', methods=['GET', 'POST'])
def mobile_logout():
    session.clear()
    return redirect('/mobile/login')


# ─── 通知中心 /mobile/notifications ──────────────────────

@mobile_bp.route('/notifications', methods=['GET'])
def mobile_notifications():
    redir = _require_login()
    if redir: return redir

    user = _current_user()
    notifications = []
    try:
        db = _db()
        uid = user.get('user_id', 0) if user else 0
        rows = db.execute(
            "SELECT id, title, content, created_at, read FROM notifications "
            "WHERE user_id=? ORDER BY created_at DESC LIMIT 30",
            (uid,)
        ).fetchall()
        notifications = [dict(r) for r in rows]
        db.close()
    except Exception:
        pass

    return render_template(
        'mobile/notifications.html',
        notifications=notifications,
        tabbar_active=None,
    )


# ─── 错题本 /mobile/wrong_book (暂重定向) ────────────────

@mobile_bp.route('/wrong_book', methods=['GET'])
def mobile_wrong_book():
    return redirect('/mobile/home')


# ─── 下载 APK ────────────────────────────────────────────

@mobile_bp.route('/apk', methods=['GET'])
def mobile_apk():
    """APK 下载页 · 指向 v25.5.0 (SharedPreferences URL)"""
    apk_path = os.path.join(PROJECT_ROOT, 'static', 'apk', 'MTSCOS-AI-Mobile-v25.5.0-debug.apk')
    if os.path.exists(apk_path):
        from flask import send_file
        return send_file(apk_path, as_attachment=True,
                         download_name='MTSCOS-AI-Mobile-v25.5.0-debug.apk',
                         mimetype='application/vnd.android.package-archive')
    return 'APK 文件不存在', 404
