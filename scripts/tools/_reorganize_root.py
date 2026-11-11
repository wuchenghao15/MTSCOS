#!/usr/bin/env python3
"""
根据开发规则 §2.2.2 归档决策树，将根目录违规文件智能归档到正确目录。
执行后根目录仅保留 §2.3.1 白名单文件。
"""
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# §2.3.1 白名单文件 - 允许留在根目录
WHITELIST = {
    'app.py', 'server_real_db.py', 'version_manager.py', 'VERSION',
    'Dockerfile', '.gitignore', 'requirements.txt',
    'requirements-python39.txt', 'README.md', 'README_EN.md',
    'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md',
    'CODE_OF_CONDUCT.md', 'LICENSE',
    # Docker相关配置也允许在根目录
    '.dockerignore', 'docker-compose.yml', '.env',
}

# 归档映射表: 文件名模式 -> 目标目录
# 按优先级从高到低匹配
ARCHIVE_RULES = [
    # 1. 数据库文件 → 不移动，仅标记（已在.gitignore）
    # 2. 日志文件 → logs/
    ('*.log', 'logs/'),
    ('feeding_script.log', 'logs/'),

    # 3. PID/心跳文件 → 删除
    ('.scheduler_pid', '_DELETE_'),
    ('.scheduler_heartbeat', '_DELETE_'),

    # 4. 大文件 → _archive/
    ('Ollama.dmg', '_archive/'),

    # 5. 临时步骤脚本 → scripts/tools/
    ('_s*.py', 'scripts/tools/'),
    ('_expand_ai_experts.py', 'scripts/tools/'),
    ('step12_*.py', 'scripts/tools/'),
    ('step12_*.json', 'test_reports/'),

    # 6. 测试报告 → test_reports/
    ('test_fixes_v6.json', 'test_reports/'),
    ('test_report.json', 'test_reports/'),
    ('test_report_v6.json', 'test_reports/'),
    ('test_results.json', 'test_reports/'),
    ('test_animations.js', 'tests/'),

    # 7. 文档 → docs/
    ('ARCHITECTURE_REPORT.md', 'docs/'),
    ('PROJECT_STRUCTURE.md', 'docs/'),
    ('SECURITY_REPORT.md', 'docs/'),
    ('SYSTEM_DOC.md', 'docs/'),
    ('UPGRADE_GUIDE_v1.7.0.md', 'docs/'),
    ('UPGRADE_PLAN.md', 'docs/'),
    ('fix_report.md', 'scripts/fix/'),

    # 8. Nginx配置 → nginx/
    ('nginx.conf', 'nginx/'),

    # 9. 配置文件 → config/
    ('vikey_whitelist.json', 'config/'),

    # 10. 调试脚本 → scripts/tools/
    ('debug_*.py', 'scripts/tools/'),

    # 11. 修复脚本 → scripts/fix/
    ('fix_*.py', 'scripts/fix/'),
    ('fix_*.md', 'scripts/fix/'),

    # 12. 升级脚本 → scripts/upgrade/
    ('upgrade_*.py', 'scripts/upgrade/'),
    ('upgrade_*.md', 'scripts/upgrade/'),

    # 13. 数据库工具 → database/
    ('db_*.py', 'database/'),
    ('analyze_db*.py', 'database/'),
    ('adapt_database.py', 'database/'),
    ('check_layout_db.py', 'database/'),
    ('split_database.py', 'database/'),
    ('setup_database.py', 'database/'),
    ('setup_full_database.py', 'database/'),
    ('init*.py', 'database/'),

    # 14. 种子数据脚本 → scripts/tools/
    ('seed_*.py', 'scripts/tools/'),

    # 15. 生成脚本 → scripts/tools/
    ('generate_*.py', 'scripts/tools/'),

    # 16. 简化/整理脚本 → scripts/tools/
    ('simplify_*.py', 'scripts/tools/'),

    # 17. 启动脚本 → scripts/
    ('start_*.py', 'scripts/'),
    ('simple_start.py', 'scripts/'),
    ('modular_start.py', 'scripts/'),
    ('start_schedulers.py', 'scripts/'),

    # 18. AI引擎模块 → ai_engines/
    ('ai_anomaly_detection.py', 'ai_engines/'),
    ('ai_code_review.py', 'ai_engines/'),
    ('ai_collaboration_network.py', 'ai_engines/'),
    ('ai_content_moderation.py', 'ai_engines/'),
    ('ai_data_augmentation.py', 'ai_engines/'),
    ('ai_data_pipeline.py', 'ai_engines/'),
    ('ai_experiment_tracker.py', 'ai_engines/'),
    ('ai_explainability.py', 'ai_engines/'),
    ('ai_federated_learning.py', 'ai_engines/'),
    ('ai_knowledge_graph.py', 'ai_engines/'),
    ('ai_model_evaluation.py', 'ai_engines/'),
    ('ai_model_manager.py', 'ai_engines/'),
    ('ai_multimodal.py', 'ai_engines/'),
    ('ai_performance_optimizer.py', 'ai_engines/'),
    ('ai_prompt_manager.py', 'ai_engines/'),
    ('ai_security_guard.py', 'ai_engines/'),
    ('ai_smart_monitor.py', 'ai_engines/'),
    ('ai_test_generator.py', 'ai_engines/'),
    ('ai_vector_store.py', 'ai_engines/'),
    ('ai_workflow_orchestrator.py', 'ai_engines/'),
    ('exam_generator.py', 'ai_engines/'),
    ('exam_judge_system.py', 'ai_engines/'),
    ('question_crawler.py', 'ai_engines/'),
    ('mt_ir14_dev_flow.py', 'ai_engines/'),
    ('mtscos.py', 'ai_engines/'),

    # 19. 系统级引擎 → engines/
    ('performance_optimizer.py', 'engines/'),
    ('security_enhancer.py', 'engines/'),
    ('education_enhancer.py', 'engines/'),
    ('education_path_planner.py', 'engines/'),
    ('frontend_enhancer.py', 'engines/'),
    ('ops_monitor_enhancer.py', 'engines/'),
    ('microservice_infrastructure.py', 'engines/'),
    ('penetration_tester.py', 'engines/'),
    ('attack_pattern_db.py', 'engines/'),
    ('blackbox_recorder.py', 'engines/'),

    # 20. 业务服务 → services/
    ('auth_manager.py', 'services/'),
    ('backup_manager.py', 'services/'),
    ('cache_manager.py', 'services/'),
    ('config_manager.py', 'services/'),
    ('error_monitor.py', 'services/'),
    ('file_manager.py', 'services/'),
    ('message_system.py', 'services/'),
    ('monitoring_system.py', 'services/'),
    ('notification_center.py', 'services/'),
    ('service_discovery.py', 'services/'),
    ('service_manager.py', 'services/'),
    ('service_mesh_proxy.py', 'services/'),
    ('skill_manager.py', 'services/'),
    ('system_monitor.py', 'services/'),
    ('task_scheduler.py', 'services/'),
    ('report_generator.py', 'services/'),
    ('dual_key_auth.py', 'services/'),
    ('vikey_detector.py', 'services/'),
    ('vpn_server.py', 'services/'),
    ('di_container.py', 'services/'),
    ('api_gateway.py', 'services/'),
    ('git_sync.py', 'services/'),

    # 21. 核心基础设施 → core/
    ('smart_db_router.py', 'core/'),
    ('smart_db_router_simple.py', 'core/'),
    ('cluster_manager.py', 'core/'),
    ('scheduler_control.py', 'core/'),
    ('auto_scheduler.py', 'core/'),
    ('routine_maintenance.py', 'core/'),

    # 22. 运维工具 → scripts/tools/
    ('automated_setup.py', 'scripts/tools/'),
    ('comprehensive_test.py', 'scripts/tools/'),
    ('architecture_engineer.py', 'scripts/tools/'),
    ('cheese_model_validator.py', 'scripts/tools/'),
    ('reset_password.py', 'scripts/tools/'),
    ('reset_password_v2.py', 'scripts/tools/'),
    ('feed_question_and_brain.py', 'scripts/tools/'),
    ('verify_round8_routes.py', 'scripts/tools/'),

    # 23. 前端文件 → src/html/
    ('openclaw_example.html', 'src/html/'),
    ('openclaw_optimized_styles.css', 'src/html/'),
]


def match_pattern(filename, pattern):
    """简单glob匹配"""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


def get_target(filename):
    """根据归档规则获取目标目录"""
    for pattern, target in ARCHIVE_RULES:
        if match_pattern(filename, pattern):
            return target
    return None


def ensure_dir(path):
    """确保目录存在"""
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def safe_move(src, dst_dir):
    """安全移动文件，处理冲突"""
    if not os.path.isfile(src):
        return 'skip_notexist'
    filename = os.path.basename(src)
    dst = os.path.join(dst_dir, filename)
    # 如果目标已存在且内容相同，跳过
    if os.path.isfile(dst):
        try:
            src_size = os.path.getsize(src)
            dst_size = os.path.getsize(dst)
            if src_size == dst_size:
                os.remove(src)
                return 'dedup'
        except:
            pass
        # 目标存在但内容不同，添加后缀
        name, ext = os.path.splitext(filename)
        i = 1
        while os.path.exists(dst):
            dst = os.path.join(dst_dir, f"{name}_root{ext}")
            if not os.path.exists(dst):
                break
            i += 1
    try:
        shutil.move(src, dst)
        return 'moved'
    except Exception as e:
        # OneDrive锁定的文件，尝试复制后删除
        try:
            shutil.copy2(src, dst)
            os.remove(src)
            return 'copied'
        except Exception as e2:
            return f'error:{e2}'


def main():
    os.chdir(BASE)

    # 确保所有目标目录存在
    target_dirs = set()
    for _, target in ARCHIVE_RULES:
        if target != '_DELETE_' and target != '_archive/':
            target_dirs.add(target)
    for d in target_dirs:
        ensure_dir(d)
    ensure_dir('_archive/')
    ensure_dir('docs/')

    # 统计
    stats = {'moved': 0, 'copied': 0, 'dedup': 0, 'deleted': 0,
             'skip_whitelist': 0, 'skip_notexist': 0, 'error': 0,
             'no_rule': 0}
    no_rule_files = []
    errors = []

    # 获取根目录所有文件
    root_files = [f for f in os.listdir('.') if os.path.isfile(f)
                  and not f.startswith('.git')]

    for filename in root_files:
        # 跳过白名单
        if filename in WHITELIST:
            stats['skip_whitelist'] += 1
            continue

        # 跳过数据库文件（已在.gitignore，不移动）
        if filename.endswith(('.db', '.db-shm', '.db-wal')):
            stats['skip_whitelist'] += 1  # 数据库文件不移动
            continue

        target = get_target(filename)

        if target is None:
            stats['no_rule'] += 1
            no_rule_files.append(filename)
            continue

        if target == '_DELETE_':
            try:
                os.remove(filename)
                stats['deleted'] += 1
            except Exception as e:
                stats['error'] += 1
                errors.append(f"删除失败 {filename}: {e}")
            continue

        result = safe_move(filename, target)
        if result == 'moved':
            stats['moved'] += 1
        elif result == 'copied':
            stats['copied'] += 1
        elif result == 'dedup':
            stats['dedup'] += 1
        elif result == 'skip_notexist':
            stats['skip_notexist'] += 1
        elif result.startswith('error'):
            stats['error'] += 1
            errors.append(f"{filename}: {result}")

    # 输出报告
    print("=" * 60)
    print("文件归档迁移报告")
    print("=" * 60)
    print(f"  移动成功:     {stats['moved']}")
    print(f"  复制成功:     {stats['copied']}")
    print(f"  去重删除:     {stats['dedup']}")
    print(f"  删除文件:     {stats['deleted']}")
    print(f"  白名单跳过:   {stats['skip_whitelist']}")
    print(f"  无规则文件:   {stats['no_rule']}")
    print(f"  错误:         {stats['error']}")
    print("-" * 60)

    if no_rule_files:
        print(f"\n⚠️ 无归档规则的文件 ({len(no_rule_files)}):")
        for f in no_rule_files:
            print(f"  {f}")

    if errors:
        print(f"\n❌ 错误 ({len(errors)}):")
        for e in errors:
            print(f"  {e}")

    # 验证根目录
    print("\n" + "=" * 60)
    print("迁移后根目录文件:")
    print("=" * 60)
    remaining = [f for f in os.listdir('.') if os.path.isfile(f)
                 and not f.startswith('.git')]
    for f in sorted(remaining):
        if f in WHITELIST or f.endswith(('.db', '.db-shm', '.db-wal')):
            print(f"  ✅ {f}")
        else:
            print(f"  ⚠️ {f} (未归档)")


if __name__ == '__main__':
    main()
