-- Migration 002 · 模块4 P2 · 辅助4张表(空缺清单/代码变更/Seed日志/限流)
-- flow_id: flow_dev_pages_functions_complete_20260818_001
-- 基准版本: v21.12.0 → 目标版本: v21.12.1
-- 执行时间: 2026-08-17T19:53:45.788050
PRAGMA foreign_keys = ON;

-- P2-A: 全系统空缺清单(6空缺类型, STEP_7 执行核心)
CREATE TABLE IF NOT EXISTS mt_dev_gap_registry (
    gap_id       TEXT PRIMARY KEY,   -- gap_{flow}_{NNNN} 业务主键
    flow_id      TEXT NOT NULL,
    gap_type     TEXT NOT NULL CHECK(gap_type IN ('A_ROUTE_NO_VIEW','B_VIEW_NO_TEMPLATE','C_TEMPLATE_SHELL','D_API_NO_IMPL','E_API_NO_TABLE','F_NO_DESIGN_TOKEN')),
    module_name  TEXT NOT NULL CHECK(module_name IN ('后端Blueprint','前端HTML模板','静态CSS/JS','数据库表_Seed')),
    resource_path TEXT NOT NULL,     -- 文件路径或路由或API路径或表名
    priority     INTEGER NOT NULL DEFAULT 5 CHECK(priority BETWEEN 1 AND 10),
    status       TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','in_progress','done','verified','cancelled')),
    assignee     TEXT,
    description_zh TEXT,
    contract_ref TEXT,              -- contract.yaml行号
    fix_commit_hash TEXT,
    version INTEGER NOT NULL DEFAULT 1,  -- 乐观锁
    deleted_at   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_gap_flow   ON mt_dev_gap_registry(flow_id);
CREATE INDEX IF NOT EXISTS idx_mt_gap_type   ON mt_dev_gap_registry(gap_type);
CREATE INDEX IF NOT EXISTS idx_mt_gap_mod    ON mt_dev_gap_registry(module_name);
CREATE INDEX IF NOT EXISTS idx_mt_gap_status ON mt_dev_gap_registry(status);
CREATE INDEX IF NOT EXISTS idx_mt_gap_prio   ON mt_dev_gap_registry(priority);

-- P2-B: 代码变更审计(STEP_7 所有变更可追溯, 逻辑FK: gap_id→mt_dev_gap_registry.gap_id)
CREATE TABLE IF NOT EXISTS mt_code_change_audit (
    change_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_id       TEXT NOT NULL,
    gap_id        TEXT,
    change_type   TEXT NOT NULL CHECK(change_type IN ('CREATE','MODIFY','DELETE','RENAME','MIGRATION','SEED')),
    file_path     TEXT,
    module_name   TEXT,
    who           TEXT NOT NULL,
    why           TEXT,
    diff_summary  TEXT,
    commit_hash   TEXT,
    review_sign_1 TEXT,            -- 人工审查签名
    review_sign_2 TEXT,            -- 陈安全AI安全审查签名
    pytest_cov    REAL DEFAULT 0.0,
    deleted_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_cc_flow ON mt_code_change_audit(flow_id);
CREATE INDEX IF NOT EXISTS idx_mt_cc_who  ON mt_code_change_audit(who);
CREATE INDEX IF NOT EXISTS idx_mt_cc_type ON mt_code_change_audit(change_type);

-- P2-C: Seed初始化日志
CREATE TABLE IF NOT EXISTS mt_seed_init_log (
    seed_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_id       TEXT,
    table_name    TEXT NOT NULL,
    seed_kind     TEXT NOT NULL CHECK(seed_kind IN ('DICT_SEED','DEMO_SEED')),
    records_count INTEGER NOT NULL DEFAULT 0,
    operator      TEXT NOT NULL,
    snapshot_path TEXT,              -- Seed快照路径(shutil.copy2)
    integrity_sha256 TEXT,           -- 插入后db文件sha256
    deleted_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_seed_table ON mt_seed_init_log(table_name);
CREATE INDEX IF NOT EXISTS idx_mt_seed_kind  ON mt_seed_init_log(seed_kind);

-- P2-D: 限流日志
CREATE TABLE IF NOT EXISTS mt_rate_limit_log (
    limit_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    flow_id     TEXT,
    ip_address  TEXT NOT NULL,
    route_path  TEXT NOT NULL,
    limit_rule  TEXT NOT NULL,        -- 60/min 等
    hit_count   INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,
    user_id     TEXT,
    user_role   TEXT,
    deleted_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mt_rl_ip   ON mt_rate_limit_log(ip_address);
CREATE INDEX IF NOT EXISTS idx_mt_rl_path ON mt_rate_limit_log(route_path);
