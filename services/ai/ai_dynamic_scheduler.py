#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI员工动态调度中间件服务 (AI Dynamic Scheduler Middleware)
==========================================================
用于MTSCOS AI项目，实现AI员工与系统功能的深度协同、动态调度、主动性和积极性。

核心能力：
    1. AI调度任务的创建、执行与生命周期管理
    2. AI员工任务分配与负载均衡
    3. AI主动行为触发与记录
    4. 系统集成配置与数据同步
    5. 员工绩效评估与调度仪表盘统计
    6. 自动调度（基于负载/绩效/优先级的智能派单）
    7. 主动性扫描（主动发现系统问题并触发处理）

线程安全：使用 threading.RLock 保证并发安全。
"""

import os
import json
import sqlite3
import threading
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logger = logging.getLogger("ai_dynamic_scheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        )
    )
    logger.addHandler(_handler)


# ---------------------------------------------------------------------------
# 主动行为类型常量
# ---------------------------------------------------------------------------
PROACTIVE_ACTION_TYPES = (
    "system_health_check",        # 系统健康检查
    "performance_optimization",   # 性能优化建议
    "security_scan",              # 安全扫描
    "data_backup",                # 数据备份
    "anomaly_detection",          # 异常检测
    "user_assistance",            # 用户协助
    "resource_optimization",      # 资源优化
    "predictive_maintenance",     # 预测性维护
)

# ---------------------------------------------------------------------------
# 任务类型 -> 推荐AI员工角色映射（用于 auto_dispatch 智能派单）
# 每种任务类型对应一组候选员工ID（可按实际部署扩充）
# ---------------------------------------------------------------------------
DEFAULT_TASK_EMPLOYEE_MAP: Dict[str, List[str]] = {
    "code_review": ["ai_architect_01", "ai_engineer_01"],
    "data_analysis": ["ai_analyst_01", "ai_engineer_01"],
    "report_generation": ["ai_analyst_01", "ai_assistant_01"],
    "system_monitoring": ["ai_ops_01", "ai_engineer_01"],
    "security_audit": ["ai_security_01", "ai_ops_01"],
    "user_support": ["ai_assistant_01", "ai_analyst_01"],
    "deployment": ["ai_ops_01", "ai_architect_01"],
    "optimization": ["ai_architect_01", "ai_engineer_01"],
    "default": ["ai_assistant_01", "ai_engineer_01", "ai_analyst_01"],
}


class AIDynamicScheduler:
    """
    AI员工动态调度中间件

    提供调度任务管理、AI员工分配、主动行为触发、系统集成、
    绩效评估、自动调度与主动性扫描等能力。
    """

    DB_PATH = "app.db"

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path: str = db_path or self.DB_PATH
        # RLock 可重入，避免同线程递归调用死锁
        self._lock = threading.RLock()
        self._init_db()
        logger.info("AIDynamicScheduler 初始化完成, db=%s", self.db_path)

    # ------------------------------------------------------------------
    # 数据库相关
    # ------------------------------------------------------------------
    def _get_connection(self) -> sqlite3.Connection:
        """获取 SQLite 连接（数据库路径为 app.db）"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # 启用外键约束
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        """初始化所有数据库表"""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # 1. AI调度任务表
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_scheduled_tasks (
                        task_id            TEXT PRIMARY KEY,
                        task_name          TEXT NOT NULL,
                        task_type          TEXT NOT NULL,
                        target_module      TEXT NOT NULL,
                        target_action      TEXT NOT NULL,
                        priority           INTEGER DEFAULT 5,
                        status             TEXT DEFAULT 'pending',
                        ai_employee_id     TEXT,
                        trigger_type       TEXT DEFAULT 'manual',
                        trigger_condition  TEXT,
                        schedule_cron      TEXT,
                        last_run           TEXT,
                        next_run           TEXT,
                        result_summary     TEXT,
                        created_at         TEXT DEFAULT (datetime('now','localtime')),
                        updated_at         TEXT DEFAULT (datetime('now','localtime'))
                    )
                    """
                )

                # 2. AI员工任务分配表
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_employee_assignments (
                        assignment_id      TEXT PRIMARY KEY,
                        employee_id        TEXT NOT NULL,
                        task_id            TEXT NOT NULL,
                        role               TEXT DEFAULT 'secondary',
                        assigned_at        TEXT DEFAULT (datetime('now','localtime')),
                        status             TEXT DEFAULT 'active',
                        performance_score  REAL DEFAULT 0.0,
                        FOREIGN KEY (task_id) REFERENCES ai_scheduled_tasks(task_id) ON DELETE CASCADE
                    )
                    """
                )

                # 3. AI主动行为记录表
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_proactive_actions (
                        action_id          TEXT PRIMARY KEY,
                        employee_id        TEXT NOT NULL,
                        action_type        TEXT NOT NULL,
                        trigger_reason     TEXT,
                        target_system      TEXT,
                        action_description TEXT,
                        impact_level       TEXT DEFAULT 'low',
                        status             TEXT DEFAULT 'pending',
                        result             TEXT,
                        created_at         TEXT DEFAULT (datetime('now','localtime'))
                    )
                    """
                )

                # 4. AI系统集成配置表
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_system_integration (
                        integration_id     TEXT PRIMARY KEY,
                        employee_id        TEXT NOT NULL,
                        system_module      TEXT NOT NULL,
                        sync_frequency     TEXT DEFAULT 'hourly',
                        last_sync          TEXT,
                        sync_status        TEXT DEFAULT 'idle',
                        data_flow_direction TEXT DEFAULT 'bidirectional',
                        adapter_config     TEXT,
                        created_at         TEXT DEFAULT (datetime('now','localtime')),
                        updated_at         TEXT DEFAULT (datetime('now','localtime'))
                    )
                    """
                )

                # 任务执行日志表（用于 get_task_logs）
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_task_logs (
                        log_id             INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id            TEXT,
                        employee_id        TEXT,
                        action             TEXT,
                        status             TEXT,
                        message            TEXT,
                        created_at         TEXT DEFAULT (datetime('now','localtime'))
                    )
                    """
                )

                # 常用索引
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON ai_scheduled_tasks(status)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_module ON ai_scheduled_tasks(target_module)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tasks_priority ON ai_scheduled_tasks(priority)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_assign_emp ON ai_employee_assignments(employee_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_assign_task ON ai_employee_assignments(task_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_proactive_emp ON ai_proactive_actions(employee_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_integration_emp ON ai_system_integration(employee_id)"
                )

                conn.commit()
                logger.debug("数据库表初始化完成")
            except Exception as e:
                conn.rollback()
                logger.error("初始化数据库失败: %s", e, exc_info=True)
                raise
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _gen_id(prefix: str = "") -> str:
        return f"{prefix}{uuid.uuid4().hex[:16]}"

    def _log_task(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        employee_id: Optional[str],
        action: str,
        status: str,
        message: str,
    ) -> None:
        """记录任务执行日志（内部方法）"""
        try:
            conn.execute(
                """
                INSERT INTO ai_task_logs
                    (task_id, employee_id, action, status, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, employee_id, action, status, message),
            )
        except Exception as e:
            logger.warning("写入任务日志失败: %s", e)

    # ------------------------------------------------------------------
    # 调度任务管理
    # ------------------------------------------------------------------
    def schedule_task(
        self,
        task_name: str,
        task_type: str,
        target_module: str,
        target_action: str,
        priority: int = 5,
        trigger_type: str = "manual",
        trigger_condition: Optional[Dict[str, Any]] = None,
        schedule_cron: Optional[str] = None,
        ai_employee_id: Optional[str] = None,
        next_run: Optional[str] = None,
    ) -> Optional[str]:
        """
        创建调度任务

        Args:
            task_name: 任务名称
            task_type: 任务类型
            target_module: 目标模块
            target_action: 目标动作
            priority: 优先级 1-10（1为最高）
            trigger_type: 触发类型 manual/scheduled/event_driven/proactive
            trigger_condition: 触发条件（dict，将序列化为 JSON）
            schedule_cron: 调度 CRON 表达式
            ai_employee_id: 指定AI员工（可选）
            next_run: 下次执行时间（可选，ISO 字符串）

        Returns:
            task_id
        """
        if not task_name or not task_type or not target_module or not target_action:
            logger.error("参数缺失: task_name/task_type/target_module/target_action 均为必填")
            return None

        if trigger_type not in ("manual", "scheduled", "event_driven", "proactive"):
            logger.error("非法 trigger_type: %s", trigger_type)
            return None

        task_id = self._gen_id("task_")
        trigger_cond_json = json.dumps(trigger_condition, ensure_ascii=False) if trigger_condition else None
        if next_run is None and trigger_type == "scheduled":
            next_run = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO ai_scheduled_tasks
                        (task_id, task_name, task_type, target_module, target_action,
                         priority, status, ai_employee_id, trigger_type, trigger_condition,
                         schedule_cron, next_run)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id, task_name, task_type, target_module, target_action,
                        int(priority), "pending", ai_employee_id, trigger_type, trigger_cond_json,
                        schedule_cron, next_run,
                    ),
                )
                self._log_task(conn, task_id, ai_employee_id, "schedule_task", "created",
                               f"任务已创建: {task_name}")
                conn.commit()
                logger.info("调度任务已创建 task_id=%s name=%s type=%s", task_id, task_name, task_type)
                return task_id
            except Exception as e:
                conn.rollback()
                logger.error("创建调度任务失败: %s", e, exc_info=True)
                return None
            finally:
                conn.close()

    def execute_task(self, task_id: str) -> bool:
        """
        执行调度任务

        状态流转：pending -> running -> completed/failed
        """
        if not task_id:
            return False

        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM ai_scheduled_tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if not row:
                    logger.warning("任务不存在: %s", task_id)
                    return False

                if row["status"] in ("running", "completed"):
                    logger.warning("任务状态不允许执行: %s (status=%s)", task_id, row["status"])
                    return False

                employee_id = row["ai_employee_id"]
                # 置为运行中
                conn.execute(
                    "UPDATE ai_scheduled_tasks SET status='running', updated_at=? WHERE task_id=?",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id),
                )
                self._log_task(conn, task_id, employee_id, "execute_task", "running",
                               f"开始执行任务: {row['task_name']}")
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error("任务执行启动失败: %s", e, exc_info=True)
                return False
            finally:
                conn.close()

        # 在锁外执行实际任务（避免长时间持锁）
        success = False
        result_summary = ""
        try:
            success, result_summary = self._invoke_target_action(
                row["target_module"], row["target_action"], dict(row)
            )
        except Exception as e:
            result_summary = f"执行异常: {e}"
            logger.error("任务执行异常 task_id=%s: %s", task_id, e, exc_info=True)

        status = "completed" if success else "failed"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE ai_scheduled_tasks
                       SET status=?, last_run=?, result_summary=?, updated_at=?
                     WHERE task_id=?
                    """,
                    (status, now, result_summary, now, task_id),
                )
                self._log_task(conn, task_id, employee_id, "execute_task", status, result_summary)
                conn.commit()
                logger.info("任务执行完成 task_id=%s status=%s", task_id, status)
                return success
            except Exception as e:
                conn.rollback()
                logger.error("更新任务执行结果失败: %s", e, exc_info=True)
                return False
            finally:
                conn.close()

    def _invoke_target_action(
        self, target_module: str, target_action: str, task: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        实际调用目标模块/动作。

        当前以模拟方式执行（中间件层），返回 True 与执行摘要。
        实际部署时可通过适配器/反射调用具体业务模块。
        """
        # 模拟执行：随机延迟与成功
        import time
        time.sleep(0.05)
        summary = (
            f"[模拟执行] 模块={target_module}, 动作={target_action}, "
            f"任务={task.get('task_name')}"
        )
        logger.debug(summary)
        return True, summary

    def get_pending_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取待执行任务（按优先级升序、创建时间升序）"""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_scheduled_tasks
                     WHERE status = 'pending'
                     ORDER BY priority ASC, created_at ASC
                     LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_tasks_by_module(self, module_name: str) -> List[Dict[str, Any]]:
        """获取某模块的任务"""
        if not module_name:
            return []
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_scheduled_tasks
                     WHERE target_module = ?
                     ORDER BY created_at DESC
                    """,
                    (module_name,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # AI员工任务分配
    # ------------------------------------------------------------------
    def assign_employee(
        self, task_id: str, employee_id: str, role: str = "secondary"
    ) -> Optional[str]:
        """分配AI员工到任务"""
        if not task_id or not employee_id:
            logger.error("task_id 与 employee_id 必填")
            return None
        if role not in ("primary", "secondary", "observer"):
            logger.error("非法 role: %s", role)
            return None

        assignment_id = self._gen_id("asg_")
        with self._lock:
            conn = self._get_connection()
            try:
                # 检查任务存在
                row = conn.execute(
                    "SELECT task_id FROM ai_scheduled_tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if not row:
                    logger.warning("任务不存在，无法分配: %s", task_id)
                    return None

                conn.execute(
                    """
                    INSERT INTO ai_employee_assignments
                        (assignment_id, employee_id, task_id, role, status, performance_score)
                    VALUES (?, ?, ?, ?, 'active', 0.0)
                    """,
                    (assignment_id, employee_id, task_id, role),
                )
                # 若指定为主负责，则同步更新任务表的 ai_employee_id
                if role == "primary":
                    conn.execute(
                        "UPDATE ai_scheduled_tasks SET ai_employee_id=?, updated_at=? WHERE task_id=?",
                        (employee_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task_id),
                    )
                self._log_task(conn, task_id, employee_id, "assign_employee", "assigned",
                               f"分配员工 {employee_id} 角色={role}")
                conn.commit()
                logger.info("员工分配成功 task=%s employee=%s role=%s", task_id, employee_id, role)
                return assignment_id
            except Exception as e:
                conn.rollback()
                logger.error("分配员工失败: %s", e, exc_info=True)
                return None
            finally:
                conn.close()

    def get_employee_assignments(self, employee_id: str) -> List[Dict[str, Any]]:
        """获取员工任务分配"""
        if not employee_id:
            return []
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT a.*, t.task_name, t.task_type, t.target_module,
                           t.target_action, t.priority, t.status AS task_status
                      FROM ai_employee_assignments a
                      LEFT JOIN ai_scheduled_tasks t ON a.task_id = t.task_id
                     WHERE a.employee_id = ?
                     ORDER BY a.assigned_at DESC
                    """,
                    (employee_id,),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 主动行为
    # ------------------------------------------------------------------
    def trigger_proactive_action(
        self,
        employee_id: str,
        action_type: str,
        trigger_reason: str,
        target_system: str,
        action_description: str,
        impact_level: str = "low",
    ) -> Optional[str]:
        """触发主动行为"""
        if not employee_id or not action_type:
            logger.error("employee_id 与 action_type 必填")
            return None
        if action_type not in PROACTIVE_ACTION_TYPES:
            logger.error("非法 action_type: %s", action_type)
            return None
        if impact_level not in ("low", "medium", "high", "critical"):
            logger.error("非法 impact_level: %s", impact_level)
            return None

        action_id = self._gen_id("act_")
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO ai_proactive_actions
                        (action_id, employee_id, action_type, trigger_reason,
                         target_system, action_description, impact_level, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'running')
                    """,
                    (action_id, employee_id, action_type, trigger_reason,
                     target_system, action_description, impact_level),
                )
                conn.commit()
                logger.info("主动行为已触发 action_id=%s employee=%s type=%s",
                            action_id, employee_id, action_type)

                # 模拟执行主动行为并回写结果
                result_text = self._execute_proactive_action(
                    action_type, target_system, action_description
                )
                conn.execute(
                    """
                    UPDATE ai_proactive_actions
                       SET status='completed', result=?
                     WHERE action_id=?
                    """,
                    (result_text, action_id),
                )
                conn.commit()
                return action_id
            except Exception as e:
                conn.rollback()
                logger.error("触发主动行为失败: %s", e, exc_info=True)
                return None
            finally:
                conn.close()

    def _execute_proactive_action(
        self, action_type: str, target_system: str, description: str
    ) -> str:
        """实际执行主动行为（模拟）"""
        import time
        time.sleep(0.03)
        return f"[完成] {action_type} on {target_system}: {description}"

    def get_proactive_actions(
        self, employee_id: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """获取主动行为记录"""
        with self._lock:
            conn = self._get_connection()
            try:
                if employee_id:
                    rows = conn.execute(
                        """
                        SELECT * FROM ai_proactive_actions
                         WHERE employee_id = ?
                         ORDER BY created_at DESC
                         LIMIT ?
                        """,
                        (employee_id, int(limit)),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM ai_proactive_actions
                         ORDER BY created_at DESC
                         LIMIT ?
                        """,
                        (int(limit),),
                    ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 系统集成
    # ------------------------------------------------------------------
    def register_system_integration(
        self,
        employee_id: str,
        system_module: str,
        sync_frequency: str = "hourly",
        data_flow_direction: str = "bidirectional",
        adapter_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """注册系统集成配置"""
        if not employee_id or not system_module:
            logger.error("employee_id 与 system_module 必填")
            return None
        if data_flow_direction not in ("bidirectional", "inbound", "outbound"):
            logger.error("非法 data_flow_direction: %s", data_flow_direction)
            return None

        integration_id = self._gen_id("int_")
        adapter_json = json.dumps(adapter_config, ensure_ascii=False) if adapter_config else None
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO ai_system_integration
                        (integration_id, employee_id, system_module, sync_frequency,
                         sync_status, data_flow_direction, adapter_config)
                    VALUES (?, ?, ?, ?, 'idle', ?, ?)
                    """,
                    (integration_id, employee_id, system_module,
                     sync_frequency, data_flow_direction, adapter_json),
                )
                conn.commit()
                logger.info("系统集成已注册 integration_id=%s module=%s",
                            integration_id, system_module)
                return integration_id
            except Exception as e:
                conn.rollback()
                logger.error("注册系统集成失败: %s", e, exc_info=True)
                return None
            finally:
                conn.close()

    def sync_system_data(self, integration_id: str) -> bool:
        """同步系统数据"""
        if not integration_id:
            return False
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM ai_system_integration WHERE integration_id = ?",
                    (integration_id,),
                ).fetchone()
                if not row:
                    logger.warning("集成配置不存在: %s", integration_id)
                    return False

                conn.execute(
                    "UPDATE ai_system_integration SET sync_status='syncing' WHERE integration_id=?",
                    (integration_id,),
                )
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error("同步启动失败: %s", e, exc_info=True)
                return False
            finally:
                conn.close()

        # 模拟同步过程
        import time
        time.sleep(0.05)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        success = True

        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE ai_system_integration
                       SET sync_status=?, last_sync=?, updated_at=?
                     WHERE integration_id=?
                    """,
                    ("success" if success else "failed", now, now, integration_id),
                )
                conn.commit()
                logger.info("数据同步完成 integration_id=%s status=%s",
                            integration_id, "success" if success else "failed")
                return success
            except Exception as e:
                conn.rollback()
                logger.error("回写同步状态失败: %s", e, exc_info=True)
                return False
            finally:
                conn.close()

    def get_system_integrations(
        self, employee_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取系统集成配置"""
        with self._lock:
            conn = self._get_connection()
            try:
                if employee_id:
                    rows = conn.execute(
                        """
                        SELECT * FROM ai_system_integration
                         WHERE employee_id = ?
                         ORDER BY created_at DESC
                        """,
                        (employee_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM ai_system_integration ORDER BY created_at DESC"
                    ).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    if d.get("adapter_config"):
                        try:
                            d["adapter_config"] = json.loads(d["adapter_config"])
                        except (ValueError, TypeError):
                            pass
                    result.append(d)
                return result
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 绩效评估
    # ------------------------------------------------------------------
    def evaluate_employee_performance(self, employee_id: str) -> Dict[str, Any]:
        """
        评估员工绩效

        指标：
            - 完成任务数
            - 失败任务数
            - 完成率
            - 主动行为数
            - 平均分配绩效评分
            - 综合绩效分（0-100）
        """
        if not employee_id:
            return {"error": "employee_id required"}

        with self._lock:
            conn = self._get_connection()
            try:
                # 关联任务统计
                stats_row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        SUM(CASE WHEN t.status='completed' THEN 1 ELSE 0 END) AS completed,
                        SUM(CASE WHEN t.status='failed' THEN 1 ELSE 0 END) AS failed,
                        SUM(CASE WHEN t.status='running' THEN 1 ELSE 0 END) AS running,
                        AVG(a.performance_score) AS avg_score
                      FROM ai_employee_assignments a
                      LEFT JOIN ai_scheduled_tasks t ON a.task_id = t.task_id
                     WHERE a.employee_id = ?
                    """,
                    (employee_id,),
                ).fetchone()

                proactive_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM ai_proactive_actions WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()

                integration_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM ai_system_integration WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()

                total = stats_row["total"] or 0
                completed = stats_row["completed"] or 0
                failed = stats_row["failed"] or 0
                running = stats_row["running"] or 0
                avg_score = stats_row["avg_score"] or 0.0
                proactive_cnt = proactive_row["cnt"] or 0
                integration_cnt = integration_row["cnt"] or 0

                completion_rate = (completed / total) if total > 0 else 0.0

                # 综合绩效分：完成率(60%) + 主动行为(20%) + 平均评分(20%)
                proactive_factor = min(proactive_cnt / 10.0, 1.0)
                score_factor = min(float(avg_score) / 100.0, 1.0) if avg_score else 0.0
                overall = round(
                    (completion_rate * 0.6 + proactive_factor * 0.2 + score_factor * 0.2) * 100,
                    2,
                )

                # 回写最近一条分配的绩效分（便于后续派单参考）
                if total > 0:
                    conn.execute(
                        """
                        UPDATE ai_employee_assignments
                           SET performance_score = ?
                         WHERE employee_id = ?
                           AND assignment_id = (
                               SELECT assignment_id FROM ai_employee_assignments
                                WHERE employee_id = ?
                                ORDER BY assigned_at DESC LIMIT 1
                           )
                        """,
                        (overall, employee_id, employee_id),
                    )
                    conn.commit()

                return {
                    "employee_id": employee_id,
                    "total_tasks": total,
                    "completed_tasks": completed,
                    "failed_tasks": failed,
                    "running_tasks": running,
                    "completion_rate": round(completion_rate, 4),
                    "proactive_actions": proactive_cnt,
                    "system_integrations": integration_cnt,
                    "avg_assignment_score": round(float(avg_score), 2),
                    "overall_performance": overall,
                    "evaluated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            except Exception as e:
                conn.rollback()
                logger.error("绩效评估失败: %s", e, exc_info=True)
                return {"error": str(e)}
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 仪表盘 & 日志
    # ------------------------------------------------------------------
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """获取调度仪表盘统计"""
        with self._lock:
            conn = self._get_connection()
            try:
                pending = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_scheduled_tasks WHERE status='pending'"
                ).fetchone()["c"]
                running = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_scheduled_tasks WHERE status='running'"
                ).fetchone()["c"]
                today = datetime.now().strftime("%Y-%m-%d")
                completed_today = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM ai_scheduled_tasks
                     WHERE status='completed' AND substr(last_run,1,10)=?
                    """,
                    (today,),
                ).fetchone()["c"]
                proactive = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_proactive_actions"
                ).fetchone()["c"]
                active_employees = conn.execute(
                    """
                    SELECT COUNT(DISTINCT employee_id) AS c
                      FROM ai_employee_assignments
                     WHERE status='active'
                    """
                ).fetchone()["c"]
                integrations = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_system_integration"
                ).fetchone()["c"]
                failed_today = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM ai_scheduled_tasks
                     WHERE status='failed' AND substr(last_run,1,10)=?
                    """,
                    (today,),
                ).fetchone()["c"]

                return {
                    "pending_tasks": pending,
                    "running_tasks": running,
                    "completed_today": completed_today,
                    "failed_today": failed_today,
                    "proactive_actions": proactive,
                    "active_employees": active_employees,
                    "system_integrations": integrations,
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            finally:
                conn.close()

    def get_task_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取任务执行日志"""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT l.*, t.task_name
                      FROM ai_task_logs l
                      LEFT JOIN ai_scheduled_tasks t ON l.task_id = t.task_id
                     ORDER BY l.created_at DESC, l.log_id DESC
                     LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 自动调度
    # ------------------------------------------------------------------
    def auto_dispatch(self) -> Dict[str, Any]:
        """
        自动调度：自动分配待执行任务给最合适的AI员工。

        调度策略：
            1. 拉取所有 pending 任务，按优先级排序
            2. 对每个任务，根据任务类型匹配候选AI员工
            3. 在候选员工中，根据 (当前负载, 历史绩效) 加权打分
               - 负载越低越好（权重 0.5）
               - 绩效越高越好（权重 0.5）
            4. 选择得分最高的员工作为 primary 分配
            5. 分配后将任务状态保持 pending，等待 execute_task 调用

        Returns:
            统计信息字典
        """
        dispatched = 0
        skipped = 0
        details: List[Dict[str, Any]] = []

        with self._lock:
            conn = self._get_connection()
            try:
                pending_rows = conn.execute(
                    """
                    SELECT * FROM ai_scheduled_tasks
                     WHERE status = 'pending'
                       AND (ai_employee_id IS NULL OR ai_employee_id = '')
                     ORDER BY priority ASC, created_at ASC
                    """
                ).fetchall()

                for row in pending_rows:
                    task = dict(row)
                    task_type = task["task_type"]
                    candidates = DEFAULT_TASK_EMPLOYEE_MAP.get(
                        task_type, DEFAULT_TASK_EMPLOYEE_MAP["default"]
                    )

                    # 计算每个候选员工的负载与绩效
                    scored: List[Tuple[str, float, int, float]] = []
                    for emp_id in candidates:
                        load = conn.execute(
                            """
                            SELECT COUNT(*) AS c FROM ai_employee_assignments
                             WHERE employee_id = ? AND status='active'
                            """,
                            (emp_id,),
                        ).fetchone()["c"]

                        perf_row = conn.execute(
                            """
                            SELECT AVG(performance_score) AS avg FROM ai_employee_assignments
                             WHERE employee_id = ?
                            """,
                            (emp_id,),
                        ).fetchone()
                        avg_perf = float(perf_row["avg"] or 0.0)

                        # 加权得分：负载越低得分越高；绩效越高得分越高
                        # 负载归一化：1 / (1 + load)
                        load_score = 1.0 / (1.0 + load)
                        # 绩效归一化到 0-1
                        perf_score = min(avg_perf / 100.0, 1.0)
                        total_score = load_score * 0.5 + perf_score * 0.5
                        scored.append((emp_id, total_score, load, avg_perf))

                    if not scored:
                        skipped += 1
                        details.append({
                            "task_id": task["task_id"],
                            "task_name": task["task_name"],
                            "status": "skipped_no_candidate",
                        })
                        continue

                    # 选择得分最高者
                    scored.sort(key=lambda x: x[1], reverse=True)
                    best_emp, best_score, best_load, best_perf = scored[0]

                    assignment_id = self._gen_id("asg_")
                    conn.execute(
                        """
                        INSERT INTO ai_employee_assignments
                            (assignment_id, employee_id, task_id, role, status, performance_score)
                        VALUES (?, ?, ?, 'primary', 'active', ?)
                        """,
                        (assignment_id, best_emp, task["task_id"], best_perf),
                    )
                    conn.execute(
                        """
                        UPDATE ai_scheduled_tasks
                           SET ai_employee_id=?, updated_at=?
                         WHERE task_id=?
                        """,
                        (best_emp, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task["task_id"]),
                    )
                    self._log_task(
                        conn, task["task_id"], best_emp, "auto_dispatch", "dispatched",
                        f"自动派单给 {best_emp} (score={best_score:.3f}, load={best_load})",
                    )
                    dispatched += 1
                    details.append({
                        "task_id": task["task_id"],
                        "task_name": task["task_name"],
                        "task_type": task_type,
                        "assigned_employee": best_emp,
                        "score": round(best_score, 4),
                        "current_load": best_load,
                        "avg_performance": round(best_perf, 2),
                    })

                conn.commit()
                logger.info("自动调度完成: dispatched=%d skipped=%d", dispatched, skipped)
                return {
                    "dispatched": dispatched,
                    "skipped": skipped,
                    "details": details,
                    "executed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            except Exception as e:
                conn.rollback()
                logger.error("自动调度失败: %s", e, exc_info=True)
                return {"error": str(e), "dispatched": 0, "skipped": skipped, "details": details}
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 主动性扫描
    # ------------------------------------------------------------------
    def proactive_scan(self) -> Dict[str, Any]:
        """
        主动性扫描：扫描系统状态，主动发现需要处理的问题并触发主动行为。

        扫描维度：
            - 系统健康检查（待执行任务堆积、失败任务激增）
            - 异常检测（最近失败任务）
            - 数据备份（提醒未同步的集成）
            - 资源优化（高负载员工识别）
            - 安全扫描（默认周期触发）

        Returns:
            扫描结果摘要
        """
        triggered: List[Dict[str, Any]] = []
        scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().strftime("%Y-%m-%d")

        with self._lock:
            conn = self._get_connection()
            try:
                # 1. 待执行任务堆积检测
                pending_cnt = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_scheduled_tasks WHERE status='pending'"
                ).fetchone()["c"]
                if pending_cnt > 20:
                    action_id = self._gen_id("act_")
                    conn.execute(
                        """
                        INSERT INTO ai_proactive_actions
                            (action_id, employee_id, action_type, trigger_reason, target_system,
                             action_description, impact_level, status, result)
                        VALUES (?, 'ai_ops_01', 'anomaly_detection',
                                ?, 'scheduler',
                                ?, 'high', 'completed', ?)
                        """,
                        (
                            action_id,
                            f"待执行任务堆积: {pending_cnt}",
                            f"建议立即执行 auto_dispatch，当前堆积 {pending_cnt} 个任务",
                            f"已记录并建议处理，pending={pending_cnt}",
                        ),
                    )
                    triggered.append({
                        "action_type": "anomaly_detection",
                        "reason": f"pending tasks overflow: {pending_cnt}",
                        "action_id": action_id,
                    })

                # 2. 今日失败任务检测
                failed_today = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM ai_scheduled_tasks
                     WHERE status='failed' AND substr(last_run,1,10)=?
                    """,
                    (today,),
                ).fetchone()["c"]
                if failed_today > 0:
                    action_id = self._gen_id("act_")
                    conn.execute(
                        """
                        INSERT INTO ai_proactive_actions
                            (action_id, employee_id, action_type, trigger_reason, target_system,
                             action_description, impact_level, status, result)
                        VALUES (?, 'ai_security_01', 'security_scan',
                                ?, 'task_executor',
                                ?, 'medium', 'completed', ?)
                        """,
                        (
                            action_id,
                            f"今日失败任务 {failed_today} 个",
                            f"建议检查失败任务根因，可能存在异常或资源问题",
                            f"已识别 {failed_today} 个失败任务，建议人工复查",
                        ),
                    )
                    triggered.append({
                        "action_type": "security_scan",
                        "reason": f"failed tasks today: {failed_today}",
                        "action_id": action_id,
                    })

                # 3. 数据备份：检查长时间未同步的集成
                stale_integrations = conn.execute(
                    """
                    SELECT integration_id, employee_id, system_module, last_sync
                      FROM ai_system_integration
                     WHERE last_sync IS NULL
                        OR last_sync < ?
                    """,
                    ((datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S"),),
                ).fetchall()
                for it in stale_integrations:
                    action_id = self._gen_id("act_")
                    conn.execute(
                        """
                        INSERT INTO ai_proactive_actions
                            (action_id, employee_id, action_type, trigger_reason, target_system,
                             action_description, impact_level, status, result)
                        VALUES (?, ?, 'data_backup',
                                ?, ?, ?, 'medium', 'completed', ?)
                        """,
                        (
                            action_id,
                            it["employee_id"],
                            f"集成 {it['system_module']} 超过24h未同步",
                            it["system_module"],
                            f"触发集成 {it['integration_id']} 数据同步",
                            f"建议执行 sync_system_data({it['integration_id']})",
                        ),
                    )
                    triggered.append({
                        "action_type": "data_backup",
                        "reason": f"stale integration: {it['system_module']}",
                        "integration_id": it["integration_id"],
                        "action_id": action_id,
                    })

                # 4. 资源优化：识别高负载员工
                overload_rows = conn.execute(
                    """
                    SELECT employee_id, COUNT(*) AS c
                      FROM ai_employee_assignments
                     WHERE status='active'
                     GROUP BY employee_id
                     HAVING c >= 5
                    """
                ).fetchall()
                for ol in overload_rows:
                    action_id = self._gen_id("act_")
                    conn.execute(
                        """
                        INSERT INTO ai_proactive_actions
                            (action_id, employee_id, action_type, trigger_reason, target_system,
                             action_description, impact_level, status, result)
                        VALUES (?, ?, 'resource_optimization',
                                ?, 'scheduler',
                                ?, 'medium', 'completed', ?)
                        """,
                        (
                            action_id,
                            ol["employee_id"],
                            f"员工 {ol['employee_id']} 活跃任务 {ol['c']} 个，负载过高",
                            f"建议将部分任务重新分配，减轻 {ol['employee_id']} 负载",
                            f"已建议负载均衡，load={ol['c']}",
                        ),
                    )
                    triggered.append({
                        "action_type": "resource_optimization",
                        "reason": f"overloaded employee: {ol['employee_id']} load={ol['c']}",
                        "action_id": action_id,
                    })

                # 5. 系统健康检查（每次扫描都记录）
                action_id = self._gen_id("act_")
                stats = self.get_dashboard_stats()
                conn.execute(
                    """
                    INSERT INTO ai_proactive_actions
                        (action_id, employee_id, action_type, trigger_reason, target_system,
                         action_description, impact_level, status, result)
                    VALUES (?, 'ai_ops_01', 'system_health_check',
                            ?, 'global',
                            ?, 'low', 'completed', ?)
                    """,
                    (
                        action_id,
                        f"定期健康检查 {scan_time}",
                        f"系统状态: pending={stats['pending_tasks']}, running={stats['running_tasks']}",
                        json.dumps(stats, ensure_ascii=False),
                    ),
                )
                triggered.append({
                    "action_type": "system_health_check",
                    "reason": "periodic health check",
                    "action_id": action_id,
                })

                conn.commit()
                logger.info("主动性扫描完成, 触发行为数=%d", len(triggered))
                return {
                    "scan_at": scan_time,
                    "triggered_count": len(triggered),
                    "triggered_actions": triggered,
                    "dashboard_snapshot": stats,
                }
            except Exception as e:
                conn.rollback()
                logger.error("主动性扫描失败: %s", e, exc_info=True)
                return {
                    "scan_at": scan_time,
                    "error": str(e),
                    "triggered_count": 0,
                    "triggered_actions": triggered,
                }
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 员工工作负载
    # ------------------------------------------------------------------
    def get_employee_workload(self, employee_id: str) -> Dict[str, Any]:
        """
        获取员工工作负载

        返回：活跃任务数、按状态分布、按角色分布、按模块分布、最近分配等
        """
        if not employee_id:
            return {"error": "employee_id required"}

        with self._lock:
            conn = self._get_connection()
            try:
                # 活跃任务数
                active_cnt = conn.execute(
                    """
                    SELECT COUNT(*) AS c FROM ai_employee_assignments
                     WHERE employee_id=? AND status='active'
                    """,
                    (employee_id,),
                ).fetchone()["c"]

                # 按任务状态分布
                status_rows = conn.execute(
                    """
                    SELECT t.status AS task_status, COUNT(*) AS c
                      FROM ai_employee_assignments a
                      LEFT JOIN ai_scheduled_tasks t ON a.task_id = t.task_id
                     WHERE a.employee_id = ?
                     GROUP BY t.status
                    """,
                    (employee_id,),
                ).fetchall()
                status_dist = {r["task_status"] or "unknown": r["c"] for r in status_rows}

                # 按角色分布
                role_rows = conn.execute(
                    """
                    SELECT role, COUNT(*) AS c
                      FROM ai_employee_assignments
                     WHERE employee_id = ?
                     GROUP BY role
                    """,
                    (employee_id,),
                ).fetchall()
                role_dist = {r["role"]: r["c"] for r in role_rows}

                # 按模块分布
                module_rows = conn.execute(
                    """
                    SELECT t.target_module, COUNT(*) AS c
                      FROM ai_employee_assignments a
                      LEFT JOIN ai_scheduled_tasks t ON a.task_id = t.task_id
                     WHERE a.employee_id = ?
                     GROUP BY t.target_module
                    """,
                    (employee_id,),
                ).fetchall()
                module_dist = {r["target_module"] or "unknown": r["c"] for r in module_rows}

                # 最近分配（5条）
                recent_rows = conn.execute(
                    """
                    SELECT a.assignment_id, a.task_id, a.role, a.status,
                           a.assigned_at, a.performance_score,
                           t.task_name, t.target_module, t.priority, t.status AS task_status
                      FROM ai_employee_assignments a
                      LEFT JOIN ai_scheduled_tasks t ON a.task_id = t.task_id
                     WHERE a.employee_id = ?
                     ORDER BY a.assigned_at DESC
                     LIMIT 5
                    """,
                    (employee_id,),
                ).fetchall()
                recent = [dict(r) for r in recent_rows]

                # 主动行为数
                proactive_cnt = conn.execute(
                    "SELECT COUNT(*) AS c FROM ai_proactive_actions WHERE employee_id=?",
                    (employee_id,),
                ).fetchone()["c"]

                # 负载等级
                if active_cnt == 0:
                    load_level = "idle"
                elif active_cnt <= 3:
                    load_level = "low"
                elif active_cnt <= 6:
                    load_level = "medium"
                elif active_cnt <= 10:
                    load_level = "high"
                else:
                    load_level = "overload"

                return {
                    "employee_id": employee_id,
                    "active_assignments": active_cnt,
                    "proactive_actions": proactive_cnt,
                    "load_level": load_level,
                    "status_distribution": status_dist,
                    "role_distribution": role_dist,
                    "module_distribution": module_dist,
                    "recent_assignments": recent,
                    "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------
ai_scheduler = AIDynamicScheduler()


if __name__ == "__main__":
    # 简单自检：初始化并打印仪表盘
    stats = ai_scheduler.get_dashboard_stats()
    print("Dashboard stats:", json.dumps(stats, ensure_ascii=False, indent=2))
