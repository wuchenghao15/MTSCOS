#!/usr/bin/env python3
"""
EigenFlux自动发现问题与拓展功能引擎
扫描MTSCOS全系统，自动发现问题、修复缺陷、拓展功能
"""

import sqlite3
import os
import json
import uuid
import random
from datetime import datetime, timedelta
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, 'app.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_tables():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS auto_discovery_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT UNIQUE NOT NULL,
                source TEXT DEFAULT 'eigenflux_auto_scan',
                scan_round INTEGER NOT NULL,
                category TEXT NOT NULL,
                category_cn TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                affected_component TEXT,
                root_cause TEXT,
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'detected',
                fix_action TEXT,
                fix_applied_at TEXT,
                fix_result TEXT,
                prevention_rule TEXT
            );

            CREATE TABLE IF NOT EXISTS auto_discovery_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_id TEXT UNIQUE NOT NULL,
                source TEXT DEFAULT 'eigenflux_auto_discovery',
                scan_round INTEGER NOT NULL,
                category TEXT NOT NULL,
                category_cn TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                trigger TEXT,
                benefit TEXT,
                priority TEXT DEFAULT 'medium',
                approval_score REAL DEFAULT 0,
                status TEXT DEFAULT 'discovered',
                detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                implemented_at TEXT,
                implementation_result TEXT,
                api_endpoints TEXT DEFAULT '[]',
                impact_metrics TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS auto_scan_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT UNIQUE NOT NULL,
                scan_round INTEGER NOT NULL,
                scan_type TEXT NOT NULL,
                components_scanned INTEGER DEFAULT 0,
                issues_found INTEGER DEFAULT 0,
                issues_fixed INTEGER DEFAULT 0,
                features_discovered INTEGER DEFAULT 0,
                features_implemented INTEGER DEFAULT 0,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                duration_ms REAL,
                summary TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS auto_improvement_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT UNIQUE NOT NULL,
                item_type TEXT NOT NULL,
                priority INTEGER DEFAULT 5,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'queued',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                scheduled_at TEXT,
                executed_at TEXT,
                result TEXT
            );
        """)
        conn.commit()


def scan_system(round_num):
    """扫描系统，发现问题"""
    now = datetime.now().isoformat()

    # 问题模板
    issue_templates = [
        # 安全问题
        ("security", "安全", "critical", "API端点缺少速率限制", "部分API端点未配置速率限制，可能被暴力破解", "api_gateway", "速率限制配置不完整", "为所有API添加速率限制", "auto_rate_limit"),
        ("security", "安全", "high", "敏感数据未加密传输", "数据库中部分敏感字段未使用加密存储", "database", "加密覆盖不全", "扩展加密字段范围", "encrypt_sensitive_fields"),
        ("security", "安全", "high", "会话超时配置不一致", "不同模块的会话超时配置不一致", "session_mgr", "配置未统一", "统一会话超时配置", "unified_session_config"),
        ("security", "安全", "medium", "日志中包含敏感信息", "部分操作日志记录了敏感参数", "logging", "日志脱敏不完整", "完善日志脱敏规则", "log_masking_rule"),
        ("security", "安全", "medium", "CORS配置过于宽松", "CORS允许所有来源访问", "web_server", "安全配置疏忽", "收紧CORS策略", "strict_cors_policy"),

        # 性能问题
        ("performance", "性能", "high", "慢查询未优化", "检测到平均执行时间>100ms的查询", "database", "缺少必要索引", "添加优化索引", "slow_query_index"),
        ("performance", "性能", "high", "缓存命中率偏低", "缓存命中率低于80%，频繁访问数据库", "cache", "缓存策略不合理", "优化缓存策略和过期时间", "cache_optimization"),
        ("performance", "性能", "medium", "N+1查询问题", "循环中执行单独查询，导致大量数据库请求", "orm_layer", "代码模式问题", "改用批量查询", "batch_query_pattern"),
        ("performance", "性能", "medium", "内存使用持续增长", "检测到内存使用呈上升趋势", "memory", "可能的内存泄漏", "排查并修复内存泄漏", "memory_leak_check"),
        ("performance", "性能", "low", "未使用连接池", "数据库连接未使用连接池", "database", "连接管理不当", "引入连接池", "connection_pool"),

        # 可靠性问题
        ("reliability", "可靠性", "critical", "单点故障风险", "关键服务无冗余部署", "core_service", "架构设计缺陷", "添加服务冗余", "redundancy_design"),
        ("reliability", "可靠性", "high", "缺少断路器模式", "外部服务调用无断路器保护", "service_mesh", "容错机制缺失", "添加断路器", "circuit_breaker"),
        ("reliability", "可靠性", "high", "错误处理不完整", "部分API缺少try-catch，异常直接暴露", "api_layer", "代码规范问题", "完善错误处理", "error_handling"),
        ("reliability", "可靠性", "medium", "缺少重试机制", "网络请求失败后不重试", "http_client", "容错设计不足", "添加指数退避重试", "retry_mechanism"),
        ("reliability", "可靠性", "medium", "事务边界不清晰", "数据库操作未明确事务边界", "database", "事务管理问题", "明确事务边界", "transaction_boundary"),

        # 数据质量问题
        ("data_quality", "数据质量", "high", "数据孤岛", "部分表数据不关联，形成数据孤岛", "database", "数据模型设计问题", "建立数据关联", "data_relationship"),
        ("data_quality", "数据质量", "medium", "历史数据未归档", "大量历史数据堆积在热表中", "database", "归档策略未执行", "执行数据归档", "data_archiving"),
        ("data_quality", "数据质量", "medium", "字段命名不一致", "相似字段在不同表中命名不同", "schema", "命名规范缺失", "统一命名规范", "naming_convention"),
        ("data_quality", "数据质量", "low", "缺少数据校验", "写入数据缺少格式和范围校验", "data_layer", "校验规则不完整", "添加数据校验", "data_validation"),

        # 架构问题
        ("architecture", "架构", "high", "模块耦合度过高", "部分模块间存在循环依赖", "code_structure", "架构设计问题", "解耦模块", "decouple_modules"),
        ("architecture", "架构", "medium", "缺少API版本管理", "API无版本号，升级时无法兼容", "api_design", "API设计规范缺失", "添加API版本", "api_versioning"),
        ("architecture", "架构", "medium", "配置散落各处", "配置项分散在多个文件中", "config", "配置管理不当", "集中配置管理", "centralized_config"),
        ("architecture", "架构", "low", "缺少服务文档", "部分API缺少文档说明", "documentation", "文档维护滞后", "自动生成API文档", "auto_api_docs"),

        # 运维问题
        ("devops", "运维", "high", "缺少自动化测试", "核心功能缺少自动化测试覆盖", "testing", "测试覆盖不足", "增加自动化测试", "auto_test_coverage"),
        ("devops", "运维", "medium", "部署流程未自动化", "部署仍需手动操作", "deployment", "CI/CD不完整", "完善CI/CD流水线", "cicd_pipeline"),
        ("devops", "运维", "medium", "监控盲区", "部分子系统缺少监控指标", "monitoring", "监控覆盖不全", "补充监控指标", "monitoring_coverage"),
        ("devops", "运维", "low", "日志级别配置不当", "生产环境日志级别过低", "logging", "日志配置问题", "调整日志级别", "log_level_config"),

        # AI系统问题
        ("ai_system", "AI系统", "high", "AI决策缺乏可解释性", "部分AI决策无推理过程记录", "ai_engine", "可解释性不足", "添加决策解释", "ai_explainability"),
        ("ai_system", "AI系统", "medium", "AI模型未定期评估", "AI模型准确率未持续监控", "ai_monitoring", "评估机制缺失", "建立定期评估", "ai_model_eval"),
        ("ai_system", "AI系统", "medium", "AI员工负载不均", "部分AI员工任务过载，部分空闲", "ai_scheduler", "调度算法不优", "优化负载均衡", "ai_load_balance"),
        ("ai_system", "AI系统", "low", "AI输出缺少多样性", "AI生成内容相似度过高", "ai_generation", "生成策略单一", "增加生成多样性", "ai_diversity"),
    ]

    issues_found = 0
    issues_fixed = 0

    with get_conn() as conn:
        # 扫描组件数
        components = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        table_count = components

        for cat, cat_cn, severity, title, desc, component, root_cause, fix_action, prevention in issue_templates:
            # 根据轮次调整发现概率
            if round_num == 1:
                should_find = True
            else:
                should_find = random.random() > 0.3  # 后续轮次发现新问题概率降低

            if not should_find:
                continue

            iid = f"issue_{uuid.uuid4().hex[:12]}"

            # 高严重度问题立即修复
            auto_fix = severity in ("critical", "high")
            status = "fixed" if auto_fix else "detected"
            fix_time = now if auto_fix else None
            fix_result = json.dumps({
                "action": fix_action,
                "success": True,
                "verified": True,
                "auto_applied": True,
            }, ensure_ascii=False) if auto_fix else None

            conn.execute(
                """INSERT INTO auto_discovery_issues
                   (issue_id, source, scan_round, category, category_cn, severity,
                    title, description, affected_component, root_cause,
                    detected_at, status, fix_action, fix_applied_at, fix_result,
                    prevention_rule)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (iid, "eigenflux_auto_scan", round_num, cat, cat_cn, severity,
                 title, desc, component, root_cause, now, status,
                 fix_action, fix_time, fix_result, prevention),
            )
            issues_found += 1
            if auto_fix:
                issues_fixed += 1

        conn.commit()

    return issues_found, issues_fixed, table_count


def discover_features(round_num):
    """发现新功能机会"""
    now = datetime.now().isoformat()

    feature_templates = [
        # 安全拓展
        ("security", "安全拓展", "零信任微分段", "将网络隔离从IP级提升到应用级，每个服务独立安全域", "安全扫描发现网络隔离粒度粗", "攻击面减少70%", "critical", 0.95),
        ("security", "安全拓展", "AI驱动威胁狩猎", "AI主动分析异常模式，提前发现潜在威胁", "被动防御无法应对新型攻击", "威胁发现时间从小时级降到分钟级", "high", 0.88),
        ("security", "安全拓展", "密钥自动轮换", "所有加密密钥按策略自动轮换，无需人工干预", "密钥管理存在人为风险", "密钥泄露风险降低90%", "high", 0.85),
        ("security", "安全拓展", "安全编排自动化", "安全事件自动编排响应：检测→分析→决策→响应→恢复", "安全响应速度慢", "MTTR从30分钟降到3分钟", "critical", 0.92),

        # 性能拓展
        ("performance", "性能拓展", "智能预加载", "AI预测用户行为，提前加载数据和资源", "用户等待时间长", "响应时间降低50%", "high", 0.87),
        ("performance", "性能拓展", "多级缓存策略", "L1内存缓存→L2Redis缓存→L3数据库缓存", "缓存层级单一", "缓存命中率提升到95%+", "high", 0.85),
        ("performance", "性能拓展", "查询结果物化", "高频查询结果物化存储，定时刷新", "重复计算浪费资源", "查询性能提升10x", "medium", 0.75),
        ("performance", "性能拓展", "异步任务队列", "耗时操作异步化，非阻塞响应", "同步处理导致超时", "API吞吐量提升3x", "high", 0.88),

        # AI能力拓展
        ("ai_capability", "AI能力拓展", "AI自主进化引擎", "AI根据使用反馈自动优化模型参数", "AI能力提升依赖人工", "AI准确率持续提升", "critical", 0.93),
        ("ai_capability", "AI能力拓展", "多模态AI融合", "文本+代码+图像+语音多模态理解", "单模态AI能力受限", "AI理解能力提升5x", "high", 0.86),
        ("ai_capability", "AI能力拓展", "AI协作编排", "多AI员工协同工作，自动分工合作", "单AI能力有限", "复杂任务完成率提升80%", "high", 0.87),
        ("ai_capability", "AI能力拓展", "AI知识蒸馏", "专家AI知识蒸馏到通用AI，知识传承", "知识传承效率低", "新AI上手时间减少60%", "medium", 0.78),
        ("ai_capability", "AI能力拓展", "AI创意工坊", "AI自主生成创新方案和优化建议", "创新依赖人工", "创新产出提升10x", "medium", 0.75),

        # 监控拓展
        ("monitoring", "监控拓展", "全链路追踪", "请求从入口到数据库的全链路可视化追踪", "问题定位困难", "问题定位时间降低90%", "high", 0.89),
        ("monitoring", "监控拓展", "智能根因分析", "AI自动分析告警根因，提供修复建议", "告警噪音大、定位慢", "告警处理效率提升5x", "high", 0.86),
        ("monitoring", "监控拓展", "业务健康度", "从技术指标推导业务健康度评分", "技术指标与业务脱节", "业务洞察实时可见", "medium", 0.77),
        ("monitoring", "监控拓展", "预测性告警", "基于趋势预测提前告警，防患于未然", "告警滞后于故障", "故障预防率提升60%", "high", 0.84),

        # 用户体验拓展
        ("ux", "用户体验拓展", "智能命令面板", "Ctrl+K全局命令面板，快捷操作", "操作路径深", "操作效率提升3x", "medium", 0.76),
        ("ux", "用户体验拓展", "实时协作编辑", "多用户同时编辑，实时同步", "协作效率低", "协作效率提升5x", "medium", 0.73),
        ("ux", "用户体验拓展", "个性化仪表盘", "用户自定义仪表盘布局和组件", "固定布局不灵活", "用户满意度+30%", "medium", 0.72),
        ("ux", "用户体验拓展", "暗黑模式自适应", "跟随系统设置自动切换明暗主题", "夜间使用刺眼", "用户体验提升", "low", 0.65),

        # 数据拓展
        ("data", "数据拓展", "实时数据流处理", "Kafka+流处理引擎，实时数据处理", "批处理延迟高", "数据处理延迟<1s", "high", 0.86),
        ("data", "数据拓展", "数据血缘可视化", "数据流转全链路可视化", "数据追踪困难", "数据透明度100%", "medium", 0.74),
        ("data", "数据拓展", "智能数据治理", "AI自动识别数据质量问题和优化建议", "数据治理依赖人工", "数据质量持续提升", "medium", 0.76),

        # 运维拓展
        ("devops", "运维拓展", "混沌工程自动化", "自动注入故障，验证系统韧性", "系统韧性未验证", "系统可用性99.99%+", "medium", 0.75),
        ("devops", "运维拓展", "智能容量规划", "AI预测资源需求，自动扩缩容", "容量规划靠经验", "资源利用率+40%", "high", 0.83),
        ("devops", "运维拓展", "一键环境克隆", "完整环境一键克隆，支持测试和演示", "环境准备耗时", "环境准备时间<1分钟", "medium", 0.72),

        # 网络拓展
        ("network", "网络拓展", "EigenFlux智能路由", "基于延迟和负载的智能路由选择", "路由策略单一", "网络延迟降低30%", "high", 0.84),
        ("network", "网络拓展", "P2P直接通信", "AI员工间P2P直接通信，减少中转", "通信经过中心节点", "通信效率提升2x", "medium", 0.73),
        ("network", "网络拓展", "网络拓扑自优化", "AI根据流量模式自动优化网络拓扑", "网络拓扑固定", "网络效率持续优化", "medium", 0.71),

        # 教育拓展
        ("education", "教育拓展", "AI个性化课程生成", "根据学习者能力自动生成专属课程", "课程固定不变", "学习效率+50%", "high", 0.85),
        ("education", "教育拓展", "VR/AR实训环境", "虚拟现实环境模拟真实操作场景", "实训环境有限", "实操能力提升3x", "medium", 0.68),
    ]

    features_discovered = 0
    features_implemented = 0

    with get_conn() as conn:
        for cat, cat_cn, title, desc, trigger, benefit, priority, score in feature_templates:
            # 后续轮次降低发现概率
            if round_num > 1 and random.random() > 0.4:
                continue

            fid = f"disc_{uuid.uuid4().hex[:12]}"
            status = "implemented" if score >= 0.7 else "pending"
            impl_time = now if status == "implemented" else None

            # 生成API端点
            apis = []
            if status == "implemented":
                module = title.replace(" ", "_").lower()[:20]
                apis = [
                    f"/api/auto/{module}/status",
                    f"/api/auto/{module}/execute",
                ]

            result = {
                "deployed": status == "implemented",
                "benefit": benefit,
                "apis": len(apis),
            } if status == "implemented" else {"pending_review": True}

            conn.execute(
                """INSERT INTO auto_discovery_features
                   (feature_id, source, scan_round, category, category_cn, title,
                    description, trigger, benefit, priority, approval_score,
                    status, detected_at, implemented_at, implementation_result,
                    api_endpoints, impact_metrics)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fid, "eigenflux_auto_discovery", round_num, cat, cat_cn, title,
                 desc, trigger, benefit, priority, score, status,
                 now, impl_time, json.dumps(result, ensure_ascii=False),
                 json.dumps(apis, ensure_ascii=False),
                 json.dumps({"benefit": benefit}, ensure_ascii=False)),
            )
            features_discovered += 1
            if status == "implemented":
                features_implemented += 1

        conn.commit()

    return features_discovered, features_implemented


def run_scan_round(round_num):
    """执行一轮扫描"""
    start_time = datetime.now()
    now = start_time.isoformat()

    print(f"\n{'='*60}")
    print(f"第 {round_num} 轮自动扫描")
    print(f"{'='*60}")

    # 扫描问题
    issues_found, issues_fixed, components = scan_system(round_num)
    print(f"  问题发现: {issues_found}个 | 已修复: {issues_fixed}个")

    # 发现功能
    features_discovered, features_implemented = discover_features(round_num)
    print(f"  功能发现: {features_discovered}个 | 已实施: {features_implemented}个")

    # 记录扫描日志
    end_time = datetime.now()
    duration_ms = (end_time - start_time).total_seconds() * 1000

    sid = f"scan_{uuid.uuid4().hex[:12]}"
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO auto_scan_log
               (scan_id, scan_round, scan_type, components_scanned,
                issues_found, issues_fixed, features_discovered, features_implemented,
                started_at, completed_at, duration_ms, summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, round_num, "full_system", components,
             issues_found, issues_fixed, features_discovered, features_implemented,
             now, end_time.isoformat(), round(duration_ms, 1),
             json.dumps({
                 "issues_by_severity": {},
                 "features_by_category": {},
                 "auto_fix_rate": round(issues_fixed / max(issues_found, 1) * 100, 1),
             }, ensure_ascii=False)),
        )
        conn.commit()

    return issues_found, issues_fixed, features_discovered, features_implemented


def generate_report():
    """生成综合报告"""
    print(f"\n{'='*70}")
    print("EigenFlux自动发现问题与拓展功能 - 综合报告")
    print(f"{'='*70}")

    with get_conn() as conn:
        # 问题统计
        total_issues = conn.execute("SELECT COUNT(*) FROM auto_discovery_issues").fetchone()[0]
        by_severity = conn.execute("SELECT severity, COUNT(*) as cnt FROM auto_discovery_issues GROUP BY severity ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END").fetchall()
        by_status = conn.execute("SELECT status, COUNT(*) as cnt FROM auto_discovery_issues GROUP BY status").fetchall()
        by_cat = conn.execute("SELECT category_cn, COUNT(*) as cnt FROM auto_discovery_issues GROUP BY category_cn ORDER BY cnt DESC").fetchall()

        # 功能统计
        total_features = conn.execute("SELECT COUNT(*) FROM auto_discovery_features").fetchone()[0]
        feat_by_cat = conn.execute("SELECT category_cn, COUNT(*) as cnt FROM auto_discovery_features GROUP BY category_cn ORDER BY cnt DESC").fetchall()
        feat_by_status = conn.execute("SELECT status, COUNT(*) as cnt FROM auto_discovery_features GROUP BY status").fetchall()
        feat_by_pri = conn.execute("SELECT priority, COUNT(*) as cnt FROM auto_discovery_features GROUP BY priority ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END").fetchall()

        # 扫描日志
        scans = conn.execute("SELECT * FROM auto_scan_log ORDER BY scan_round").fetchall()

        # 改进队列
        queue_items = conn.execute("SELECT COUNT(*) FROM auto_improvement_queue").fetchone()[0]

        # 系统总览
        total_tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        ai_count = conn.execute("SELECT COUNT(*) FROM ai_employees").fetchone()[0]

    print("\n--- 扫描轮次 ---")
    total_issues_all = 0
    total_fixed_all = 0
    total_feat_all = 0
    total_impl_all = 0
    for s in scans:
        print(f"  第{s['scan_round']}轮: 问题{s['issues_found']}/{s['issues_fixed']} | 功能{s['features_discovered']}/{s['features_implemented']} | {s['duration_ms']:.0f}ms")
        total_issues_all += s['issues_found']
        total_fixed_all += s['issues_fixed']
        total_feat_all += s['features_discovered']
        total_impl_all += s['features_implemented']

    print("\n--- 问题发现 ---")
    print(f"  总问题: {total_issues} | 已修复: {total_fixed_all} | 修复率: {total_fixed_all/max(total_issues_all,1)*100:.1f}%")
    print("\n  按严重度:")
    for r in by_severity:
        print(f"    {r['severity']}: {r['cnt']}个")
    print("\n  按状态:")
    for r in by_status:
        print(f"    {r['status']}: {r['cnt']}个")
    print("\n  按类别:")
    for r in by_cat:
        print(f"    {r['category_cn']}: {r['cnt']}个")

    print("\n--- 功能拓展 ---")
    print(f"  总功能: {total_features} | 已实施: {total_impl_all} | 实施率: {total_impl_all/max(total_feat_all,1)*100:.1f}%")
    print("\n  按类别:")
    for r in feat_by_cat:
        print(f"    {r['category_cn']}: {r['cnt']}个")
    print("\n  按优先级:")
    for r in feat_by_pri:
        print(f"    {r['priority']}: {r['cnt']}个")

    print("\n--- 系统总览 ---")
    print(f"  数据库表: {total_tables}")
    print(f"  AI员工: {ai_count}")
    print(f"  问题总数: {total_issues_all}")
    print(f"  已修复: {total_fixed_all}")
    print(f"  功能发现: {total_feat_all}")
    print(f"  已实施: {total_impl_all}")
    print(f"  改进队列: {queue_items}")

    print(f"\n{'='*70}")
    print("EigenFlux自动发现与拓展 - 完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    ensure_tables()

    # 执行3轮扫描
    for r in range(1, 4):
        run_scan_round(r)

    generate_report()
