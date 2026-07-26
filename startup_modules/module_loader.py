#!/usr/bin/env python3
"""
功能模块加载器 - 6阶段模块加载
负责加载所有功能模块和API蓝图
"""

import os
import sys
import importlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

class ModuleLoader:
    def __init__(self, app):
        self.app = app
        self.loaded_modules = []
        self.failed_modules = []
        self.loading_order = []
        
        self.stages = [
            ('stage_auth', '认证模块', [
                ('auth_manager', 'auth_manager'),
            ]),
            ('stage_core_services', '核心服务', [
                ('config_manager', 'config_manager'),
                ('cache_manager', 'cache_manager'),
                ('activity_log_service', 'activity_log_service'),
                ('error_monitor', 'error_monitor'),
            ]),
            ('stage_system', '系统模块', [
                ('system_monitor', 'system_monitor'),
                ('task_scheduler', 'task_scheduler'),
                ('skill_manager', 'skill_manager'),
            ]),
            ('stage_ai', 'AI引擎', [
                ('ai_engine', 'ai_engine'),
                ('ai_brain', 'ai_brain'),
            ]),
            ('stage_question', '题库模块', [
                ('unified_question_bank', 'ai_engines.unified_question_bank'),
                ('dynamic_question_engine', 'ai_engines.dynamic_question_engine'),
            ]),
            ('stage_api', 'API接口', []),
        ]
    
    def load_module(self, module_name, import_path=None):
        if not import_path:
            import_path = module_name
        
        try:
            module = importlib.import_module(import_path)
            self.loaded_modules.append(module_name)
            return True, None
        except Exception as e:
            self.failed_modules.append(module_name)
            return False, str(e)
    
    def load_blueprints(self):
        blueprints = [
            ('agent_management_api', 'app.api.agent_management_api'),
            ('ai_dashboard_api', 'app.api.ai_dashboard_api'),
            ('ai_professional_api', 'app.api.ai_professional_api'),
            ('ai_recommendation_api', 'app.api.ai_recommendation_api'),
            ('ai_prediction_api', 'app.api.ai_prediction_api'),
            ('ai_decision_api', 'app.api.ai_decision_api'),
            ('ai_cognitive_api', 'app.api.ai_cognitive_api'),
            ('ai_qna_api', 'app.api.ai_qna_api'),
            ('ai_adaptive_api', 'app.api.ai_adaptive_api'),
            ('ai_evaluation_api', 'app.api.ai_evaluation_api'),
            ('ai_emotion_api', 'app.api.ai_emotion_api'),
            ('ai_memory_api', 'app.api.ai_memory_api'),
            ('system_extension_api', 'app.api.system_extension_api'),
            ('version_unified_api', 'app.api.version_unified_api'),
            ('health_api', 'app.api.health_api'),
            ('log_api', 'app.api.log_api'),
            ('config_api', 'app.api.config_api'),
            ('activity_api', 'app.api.activity_api'),
            ('export_api', 'app.api.export_api'),
            ('ai_engine_api', 'app.api.ai_engine_api'),
            ('ai_brain_api', 'app.api.ai_brain_api'),
            ('ai_cluster_api', 'app.api.ai_cluster_api'),
            ('ai_self_learning_api', 'app.api.ai_self_learning_api'),
            ('ai_gamification_api', 'app.api.ai_gamification_api'),
            ('ai_monitoring_api', 'app.api.ai_monitoring_api'),
            ('ai_auto_upgrade_api', 'app.api.ai_auto_upgrade_api'),
            ('ai_test_api', 'app.api.ai_test_api'),
            ('history_api', 'app.api.history_api'),
            ('ai_enterprise_api', 'app.api.ai_enterprise_api'),
            ('chinese_listening_api', 'app.api.chinese_listening_api'),
            ('unified_question_api', 'app.api.unified_question_api'),
            ('dynamic_question_api', 'app.api.dynamic_question_api'),
        ]
        
        registered = 0
        failed = 0
        
        for bp_name, module_path in blueprints:
            try:
                module = __import__(module_path, fromlist=[bp_name])
                bp = getattr(module, bp_name)
                self.app.register_blueprint(bp)
                registered += 1
                self.loaded_modules.append(bp_name)
            except Exception as e:
                failed += 1
                self.failed_modules.append(bp_name)
        
        return {'registered': registered, 'failed': failed}
    
    def load_all_modules(self):
        completed_stages = 0
        total_stages = len(self.stages)
        
        for stage_name, stage_desc, modules in self.stages:
            self.loading_order.append(stage_name)
            
            if stage_name == 'stage_api':
                result = self.load_blueprints()
                completed_stages += 1
                continue
            
            for module_name, import_path in modules:
                self.load_module(module_name, import_path)
            
            completed_stages += 1
        
        return {
            'completed_stages': completed_stages,
            'total_stages': total_stages,
            'loaded_modules': len(self.loaded_modules),
            'failed_modules': len(self.failed_modules),
            'failed_list': self.failed_modules,
        }
