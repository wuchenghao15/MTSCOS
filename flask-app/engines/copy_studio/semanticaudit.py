#!/usr/bin/env python3
"""
📝 copy_studio — semanticaudit (v26.0 Step5)
=============================================
语义一致性巡检 + AI 腔检测 + 自动修复草案生成.

规则:
  1. ai_tone          — AI 腔高频词 (内心五味杂陈 / 不禁 / 仿佛 / 宛如 / 不由得)
  2. pronoun_shift    — 人称漂移 (我/他/她 在一段内反复切换)
  3. char_name_drift  — 角色名前缀不一致 (周衍 vs 周刑警 vs 老周 出现多套指代)
  4. punctuation      — 中文语境里混入半角标点 + 连续 3+ 感叹号/问号
  5. repetition       — 同一句/短语在同项目章节重复 (跨章节 chunk 相似度 > 0.85)

设计原则: 所有规则纯 Python, 零外部依赖. 任何单规则异常都不阻断其他规则.
自动修复草案: 仅给建议 (suggestion 字段), 不自动改内容 — 人类确认后再落 fix_content.
"""
from __future__ import annotations
import re, math, collections
from typing import Dict, List, Any, Optional

# ═══════════════════════════════════════════════════════════
# 规则 1: AI 腔高频词
# ═══════════════════════════════════════════════════════════
_AI_TONE_PATTERNS = [
    (r'内心.{0,6}五味杂陈', '内心五味杂陈系列'),
    (r'(不禁|不由得|忍不住)[，,]?\s*感到', '不禁/不由得感到'),
    (r'仿佛.{0,4}般', '仿佛/宛如/犹如般比喻'),
    (r'宛如.{0,4}一般', '宛如/犹如一般比喻'),
    (r'犹如.{0,4}一样', '犹如/仿佛一样比喻'),
    (r'心中.{0,4}涌起.{0,8}(波澜|涟漪|感动)', '心中涌起波澜/涟漪'),
    (r'一股.{0,6}涌上心头', '一股XX涌上心头'),
    (r'令.{0,4}深思', '令人深思'),
    (r'感慨.{0,6}万千', '感慨万千'),
]


def check_ai_tone(text: str) -> List[Dict[str, Any]]:
    issues = []
    for pat, label in _AI_TONE_PATTERNS:
        for m in re.finditer(pat, text):
            issues.append({
                'issue_type': 'ai_tone',
                'severity': 'medium',
                'description': f'AI 腔词 "{m.group()}" ({label}) 出现在位置 {m.start()}',
                'suggestion': f'删除或替换为具体动作/感官描写, 避免情绪标签词',
                'position': m.start(),
                'context': text[max(0, m.start() - 20):m.end() + 20],
            })
    return issues


# ═══════════════════════════════════════════════════════════
# 规则 2: 人称漂移 (段落内我/他/她 切换 > 3 次)
# ═══════════════════════════════════════════════════════════
def check_pronoun_shift(text: str) -> List[Dict[str, Any]]:
    issues = []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    for pi, para in enumerate(paragraphs):
        # 提取人称代词序列
        pronouns = re.findall(r'[我他她]', para)
        if len(pronouns) < 4:
            continue
        shifts = sum(1 for i in range(1, len(pronouns)) if pronouns[i] != pronouns[i - 1])
        if shifts >= 3:
            issues.append({
                'issue_type': 'pronoun_shift',
                'severity': 'medium',
                'description': f'第 {pi + 1} 段人称代词切换 {shifts} 次 ({len(pronouns)} 个代词): {"".join(pronouns)}',
                'suggestion': '该段 POV 不稳定, 建议统一视角或拆分多视角段',
                'paragraph_no': pi + 1,
                'shifts': shifts,
            })
    return issues


# ═══════════════════════════════════════════════════════════
# 规则 3: 角色名前缀不一致 (项目内角色名出现多套指代)
# ═══════════════════════════════════════════════════════════
def check_char_name_drift(text: str, known_names: List[str]) -> List[Dict[str, Any]]:
    """known_names: 项目 mt_copy_characters 的 name 列表. 前缀 2 字匹配."""
    issues = []
    if not known_names:
        return issues
    # 按前缀 2 字分组收集所有出现的名字/称呼
    prefix_map: Dict[str, List[str]] = collections.defaultdict(list)
    for full in known_names:
        prefix = full[:2] if len(full) >= 2 else full
        prefix_map[prefix].append(full)

    found_groups: Dict[str, set] = {}
    for prefix, full_names in prefix_map.items():
        # 在文本中找: 全名 + 单字前缀 + 前缀+"刑警/医生/老板/老/小/哥/姐/叔" 等
        variants = set()
        for fn in full_names:
            variants.add(fn)
            if len(fn) >= 2:
                variants.add(fn[:2])
                variants.add('老' + fn[-1])  # 老周
                variants.add('小' + fn[-1])  # 小周
                variants.add(fn[-1] + '哥')  # 衍哥
                variants.add(fn[-1] + '姐')
                variants.add(fn[-1] + '叔')
                variants.add(fn[:1] + '刑警')  # 周刑警
                variants.add(fn[:1] + '医生')
                variants.add(fn[:1] + '老板')
        # 文本中实际出现的变体
        actual = set()
        for v in variants:
            if len(v) >= 1 and v in text:
                actual.add(v)
        if len(actual) >= 2:
            found_groups[prefix] = actual

    for prefix, variants in found_groups.items():
        issues.append({
            'issue_type': 'char_name_drift',
            'severity': 'low',
            'description': f'角色 "{prefix}..." 出现多套指代: {"/".join(sorted(variants))}',
            'suggestion': f'统一为 "{list(prefix_map[prefix])[0]}", 其余变体替换为全名或代词',
        })
    return issues


# ═══════════════════════════════════════════════════════════
# 规则 4: 标点 (半角混入 + 连续 3+ 感叹/问号)
# ═══════════════════════════════════════════════════════════
def check_punctuation(text: str) -> List[Dict[str, Any]]:
    issues = []
    # 半角标点 (中文语境)
    half_pos = []
    for ch in ',;:!?()\'"':
        idx = 0
        while True:
            pos = text.find(ch, idx)
            if pos == -1:
                break
            # 检查周围是否有中文字 (有则认为在中文语境里)
            context = text[max(0, pos - 1):pos + 2]
            if re.search(r'[\u4e00-\u9fff]', context):
                half_pos.append(pos)
            idx = pos + 1
    if half_pos:
        # 只报第一次出现位置, 列出全部
        issues.append({
            'issue_type': 'half_width_punct',
            'severity': 'low',
            'description': f'发现 {len(half_pos)} 处半角标点在中文语境中 (建议全角): {text[half_pos[0]]} 位置 {half_pos[0]}',
            'suggestion': '批量替换半角 , ; : ! ? ( ) 为全角 ， ； ： ！ ？ （ ）',
            'count': len(half_pos),
        })

    # 连续 3+ 感叹/问号
    for m in re.finditer(r'[！!]{3,}|[？?]{3,}', text):
        issues.append({
            'issue_type': 'excessive_punct',
            'severity': 'low',
            'description': f'连续 {len(m.group())} 个 {m.group()[0]} 位置 {m.start()}',
            'suggestion': '最多保留 2 个, 或用句式调整表达情绪',
            'position': m.start(),
        })
    return issues


# ═══════════════════════════════════════════════════════════
# 规则 5: 跨章节重复句 (chunk 级 cosine > 0.85)
# ═══════════════════════════════════════════════════════════
def _char_tfidf(texts: List[str]) -> List[List[float]]:
    """纯 char 级 TF-IDF (极简版, 用于长文本相似度)."""
    from collections import Counter
    # 字频
    tf_all = [Counter(t) for t in texts]
    df = Counter()
    for tf in tf_all:
        for c in set(tf.keys()):
            df[c] += 1
    n = len(texts)
    vecs = []
    for tf in tf_all:
        vec = []
        total = sum(tf.values()) or 1
        for c, cnt in tf.items():
            tfidf = (cnt / total) * math.log(1 + n / df[c])
            vec.append((c, tfidf))
        vecs.append(vec)
    return vecs


def _cosine_sparse(a: List[tuple], b: List[tuple]) -> float:
    da = dict(a); db = dict(b)
    common = set(da.keys()) & set(db.keys())
    dot = sum(da[c] * db[c] for c in common)
    na = math.sqrt(sum(v * v for v in da.values()))
    nb = math.sqrt(sum(v * v for v in db.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def check_repetition(chapter_texts: List[tuple], threshold: float = 0.85,
                     max_paras_per_chapter: int = 80, skip_chapters_gt: int = 20) -> List[Dict[str, Any]]:
    """检测同项目不同章节间的重复段落.
    chapter_texts: [(chapter_id, chapter_no, content), ...]

    O(n²) 保护:
      - 章节数 > skip_chapters_gt → 跳过 (项目太大, 语义巡检太昂贵)
      - 每章最多采样 max_paras_per_chapter 个段落 (按长度 top-N)
    """
    issues = []
    if len(chapter_texts) < 2:
        return issues
    if len(chapter_texts) > skip_chapters_gt:
        return issues  # 太大, 跳过
    # 按段落切分 + 采样 (长段落优先)
    all_paras: List[tuple] = []  # (chapter_id, chapter_no, para_idx, para_text)
    for cid, cno, content in chapter_texts:
        paras = [(pi, p.strip()) for pi, p in enumerate(re.split(r'\n\s*\n', content))
                 if p.strip() and len(p.strip()) > 20]
        # 按长度排序取 top-N
        paras.sort(key=lambda x: -len(x[1]))
        for pi, p in paras[:max_paras_per_chapter]:
            all_paras.append((cid, cno, pi, p))
    if len(all_paras) < 2:
        return issues
    # 字 TF-IDF + 两两对比 (para 数多时采样 top tfidf 避免 O(n²))
    vecs = _char_tfidf([p[3] for p in all_paras])
    for i in range(len(all_paras)):
        for j in range(i + 1, len(all_paras)):
            a = all_paras[i]; b = all_paras[j]
            if a[0] == b[0]:
                continue  # 同章内重复由别的规则处理
            sim = _cosine_sparse(vecs[i], vecs[j])
            if sim >= threshold:
                issues.append({
                    'issue_type': 'cross_chapter_repeat',
                    'severity': 'medium',
                    'description': f'v{a[1]}p{a[2]} 与 v{b[1]}p{b[2]} 相似度 {sim:.2f}',
                    'suggestion': '检查两处段落是否描写同一事件, 若重复则删除后章冗余描写',
                    'chapter_a': a[0], 'para_a': a[2],
                    'chapter_b': b[0], 'para_b': b[2],
                    'similarity': round(sim, 3),
                })
    return issues


# ═══════════════════════════════════════════════════════════
# 统一入口 (service.run_consistency_check 调用)
# ═══════════════════════════════════════════════════════════
def audit_chapters(
    chapters: List[Dict[str, Any]],
    char_names: Optional[List[str]] = None,
    enabled_rules: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """统一语义巡检. 逐章跑启用的规则, 附加 chapter_id 后返回.

    enabled_rules 默认全开: ai_tone / pronoun_shift / char_name_drift / punctuation / repetition
    """
    if enabled_rules is None:
        enabled_rules = ['ai_tone', 'pronoun_shift', 'char_name_drift', 'punctuation', 'repetition']
    char_names = char_names or []

    issues: List[Dict[str, Any]] = []
    chapter_texts = [(c['chapter_id'], c.get('chapter_no', 0), c.get('content') or '')
                     for c in chapters if (c.get('content') or '').strip()]

    for cid, cno, content in chapter_texts:
        for rule_name in enabled_rules:
            try:
                if rule_name == 'ai_tone':
                    for iss in check_ai_tone(content):
                        iss.update({'chapter_id': cid, 'chapter_no': cno})
                        issues.append(iss)
                elif rule_name == 'pronoun_shift':
                    for iss in check_pronoun_shift(content):
                        iss.update({'chapter_id': cid, 'chapter_no': cno})
                        issues.append(iss)
                elif rule_name == 'char_name_drift':
                    for iss in check_char_name_drift(content, char_names):
                        iss.update({'chapter_id': cid, 'chapter_no': cno})
                        issues.append(iss)
                elif rule_name == 'punctuation':
                    for iss in check_punctuation(content):
                        iss.update({'chapter_id': cid, 'chapter_no': cno})
                        issues.append(iss)
            except Exception as e:
                issues.append({
                    'issue_type': f'{rule_name}_error', 'severity': 'info',
                    'description': f'规则 {rule_name} 执行异常: {e}',
                    'chapter_id': cid, 'chapter_no': cno,
                })

    # 跨章重复 (需全量 chapter_texts)
    if 'repetition' in enabled_rules:
        try:
            for iss in check_repetition(chapter_texts):
                issues.append(iss)
        except Exception as e:
            issues.append({
                'issue_type': 'repetition_error', 'severity': 'info',
                'description': f'跨章重复检测异常: {e}',
            })

    return issues


# CLI 自检
if __name__ == '__main__':
    test = """周衍走到门口，心里不禁感到五味杂陈。
仿佛这个案子的真相仿佛一个谜。

他推开门，老魏在等他。周刑警把证物袋递过去。
衍哥心中涌起一股莫名的感动，令人深思。
周衍。老周。周刑警。三人出现了！"""
    issues = audit_chapters(
        [{'chapter_id': 't1', 'chapter_no': 1, 'content': test}],
        char_names=['周衍', '老魏'],
    )
    for i in issues:
        print(f"  [{i['issue_type']}] {i.get('severity','?')} {i.get('description','')[:60]}")
    print(f"total: {len(issues)}")
