"""
文案资产存储引擎 (Copy Asset Storage Engine)
CHMS-01: 文案入库/分类/标签/版本/多语言

归档: flask-app/services/copy_hub/copy_asset_service.py
流程: §14 12步骤 STEP_7_EXECUTE
"""
import os
import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any


# 文案分类常量
COPY_TYPES = [
    'UI_TEXT', 'DOC_TEXT', 'AI_PROMPT',
    'KNOWLEDGE', 'QUESTION', 'RULE_TEXT', 'NOTIFICATION'
]

SOURCE_STATUS = ['LOCAL', 'CLOUD_PENDING', 'EXTRACTED']
COPY_STATUS = ['ACTIVE', 'INACTIVE', 'PENDING_REVIEW']


class CopyAssetService:
    """文案资产存储引擎"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # 默认数据库路径
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(base, 'app.db')
        self.db_path = db_path
        self._cache = {}  # 简单内存缓存
        self._cache_ttl = 300  # 5分钟缓存
        self._cache_ts = {}

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _is_cache_valid(self, key: str) -> bool:
        if key not in self._cache_ts:
            return False
        return (datetime.now().timestamp() - self._cache_ts[key]) < self._cache_ttl

    # ========== 文案 CRUD ==========

    def create_copy(self, copy_key: str, copy_type: str, copy_content: str,
                    module_path: str = '', page_path: str = '',
                    copy_content_en: str = '', fallback_hardcoded: str = '',
                    source_status: str = 'LOCAL', tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """新增文案资产"""
        if copy_type not in COPY_TYPES:
            return {'success': False, 'error': f'无效文案类型: {copy_type}'}
        if source_status not in SOURCE_STATUS:
            return {'success': False, 'error': f'无效来源状态: {source_status}'}

        tags_json = json.dumps(tags or [], ensure_ascii=False)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO mt_copy_assets
                   (copy_key, copy_type, copy_content, copy_content_en,
                    module_path, page_path, status, version,
                    fallback_hardcoded, source_status, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', 1, ?, ?, ?, ?, ?)""",
                (copy_key, copy_type, copy_content, copy_content_en,
                 module_path, page_path, fallback_hardcoded, source_status,
                 tags_json, now, now)
            )
            copy_id = cur.lastrowid
            # 记录初始版本
            cur.execute(
                """INSERT INTO mt_copy_versions
                   (copy_id, content_snapshot, version_number, changed_by, change_reason, created_at)
                   VALUES (?, ?, 1, 'system', '初始入库', ?)""",
                (copy_id, copy_content, now)
            )
            conn.commit()
            conn.close()
            return {'success': True, 'copy_id': copy_id, 'copy_key': copy_key}
        except sqlite3.IntegrityError:
            return {'success': False, 'error': f'文案键已存在: {copy_key}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_copy(self, copy_key: str, lang: str = 'zh') -> Optional[str]:
        """获取文案内容（统一调用入口，支持降级兜底）"""
        # 查缓存
        cache_key = f'{copy_key}:{lang}'
        if self._is_cache_valid(cache_key):
            return self._cache.get(cache_key)

        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT copy_content, copy_content_en, fallback_hardcoded, status "
                "FROM mt_copy_assets WHERE copy_key = ?",
                (copy_key,)
            )
            row = cur.fetchone()
            conn.close()

            if row is None:
                return None  # 文案不存在

            if row['status'] != 'ACTIVE':
                return None  # 文案不可用

            # 优先返回对应语言，英文为空则降级中文
            if lang == 'en' and row['copy_content_en']:
                content = row['copy_content_en']
            else:
                content = row['copy_content']

            # 如果内容为空，降级返回硬编码兜底值
            if not content and row['fallback_hardcoded']:
                content = row['fallback_hardcoded']

            # 写缓存
            self._cache[cache_key] = content
            self._cache_ts[cache_key] = datetime.now().timestamp()
            return content
        except Exception:
            return None

    def get_copy_batch(self, prefix: str, lang: str = 'zh') -> Dict[str, str]:
        """批量获取文案（按 key 前缀）"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT copy_key, copy_content, copy_content_en, fallback_hardcoded, status "
                "FROM mt_copy_assets WHERE copy_key LIKE ? AND status = 'ACTIVE'",
                (f'{prefix}%',)
            )
            rows = cur.fetchall()
            conn.close()

            result = {}
            for row in rows:
                if lang == 'en' and row['copy_content_en']:
                    content = row['copy_content_en']
                else:
                    content = row['copy_content']
                if not content and row['fallback_hardcoded']:
                    content = row['fallback_hardcoded']
                result[row['copy_key']] = content
            return result
        except Exception:
            return {}

    def get_copy_by_module(self, module_path: str, lang: str = 'zh') -> Dict[str, str]:
        """按模块获取文案"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT copy_key, copy_content, copy_content_en, fallback_hardcoded, status "
                "FROM mt_copy_assets WHERE module_path = ? AND status = 'ACTIVE'",
                (module_path,)
            )
            rows = cur.fetchall()
            conn.close()
            result = {}
            for row in rows:
                if lang == 'en' and row['copy_content_en']:
                    content = row['copy_content_en']
                else:
                    content = row['copy_content']
                if not content and row['fallback_hardcoded']:
                    content = row['fallback_hardcoded']
                result[row['copy_key']] = content
            return result
        except Exception:
            return {}

    def update_copy(self, copy_key: str, copy_content: str = None,
                    copy_content_en: str = None, changed_by: str = 'system',
                    change_reason: str = '') -> Dict[str, Any]:
        """更新文案（自动记录版本历史）"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT copy_id, copy_content, version FROM mt_copy_assets WHERE copy_key = ?", (copy_key,))
            row = cur.fetchone()
            if row is None:
                conn.close()
                return {'success': False, 'error': f'文案不存在: {copy_key}'}

            copy_id = row['copy_id']
            old_content = row['copy_content']
            old_version = row['version']
            new_version = old_version + 1

            # 更新主表
            if copy_content is not None and copy_content_en is not None:
                cur.execute(
                    "UPDATE mt_copy_assets SET copy_content=?, copy_content_en=?, version=?, updated_at=? WHERE copy_key=?",
                    (copy_content, copy_content_en, new_version, now, copy_key)
                )
            elif copy_content is not None:
                cur.execute(
                    "UPDATE mt_copy_assets SET copy_content=?, version=?, updated_at=? WHERE copy_key=?",
                    (copy_content, new_version, now, copy_key)
                )
            elif copy_content_en is not None:
                cur.execute(
                    "UPDATE mt_copy_assets SET copy_content_en=?, version=?, updated_at=? WHERE copy_key=?",
                    (copy_content_en, new_version, now, copy_key)
                )

            # 记录版本历史
            cur.execute(
                """INSERT INTO mt_copy_versions
                   (copy_id, content_snapshot, version_number, changed_by, change_reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (copy_id, copy_content or old_content, new_version, changed_by, change_reason, now)
            )
            conn.commit()
            conn.close()

            # 清缓存
            self._cache.pop(f'{copy_key}:zh', None)
            self._cache.pop(f'{copy_key}:en', None)
            return {'success': True, 'copy_id': copy_id, 'new_version': new_version}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def delete_copy(self, copy_key: str) -> Dict[str, Any]:
        """下线文案（软删除，status -> INACTIVE）"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("UPDATE mt_copy_assets SET status='INACTIVE', updated_at=? WHERE copy_key=?",
                        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), copy_key))
            affected = cur.rowcount
            conn.commit()
            conn.close()
            self._cache.pop(f'{copy_key}:zh', None)
            self._cache.pop(f'{copy_key}:en', None)
            if affected == 0:
                return {'success': False, 'error': f'文案不存在: {copy_key}'}
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ========== 统计与查询 ==========

    def get_stats(self) -> Dict[str, Any]:
        """获取文案资产统计"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            # 总数
            cur.execute("SELECT COUNT(*) AS total FROM mt_copy_assets")
            total = cur.fetchone()['total']
            # 按分类
            cur.execute("SELECT copy_type, COUNT(*) AS cnt FROM mt_copy_assets GROUP BY copy_type")
            by_type = {row['copy_type']: row['cnt'] for row in cur.fetchall()}
            # 按状态
            cur.execute("SELECT status, COUNT(*) AS cnt FROM mt_copy_assets GROUP BY status")
            by_status = {row['status']: row['cnt'] for row in cur.fetchall()}
            # 按来源
            cur.execute("SELECT source_status, COUNT(*) AS cnt FROM mt_copy_assets GROUP BY source_status")
            by_source = {row['source_status']: row['cnt'] for row in cur.fetchall()}
            # 云占用待治理
            cur.execute("SELECT COUNT(*) AS cnt FROM mt_copy_assets WHERE source_status='CLOUD_PENDING'")
            cloud_pending = cur.fetchone()['cnt']
            conn.close()
            return {
                'total': total,
                'by_type': by_type,
                'by_status': by_status,
                'by_source': by_source,
                'cloud_pending': cloud_pending
            }
        except Exception as e:
            return {'error': str(e)}

    def list_copies(self, copy_type: str = None, status: str = None,
                    source_status: str = None, limit: int = 100,
                    offset: int = 0) -> List[Dict[str, Any]]:
        """列出文案（支持筛选）"""
        query = "SELECT * FROM mt_copy_assets WHERE 1=1"
        params = []
        if copy_type:
            query += " AND copy_type = ?"
            params.append(copy_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        if source_status:
            query += " AND source_status = ?"
            params.append(source_status)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def find_duplicates(self) -> List[Dict[str, Any]]:
        """查找重复文案（内容相同）"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT copy_content, COUNT(*) AS cnt, GROUP_CONCAT(copy_key) AS keys
                   FROM mt_copy_assets
                   WHERE status='ACTIVE' AND copy_content != ''
                   GROUP BY copy_content HAVING cnt > 1"""
            )
            rows = cur.fetchall()
            conn.close()
            return [{'content': row['copy_content'][:100], 'count': row['cnt'],
                     'keys': row['keys']} for row in rows]
        except Exception:
            return []

    def find_orphans(self) -> List[Dict[str, Any]]:
        """查找孤立文案（无功能映射）"""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT a.copy_key, a.copy_type, a.copy_content
                   FROM mt_copy_assets a
                   LEFT JOIN mt_copy_feature_mapping m ON a.copy_id = m.copy_id
                   WHERE m.mapping_id IS NULL AND a.status='ACTIVE'"""
            )
            rows = cur.fetchall()
            conn.close()
            return [{'copy_key': row['copy_key'], 'copy_type': row['copy_type'],
                     'content': row['copy_content'][:100]} for row in rows]
        except Exception:
            return []
