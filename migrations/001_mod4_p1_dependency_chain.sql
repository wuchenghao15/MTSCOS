-- Migration 001 · 模块4 P1 · 依赖链5张表(执行顺序依赖链)
-- flow_id: flow_dev_pages_functions_complete_20260818_001
-- 基准版本: v21.12.0 → 目标版本: v21.12.1
-- 执行时间: 2026-08-17T19:53:45.787484
PRAGMA foreign_keys = ON;

-- P1-A: 异常码字典(最底层,无外键)
CREATE TABLE IF NOT EXISTS mt_exception_code_dict (
    code_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_code TEXT NOT NULL UNIQUE,
    exception_type TEXT NOT NULL,
    http_status    INTEGER DEFAULT 500,
    title_zh       TEXT NOT NULL,
    description_zh TEXT,
    severity       TEXT NOT NULL DEFAULT 'warning' CHECK(severity IN ('info','warning','error','critical')),
    repair_suggestion TEXT,
    design_tokens  TEXT,
    deleted_at     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_exc_code ON mt_exception_code_dict(exception_code);
CREATE INDEX IF NOT EXISTS idx_mt_exc_sev  ON mt_exception_code_dict(severity);

-- P1-B: 修复策略库(字典底, 逻辑FK → mt_exception_code_dict.exception_code)
-- 注: SQLite CREATE TABLE IF NOT EXISTS + FK 在旧表已存在时会抛no such column, 故仅逻辑FK+INDEX
CREATE TABLE IF NOT EXISTS mt_repair_strategy_lib (
    strategy_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    exception_code TEXT NOT NULL,
    strategy_level TEXT NOT NULL DEFAULT 'manual' CHECK(strategy_level IN ('auto','semi_auto','manual')),
    description_zh TEXT,
    fix_script     TEXT,
    validation_sql TEXT,
    rollback_script TEXT,
    success_rate   REAL DEFAULT 0.0,
    apply_count    INTEGER DEFAULT 0,
    deleted_at     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_rp_exc ON mt_repair_strategy_lib(exception_code);
CREATE INDEX IF NOT EXISTS idx_mt_rp_lvl ON mt_repair_strategy_lib(strategy_level);

-- P1-C: Blueprint失败日志(无FK依赖)
CREATE TABLE IF NOT EXISTS mt_blueprint_fail_log (
    fail_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    blueprint_name TEXT NOT NULL,
    import_path   TEXT,
    error_message TEXT,
    stack_trace   TEXT,
    severity      TEXT NOT NULL DEFAULT 'error' CHECK(severity IN ('warning','error','critical')),
    is_fault_tolerant INTEGER NOT NULL DEFAULT 1,  -- 1=容错(不影响整体) 0=致命
    retry_count   INTEGER DEFAULT 0,
    last_retry_at TEXT,
    deleted_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_bp_name ON mt_blueprint_fail_log(blueprint_name);
CREATE INDEX IF NOT EXISTS idx_mt_bp_sev  ON mt_blueprint_fail_log(severity);

-- P1-D: 权限审计明细(逻辑FK: exception_code→mt_exception_code_dict.exception_code)
CREATE TABLE IF NOT EXISTS mt_permission_audit_detail (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_id        TEXT,
    request_id     TEXT,
    user_id        TEXT,
    username       TEXT,
    user_role      TEXT,
    user_group     TEXT,
    route_path     TEXT,
    blueprint_name TEXT,
    permission_level TEXT,
    status_check   TEXT CHECK(status_check IN ('PASS','FAIL','SKIP')),
    exception_code TEXT,
    ip_address     TEXT,
    user_agent     TEXT,
    vikey_ok       INTEGER DEFAULT 0,
    timestamp_iso  TEXT NOT NULL,
    extra_json     TEXT,
    deleted_at     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_pm_user  ON mt_permission_audit_detail(user_id);
CREATE INDEX IF NOT EXISTS idx_mt_pm_route ON mt_permission_audit_detail(route_path);
CREATE INDEX IF NOT EXISTS idx_mt_pm_time  ON mt_permission_audit_detail(timestamp_iso);
CREATE INDEX IF NOT EXISTS idx_mt_pm_flow  ON mt_permission_audit_detail(flow_id);

-- P1-E: 路由冲突日志(逻辑FK: audit_ref_id→mt_permission_audit_detail.audit_id)
CREATE TABLE IF NOT EXISTS mt_route_conflict_log (
    conflict_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_id       TEXT,
    route_path    TEXT NOT NULL,
    blueprint_a   TEXT, blueprint_b   TEXT,
    rule_a        TEXT, rule_b        TEXT,
    conflict_type TEXT NOT NULL CHECK(conflict_type IN ('duplicate_path','method_overlap','permission_mismatch','param_collision','cors_mismatch')),
    severity      TEXT NOT NULL DEFAULT 'error' CHECK(severity IN ('warning','error','critical')),
    resolution    TEXT,
    audit_ref_id  INTEGER,
    deleted_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_rt_path  ON mt_route_conflict_log(route_path);
CREATE INDEX IF NOT EXISTS idx_mt_rt_type  ON mt_route_conflict_log(conflict_type);
CREATE INDEX IF NOT EXISTS idx_mt_rt_flow  ON mt_route_conflict_log(flow_id);
