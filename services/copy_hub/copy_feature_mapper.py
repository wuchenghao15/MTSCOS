"""
文案-功能关联引擎 (Copy Feature Mapper)
CHMS-03: 文案与功能模块映射，联动审计

归档: flask-app/services/copy_hub/copy_feature_mapper.py
流程: §14 12步骤 STEP_7_EXECUTE
"""
import os
import sqlite3
from typing import Optional, List, Dict, Any


class CopyFeatureMapper:
    """文案-功能关联引擎"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base, 'app.db')
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def link_copy_to_feature(self, copy_key: str, feature_module: str,
                             service_file: str, route_path: str = '',
                             module_path: str = '') -> Dict[str, Any]:
        """关联文案到功能模块"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            # 查 copy_id
            cur.execute("SELECT copy_id FROM mt_copy_assets WHERE copy_key = ?", (copy_key,))
            row = cur.fetchone()
            if row is None:
                conn.close()
                return {'success': False, 'error': f'文案不存在: {copy_key}'}
            copy_id = row['copy_id']
            # 检查是否已存在映射
            cur.execute(
                "SELECT mapping_id FROM mt_copy_feature_mapping WHERE copy_id=? AND service_file=?",
                (copy_id, service_file)
            )
            existing = cur.fetchone()
            if existing:
                conn.close()
                return {'success': False, 'error': '映射已存在'}
            cur.execute(
                """INSERT INTO mt_copy_feature_mapping
                   (copy_id, feature_module, route_path, service_file, module_path)
                   VALUES (?, ?, ?, ?, ?)""",
                (copy_id, feature_module, route_path, service_file, module_path)
            )
            conn.commit()
            conn.close()
            return {'success': True, 'mapping_id': cur.lastrowid}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_copies_by_route(self, route_path: str) -> List[Dict[str, Any]]:
        """按路由获取关联文案"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT a.copy_key, a.copy_content, a.copy_type, m.service_file
                   FROM mt_copy_assets a
                   JOIN mt_copy_feature_mapping m ON a.copy_id = m.copy_id
                   WHERE m.route_path = ? AND a.status='ACTIVE'""",
                (route_path,)
            )
            rows = cur.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def get_copies_by_service(self, service_file: str) -> List[Dict[str, Any]]:
        """按服务文件获取关联文案"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT a.copy_key, a.copy_content, a.copy_type, m.route_path
                   FROM mt_copy_assets a
                   JOIN mt_copy_feature_mapping m ON a.copy_id = m.copy_id
                   WHERE m.service_file = ? AND a.status='ACTIVE'""",
                (service_file,)
            )
            rows = cur.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def get_features_by_copy(self, copy_key: str) -> List[Dict[str, Any]]:
        """获取文案关联的所有功能"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT m.feature_module, m.route_path, m.service_file, m.module_path
                   FROM mt_copy_feature_mapping m
                   JOIN mt_copy_assets a ON a.copy_id = m.copy_id
                   WHERE a.copy_key = ?""",
                (copy_key,)
            )
            rows = cur.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def audit_coverage(self) -> Dict[str, Any]:
        """审计文案-功能覆盖情况"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            # 总文案数
            cur.execute("SELECT COUNT(*) AS cnt FROM mt_copy_assets WHERE status='ACTIVE'")
            total = cur.fetchone()['cnt']
            # 有映射的文案数
            cur.execute(
                """SELECT COUNT(DISTINCT a.copy_id) AS cnt
                   FROM mt_copy_assets a
                   JOIN mt_copy_feature_mapping m ON a.copy_id = m.copy_id
                   WHERE a.status='ACTIVE'"""
            )
            linked = cur.fetchone()['cnt']
            # 未映射（孤立）文案数
            orphan = total - linked
            # 覆盖率
            coverage = (linked / total * 100) if total > 0 else 0
            conn.close()
            return {
                'total_copies': total,
                'linked_copies': linked,
                'orphan_copies': orphan,
                'coverage_percent': round(coverage, 2)
            }
        except Exception as e:
            return {'error': str(e)}

    def unlink_copy(self, copy_key: str, service_file: str = None) -> Dict[str, Any]:
        """解除文案-功能关联"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT copy_id FROM mt_copy_assets WHERE copy_key = ?", (copy_key,))
            row = cur.fetchone()
            if row is None:
                conn.close()
                return {'success': False, 'error': f'文案不存在: {copy_key}'}
            copy_id = row['copy_id']
            if service_file:
                cur.execute("DELETE FROM mt_copy_feature_mapping WHERE copy_id=? AND service_file=?",
                            (copy_id, service_file))
            else:
                cur.execute("DELETE FROM mt_copy_feature_mapping WHERE copy_id=?", (copy_id,))
            affected = cur.rowcount
            conn.commit()
            conn.close()
            return {'success': True, 'removed': affected}
        except Exception as e:
            return {'success': False, 'error': str(e)}
