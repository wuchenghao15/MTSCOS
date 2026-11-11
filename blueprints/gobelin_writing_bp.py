#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古灵阁文化娱乐产出 — 网文创作系统蓝图 (gobelin_writing_bp.py)
===============================================================
根据一句话中心思想 + 用户选择的参数 (字数/文体/类型/媒介/受众/IP扩展等)
自动生成长文, 可迭代改写, 支持多种输出格式.

参数规格见: mt_gobelin_system.subsystem_key='CULTURE'
"""
from __future__ import annotations
import os, json, sqlite3, time, uuid, datetime, hashlib
from flask import Blueprint, jsonify, request, send_file

gobelin_writing_bp = Blueprint('gobelin_writing', __name__, url_prefix='/api/writing')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'app.db')

# ═══════════════════════════════════════════════════════════════
# 创作参数枚举 (仙女自动补充版)
# ═══════════════════════════════════════════════════════════════

WORD_COUNT_PRESETS = {
    'flash': 500,      # 微小说
    'short': 2000,     # 短篇
    'medium': 5000,    # 中篇
    'long': 10000,     # 长篇
    'serial': 0,       # 连载 (后续追加)
}

GENRE_TAGS = [
    # 言情
    '古言','现言','仙侠言情','都市言情','科幻言情','虐恋','甜宠','破镜重圆','先婚后爱',
    # 悬疑推理
    '硬核推理','社会派','心理悬疑','密室','刑侦','法医','悬疑言情',
    # 都市
    '商战','职场','校园','家庭','都市异能','重生都市','系统流',
    # 玄幻仙侠
    '修真','洪荒','末世','无限流','龙傲天','废柴逆袭','仙侠言情',
    # 科幻
    '硬科幻','软科幻','赛博朋克','末日','星际','时空穿梭','AI觉醒',
    # 历史
    '正剧','穿越','架空历史','历史同人','权谋','战争',
    # 其他
    '军事','体育','游戏','治愈','恐怖','灵异','二次元','同人',
]

MEDIA_FORMATS = [
    {'key':'novel_long',    'label':'📖 长篇小说',        'desc':'100万字+, 多卷结构'},
    {'key':'novel_short',   'label':'📕 短篇故事',        'desc':'3万字内, 完整闭环'},
    {'key':'movie_script',  'label':'🎬 电影剧本',        'desc':'90-120分钟, 三幕式'},
    {'key':'short_video',   'label':'🎥 短视频脚本',      'desc':'30s-3min × N集, 竖屏'},
    {'key':'tv_script',     'label':'📺 电视剧本',        'desc':'30-60集, 45min/集'},
    {'key':'stage_play',    'label':'🎭 话剧/舞台剧',     'desc':'2-3小时, 现场'},
    {'key':'podcast',       'label':'🎙️ 播客/音频剧',     'desc':'声音优先, 无视觉'},
    {'key':'ad_script',     'label':'📱 广告脚本',        'desc':'产品/品牌/公益'},
    {'key':'game_script',   'label':'🎮 游戏剧本',        'desc':'主线/支线/NPC'},
    {'key':'poem',          'label':'🖋️ 诗歌/散文',      'desc':'抒情/叙事'},
    {'key':'interview',     'label':'💬 访谈/对话',      'desc':'问答体'},
]

STRUCTURE_TEMPLATES = [
    {'key':'three_act',  'label':'三幕式',      'desc':'建置-对抗-结局 (90分钟电影标准)'},
    {'key':'five_act',   'label':'五幕式',      'desc':'起-承-转-合-收 (传统戏剧)'},
    {'key':'zhanghui',   'label':'章回体',      'desc':'每回有钩子, 首尾相接'},
    {'key':'hero_journey','label':'英雄之旅',    'desc':'12阶段 (坎贝尔原型)'},
    {'key':'kishotenketsu','label':'起承転結',    'desc':'日本短篇结构, 无冲突'},
    {'key':'fragment',   'label':'碎片化',      'desc':'多视角拼贴, 非线性'},
    {'key':'serial',     'label':'连载体',      'desc':'每章末必留钩子'},
]

AUDIENCE_PROFILES = [
    {'key':'gen_z',     'label':'Z世代 (18-25)',  'tags':['快节奏','强钩子','CP','爽文','反转']},
    {'key':'millennial','label':'千禧一代 (26-40)','tags':['深度','社会议题','情感共鸣','现实']},
    {'key':'middle',    'label':'中年 (41-60)',   'tags':['历史','家庭','人生感悟','稳健']},
    {'key':'all_ages',  'label':'全年龄',         'tags':['普适','温暖','正义','成长']},
    {'key':'female',    'label':'女性向',         'tags':['情感细腻','CP','甜宠','虐恋','宫斗']},
    {'key':'male',      'label':'男性向',         'tags':['爽文','升级','热血','权谋','战争']},
]

IP_EXTENSION_OPTIONS = [
    {'key':'fanfic',      'label':'同人 (Fanfic)',  'desc':'基于已有IP二次创作'},
    {'key':'crossover',   'label':'同创 (Crossover)','desc':'多IP混搭联动'},
    {'key':'cp',          'label':'CP 向',          'desc':'恋爱线设计/虐恋/甜宠'},
    {'key':'series',      'label':'大型系列',       'desc':'宇宙观/多主角/衍生'},
    {'key':'prequel',     'label':'前传',           'desc':'时间线之前的故事'},
    {'key':'sequel',      'label':'后传',           'desc':'时间线之后的故事'},
    {'key':'au',          'label':'平行世界 (AU)',  'desc':'假设性改写'},
]

# ═══════════════════════════════════════════════════════════════
# DB 初始化
# ═══════════════════════════════════════════════════════════════
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def _init_tables():
    conn = _db(); cur = conn.cursor()
    
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_writing_project (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_hash TEXT UNIQUE,
        title TEXT,
        core_idea TEXT NOT NULL,
        genre TEXT,
        sub_genre TEXT,
        media_format TEXT,
        structure TEXT,
        target_words INTEGER DEFAULT 5000,
        audience TEXT,
        ip_extensions TEXT,       -- JSON array
        style_anchor TEXT,
        outline TEXT,             -- 大纲 JSON
        content TEXT,             -- 生成内容
        status TEXT DEFAULT 'draft',   -- draft / outlining / writing / revising / done
        version INTEGER DEFAULT 1,
        word_count INTEGER DEFAULT 0,
        quality_score REAL,
        model_used TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_writing_iteration (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        iteration INTEGER DEFAULT 1,
        action TEXT,              -- generate / revise / expand / condense
        prompt TEXT,
        output_content TEXT,
        word_count INTEGER DEFAULT 0,
        model_used TEXT,
        latency_ms INTEGER,
        fed_to_brain INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_writing_fandom (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        fandom_type TEXT,          -- fanfic / crossover / cp / series / au
        source_ip TEXT,
        characters TEXT,           -- JSON array
        relationship_map TEXT,     -- JSON
        tag TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    
    conn.commit(); conn.close()

# ═══════════════════════════════════════════════════════════════
# API: 参数枚举 (前端下拉)
# ═══════════════════════════════════════════════════════════════
@gobelin_writing_bp.route('/params')
def api_writing_params():
    """返回所有创作参数枚举 — 前端创作台用"""
    return jsonify({
        'success': True,
        'data': {
            'word_count_presets': WORD_COUNT_PRESETS,
            'genre_tags': GENRE_TAGS,
            'media_formats': MEDIA_FORMATS,
            'structure_templates': STRUCTURE_TEMPLATES,
            'audience_profiles': AUDIENCE_PROFILES,
            'ip_extension_options': IP_EXTENSION_OPTIONS,
            # 仙女自动补充项
            'fairy_autofill': {
                'reference_works': True,      # 自动匹配同类型Top3
                'style_anchor': True,         # 风格锚定
                'hooks': True,                # 每300字小钩子
                'rhythm_curve': True,         # 节奏曲线
                'character_arc': True,        # 人物弧光
                'worldbuilding_density': True,# 世界观密度
                'dialogue_ratio': True,       # 对话占比
                'foreshadowing': True,        # 伏笔回收
                'hit_elements': True,         # 爆款元素
            }
        }
    })

# ═══════════════════════════════════════════════════════════════
# API: 创作 (核心入口)
# ═══════════════════════════════════════════════════════════════
@gobelin_writing_bp.route('/create', methods=['POST'])
def api_writing_create():
    """
    v26.12 整合版 — 代理到 copy_studio engine.quick_create
    对齐旧 API 格式: body = { core_idea, word_count, genre, media_format, ... }
    """
    body = request.get_json(silent=True) or {}
    core_idea = (body.get('core_idea') or body.get('description') or '').strip()
    if not core_idea:
        return jsonify({'success': False, 'error': 'core_idea 必填 — 给我一句话中心思想'}), 400

    # 参数归一化
    wc_preset = body.get('word_count_preset')
    target_words = body.get('word_count') or (WORD_COUNT_PRESETS.get(wc_preset, 5000) if wc_preset else 5000)
    genre = body.get('genre', 'novel')
    media_fmt = body.get('media_format', 'novel_short')
    title = body.get('title', '')
    user_role = session.get('role', 'teacher') if 'session' in dir() else 'teacher'

    # 代理到 copy_studio service
    try:
        from engines.copy_studio.service import ApprovalService
        svc = ApprovalService()
        result = svc.quick_create(
            core_idea=core_idea, genre=genre, media_fmt=media_fmt,
            target_words=int(target_words), title=title,
            initiator=session.get('username', 'wuchenghao15') if 'session' in dir() else 'wuchenghao15',
        )
    except Exception as e:
        return jsonify({'success': False, 'error': f'copy_studio engine error: {e}'}), 500

    if not result:
        return jsonify({'success': False, 'error': 'AI 引擎无输出'}), 503

    return jsonify({
        'success': True,
        'data': {
            'project_id': result['project_id'],
            'title': result['title'],
            'word_count': result['total_words'],
            'target_words': int(target_words),
            'model_used': result.get('ollama_model', 'ollama'),
            'chapter_count': result['chapter_count'],
            'content_preview': (result.get('full_text') or '')[:1000],
            'ollama_ok': result.get('ollama_ok', False),
        }
    })

# ═══════════════════════════════════════════════════════════════
# 兼容路由 — writing_server.py 风格 (前端 writing-studio.html 调用)
# ═══════════════════════════════════════════════════════════════

@gobelin_writing_bp.route('/genres')
def api_writing_genres():
    """兼容 writing_server.py /api/writing/genres"""
    genres = [
        '玄幻修仙','都市异能','穿越重生','科幻末世','历史架空',
        '悬疑推理','军事谍战','体育竞技','游戏竞技','二次元',
        '言情甜宠','耽美BL','百合GL','女尊','种田日常',
        '武侠江湖','奇幻魔法','蒸汽朋克','赛博朋克','灵异鬼怪',
        '纪实传记','官场商战','职场奋斗','校园青春','家庭伦理',
        '轻小说','同人衍生','快穿','系统流','无限流',
        '克苏鲁','废土','末日','星际','机甲',
        '仙侠','修真','洪荒','神话','都市',
        '高武','国术','异能','时空','位面',
    ]
    return jsonify({'genres': genres, 'audiences': ['男频','女频','中性','青少年','成人']})

@gobelin_writing_bp.route('/models')
def api_writing_models():
    """兼容 writing_server.py /api/writing/models — 自动检测本地 Ollama"""
    default_model = 'qwen2.5:1.5b'  # mini 默认
    models = [default_model]
    try:
        import requests as _req
        r = _req.get('http://127.0.0.1:11434/api/tags', timeout=3)
        if r.status_code == 200:
            detected = [m['name'] for m in r.json().get('models', [])]
            if detected:
                models = detected
                # 偏好排序
                for pref in ['qwen2.5:14b','qwen2.5:7b','qwen2.5:3b','qwen2.5:1.5b']:
                    if pref in models:
                        default_model = pref
                        break
    except Exception:
        pass
    return jsonify({'ollama_alive': len(models)>0, 'models': models, 'default': default_model})

@gobelin_writing_bp.route('/generate', methods=['POST'])
def api_writing_generate():
    """v26.12 整合版 — 兼容 writing_server.py 风格, 代理到 copy_studio engine.quick_create"""
    body = request.get_json(silent=True) or {}
    core_idea = (body.get('core_idea') or body.get('description') or '').strip()
    title = body.get('title') or ''
    genre = body.get('genre') or 'novel'
    word_target = int(body.get('word_target') or body.get('word_count') or 2000)
    if not core_idea:
        return jsonify({'ok': False, 'error': '请输入核心创意'}), 400

    try:
        from engines.copy_studio.service import ApprovalService
        svc = ApprovalService()
        result = svc.quick_create(
            core_idea=core_idea, genre=genre, target_words=word_target,
            media_fmt='novel_short', title=title,
        )
    except Exception as e:
        return jsonify({'ok': False, 'error': f'copy_studio engine: {e}'}), 500

    return jsonify({
        'ok': bool(result),
        'project_id': result['project_id'] if result else None,
        'title': result['title'] if result else title,
        'content': (result.get('full_text') if result else '') or '',
        'word_count': result.get('total_words', 0) if result else 0,
        'model_used': result.get('ollama_model', 'ollama') if result else 'ollama',
        'elapsed_seconds': 0,
        'ollama_alive': result.get('ollama_ok', False) if result else False,
    })


# ═══════════════════════════════════════════════════════════════
# AI 生成辅助 (本地/模拟)
# ═══════════════════════════════════════════════════════════════

def _auto_reference_works(genre, media_fmt):
    """仙女自动匹配参考作品 (简版 — 真实应查向量库)"""
    ref_map = {
        '古言': ['《步步惊心》桐华', '《琅琊榜》海宴', '《知否知否》关心则乱'],
        '都市言情': ['《何以笙箫默》顾漫', '《他来了请闭眼》丁墨', '《欢乐颂》阿耐'],
        '悬疑推理': ['《白夜行》东野圭吾', '《心理罪》雷米', '《无证之罪》紫金陈'],
        '修真': ['《诛仙》萧鼎', '《凡人修仙传》忘语', '《仙逆》耳根'],
        '硬科幻': ['《三体》刘慈欣', '《流浪地球》刘慈欣', '《北京折叠》郝景芳'],
        '历史': ['《庆余年》猫腻', '《赘婿》愤怒的香蕉', '《家园》酒徒'],
    }
    return ref_map.get(genre, ['同类型热门作品 Top 3'])

def _auto_rhythm(media_fmt, target_words):
    """自动节奏曲线建议"""
    rhythm_map = {
        'novel_long': '紧→松→紧→爆→收 (每10章一个大转折)',
        'novel_short': '钩→升→爆→收 (3000字内闭环)',
        'movie_script': '建置(25%)→对抗(50%)→高潮(15%)→结局(10%)',
        'short_video': '0-3s钩子→3-20s冲突→20-30s反转/升华',
        'tv_script': '每集开头悬念→中间冲突→结尾钩子 (吸引下集)',
    }
    return rhythm_map.get(media_fmt, '起-承-转-合')

def _generate_outline(core_idea, genre, media_fmt, structure, target_words):
    """自动大纲 (简版 — 真实应调 AI)"""
    # 按 target_words 分段数
    if target_words >= 50000:
        parts = ['第一卷·起', '第二卷·承', '第三卷·转', '第四卷·合', '第五卷·终']
    elif target_words >= 10000:
        parts = ['第一部·建', '第二部·抗', '第三部·收']
    elif target_words >= 2000:
        parts = ['起', '承', '爆', '收']
    else:
        parts = ['起', '爆', '收']
    
    return {
        'structure': structure,
        'segments': [{'title': p, 'words': target_words // len(parts), 'hook': f'{p} 结尾留大钩子'} for p in parts],
        'character_arc': '主角: 3阶转变 (弱→觉醒→爆发) | 核心配角: 2阶弧光',
        'foreshadowing': ['开篇伏笔 X → 中段回收', '人物 Y 的真实身份 → 结局揭露'],
        'hook_density': f'每 {max(300, target_words // 10)} 字一个小钩子',
    }

def _auto_title(core_idea, genre):
    """自动标题"""
    # 简版: 取核心思想前 12 字 + 类型后缀
    clean = core_idea[:12].replace('\n', '').strip()
    suffix = {'古言':'· 玉碎宫倾','都市言情':'· 不期而遇','悬疑推理':'· 暗流涌动',
             '修真':'· 破境重生','硬科幻':'· 奇点降临'}.get(genre, '')
    return f"{clean}{suffix}" if suffix else clean

def _call_ai_generate(core_idea, params):
    """
    调用 AI 生文 — 优先本地 ollama, 失败返回模拟内容
    真实接入: ollama local_ai think engine
    """
    target = params.get('target_words', 5000)
    genre = params.get('genre', '')
    media = params.get('media_format', 'novel_short')
    
    # 先试本地 AI
    try:
        import requests as _req
        prompt = f"""你是顶级网文大神. 根据以下要求创作:

中心思想: {core_idea}
字数目标: {target} 字
类型: {genre}
体裁: {media}
结构: {params.get('structure','three_act')}
风格锚定: {params.get('style_anchor','自然流畅')}
创作建议:
  - 每300字一个小钩子
  - 人物对话占比 30-40%
  - 节奏: 紧-松-紧-爆-收

请直接输出正文, 不要解释. 开头用一个吸睛的第一段."""

        r = _req.post('http://127.0.0.1:11434/api/generate', 
                      json={'model':'qwen2.5:14b','prompt':prompt,'stream':False,
                            'options':{'num_predict':min(target*2,8000)}},
                      timeout=120)
        if r.status_code == 200:
            data = r.json()
            content = data.get('response', '')
            if len(content) > 100:
                return content, 'ollama/qwen2.5-14b'
    except Exception:
        pass
    
    # 降级返回框架内容 (占位, 真实部署时必有 AI)
    content = f"""《{_auto_title(core_idea, genre)}》

--- 创作中 ---
中心思想: {core_idea}
类型: {genre} | 体裁: {media} | 目标: {target} 字

[此处为 AI 实时生成的正文内容]

当前环境未检测到本地 AI (ollama), 已记录创作请求,
待 AI 服务启动后可通过 /api/writing/expand 继续生成.

--- 自动大纲 ---
{json.dumps(params.get('outline', {}), ensure_ascii=False, indent=2)}

--- 仙女笔记 ---
{chr(10).join(params.get('fairy_notes', []))}
"""
    return content, 'fallback-framework'

def _feed_writing_to_brain(conn, project_id, title, core_idea, genre, content):
    """投喂 AI 脑库"""
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO mt_ai_brain_feed_log 
            (flow_id, feed_target, payload_preview, feed_content, feed_kind, fed_at)
        VALUES (?,?,?,?,?,datetime('now','localtime'))""", (
            f"WRITING-{project_id}", "writing",
            f"《{title}》[{genre}] {core_idea[:50]}",
            json.dumps({'title': title, 'core_idea': core_idea, 'genre': genre,
                       'content_preview': content[:2000]}, ensure_ascii=False),
            'CULTURE_WRITING'
        ))
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════
# API: 迭代改写 (v26.12 整合版 — 代理到 copy_studio)
# ═══════════════════════════════════════════════════════════════
@gobelin_writing_bp.route('/<int:pid>/revise', methods=['POST'])
def api_writing_revise(pid):
    """迭代改写: 扩写 / 缩写 / 改风格 / 续写 — 代理到 copy_studio service.revise_chapter"""
    body = request.get_json(silent=True) or {}
    action = body.get('action', 'revise')
    instruction = body.get('instruction', '')

    # 先查 mt_copy_projects (新权威表), 再查 mt_writing_project (legacy)
    try:
        from engines.copy_studio.db import get_conn
        with get_conn() as c:
            # gobelin 的 int pid 可能是 copy_studio project_id 的后 6 位
            # 先直接查 legacy 表, 同时查 copy_studio 按标题匹配
            c.execute("SELECT * FROM mt_writing_project WHERE id=?", (pid,))
            legacy = c.fetchone()
            if legacy:
                # legacy 项目 → 在 copy_studio 里找对应项目
                c.execute("SELECT project_id FROM mt_copy_projects WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 1",
                          (f"%{legacy['title'][:15]}%",))
                copy_row = c.fetchone()
            else:
                copy_row = None

            if copy_row:
                project_id = copy_row['project_id']
                # 取最新有内容的章节来 revise
                c.execute("SELECT chapter_id FROM mt_copy_chapters WHERE project_id=? AND content IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                          (project_id,))
                ch = c.fetchone()
                if ch:
                    chapter_id = ch['chapter_id']
                else:
                    return jsonify({'success': False, 'error': 'copy_studio 项目无章节'}), 404
            elif legacy and legacy['content']:
                # legacy 项目但没迁移 → 直接返回提示
                return jsonify({'success': False, 'error': f'legacy 项目请先迁移到 copy_studio'}), 404
            else:
                return jsonify({'success': False, 'error': 'project not found (copy_studio + legacy)'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': f'db lookup error: {e}'}), 500

    # 代理到 copy_studio service
    try:
        from engines.copy_studio.service import ApprovalService
        svc = ApprovalService()
        result = svc.revise_chapter(chapter_id, action=action, instruction=instruction)
    except Exception as e:
        return jsonify({'success': False, 'error': f'copy_studio revise: {e}'}), 500

    if not result:
        return jsonify({'success': False, 'error': '改写失败 — 可能章节无正文或 AI 离线'}), 503

    return jsonify({
        'success': True,
        'data': {
            'project_id': pid,
            'chapter_id': result['chapter_id'],
            'action': action,
            'old_version_no': result.get('old_version_no'),
            'new_content': result['new_content'][:2000],
            'word_count': len(result['new_content']),
            'diff_chars': result.get('diff_chars', 0),
            'duration_sec': result.get('duration_sec', 0),
        }
    })

# ═══════════════════════════════════════════════════════════════
# API: 项目列表 / 详情 (v26.12 整合版 — 查 copy_studio 优先)
# ═══════════════════════════════════════════════════════════════
@gobelin_writing_bp.route('/projects')
def api_writing_projects():
    """我的创作项目列表 — copy_studio mt_copy_projects + legacy mt_writing_project 合并"""
    limit = min(int(request.args.get('limit', 20)), 100)
    rows = []
    try:
        from engines.copy_studio.db import get_conn
        with get_conn() as c:
            c.execute("""
                SELECT project_id as id, title, genre, target_words, current_words as word_count,
                       status, initiator, created_at, updated_at,
                       (SELECT COUNT(*) FROM mt_copy_chapters WHERE project_id=p.project_id) as chapter_count
                FROM mt_copy_projects p ORDER BY updated_at DESC LIMIT ?""", (limit,))
            for r in c.fetchall():
                d = dict(r)
                d['source'] = 'copy_studio'
                rows.append(d)
            # legacy 项目 (排除已在 copy_studio 的)
            legacy_ids = {str(r['id'])[-6:] if len(str(r['id'])) > 6 else str(r['id']) for r in rows}
            c.execute("SELECT id, title, core_idea, genre, word_count, status, created_at FROM mt_writing_project ORDER BY id DESC LIMIT ?", (limit,))
            for r in c.fetchall():
                d = dict(r)
                d['source'] = 'legacy'
                rows.append(d)
    except Exception:
        pass
    return jsonify({'success': True, 'data': rows})

@gobelin_writing_bp.route('/<int:pid>')
def api_writing_project_detail(pid):
    """项目详情 — copy_studio 优先, fallback legacy"""
    try:
        from engines.copy_studio.db import get_conn
        with get_conn() as c:
            # 先查 legacy int pid
            c.execute("SELECT * FROM mt_writing_project WHERE id=?", (pid,))
            legacy = c.fetchone()
            # 查 copy_studio 按标题匹配
            copy_proj = None
            if legacy and legacy['title']:
                c.execute("SELECT * FROM mt_copy_projects WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 1",
                          (f"%{legacy['title'][:15]}%",))
                copy_proj = c.fetchone()
            if not copy_proj:
                # 也查 copy_studio project_id 的后几位匹配 pid
                c.execute("SELECT * FROM mt_copy_projects WHERE substr(project_id, -6)=?", (str(pid).zfill(6),))
                copy_proj = c.fetchone()
    except Exception as e:
        return jsonify({'success': False, 'error': f'db error: {e}'}), 500

    if not copy_proj and not legacy:
        return jsonify({'success': False, 'error': 'not found'}), 404

    # copy_studio 优先
    if copy_proj:
        try:
            from engines.copy_studio.service import ApprovalService
            svc = ApprovalService()
            p = svc.get_project(copy_proj['project_id'])
            chapters = svc.list_chapters(copy_proj['project_id'])
            return jsonify({'success': True, 'data': {'project': p, 'chapters': chapters, 'source': 'copy_studio'}})
        except Exception:
            pass

    # fallback legacy
    legacy_dict = dict(legacy) if legacy else {}
    for k in ['outline', 'ip_extensions']:
        if legacy_dict.get(k):
            try: legacy_dict[k] = json.loads(legacy_dict[k])
            except: pass
    return jsonify({'success': True, 'data': {'project': legacy_dict, 'source': 'legacy'}})

# ═══════════════════════════════════════════════════════════════
# API: 导出 (v26.12 整合版 — 代理到 copy_studio service.export_project)
# ═══════════════════════════════════════════════════════════════
@gobelin_writing_bp.route('/<int:pid>/export/<fmt>')
def api_writing_export(pid, fmt):
    """导出格式: txt / md / json — copy_studio 优先, fallback legacy"""
    if fmt not in ('txt', 'md', 'json'):
        return jsonify({'success': False, 'error': f'unknown fmt: {fmt}'}), 400

    # 先定位到 copy_studio project_id
    copy_pid = None
    try:
        from engines.copy_studio.db import get_conn
        with get_conn() as c:
            c.execute("SELECT project_id FROM mt_copy_projects WHERE substr(project_id, -6)=?", (str(pid).zfill(6),))
            row = c.fetchone()
            if row: copy_pid = row['project_id']
            if not copy_pid:
                c.execute("SELECT title FROM mt_writing_project WHERE id=?", (pid,))
                legacy_title = (c.fetchone() or [None])[0]
                if legacy_title:
                    c.execute("SELECT project_id FROM mt_copy_projects WHERE title LIKE ? ORDER BY updated_at DESC LIMIT 1",
                              (f"%{legacy_title[:15]}%",))
                    row = c.fetchone()
                    if row: copy_pid = row['project_id']
    except Exception:
        pass

    if copy_pid:
        try:
            from engines.copy_studio.service import ApprovalService
            svc = ApprovalService()
            raw = svc.export_project(copy_pid, fmt)
            return jsonify({'success': True, 'content': raw.decode('utf-8'), 'project_id': copy_pid, 'fmt': fmt})
        except Exception as e:
            return jsonify({'success': False, 'error': f'copy_studio export: {e}'}), 500

    # fallback legacy
    try:
        from engines.copy_studio.db import get_conn
        with get_conn() as c:
            c.execute("SELECT * FROM mt_writing_project WHERE id=?", (pid,))
            proj = c.fetchone()
        if not proj:
            return jsonify({'success': False, 'error': 'not found'}), 404
        content = proj['content'] or ''
        if fmt == 'md':
            content = f"# 《{proj['title']}》\n\n{content}"
        return jsonify({'success': True, 'content': content, 'filename': f"{proj['title']}.{fmt}"})
    except Exception as e:
        return jsonify({'success': False, 'error': f'legacy fallback failed: {e}'}), 500

# ═══════════════════════════════════════════════════════════════
# 注册函数
# ═══════════════════════════════════════════════════════════════
def register_gobelin_writing_bp(app):
    """注册到 Flask app"""
    app.register_blueprint(gobelin_writing_bp)
    _init_tables()
    return True

_init_tables()  # 模块加载时就建表
print("✅ gobelin_writing_bp 加载完成 — 古灵阁网文创作系统")
