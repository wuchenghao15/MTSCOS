"""
文案资产抽取脚本 (Copy Extraction Script)
扫描系统现有文案并入库

归档: flask-app/scripts/copy_extraction_script.py
流程: §14 12步骤 STEP_7_EXECUTE
用法: python copy_extraction_script.py
"""
import os
import re
import sys
import json
import sqlite3
from datetime import datetime

# 项目根目录 (脚本位于 flask-app/scripts/，向上3层到项目根)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 主数据库位于 flask-app/app.db
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app.db')

# 文案抽取规则
HTML_TITLE_RE = re.compile(r'<title[^>]*>([^<]+)</title>', re.I)
HTML_META_DESC_RE = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', re.I)
HTML_BUTTON_RE = re.compile(r'<button[^>]*>([^<]+)</button>', re.I)
HTML_LABEL_RE = re.compile(r'<label[^>]*>([^<]+)</label>', re.I)
HTML_H_RE = re.compile(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', re.I)
HTML_PLACEHOLDER_RE = re.compile(r'placeholder=["\']([^"\']+)["\']', re.I)

# Python flash 消息
FLASH_RE = re.compile(r'flash\s*\(\s*["\']([^"\']+)["\']', re.I)
# Python 字典中的中文文案
PY_CN_STRING_RE = re.compile(r"['\"]([^'\"]*[\u4e00-\u9fff][^'\"]*)['\"]", re.I)

# AI 提示词模板（硬编码在 _register_default_templates 中）
AI_PROMPT_RE = re.compile(r'(tpl_\w+)\s*=\s*["\']([^"\']{10,})["\']', re.I)


class CopyExtractor:
    """文案资产抽取器"""

    def __init__(self):
        self.db_path = DB_PATH
        self.extracted = []
        self.seen_keys = set()
        self.stats = {'UI_TEXT': 0, 'DOC_TEXT': 0, 'AI_PROMPT': 0,
                      'KNOWLEDGE': 0, 'QUESTION': 0, 'RULE_TEXT': 0, 'NOTIFICATION': 0}

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _add_copy(self, copy_key, copy_type, content, module_path='', page_path='',
                  fallback_hardcoded='', source_status='LOCAL'):
        if not content or not content.strip():
            return
        content = content.strip()
        if copy_key in self.seen_keys:
            copy_key = f'{copy_key}_{hash(content) % 10000}'
        if copy_key in self.seen_keys:
            return
        self.seen_keys.add(copy_key)
        self.extracted.append({
            'copy_key': copy_key,
            'copy_type': copy_type,
            'copy_content': content,
            'module_path': module_path,
            'page_path': page_path,
            'fallback_hardcoded': fallback_hardcoded,
            'source_status': source_status
        })
        self.stats[copy_type] = self.stats.get(copy_type, 0) + 1

    def extract_html_copies(self):
        """抽取 HTML 模板文案"""
        templates_dirs = [
            os.path.join(PROJECT_ROOT, 'flask-app', 'templates'),
            os.path.join(PROJECT_ROOT, 'frontend', 'pages'),
        ]
        for tdir in templates_dirs:
            if not os.path.isdir(tdir):
                continue
            for root, dirs, files in os.walk(tdir):
                for f in files:
                    if not f.endswith('.html'):
                        continue
                    fpath = os.path.join(root, f)
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                            content = fp.read()
                    except Exception:
                        continue
                    rel_path = os.path.relpath(fpath, PROJECT_ROOT)
                    page_name = os.path.splitext(f)[0]
                    # 标题
                    for m in HTML_TITLE_RE.finditer(content):
                        self._add_copy(f'ui.{page_name}.title', 'UI_TEXT', m.group(1),
                                       module_path='templates', page_path=rel_path)
                    # meta描述
                    for m in HTML_META_DESC_RE.finditer(content):
                        self._add_copy(f'ui.{page_name}.description', 'UI_TEXT', m.group(1),
                                       module_path='templates', page_path=rel_path)
                    # 按钮
                    for i, m in enumerate(HTML_BUTTON_RE.finditer(content)):
                        self._add_copy(f'ui.{page_name}.button.{i}', 'UI_TEXT', m.group(1),
                                       module_path='templates', page_path=rel_path)
                    # 标签
                    for i, m in enumerate(HTML_LABEL_RE.finditer(content)):
                        self._add_copy(f'ui.{page_name}.label.{i}', 'UI_TEXT', m.group(1),
                                       module_path='templates', page_path=rel_path)
                    # 标题h1-h6
                    for i, m in enumerate(HTML_H_RE.finditer(content)):
                        self._add_copy(f'ui.{page_name}.heading.{i}', 'UI_TEXT', m.group(1),
                                       module_path='templates', page_path=rel_path)
                    # placeholder
                    for i, m in enumerate(HTML_PLACEHOLDER_RE.finditer(content)):
                        self._add_copy(f'ui.{page_name}.placeholder.{i}', 'UI_TEXT', m.group(1),
                                       module_path='templates', page_path=rel_path)

    def extract_ai_prompts(self):
        """抽取 AI 提示词文案"""
        prompt_file = os.path.join(PROJECT_ROOT, 'flask-app', 'ai_engines', 'ai_prompt_manager.py')
        if not os.path.isfile(prompt_file):
            return
        try:
            with open(prompt_file, 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
        except Exception:
            return
        for m in AI_PROMPT_RE.finditer(content):
            tpl_name = m.group(1)
            tpl_content = m.group(2)
            self._add_copy(f'ai.prompt.{tpl_name}', 'AI_PROMPT', tpl_content,
                           module_path='ai_engines', page_path='ai_prompt_manager.py',
                           fallback_hardcoded=tpl_content, source_status='LOCAL')

    def extract_knowledge_base(self):
        """抽取知识库默认文档"""
        kb_file = os.path.join(PROJECT_ROOT, 'flask-app', 'ai_engines', 'ai_knowledge_base.py')
        if not os.path.isfile(kb_file):
            return
        try:
            with open(kb_file, 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
        except Exception:
            return
        # 抽取知识文档标题和内容
        doc_blocks = re.findall(r"['\"](title|content|name)['\"]\s*:\s*['\"]([^'\"]{5,})['\"]", content, re.I)
        for i, (field, value) in enumerate(doc_blocks):
            self._add_copy(f'knowledge.default.{field}.{i}', 'KNOWLEDGE', value,
                           module_path='ai_engines', page_path='ai_knowledge_base.py',
                           fallback_hardcoded=value, source_status='LOCAL')

    def extract_brain_library(self):
        """抽取脑库初始内容"""
        brain_file = os.path.join(PROJECT_ROOT, 'flask-app', 'ai_engines', 'brain', 'ai_brain_library.py')
        if not os.path.isfile(brain_file):
            return
        try:
            with open(brain_file, 'r', encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
        except Exception:
            return
        # 抽取 _create_initial_* 方法中的中文文案
        initial_blocks = re.findall(r"['\"]([^'\"]*[\u4e00-\u9fff][^'\"]*)['\"]", content)
        for i, text in enumerate(initial_blocks):
            if len(text) > 3:
                self._add_copy(f'brain.initial.{i}', 'KNOWLEDGE', text,
                               module_path='ai_engines/brain', page_path='ai_brain_library.py',
                               fallback_hardcoded=text, source_status='LOCAL')

    def extract_rule_docs(self):
        """抽取系统规则文案（仅索引，不入库内容）"""
        rules_dir = os.path.join(PROJECT_ROOT, '.trae', 'rules')
        if not os.path.isdir(rules_dir):
            return
        for f in os.listdir(rules_dir):
            if not f.endswith('.md'):
                continue
            fpath = os.path.join(rules_dir, f)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                    first_line = fp.readline().strip()
                # 仅记录规则文件标题作为索引
                title = first_line.lstrip('# ').strip() or f
                self._add_copy(f'rule.{os.path.splitext(f)[0]}', 'RULE_TEXT', title,
                               module_path='.trae/rules', page_path=f, source_status='LOCAL')
            except Exception:
                continue

    def extract_js_copies(self):
        """抽取前端JS中的文案"""
        js_dirs = [
            os.path.join(PROJECT_ROOT, 'frontend', 'JavaScript'),
            os.path.join(PROJECT_ROOT, 'frontend', 'assets', 'js'),
        ]
        for jdir in js_dirs:
            if not os.path.isdir(jdir):
                continue
            for f in os.listdir(jdir):
                if not f.endswith('.js'):
                    continue
                fpath = os.path.join(jdir, f)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as fp:
                        content = fp.read()
                except Exception:
                    continue
                js_name = os.path.splitext(f)[0]
                # 抽取中文文案
                cn_strings = PY_CN_STRING_RE.findall(content)
                for i, text in enumerate(cn_strings):
                    if len(text) > 2 and any(c for c in text if '\u4e00' <= c <= '\u9fff'):
                        self._add_copy(f'js.{js_name}.text.{i}', 'UI_TEXT', text,
                                       module_path='frontend/JavaScript', page_path=f,
                                       fallback_hardcoded=text, source_status='LOCAL')

    def save_to_db(self):
        """将抽取的文案入库"""
        if not self.extracted:
            print('无文案需入库')
            return 0
        conn = self._get_conn()
        cur = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        inserted = 0
        for item in self.extracted:
            try:
                cur.execute(
                    """INSERT OR IGNORE INTO mt_copy_assets
                       (copy_key, copy_type, copy_content, copy_content_en, module_path, page_path,
                        status, version, fallback_hardcoded, source_status, tags, created_at, updated_at)
                       VALUES (?, ?, ?, '', ?, ?, 'ACTIVE', 1, ?, ?, '[]', ?, ?)""",
                    (item['copy_key'], item['copy_type'], item['copy_content'],
                     item['module_path'], item['page_path'], item['fallback_hardcoded'],
                     item['source_status'], now, now)
                )
                if cur.rowcount > 0:
                    inserted += 1
                    copy_id = cur.lastrowid
                    cur.execute(
                        """INSERT INTO mt_copy_versions
                           (copy_id, content_snapshot, version_number, changed_by, change_reason, created_at)
                           VALUES (?, ?, 1, 'extraction_script', '文案抽取入库', ?)""",
                        (copy_id, item['copy_content'], now)
                    )
            except Exception as e:
                print(f'入库失败 {item["copy_key"]}: {e}')
        conn.commit()
        conn.close()
        return inserted

    def run(self):
        """执行完整抽取流程"""
        print('='*60)
        print('MTSCOS 文案资产抽取脚本')
        print(f'项目根目录: {PROJECT_ROOT}')
        print(f'数据库: {self.db_path}')
        print('='*60)

        print('\n[1/6] 抽取 HTML 模板文案...')
        self.extract_html_copies()
        print(f'  已抽取 {self.stats["UI_TEXT"]} 条 UI 文案')

        print('[2/6] 抽取 AI 提示词...')
        self.extract_ai_prompts()
        print(f'  已抽取 {self.stats["AI_PROMPT"]} 条 AI 提示词')

        print('[3/6] 抽取知识库内容...')
        self.extract_knowledge_base()
        print(f'  已抽取 {self.stats["KNOWLEDGE"]} 条知识库内容')

        print('[4/6] 抽取脑库初始内容...')
        self.extract_brain_library()
        print(f'  已抽取 {self.stats["KNOWLEDGE"]} 条知识/脑库内容(累计)')

        print('[5/6] 抽取系统规则文案...')
        self.extract_rule_docs()
        print(f'  已抽取 {self.stats["RULE_TEXT"]} 条规则文案')

        print('[6/6] 抽取前端JS文案...')
        self.extract_js_copies()
        print(f'  已抽取 {self.stats["UI_TEXT"]} 条 UI 文案(累计)')

        print('\n' + '='*60)
        print('抽取统计:')
        for k, v in self.stats.items():
            print(f'  {k}: {v} 条')
        print(f'  总计: {len(self.extracted)} 条')
        print('='*60)

        print('\n入库中...')
        inserted = self.save_to_db()
        print(f'成功入库 {inserted} 条文案')
        print('抽取完成！')


if __name__ == '__main__':
    extractor = CopyExtractor()
    extractor.run()
