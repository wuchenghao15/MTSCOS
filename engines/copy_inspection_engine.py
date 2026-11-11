"""
文案巡检引擎 (Copy Inspection Engine)
CHMS-06: 文案合规巡检（缺失/重复/占位/硬编码检测）

归档: flask-app/engines/copy_inspection_engine.py
流程: §14 12步骤 STEP_7_EXECUTE
"""
from __future__ import annotations
import os
import re
import sys
import sqlite3
import json
from typing import Dict, Any, List


class CopyInspectionEngine:
    """文案合规巡检引擎"""

    def __init__(self, db_path: str = None, project_root: str = None):
        if db_path is None:
            # db_path 归正 (flow_bigdata_evolve_20261021): 原默认 flask-app/app.db(不存在) → 项目主库 database/app.db
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base, 'database', 'app.db')
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.db_path = db_path
        self.project_root = project_root

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def inspect_missing(self) -> List[Dict[str, Any]]:
        """检测缺失文案：页面/服务引用了文案key但数据库中不存在"""
        findings = []
        # 检查模板文件中引用的文案key是否在库
        templates_dir = os.path.join(self.project_root, 'flask-app', 'templates')
        if os.path.isdir(templates_dir):
            for root, dirs, files in os.walk(templates_dir):
                for f in files:
                    if not f.endswith('.html'):
                        continue
                    fpath = os.path.join(root, f)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                            content = fp.read()
                        # 查找 copy_key 引用模式
                        keys = re.findall(r"copy_key['\"]?\s*[:=]\s*['\"]([\w.]+)['\"]", content)
                        keys += re.findall(r"/api/copy/([\w.]+)", content)
                        for key in set(keys):
                            conn = self._get_conn()
                            cur = conn.cursor()
                            cur.execute("SELECT copy_id FROM mt_copy_assets WHERE copy_key=?", (key,))
                            if cur.fetchone() is None:
                                findings.append({
                                    'type': 'MISSING',
                                    'file': os.path.relpath(fpath, self.project_root),
                                    'copy_key': key,
                                    'detail': f'模板引用了文案key {key} 但数据库中不存在'
                                })
                            conn.close()
                    except Exception:
                        continue
        return findings

    def inspect_duplicates(self) -> List[Dict[str, Any]]:
        """检测重复文案"""
        findings = []
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT copy_content, COUNT(*) AS cnt, GROUP_CONCAT(copy_key) AS keys
                   FROM mt_copy_assets
                   WHERE status='ACTIVE' AND copy_content != ''
                   GROUP BY copy_content HAVING cnt > 1"""
            )
            for row in cur.fetchall():
                findings.append({
                    'type': 'DUPLICATE',
                    'content_preview': row['copy_content'][:100],
                    'count': row['cnt'],
                    'keys': row['keys'],
                    'detail': f'发现{row["cnt"]}条内容相同的文案'
                })
            conn.close()
        except Exception:
            pass
        return findings

    def inspect_placeholders(self) -> List[Dict[str, Any]]:
        """检测占位文案"""
        findings = []
        placeholder_patterns = [
            (r'TODO|FIXME|PLACEHOLDER', 'TODO/FIXME标记'),
            (r'占位|待补充|待完善', '占位标记'),
            (r'模拟|假数据|mock|dummy', '模拟/假数据'),
            (r'.+页面。$', '占位页特征'),
            (r'/templates/.+\.html', '模板路径泄露'),
        ]
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT copy_key, copy_content, page_path FROM mt_copy_assets WHERE status='ACTIVE'")
            for row in cur.fetchall():
                content = row['copy_content']
                for pattern, desc in placeholder_patterns:
                    if re.search(pattern, content, re.I):
                        findings.append({
                            'type': 'PLACEHOLDER',
                            'copy_key': row['copy_key'],
                            'pattern': desc,
                            'content_preview': content[:100],
                            'detail': f'文案包含占位特征: {desc}'
                        })
                        break
            conn.close()
        except Exception:
            pass
        return findings

    def inspect_hardcoded(self) -> List[Dict[str, Any]]:
        """检测硬编码文案（代码中内联的中文文案未入库）"""
        findings = []
        sensitive_patterns = [
            (r'password\s*[:=]\s*[\'"][^\'"]+[\'"]', '硬编码密码'),
            (r'(?:api_?key|secret|token)\s*[:=]\s*[\'"][^\'"]+[\'"]', '硬编码密钥'),
            (r'mockValidTokens\s*=\s*\[', '硬编码测试凭据'),
        ]
        scan_dirs = [
            os.path.join(self.project_root, 'flask-app', 'ai_engines'),
            os.path.join(self.project_root, 'flask-app', 'services'),
            os.path.join(self.project_root, 'frontend', 'JavaScript'),
            os.path.join(self.project_root, 'frontend', 'assets', 'js'),
        ]
        for scan_dir in scan_dirs:
            if not os.path.isdir(scan_dir):
                continue
            for root, dirs, files in os.walk(scan_dir):
                # 误报豁免 (flow_hardfix_audit_20261021): 实测104条CRITICAL全为误报——
                # ①_*_fusion 系列第三方参考库(_m_flow/_cog/_SimpleMem/_semantica, tests fixture为主)非本项目运行代码
                # ②tests/fixtures 目录
                rel_root = os.path.relpath(root, self.project_root).replace('\\', '/')
                if ('_fusion/' in rel_root or rel_root.endswith('_fusion') or '/cookbook/' in rel_root
                        or '/tests' in rel_root or '/fixtures' in rel_root or 'test_' in os.path.basename(root)):
                    continue
                for f in files:
                    if not (f.endswith('.py') or f.endswith('.js')):
                        continue
                    fpath = os.path.join(root, f)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                            content = fp.read()
                        # 占位/假值豁免: 模板变量{{}}、文档占位<KEY>、常见测试假值 (教程模板与教学示例非真泄露)
                        _FAKE = re.compile(
                            r'\{\{[^}]*\}\}|<[^>]+>|test|changeme|dummy|example|placeholder|your[_-]|xxx|'
                            r'\$\{[^}]*\}|WRITE_KEY|READ_KEY|password\s*=\s*\'?\"?\'?$', re.I)
                        for pattern, desc in sensitive_patterns:
                            real = [m for m in re.findall(pattern, content, re.I) if not _FAKE.search(m)]
                            matches = real
                            if matches:
                                findings.append({
                                    'type': 'HARDCODED',
                                    'file': os.path.relpath(fpath, self.project_root),
                                    'pattern': desc,
                                    'count': len(matches),
                                    'detail': f'{f} 中检测到{len(matches)}处{desc}'
                                })
                    except Exception:
                        continue
        return findings

    def run_full_inspection(self) -> Dict[str, Any]:
        """执行完整巡检"""
        missing = self.inspect_missing()
        duplicates = self.inspect_duplicates()
        placeholders = self.inspect_placeholders()
        hardcoded = self.inspect_hardcoded()

        all_findings = missing + duplicates + placeholders + hardcoded
        # 确定严重等级
        severity = 'INFO'
        if hardcoded:
            severity = 'CRITICAL'
        elif placeholders:
            severity = 'WARNING'
        elif duplicates or missing:
            severity = 'WARNING'

        # 落库巡检报告
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            # 引擎自治建表 (flow_bigdata_evolve_20261021): 大数据推演发现全仓无人建此表, 引擎写库必败 → 自建
            cur.execute("""CREATE TABLE IF NOT EXISTS mt_copy_inspection_report (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inspection_type TEXT NOT NULL,
                findings_json TEXT,
                severity TEXT DEFAULT 'INFO',
                total_findings INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )""")
            for finding_type, findings in [('MISSING', missing), ('DUPLICATE', duplicates),
                                            ('PLACEHOLDER', placeholders), ('HARDCODED', hardcoded)]:
                cur.execute(
                    """INSERT INTO mt_copy_inspection_report
                       (inspection_type, findings_json, severity, total_findings)
                       VALUES (?, ?, ?, ?)""",
                    (finding_type, json.dumps(findings, ensure_ascii=False),
                     severity if findings else 'INFO', len(findings))
                )
            # P1 巡检语义化 (flow_p1_wave_20261021): 发现项附脑库历史相似解法 top-2 (零token, fail-open)
            if all_findings:
                try:
                    hints = []
                    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    from ai_brain_vector_engine import search_brain
                    for f in all_findings[:3]:
                        desc = (f.get('message') or f.get('description') or f.get('file') or str(f))[:60]
                        try:
                            so = search_brain(f'文案巡检 {desc}', top_k=2)
                            hints.append({'finding': desc, 'matches': [
                                {'title': (r.get('title') or '')[:50],
                                 'preview': (r.get('content_preview') or '')[:100],
                                 'score': round(float(r.get('score') or 0), 3)}
                                for r in (so.get('results') or [])]})
                        except Exception:
                            continue
                    if hints:
                        cur.execute(
                            """INSERT INTO mt_copy_inspection_report
                               (inspection_type, findings_json, severity, total_findings)
                               VALUES ('SEMANTIC_HINTS', ?, 'INFO', ?)""",
                            (json.dumps(hints, ensure_ascii=False), len(hints)))
                except Exception:
                    pass  # fail-open: 语义增强不阻塞落库
            conn.commit()
            conn.close()
        except Exception:
            pass

        return {
            'total_findings': len(all_findings),
            'severity': severity,
            'breakdown': {
                'missing': len(missing),
                'duplicates': len(duplicates),
                'placeholders': len(placeholders),
                'hardcoded': len(hardcoded)
            },
            'findings': {
                'missing': missing,
                'duplicates': duplicates,
                'placeholders': placeholders,
                'hardcoded': hardcoded
            }
        }


def main():
    """daemon 入口 (flow_bigdata_evolve_20261021): andromeda_core 注册 `copy_inspection_engine.py --loop`
    但原文件无 __main__ → daemon 空转、巡检从未落库。补: --loop 常驻(900s) / 无参单次。"""
    import time
    interval = 900
    if '--loop' in sys.argv:
        print('[sys_copy_inspection] loop 模式启动, 周期 %ds' % interval, flush=True)
        while True:
            try:
                r = CopyInspectionEngine().run_full_inspection()
                print('[sys_copy_inspection] findings=%d severity=%s' % (r['total_findings'], r['severity']), flush=True)
            except Exception as e:
                print('[sys_copy_inspection] 轮次异常(fail-open):', e, flush=True)
            time.sleep(interval)
    else:
        r = CopyInspectionEngine().run_full_inspection()
        print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])


if __name__ == '__main__':
    main()
