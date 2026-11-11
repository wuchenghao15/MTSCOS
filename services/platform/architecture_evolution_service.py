#!/usr/bin/env python3
"""
MTSCOS 教育系统架构演进服务
================================
面向 MTSCOS AI 教育平台的系统架构演进与治理服务，覆盖以下六大演进方向：

1. 微服务化   —— 用户服务 / 题库服务 / 考试服务 / AI 服务 / 分析服务拆分
2. API 网关   —— 认证 / 限流 / 路由 / 监控统一入口
3. 多租户 SaaS —— 多学校 / 机构独立部署或共享
4. 移动端     —— 管理App / 学习App / 微信小程序 / PWA
5. 安全合规   —— 零信任 / 数据加密 / 等保2.0 / VIKEY 硬件认证
6. AIOps      —— 异常检测 / 根因分析 / 自愈 / 容量预测

通过 SQLite 持久化架构模块、演进计划、插件、监控指标、安全合规与移动端平台信息，
为平台的架构治理、演进决策与可视化提供统一的数据底座。
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

# ----------------------------------------------------------------------------
# 数据库路径解析：优先使用 core/db_path.py 的 get_db_path，失败回退到 PROJECT_ROOT/app.db
# ----------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from core.db_path import get_db_path as _mtscos_get_db_path  # type: ignore
    DATABASE_PATH = _mtscos_get_db_path('app.db')
except Exception as _import_err:  # pragma: no cover - 兜底路径
    DATABASE_PATH = os.path.join(_PROJECT_ROOT, 'app.db')

# 确保数据库所在目录存在
try:
    _db_dir = os.path.dirname(os.path.abspath(DATABASE_PATH))
    if _db_dir and not os.path.exists(_db_dir):
        os.makedirs(_db_dir, exist_ok=True)
except Exception:
    pass

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ArchitectureEvolutionService:
    """MTSCOS 系统架构演进服务类。

    负责架构模块注册、演进计划管理、插件治理、监控告警、安全合规审计与
    移动端平台管理，为平台架构治理提供端到端的数据与逻辑支撑。
    """

    # ---------------- 枚举常量（约束各字段取值范围） ----------------
    MODULE_TYPES = ['core', 'microservice', 'api_gateway', 'message_queue', 'cache', 'database']
    EVOLUTION_DIRECTIONS = ['microservice', 'multi_tenant', 'mobile', 'cloud_native', 'security', 'aiops']
    COMPLIANCE_TYPES = ['zero_trust', 'data_security', 'gdpr', 'pipl', '等保2.0', 'vikey']
    MOBILE_PLATFORMS = ['admin_app', 'learner_app', 'wechat_mini', 'pwa']
    PLAN_STATUSES = ['planning', 'in_progress', 'completed', 'cancelled', 'on_hold']
    PRIORITIES = ['low', 'medium', 'high', 'critical']

    # 各合规类型审计时需要核对的配置字段（用于 audit_compliance 的规则校验）
    COMPLIANCE_REQUIRED_KEYS = {
        'zero_trust': ['identity_verification', 'device_verification', 'least_privilege'],
        'data_security': ['encryption_at_rest', 'encryption_in_transit', 'key_management'],
        'gdpr': ['consent_management', 'data_subject_rights', 'breach_notification'],
        'pipl': ['data_classification', 'cross_border_transfer', 'consent'],
        '等保2.0': ['level', 'security_domain', 'audit_log'],
        'vikey': ['hardware_key', 'authentication_server', 'certificate'],
    }

    # ---------------- 六大架构方向的默认落地数据 ----------------
    # 微服务化：核心业务服务拆分
    DEFAULT_MICROSERVICES = [
        ('user_service', 'microservice', '用户服务：认证、权限、组织架构', 'Flask + JWT + PostgreSQL'),
        ('question_bank_service', 'microservice', '题库服务：题目管理、检索、版本控制', 'FastAPI + Elasticsearch'),
        ('exam_service', 'microservice', '考试服务：考试流程、防作弊、自动批改', 'Flask + Redis'),
        ('ai_service', 'microservice', 'AI 服务：智能问答、批改、推荐', 'Python + Transformers'),
        ('analytics_service', 'microservice', '分析服务：学习分析、数据看板', 'Python + ClickHouse'),
    ]
    # API 网关：统一入口
    DEFAULT_API_GATEWAY = [
        ('api_gateway', 'api_gateway', 'API 网关：认证 / 限流 / 路由 / 监控统一入口', 'Kong + Nginx'),
    ]
    # 多租户 SaaS：基础设施
    DEFAULT_MULTI_TENANT = [
        ('tenant_manager', 'core', '多租户管理：多学校 / 机构独立或共享部署', 'Python + 租户隔离策略'),
    ]
    # 移动端：四端覆盖
    DEFAULT_MOBILE_PLATFORMS = [
        ('admin_app', ['管理后台', '审批', '数据看板'], 'https://download.mtscos.edu/admin'),
        ('learner_app', ['在线学习', '作业', '考试', '消息推送'], 'https://download.mtscos.edu/learner'),
        ('wechat_mini', ['轻量学习', '签到', '通知'], 'https://mp.weixin.qq.com/mtscos'),
        ('pwa', ['离线学习', '跨端访问'], 'https://app.mtscos.edu/pwa'),
    ]
    # 安全合规：六类配置
    DEFAULT_COMPLIANCE = [
        ('zero_trust', {'identity_verification': True, 'device_verification': True, 'least_privilege': True}),
        ('data_security', {'encryption_at_rest': 'AES-256', 'encryption_in_transit': 'TLS1.3', 'key_management': 'KMS'}),
        ('vikey', {'hardware_key': 'VIKEY-PRO', 'authentication_server': 'vikey-auth.mtscos.edu', 'certificate': 'MTSCOS-ROOT-CA'}),
        ('等保2.0', {'level': '三级', 'security_domain': '教育核心域', 'audit_log': True}),
    ]
    # 默认演进计划（对应六大方向）
    DEFAULT_PLANS = [
        ('微服务化拆分演进', 'microservice', '将单体应用拆分为用户/题库/考试/AI/分析五大微服务',
         [{'name': '服务边界划分', 'status': 'pending'}, {'name': '服务独立部署', 'status': 'pending'},
          {'name': '服务网格接入', 'status': 'pending'}]),
        ('多租户 SaaS 化演进', 'multi_tenant', '支持多学校 / 机构独立或共享部署',
         [{'name': '租户隔离设计', 'status': 'pending'}, {'name': '租户计费体系', 'status': 'pending'},
          {'name': '灰度上线', 'status': 'pending'}]),
        ('移动端全覆盖演进', 'mobile', '管理App / 学习App / 微信小程序 / PWA 四端打通',
         [{'name': '学习App 上线', 'status': 'pending'}, {'name': '管理App 上线', 'status': 'pending'},
          {'name': '小程序与 PWA', 'status': 'pending'}]),
        ('云原生架构演进', 'cloud_native', '容器化、服务网格、弹性伸缩',
         [{'name': '容器化改造', 'status': 'pending'}, {'name': 'Kubernetes 编排', 'status': 'pending'},
          {'name': '弹性伸缩', 'status': 'pending'}]),
        ('安全合规体系建设', 'security', '零信任 / 数据加密 / 等保2.0 / VIKEY 硬件认证',
         [{'name': '零信任落地', 'status': 'pending'}, {'name': '等保2.0 测评', 'status': 'pending'},
          {'name': 'VIKEY 接入', 'status': 'pending'}]),
        ('AIOps 智能运维演进', 'aiops', '异常检测 / 根因分析 / 自愈 / 容量预测',
         [{'name': '异常检测接入', 'status': 'pending'}, {'name': '根因分析', 'status': 'pending'},
          {'name': '自愈与容量预测', 'status': 'pending'}]),
    ]

    def __init__(self, db_path: Optional[str] = None) -> None:
        """初始化架构演进服务。

        Args:
            db_path: SQLite 数据库路径，默认使用模块级 DATABASE_PATH。
        """
        self.db_path = db_path or DATABASE_PATH
        self._lock = threading.RLock()
        self.init_tables()

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------
    def _get_connection(self) -> sqlite3.Connection:
        """获取 SQLite 数据库连接（启用外键与行工厂）。"""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        return conn

    @staticmethod
    def _now() -> str:
        """获取当前时间字符串。"""
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def _json_dumps(value: Any) -> str:
        """安全序列化 JSON。"""
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning("JSON 序列化失败: %s", e)
            return '[]'

    @staticmethod
    def _json_loads(value: Any, default: Any = None) -> Any:
        """安全反序列化 JSON。"""
        if default is None:
            default = []
        if value is None or value == '':
            return default
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            logger.warning("JSON 反序列化失败: %s", e)
            return default

    # ------------------------------------------------------------------
    # 表结构初始化
    # ------------------------------------------------------------------
    def init_tables(self) -> Dict[str, Any]:
        """初始化全部架构相关数据表。"""
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                # 1. 架构模块注册表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS architecture_modules (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        module_name  TEXT NOT NULL UNIQUE,
                        module_type  TEXT NOT NULL,
                        description  TEXT DEFAULT '',
                        tech_stack   TEXT DEFAULT '',
                        status       TEXT DEFAULT 'active',
                        health_score INTEGER DEFAULT 100,
                        created_at   TEXT
                    )
                ''')
                # 2. 架构演进计划表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS architecture_evolution_plans (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        plan_name     TEXT NOT NULL,
                        direction     TEXT NOT NULL,
                        description   TEXT DEFAULT '',
                        phases        TEXT DEFAULT '[]',
                        current_phase INTEGER DEFAULT 0,
                        status        TEXT DEFAULT 'planning',
                        priority      TEXT DEFAULT 'medium',
                        created_at    TEXT
                    )
                ''')
                # 3. 插件系统注册表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS architecture_plugins (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        plugin_name TEXT NOT NULL,
                        plugin_type TEXT DEFAULT 'extension',
                        version     TEXT DEFAULT '1.0.0',
                        entry_point TEXT DEFAULT '',
                        is_active   INTEGER DEFAULT 1,
                        config      TEXT DEFAULT '{}',
                        created_at  TEXT
                    )
                ''')
                # 4. 架构监控指标表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS architecture_monitoring (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        module_name  TEXT NOT NULL,
                        metric_name  TEXT NOT NULL,
                        metric_value REAL DEFAULT 0,
                        threshold    REAL DEFAULT 0,
                        status       TEXT DEFAULT 'normal',
                        recorded_at  TEXT
                    )
                ''')
                # 5. 安全合规配置表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS architecture_security_compliance (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        compliance_type TEXT NOT NULL,
                        config          TEXT DEFAULT '{}',
                        audit_status    TEXT DEFAULT 'pending',
                        last_audit      TEXT,
                        created_at      TEXT
                    )
                ''')
                # 6. 移动端平台表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS architecture_mobile_platforms (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform     TEXT NOT NULL,
                        features     TEXT DEFAULT '[]',
                        status       TEXT DEFAULT 'active',
                        download_url TEXT DEFAULT '',
                        created_at   TEXT
                    )
                ''')
                conn.commit()
                logger.info("架构演进服务数据表初始化完成: %s", self.db_path)
                return {'success': True, 'message': '数据表初始化完成', 'db_path': self.db_path}
            except sqlite3.Error as e:
                logger.error("初始化架构数据表失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 架构模块管理
    # ------------------------------------------------------------------
    def register_module(self, module_name: str, module_type: str, description: str = '',
                        tech_stack: str = '') -> Dict[str, Any]:
        """注册架构模块。

        Args:
            module_name: 模块名称（唯一）。
            module_type: 模块类型，取值见 MODULE_TYPES。
            description: 模块描述。
            tech_stack: 技术栈说明。
        """
        if not module_name or not module_type:
            return {'success': False, 'error': 'module_name 与 module_type 不能为空'}
        if module_type not in self.MODULE_TYPES:
            return {'success': False, 'error': f'非法模块类型: {module_type}，允许: {self.MODULE_TYPES}'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM architecture_modules WHERE module_name = ?', (module_name,))
                existing = cursor.fetchone()
                if existing is not None:
                    # 已存在则更新描述与技术栈
                    cursor.execute(
                        'UPDATE architecture_modules SET description = ?, tech_stack = ? WHERE module_name = ?',
                        (description, tech_stack, module_name)
                    )
                    conn.commit()
                    logger.info("架构模块已存在，更新描述: %s", module_name)
                    return {'success': True, 'module_id': existing['id'], 'module_name': module_name,
                            'action': 'updated'}
                cursor.execute(
                    'INSERT INTO architecture_modules (module_name, module_type, description, tech_stack, status, health_score, created_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (module_name, module_type, description, tech_stack, 'active', 100, self._now())
                )
                conn.commit()
                module_id = cursor.lastrowid
                logger.info("注册架构模块成功: %s (id=%s)", module_name, module_id)
                return {'success': True, 'module_id': module_id, 'module_name': module_name, 'action': 'created'}
            except sqlite3.Error as e:
                logger.error("注册架构模块失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    def get_all_modules(self) -> Dict[str, Any]:
        """获取所有架构模块。"""
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM architecture_modules ORDER BY id ASC')
                rows = cursor.fetchall()
                modules = [dict(r) for r in rows]
                return {'success': True, 'count': len(modules), 'modules': modules}
            except sqlite3.Error as e:
                logger.error("获取架构模块列表失败: %s", e)
                return {'success': False, 'error': str(e), 'modules': []}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 演进计划管理
    # ------------------------------------------------------------------
    def create_evolution_plan(self, plan_name: str, direction: str, description: str = '',
                              phases: Optional[List[Any]] = None) -> Dict[str, Any]:
        """创建架构演进计划。

        Args:
            plan_name: 计划名称。
            direction: 演进方向，取值见 EVOLUTION_DIRECTIONS。
            description: 计划描述。
            phases: 阶段列表，每个阶段为 dict（如 {'name': '阶段一', 'status': 'pending'}）。
        """
        if not plan_name or not direction:
            return {'success': False, 'error': 'plan_name 与 direction 不能为空'}
        if direction not in self.EVOLUTION_DIRECTIONS:
            return {'success': False, 'error': f'非法演进方向: {direction}，允许: {self.EVOLUTION_DIRECTIONS}'}
        if phases is None:
            phases = []
        if not isinstance(phases, list):
            return {'success': False, 'error': 'phases 必须为列表'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO architecture_evolution_plans '
                    '(plan_name, direction, description, phases, current_phase, status, priority, created_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (plan_name, direction, description, self._json_dumps(phases), 0, 'planning', 'medium', self._now())
                )
                conn.commit()
                plan_id = cursor.lastrowid
                logger.info("创建演进计划成功: %s (id=%s, direction=%s)", plan_name, plan_id, direction)
                return {'success': True, 'plan_id': plan_id, 'plan_name': plan_name,
                        'direction': direction, 'total_phases': len(phases)}
            except sqlite3.Error as e:
                logger.error("创建演进计划失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    def advance_plan_phase(self, plan_id: int) -> Dict[str, Any]:
        """推进计划到下一阶段。

        current_phase 语义：1-based 当前阶段编号，0 表示尚未开始，等于阶段总数表示已全部完成。
        """
        if plan_id is None:
            return {'success': False, 'error': 'plan_id 不能为空'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM architecture_evolution_plans WHERE id = ?', (plan_id,))
                row = cursor.fetchone()
                if row is None:
                    return {'success': False, 'error': f'未找到演进计划: id={plan_id}'}
                plan = dict(row)
                if plan['status'] == 'completed':
                    return {'success': True, 'plan_id': plan_id, 'message': '计划已完成，无需推进',
                            'current_phase': plan['current_phase'], 'status': 'completed'}
                if plan['status'] == 'cancelled':
                    return {'success': False, 'error': '计划已取消，无法推进'}

                phases = self._json_loads(plan['phases'], [])
                total = len(phases)
                current = int(plan['current_phase'])
                if total == 0:
                    return {'success': False, 'error': '计划未定义任何阶段，无法推进'}

                # 推进逻辑：current < total 则前进一格，达到 total 则标记完成
                if current < total:
                    current += 1
                    new_status = 'completed' if current >= total else 'in_progress'
                else:
                    new_status = 'completed'

                cursor.execute(
                    'UPDATE architecture_evolution_plans SET current_phase = ?, status = ? WHERE id = ?',
                    (current, new_status, plan_id)
                )
                conn.commit()
                logger.info("推进计划阶段成功: plan_id=%s, current_phase=%s/%s, status=%s",
                            plan_id, current, total, new_status)
                return {
                    'success': True,
                    'plan_id': plan_id,
                    'plan_name': plan['plan_name'],
                    'current_phase': current,
                    'total_phases': total,
                    'status': new_status,
                    'current_phase_name': phases[current - 1].get('name', f'阶段{current}') if current > 0 else None,
                }
            except sqlite3.Error as e:
                logger.error("推进计划阶段失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    def get_active_plans(self) -> Dict[str, Any]:
        """获取活跃计划（非完成、非取消）。"""
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT * FROM architecture_evolution_plans '
                    'WHERE status NOT IN (?, ?) ORDER BY priority DESC, created_at ASC',
                    ('completed', 'cancelled')
                )
                rows = cursor.fetchall()
                plans = []
                for r in rows:
                    p = dict(r)
                    p['phases'] = self._json_loads(p.get('phases'), [])
                    plans.append(p)
                return {'success': True, 'count': len(plans), 'plans': plans}
            except sqlite3.Error as e:
                logger.error("获取活跃计划失败: %s", e)
                return {'success': False, 'error': str(e), 'plans': []}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 插件系统管理
    # ------------------------------------------------------------------
    def register_plugin(self, plugin_name: str, plugin_type: str, entry_point: str = '',
                        config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """注册插件。

        Args:
            plugin_name: 插件名称。
            plugin_type: 插件类型（如 extension / integration / theme）。
            entry_point: 插件入口（模块路径或函数签名）。
            config: 插件配置字典。
        """
        if not plugin_name or not plugin_type:
            return {'success': False, 'error': 'plugin_name 与 plugin_type 不能为空'}
        if config is None:
            config = {}
        if not isinstance(config, dict):
            return {'success': False, 'error': 'config 必须为字典'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO architecture_plugins '
                    '(plugin_name, plugin_type, version, entry_point, is_active, config, created_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (plugin_name, plugin_type, '1.0.0', entry_point, 1, self._json_dumps(config), self._now())
                )
                conn.commit()
                plugin_id = cursor.lastrowid
                logger.info("注册插件成功: %s (id=%s)", plugin_name, plugin_id)
                return {'success': True, 'plugin_id': plugin_id, 'plugin_name': plugin_name}
            except sqlite3.Error as e:
                logger.error("注册插件失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 监控与健康检查
    # ------------------------------------------------------------------
    def record_monitoring(self, module_name: str, metric_name: str, value: float,
                          threshold: float) -> Dict[str, Any]:
        """记录监控指标。

        约定 threshold 为指标上限（value 越低越好），据此计算状态：
        - value > threshold            => critical（严重）
        - value > threshold * 0.8      => warning（告警）
        - 其余                          => normal（正常）
        记录后同步刷新对应模块的健康分。
        """
        if not module_name or not metric_name:
            return {'success': False, 'error': 'module_name 与 metric_name 不能为空'}
        try:
            value = float(value)
            threshold = float(threshold)
        except (TypeError, ValueError) as e:
            return {'success': False, 'error': f'value/threshold 必须为数值: {e}'}

        if threshold > 0:
            if value > threshold:
                status = 'critical'
            elif value > threshold * 0.8:
                status = 'warning'
            else:
                status = 'normal'
        else:
            status = 'normal'

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO architecture_monitoring '
                    '(module_name, metric_name, metric_value, threshold, status, recorded_at) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (module_name, metric_name, value, threshold, status, self._now())
                )
                conn.commit()
                record_id = cursor.lastrowid
                logger.info("记录监控指标: %s.%s = %s (阈值 %s) => %s",
                            module_name, metric_name, value, threshold, status)
                # 同步刷新模块健康分
                health = self._compute_health_score(module_name, conn)
                cursor.execute(
                    'UPDATE architecture_modules SET health_score = ? WHERE module_name = ?',
                    (health, module_name)
                )
                conn.commit()
                return {
                    'success': True, 'record_id': record_id, 'module_name': module_name,
                    'metric_name': metric_name, 'value': value, 'threshold': threshold,
                    'status': status, 'health_score': health,
                }
            except sqlite3.Error as e:
                logger.error("记录监控指标失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    def _compute_health_score(self, module_name: str, conn: sqlite3.Connection) -> int:
        """根据最近 10 条监控记录计算模块健康分（0-100）。

        normal 计 0 扣分，warning 每条扣 8 分，critical 每条扣 20 分，最低 0 分；
        无记录则视为满分 100。
        """
        try:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT status FROM architecture_monitoring WHERE module_name = ? '
                'ORDER BY id DESC LIMIT 10',
                (module_name,)
            )
            rows = cursor.fetchall()
            if not rows:
                return 100
            score = 100
            for r in rows:
                s = r['status']
                if s == 'critical':
                    score -= 20
                elif s == 'warning':
                    score -= 8
            return max(score, 0)
        except sqlite3.Error as e:
            logger.warning("计算健康分失败: %s", e)
            return 100

    def check_health(self, module_name: str) -> Dict[str, Any]:
        """检查模块健康状态。

        综合健康分与最近监控记录给出健康结论：
        - health_score >= 80  => healthy
        - health_score >= 50  => degraded
        - 其余                 => critical
        """
        if not module_name:
            return {'success': False, 'error': 'module_name 不能为空'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM architecture_modules WHERE module_name = ?', (module_name,))
                row = cursor.fetchone()
                if row is None:
                    return {'success': False, 'error': f'未找到模块: {module_name}'}
                module = dict(row)

                health = self._compute_health_score(module_name, conn)
                # 同步回写最新健康分
                cursor.execute(
                    'UPDATE architecture_modules SET health_score = ? WHERE module_name = ?',
                    (health, module_name)
                )
                conn.commit()

                cursor.execute(
                    'SELECT metric_name, metric_value, threshold, status, recorded_at '
                    'FROM architecture_monitoring WHERE module_name = ? '
                    'ORDER BY id DESC LIMIT 10',
                    (module_name,)
                )
                recent = [dict(r) for r in cursor.fetchall()]

                if health >= 80:
                    conclusion = 'healthy'
                elif health >= 50:
                    conclusion = 'degraded'
                else:
                    conclusion = 'critical'

                logger.info("模块健康检查: %s => health=%s, conclusion=%s", module_name, health, conclusion)
                return {
                    'success': True,
                    'module_name': module_name,
                    'module_type': module.get('module_type'),
                    'health_score': health,
                    'conclusion': conclusion,
                    'recent_metrics': recent,
                    'critical_count': sum(1 for m in recent if m.get('status') == 'critical'),
                    'warning_count': sum(1 for m in recent if m.get('status') == 'warning'),
                }
            except sqlite3.Error as e:
                logger.error("检查模块健康失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 安全合规管理
    # ------------------------------------------------------------------
    def setup_compliance(self, compliance_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """配置安全合规。

        Args:
            compliance_type: 合规类型，取值见 COMPLIANCE_TYPES。
            config: 合规配置字典。
        """
        if not compliance_type:
            return {'success': False, 'error': 'compliance_type 不能为空'}
        if compliance_type not in self.COMPLIANCE_TYPES:
            return {'success': False, 'error': f'非法合规类型: {compliance_type}，允许: {self.COMPLIANCE_TYPES}'}
        if config is None or not isinstance(config, dict):
            return {'success': False, 'error': 'config 必须为字典'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT id FROM architecture_security_compliance WHERE compliance_type = ?',
                    (compliance_type,)
                )
                existing = cursor.fetchone()
                if existing is not None:
                    cursor.execute(
                        'UPDATE architecture_security_compliance SET config = ?, audit_status = ? WHERE compliance_type = ?',
                        (self._json_dumps(config), 'pending', compliance_type)
                    )
                    conn.commit()
                    logger.info("更新安全合规配置: %s", compliance_type)
                    return {'success': True, 'compliance_id': existing['id'], 'action': 'updated'}
                cursor.execute(
                    'INSERT INTO architecture_security_compliance '
                    '(compliance_type, config, audit_status, last_audit, created_at) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (compliance_type, self._json_dumps(config), 'pending', None, self._now())
                )
                conn.commit()
                compliance_id = cursor.lastrowid
                logger.info("配置安全合规成功: %s (id=%s)", compliance_type, compliance_id)
                return {'success': True, 'compliance_id': compliance_id, 'action': 'created'}
            except sqlite3.Error as e:
                logger.error("配置安全合规失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    def audit_compliance(self, compliance_type: str) -> Dict[str, Any]:
        """执行合规审计。

        依据 COMPLIANCE_REQUIRED_KEYS 中该类型必备字段进行规则校验，缺失任一字段则审计不通过。
        """
        if not compliance_type:
            return {'success': False, 'error': 'compliance_type 不能为空'}
        if compliance_type not in self.COMPLIANCE_TYPES:
            return {'success': False, 'error': f'非法合规类型: {compliance_type}，允许: {self.COMPLIANCE_TYPES}'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT * FROM architecture_security_compliance WHERE compliance_type = ?',
                    (compliance_type,)
                )
                row = cursor.fetchone()
                if row is None:
                    return {'success': False, 'error': f'未找到合规配置: {compliance_type}'}
                record = dict(row)
                config = self._json_loads(record.get('config'), {})

                required = self.COMPLIANCE_REQUIRED_KEYS.get(compliance_type, [])
                missing = [k for k in required if k not in config or config.get(k) in (None, '', False, 0)]
                # 注：布尔 False / 0 视为未启用，按缺失处理；如需显式关闭可扩展方向参数
                passed = len(missing) == 0
                audit_status = 'passed' if passed else 'failed'
                now = self._now()

                cursor.execute(
                    'UPDATE architecture_security_compliance SET audit_status = ?, last_audit = ? WHERE compliance_type = ?',
                    (audit_status, now, compliance_type)
                )
                conn.commit()
                logger.info("合规审计完成: %s => %s (缺失: %s)", compliance_type, audit_status, missing)
                return {
                    'success': True,
                    'compliance_type': compliance_type,
                    'audit_status': audit_status,
                    'passed': passed,
                    'required_keys': required,
                    'missing_keys': missing,
                    'last_audit': now,
                }
            except sqlite3.Error as e:
                logger.error("执行合规审计失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 移动端平台管理
    # ------------------------------------------------------------------
    def register_mobile_platform(self, platform: str, features: Optional[List[str]] = None,
                                 download_url: str = '') -> Dict[str, Any]:
        """注册移动端平台。

        Args:
            platform: 平台标识，取值见 MOBILE_PLATFORMS。
            features: 平台特性列表。
            download_url: 下载地址。
        """
        if not platform:
            return {'success': False, 'error': 'platform 不能为空'}
        if platform not in self.MOBILE_PLATFORMS:
            return {'success': False, 'error': f'非法平台标识: {platform}，允许: {self.MOBILE_PLATFORMS}'}
        if features is None:
            features = []
        if not isinstance(features, list):
            return {'success': False, 'error': 'features 必须为列表'}

        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM architecture_mobile_platforms WHERE platform = ?', (platform,))
                existing = cursor.fetchone()
                if existing is not None:
                    cursor.execute(
                        'UPDATE architecture_mobile_platforms SET features = ?, download_url = ?, status = ? WHERE platform = ?',
                        (self._json_dumps(features), download_url, 'active', platform)
                    )
                    conn.commit()
                    logger.info("更新移动端平台: %s", platform)
                    return {'success': True, 'platform_id': existing['id'], 'platform': platform, 'action': 'updated'}
                cursor.execute(
                    'INSERT INTO architecture_mobile_platforms (platform, features, status, download_url, created_at) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (platform, self._json_dumps(features), 'active', download_url, self._now())
                )
                conn.commit()
                platform_id = cursor.lastrowid
                logger.info("注册移动端平台成功: %s (id=%s)", platform, platform_id)
                return {'success': True, 'platform_id': platform_id, 'platform': platform, 'action': 'created'}
            except sqlite3.Error as e:
                logger.error("注册移动端平台失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 汇总查询
    # ------------------------------------------------------------------
    def get_evolution_summary(self) -> Dict[str, Any]:
        """获取架构演进汇总（模块 / 计划 / 插件 / 监控 / 合规 / 移动端全维度统计）。"""
        with self._lock:
            conn = None
            try:
                conn = self._get_connection()
                cursor = conn.cursor()

                # 模块统计
                cursor.execute('SELECT COUNT(*) AS c FROM architecture_modules')
                total_modules = cursor.fetchone()['c']
                cursor.execute('SELECT module_type, COUNT(*) AS c FROM architecture_modules GROUP BY module_type')
                modules_by_type = {r['module_type']: r['c'] for r in cursor.fetchall()}
                cursor.execute('SELECT status, COUNT(*) AS c FROM architecture_modules GROUP BY status')
                modules_by_status = {r['status']: r['c'] for r in cursor.fetchall()}
                cursor.execute('SELECT AVG(health_score) AS avg_score FROM architecture_modules')
                avg_health = cursor.fetchone()['avg_score'] or 100

                # 计划统计
                cursor.execute('SELECT COUNT(*) AS c FROM architecture_evolution_plans')
                total_plans = cursor.fetchone()['c']
                cursor.execute(
                    'SELECT COUNT(*) AS c FROM architecture_evolution_plans WHERE status NOT IN (?, ?)',
                    ('completed', 'cancelled')
                )
                active_plans = cursor.fetchone()['c']
                cursor.execute('SELECT direction, COUNT(*) AS c FROM architecture_evolution_plans GROUP BY direction')
                plans_by_direction = {r['direction']: r['c'] for r in cursor.fetchall()}
                cursor.execute('SELECT status, COUNT(*) AS c FROM architecture_evolution_plans GROUP BY status')
                plans_by_status = {r['status']: r['c'] for r in cursor.fetchall()}

                # 插件统计
                cursor.execute('SELECT COUNT(*) AS c FROM architecture_plugins')
                total_plugins = cursor.fetchone()['c']
                cursor.execute('SELECT COUNT(*) AS c FROM architecture_plugins WHERE is_active = 1')
                active_plugins = cursor.fetchone()['c']

                # 监控统计
                cursor.execute('SELECT COUNT(*) AS c FROM architecture_monitoring')
                total_monitoring = cursor.fetchone()['c']
                cursor.execute(
                    'SELECT COUNT(*) AS c FROM (SELECT status FROM architecture_monitoring '
                    'ORDER BY id DESC LIMIT 50) WHERE status IN (?, ?)',
                    ('critical', 'warning')
                )
                recent_alerts = cursor.fetchone()['c']

                # 合规统计
                cursor.execute('SELECT compliance_type, audit_status FROM architecture_security_compliance')
                compliance_rows = cursor.fetchall()
                compliance_by_status: Dict[str, int] = {}
                for r in compliance_rows:
                    compliance_by_status[r['audit_status']] = compliance_by_status.get(r['audit_status'], 0) + 1

                # 移动端统计
                cursor.execute('SELECT platform, status FROM architecture_mobile_platforms')
                mobile_rows = cursor.fetchall()
                mobile_by_status: Dict[str, int] = {}
                for r in mobile_rows:
                    mobile_by_status[r['status']] = mobile_by_status.get(r['status'], 0) + 1

                return {
                    'success': True,
                    'generated_at': self._now(),
                    'modules': {
                        'total': total_modules,
                        'by_type': modules_by_type,
                        'by_status': modules_by_status,
                        'avg_health_score': round(avg_health, 1),
                    },
                    'plans': {
                        'total': total_plans,
                        'active': active_plans,
                        'by_direction': plans_by_direction,
                        'by_status': plans_by_status,
                    },
                    'plugins': {'total': total_plugins, 'active': active_plugins},
                    'monitoring': {'total_records': total_monitoring, 'recent_alerts': recent_alerts},
                    'compliance': {'total': len(compliance_rows), 'by_status': compliance_by_status},
                    'mobile': {'total': len(mobile_rows), 'by_status': mobile_by_status},
                    'directions': self.EVOLUTION_DIRECTIONS,
                }
            except sqlite3.Error as e:
                logger.error("获取架构演进汇总失败: %s", e)
                return {'success': False, 'error': str(e)}
            finally:
                if conn is not None:
                    conn.close()

    # ------------------------------------------------------------------
    # 六大架构方向落地：一键播种默认架构资产
    # ------------------------------------------------------------------
    def seed_default_architecture(self) -> Dict[str, Any]:
        """一键播种六大架构方向的默认模块、计划、合规与移动端平台。

        用于在新环境快速建立架构演进基线，便于演示与进一步定制。
        """
        results: Dict[str, Any] = {'success': True, 'modules': [], 'plans': [], 'compliance': [], 'mobile': []}

        # 1. 微服务化模块 + API 网关 + 多租户核心
        for name, mtype, desc, stack in (self.DEFAULT_MICROSERVICES + self.DEFAULT_API_GATEWAY
                                         + self.DEFAULT_MULTI_TENANT):
            res = self.register_module(name, mtype, desc, stack)
            results['modules'].append(res)

        # 2. 默认演进计划（覆盖六大方向）
        for plan_name, direction, desc, phases in self.DEFAULT_PLANS:
            res = self.create_evolution_plan(plan_name, direction, desc, phases)
            results['plans'].append(res)

        # 3. 默认安全合规配置
        for ctype, config in self.DEFAULT_COMPLIANCE:
            res = self.setup_compliance(ctype, config)
            results['compliance'].append(res)

        # 4. 默认移动端平台
        for platform, features, url in self.DEFAULT_MOBILE_PLATFORMS:
            res = self.register_mobile_platform(platform, features, url)
            results['mobile'].append(res)

        logger.info("六大架构方向默认资产播种完成")
        return results


# 全局服务实例
architecture_evolution_service = ArchitectureEvolutionService()


if __name__ == '__main__':
    # 简单自测：播种默认架构并输出汇总
    svc = architecture_evolution_service
    svc.seed_default_architecture()
    print(json.dumps(svc.get_evolution_summary(), ensure_ascii=False, indent=2))
    print(json.dumps(svc.check_health('user_service'), ensure_ascii=False, indent=2))
    if svc.get_active_plans().get('plans'):
        first_plan = svc.get_active_plans()['plans'][0]
        print(json.dumps(svc.advance_plan_phase(first_plan['id']), ensure_ascii=False, indent=2))
    print(json.dumps(svc.audit_compliance('zero_trust'), ensure_ascii=False, indent=2))
