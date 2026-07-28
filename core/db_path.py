import os
import sys
import sqlite3
import shutil
from functools import wraps

_PROJECT_ROOT = None
_PATCHED = False
_MARKER_FILENAMES = [
    'MTSCOS_PROJECT_ROOT',
    'modular_start.py',
    'server_real_db.py',
    'app.py',
    'VERSION',
]


def resolve_project_root():
    global _PROJECT_ROOT
    if _PROJECT_ROOT and os.path.exists(_PROJECT_ROOT):
        return _PROJECT_ROOT
    current = os.path.dirname(os.path.abspath(__file__))
    max_level = 12
    for _ in range(max_level):
        hits = 0
        for m in _MARKER_FILENAMES:
            if os.path.exists(os.path.join(current, m)):
                hits += 1
        if hits >= 2:
            for sub in ('Database', 'data', 'templates', 'ai_engines'):
                if os.path.isdir(os.path.join(current, sub)):
                    hits += 1
                    break
        if hits >= 2:
            _PROJECT_ROOT = current
            return _PROJECT_ROOT
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return _PROJECT_ROOT


def _score_db_path(path):
    if not os.path.exists(path):
        return -1, 0
    size = os.path.getsize(path)
    if size == 0:
        return -1, 0
    core_weight = {
        'users': 10, 'questions': 10, 'permissions': 8,
        'system_config': 8, 'system_versions': 8,
        'exams': 6, 'courses': 5, 'system_rules': 5,
        'ai_firewall_rules': 4, 'question_bank': 3,
        'ai_brain_bank': 3, 'access_logs': 3, 'ai_employees': 3,
    }
    try:
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = set(r[0] for r in cur.fetchall())
        score = 0
        table_count = len(tables)
        for t, w in core_weight.items():
            if t not in tables:
                continue
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                n = cur.fetchone()[0]
                if n > 0:
                    score += w
            except Exception:
                continue
        conn.close()
    except Exception:
        return size * 0 + 0, size
    total = score * 1024 * 1024 + min(size, 50 * 1024 * 1024) + table_count * 100
    return total, table_count


def _discover_canonical_dbs():
    root = resolve_project_root()
    out = {}
    candidate_dirs = [
        os.path.join(root, 'data', 'databases'),
        os.path.join(root, 'flask-app'),
        os.path.join(root, 'Database'),
        root,
        os.path.join(root, 'flask-app', 'split_databases'),
    ]
    scan_db_names = [
        'app.db', 'auth.db', 'mtscos.db', 'version_unified.db',
        'scheduler.db', 'activity_logs.db', 'system_extensions.db',
        'self_learning.db', 'session_security.db', 'permission_manager.db',
        'primary.db', 'backup.db', 'system.db', 'config.db',
        'exam.db', 'question.db', 'user.db', 'learning.db', 'ai.db',
        'log.db', 'proctor.db', 'admin.db', 'physics.db', 'math.db',
        'other.db', 'intelligent_evaluation.db', 'ai_memory.db',
        'emotion_analysis.db', 'ai_adaptive_learning.db', 'ai_qna.db',
        'ai_cognitive.db', 'ai_decision.db', 'ai_prediction.db',
        'ai_recommendation.db', 'professional_role.db',
        'skill_evolution.db', 'theme_manager.db',
    ]
    for name in scan_db_names:
        best = None
        best_score = -1
        seen = set()
        for d in candidate_dirs:
            p = os.path.join(d, name)
            rp = os.path.realpath(p) if os.path.exists(p) else p
            if rp in seen:
                continue
            seen.add(rp)
            score, _ = _score_db_path(p)
            if score > best_score:
                best_score = score
                best = p
        if best and os.path.exists(best):
            out[name] = best
    if 'auth.db' not in out:
        for d in candidate_dirs:
            cand = os.path.join(d, 'split_databases', 'auth.db')
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                out['auth.db'] = cand
                break
    if 'app.db' not in out:
        for p in (os.path.join(root, 'Database', 'app.db'),
                  os.path.join(root, 'app.db')):
            if os.path.exists(p):
                out['app.db'] = p
                break
    return out


_DB_MAPPING = None


def _get_mapping():
    global _DB_MAPPING
    if _DB_MAPPING is None:
        _DB_MAPPING = _discover_canonical_dbs()
    return _DB_MAPPING


def refresh_mapping():
    global _DB_MAPPING
    _DB_MAPPING = None
    return _get_mapping()


def get_db_path(db_name):
    root = resolve_project_root()
    mapping = _get_mapping()
    base = os.path.basename(db_name)
    if not base:
        return os.path.join(root, 'Database', 'app.db')
    if os.path.isabs(db_name):
        cand = db_name
        if not os.path.exists(cand) or (os.path.exists(cand) and os.path.getsize(cand) == 0):
            alt = mapping.get(base)
            if alt and alt != cand:
                return alt
        return cand
    if base in mapping:
        return mapping[base]
    return os.path.join(root, 'Database', base)


def map_db_name(db_name):
    mapping = _get_mapping()
    base = os.path.basename(db_name)
    return mapping.get(base, os.path.join(resolve_project_root(), 'Database', base))


def db_conn(db_name, *args, **kwargs):
    path = get_db_path(db_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return sqlite3.connect(path, *args, **kwargs)


def patch_sqlite3_connect(verbose=False):
    global _PATCHED
    if _PATCHED:
        return getattr(sqlite3, '_mtscos_original_connect', sqlite3.connect)
    try:
        original_connect = sqlite3.connect
    except Exception:
        original_connect = sqlite3.connect
    sqlite3._mtscos_original_connect = original_connect
    mapping = _get_mapping()

    @wraps(original_connect)
    def new_connect(database, *args, **kwargs):
        actual_path = database
        redirected = False
        if isinstance(database, str) and database != ':memory:':
            base = os.path.basename(database)
            if base in mapping:
                canonical = mapping[base]
                if database != canonical:
                    if not os.path.isabs(database):
                        actual_path = canonical
                        redirected = True
                    elif (os.path.exists(database)
                          and os.path.exists(canonical)
                          and os.path.getsize(database) < max(4096, os.path.getsize(canonical) * 0.05)):
                        actual_path = canonical
                        redirected = True
                    elif not os.path.exists(database):
                        actual_path = canonical
                        redirected = True
        if verbose and redirected:
            try:
                sys.stderr.write(f"[DB Patch] sqlite3.connect('{database}') -> '{actual_path}'\n")
            except Exception:
                pass
        if actual_path != ':memory:':
            os.makedirs(os.path.dirname(os.path.abspath(actual_path)), exist_ok=True)
        return original_connect(actual_path, *args, **kwargs)

    sqlite3.connect = new_connect
    try:
        import pysqlite3  # type: ignore
        try:
            pysqlite3.connect = new_connect
        except Exception:
            pass
    except Exception:
        pass
    _PATCHED = True
    return original_connect


def is_patched():
    global _PATCHED
    return _PATCHED


def db_status_report():
    root = resolve_project_root()
    mapping = _get_mapping()
    lines = []
    lines.append(f"[DB Status] project_root = {root}")
    lines.append(f"[DB Status] patched = {_PATCHED}")
    lines.append(f"[DB Status] discovered databases = {len(mapping)}")
    for name, path in sorted(mapping.items()):
        try:
            size = os.path.getsize(path)
        except Exception:
            size = -1
        lines.append(f"  - {name} => {path} ({size} bytes)")
    return '\n'.join(lines)


def try_merge_small_app_db():
    root = resolve_project_root()
    mapping = _get_mapping()
    canon = mapping.get('app.db')
    if not canon:
        return
    small_candidates = [
        os.path.join(root, 'app.db'),
        os.path.join(root, 'Database', 'app.db'),
    ]
    for sc in small_candidates:
        if not os.path.exists(sc) or os.path.abspath(sc) == os.path.abspath(canon):
            continue
        if os.path.getsize(sc) > 0 and os.path.getsize(sc) < 20 * 1024 * 1024:
            try:
                os.remove(sc)
                shutil.copy2(canon, sc)
                sys.stderr.write(f"[DB Merge] updated small {sc} from canonical {canon}\n")
            except Exception:
                pass


__all__ = [
    'resolve_project_root', 'get_db_path', 'db_conn', 'map_db_name',
    'patch_sqlite3_connect', 'is_patched', 'db_status_report',
    'refresh_mapping', 'try_merge_small_app_db',
]
