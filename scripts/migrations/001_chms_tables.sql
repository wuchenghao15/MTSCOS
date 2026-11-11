-- ============================================================
-- MTSCOS AI Project - 文案中枢管理系统(CHMS) 数据库建表脚本
-- 流程: §14 12步骤 STEP_7_EXECUTE
-- 版本: v21.7.0 -> v21.8.0
-- 日期: 2026-08-15
-- 归档: flask-app/scripts/migrations/001_chms_tables.sql
-- ============================================================

-- 1. 文案资产主表
CREATE TABLE IF NOT EXISTS mt_copy_assets (
    copy_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    copy_key           TEXT    NOT NULL UNIQUE,          -- 文案唯一键 如 ui.login.title
    copy_type          TEXT    NOT NULL,                  -- UI_TEXT/DOC_TEXT/AI_PROMPT/KNOWLEDGE/QUESTION/RULE_TEXT/NOTIFICATION
    copy_content       TEXT    NOT NULL DEFAULT '',        -- 中文文案(权威版本)
    copy_content_en    TEXT    NOT NULL DEFAULT '',        -- 英文文案(占位)
    module_path        TEXT    NOT NULL DEFAULT '',        -- 所属模块目录
    page_path          TEXT    NOT NULL DEFAULT '',        -- 所属页面路径
    status             TEXT    NOT NULL DEFAULT 'ACTIVE',  -- ACTIVE/INACTIVE/PENDING_REVIEW
    version            INTEGER NOT NULL DEFAULT 1,         -- 版本号
    fallback_hardcoded TEXT    NOT NULL DEFAULT '',        -- 原始硬编码值(降级兜底)
    source_status      TEXT    NOT NULL DEFAULT 'LOCAL',   -- LOCAL/CLOUD_PENDING/EXTRACTED
    tags               TEXT    NOT NULL DEFAULT '[]',     -- 标签 JSON 数组
    created_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 2. 文案-功能映射表
CREATE TABLE IF NOT EXISTS mt_copy_feature_mapping (
    mapping_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    copy_id         INTEGER NOT NULL,
    feature_module  TEXT    NOT NULL DEFAULT '',  -- 功能模块名
    route_path      TEXT    NOT NULL DEFAULT '',  -- 路由路径(可空)
    service_file    TEXT    NOT NULL,             -- 服务文件(必填)
    module_path     TEXT    NOT NULL DEFAULT '',  -- 模块目录
    linked_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (copy_id) REFERENCES mt_copy_assets(copy_id)
);

-- 3. 文案版本历史表
CREATE TABLE IF NOT EXISTS mt_copy_versions (
    version_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    copy_id         INTEGER NOT NULL,
    content_snapshot TEXT   NOT NULL,               -- 文案快照
    version_number  INTEGER NOT NULL,
    changed_by      TEXT    NOT NULL DEFAULT 'system',
    change_reason   TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (copy_id) REFERENCES mt_copy_assets(copy_id)
);

-- 4. AI优化日志表
CREATE TABLE IF NOT EXISTS mt_copy_optimization_log (
    opt_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    copy_id         INTEGER NOT NULL,
    quality_score   REAL    NOT NULL DEFAULT 0,     -- 综合质量分 0-100
    score_clarity   REAL    NOT NULL DEFAULT 0,     -- 清晰度
    score_consistency REAL  NOT NULL DEFAULT 0,     -- 一致性
    score_completeness REAL NOT NULL DEFAULT 0,      -- 完整性
    score_accuracy  REAL    NOT NULL DEFAULT 0,      -- 准确性
    score_safety    REAL    NOT NULL DEFAULT 0,      -- 安全合规
    suggestion      TEXT    NOT NULL DEFAULT '',      -- 优化建议
    applied         INTEGER NOT NULL DEFAULT 0,       -- 是否已应用 0/1
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (copy_id) REFERENCES mt_copy_assets(copy_id)
);

-- 5. 巡检报告表
CREATE TABLE IF NOT EXISTS mt_copy_inspection_report (
    report_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    inspection_type  TEXT    NOT NULL,                 -- MISSING/DUPLICATE/PLACEHOLDER/HARDCODED
    findings_json    TEXT    NOT NULL DEFAULT '[]',     -- 发现项 JSON
    severity         TEXT    NOT NULL DEFAULT 'INFO',  -- INFO/WARNING/CRITICAL
    total_findings   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_copy_assets_key ON mt_copy_assets(copy_key);
CREATE INDEX IF NOT EXISTS idx_copy_assets_type ON mt_copy_assets(copy_type);
CREATE INDEX IF NOT EXISTS idx_copy_assets_status ON mt_copy_assets(status);
CREATE INDEX IF NOT EXISTS idx_copy_assets_source ON mt_copy_assets(source_status);
CREATE INDEX IF NOT EXISTS idx_copy_mapping_route ON mt_copy_feature_mapping(route_path);
CREATE INDEX IF NOT EXISTS idx_copy_mapping_service ON mt_copy_feature_mapping(service_file);
CREATE INDEX IF NOT EXISTS idx_copy_mapping_module ON mt_copy_feature_mapping(module_path);
CREATE INDEX IF NOT EXISTS idx_copy_versions_copyid ON mt_copy_versions(copy_id);
CREATE INDEX IF NOT EXISTS idx_copy_optlog_copyid ON mt_copy_optimization_log(copy_id);

-- 初始化：文案分类字典
INSERT OR IGNORE INTO mt_copy_assets (copy_key, copy_type, copy_content, module_path, tags) VALUES
('chms.meta.classification.ui_text', 'RULE_TEXT', 'UI界面文案：页面标题/描述/按钮/标签/错误提示/flash消息', 'copy_hub', '["meta","classification"]'),
('chms.meta.classification.doc_text', 'RULE_TEXT', '文档说明文案：README/架构文档/指南/变更日志/报告', 'copy_hub', '["meta","classification"]'),
('chms.meta.classification.ai_prompt', 'RULE_TEXT', 'AI提示词文案：系统提示词/问答/摘要/翻译/代码审查模板', 'copy_hub', '["meta","classification"]'),
('chms.meta.classification.knowledge', 'RULE_TEXT', '知识库内容：知识文档/脑库初始内容/能力描述', 'copy_hub', '["meta","classification"]'),
('chms.meta.classification.question', 'RULE_TEXT', '题库内容：题目/选项/解析/难度/类别', 'copy_hub', '["meta","classification"]'),
('chms.meta.classification.rule_text', 'RULE_TEXT', '系统规则文案：开发规则/设计规范/操作规范/权限规则', 'copy_hub', '["meta","classification"]'),
('chms.meta.classification.notification', 'RULE_TEXT', '通知/消息文案：flash消息/邮件/短信/企业微信推送', 'copy_hub', '["meta","classification"]');

-- 执行完毕
SELECT 'CHMS tables created successfully: 5 tables + 9 indexes + 7 classification records' AS result;
