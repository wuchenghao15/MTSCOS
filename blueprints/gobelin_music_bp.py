#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古灵阁 · 囚牛音乐工作室 (gobelin_music_bp.py)
===============================================
文生音乐全管线: 情绪 → 歌词 → 旋律骨架 → 配器 → 结构 → 播放建议
输出: 完整歌曲策划案 + 歌词 + 编曲描述 + AI 生成音频提示词

依赖: Ollama (127.0.0.1:11434) 本地推理
注册: register_gobelin_music_bp(app)
"""
from __future__ import annotations
import os, json, sqlite3, time, uuid, datetime
from flask import Blueprint, jsonify, request, current_app

gobelin_music_bp = Blueprint('gobelin_music', __name__, url_prefix='/api/music')

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'app.db')
_OLLAMA = 'http://127.0.0.1:11434'
_DEFAULT_MODEL = os.environ.get('GOBELIN_MODEL', 'qwen2.5:7b')

# ═══════════════════════════════════════════════════════════════
# 音乐模板库
# ═══════════════════════════════════════════════════════════════

GENRE_TAGS = [
    '流行 Pop', '摇滚 Rock', '电子 EDM', '嘻哈 Hip-Hop', 'R&B 节奏布鲁斯',
    '民谣 Folk', '古典 Classical', '爵士 Jazz', '蓝调 Blues', '乡村 Country',
    '金属 Metal', '朋克 Punk', '灵魂 Soul', '放克 Funk', '雷鬼 Reggae',
    '拉丁 Latin', 'K-Pop', 'J-Pop', 'C-Pop 国风', '游戏原声 OST',
    '电影配乐', 'Lo-Fi Chill', '氛围 Ambient', 'Dubstep', 'House',
    'Techno', 'Trance 恍惚', 'Folk Rock', 'Indie', 'EMO', '后摇滚 Post-Rock',
    '中国风古风', '国风电子', '禅意音乐', '冥想音乐', '儿童音乐',
]

MOODS = [
    {'key':'uplift','label':'🎈 欢快激昂','bpm':'120-140','energy':'high','description':'开心、乐观、庆祝'},
    {'key':'melancholy','label':'🌧️ 忧伤诗意','bpm':'60-80','energy':'low','description':'怀旧、伤感、离别'},
    {'key':'romance','label':'💝 浪漫甜蜜','bpm':'75-95','energy':'medium','description':'恋爱、表白、心动'},
    {'key':'epic','label':'⚔️ 史诗壮阔','bpm':'100-130','energy':'high','description':'英雄、征途、荣耀'},
    {'key':'chill','label':'🌿 慵懒放松','bpm':'70-90','energy':'low','description':'休闲、咖啡馆、雨后'},
    {'key':'dark','label':'🕷️ 暗黑神秘','bpm':'80-110','energy':'medium-low','description':'悬疑、夜曲、哥特'},
    {'key':'groove','label':'🕺 动感摇摆','bpm':'110-130','energy':'high','description':'舞曲、派对、Disco'},
    {'key':'heal','label':'🌸 治愈温暖','bpm':'65-85','energy':'low','description':'冥想、疗愈、睡前'},
    {'key':'fire','label':'🔥 热血炸裂','bpm':'140-180','energy':'very_high','description':'战斗、竞速、极限'},
    {'key':'nostalgia','label':'📷 怀旧复古','bpm':'80-100','energy':'medium','description':'80s/90s、童年、记忆'},
]

STRUCTURES = [
    {'key':'pop_standard','label':'流行标准','pattern':'Verse1-Pre1-Chorus1-Verse2-Pre2-Chorus2-Bridge-Chorus3-Outro'},
    {'key':'ballad','label':'抒情慢歌','pattern':'Intro-Verse1-Pre1-Chorus1-Verse2-Chorus2-Bridge-Chorus-Outro'},
    {'key':'edm','label':'电子舞曲','pattern':'Intro-Buildup-Drop-Breakdown-Buildup-Drop2-Outro'},
    {'key':'hiphop','label':'嘻哈标准','pattern':'Intro-Verse1-Chorus-Verse2-Chorus-Bridge-Chorus-Outro'},
    {'key':'epic','label':'史诗叙事','pattern':'Overture-Act1-Refrain-Act2-Refrain-Battle-Refrain-End'},
    {'key':'minimal','label':'极简氛围','pattern':'Intro-Theme1-Variation1-Theme2-Variation2-Outro'},
    {'key':'round','label':'轮唱回旋','pattern':'A-B-A-B-A-Coda'},
]

INSTRUMENTS = [
    '钢琴 Piano', '吉他 Guitar', '电吉他 E.Guitar', '贝斯 Bass', '架子鼓 Drums',
    '合成器 Synth', '弦乐 Strings', '小提琴 Violin', '大提琴 Cello', '管风琴 Organ',
    '口琴 Harmonica', '萨克斯 Saxophone', '小号 Trumpet', '长笛 Flute', '单簧管 Clarinet',
    '二胡 Erhu', '古筝 Guzheng', '琵琶 Pipa', '笛子 Dizi', '古琴 Guqin',
    '木鱼 Woodblock', '锣 Gong', '电子鼓 E-Drums', '打击乐 Percussion',
    '人声合唱 Choir', '电钢 Electric Piano', '钢片琴 Celesta', '颤音琴 Vibraphone',
]

# ═══════════════════════════════════════════════════════════════
# DB
# ═══════════════════════════════════════════════════════════════

def _db():
    conn = sqlite3.connect(_DB, timeout=10)
    conn.execute('PRAGMA busy_timeout=10000')
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_tables():
    conn = _db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS mt_gobelin_music_project (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, core_idea TEXT, genre TEXT, mood TEXT, structure_key TEXT,
        bpm INTEGER DEFAULT 90, key_sig TEXT DEFAULT 'C',
        vocal_style TEXT, instruments TEXT, lyrics TEXT,
        melody_outline TEXT, arrangement TEXT, ai_prompt TEXT,
        model_used TEXT, status TEXT DEFAULT 'created',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS mt_gobelin_music_section (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, section_order INTEGER, section_name TEXT,
        lyrics TEXT, melody_hint TEXT, chord_prog TEXT, duration_sec INTEGER,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(project_id) REFERENCES mt_gobelin_music_project(id)
    )''')
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════
# Ollama
# ═══════════════════════════════════════════════════════════════

def _ollama_available():
    try:
        import requests
        r = requests.get(f'{_OLLAMA}/api/tags', timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def _call_ollama(prompt, model=None, num_predict=4000, temp=0.8):
    import requests
    model = model or _DEFAULT_MODEL
    payload = {'model': model, 'prompt': prompt, 'stream': False,
               'options': {'num_predict': num_predict, 'temperature': temp}}
    try:
        r = requests.post(f'{_OLLAMA}/api/generate', json=payload, timeout=300)
        if r.status_code == 200:
            return r.json().get('response', ''), True
        return f'Ollama HTTP {r.status_code}', False
    except Exception as e:
        return f'Ollama 调用失败: {e}', False

# ═══════════════════════════════════════════════════════════════
# 管线
# ═══════════════════════════════════════════════════════════════

_FULL_PROMPT = """你是格莱美获奖级别的全才音乐制作人 + 作词人 + 作曲家。

项目需求:
- 标题: {title}
- 核心主题: {idea}
- 风格流派: {genre}
- 情绪基调: {mood}
- 结构模板: {structure}
- 速度(BPM): {bpm}
- 调性: {key_sig}
- 演唱风格: {vocal_style}
- 主要乐器: {instruments}

请输出一份完整的音乐策划案 Markdown, 包含:

## 1. 歌曲概述
{2-3句概述 + 整体感觉关键词}

## 2. 全曲结构与时长分配
{按 {structure} 展开每个段落的角色和预估时长}

## 3. 完整歌词
{标注段落标签 [Verse 1], [Pre-Chorus 1], [Chorus 1], [Bridge] 等}

## 4. 旋律骨架
{每个段落的音域走势、高潮位置、hook 描述}

## 5. 和弦走向
{每个段落的和弦, 用罗马数字或字母表}

## 6. 编曲方案
{配器分层 + 各乐器在何处进入/退出 + 动态变化}

## 7. AI 音乐生成 Prompt
{一段可直接用于 Suno/Udio/MusicGen/Stable Audio 等 AI 音乐工具的英文 prompt}

要求:
- 歌词要有记忆点, 副歌必须抓耳
- 旋律走向符合情绪曲线
- 编曲要有层次变化, 不是平铺直叙
- AI Prompt 要包含风格/情绪/乐器/速度/结构描述

直接输出 Markdown, 不要解释:"""

def _gen_full_track(title, idea, genre, mood, structure, bpm, key_sig, vocal, instruments, model=None):
    prompt = _FULL_PROMPT.format(
        title=title or idea[:20], idea=idea, genre=genre, mood=mood,
        structure=structure, bpm=bpm, key_sig=key_sig,
        vocal_style=vocal, instruments=instruments
    )
    return _call_ollama(prompt, model=model, num_predict=6000, temp=0.75)

# ═══════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════

@gobelin_music_bp.route('/health')
def health():
    alive = _ollama_available()
    return jsonify({
        'service': '古灵阁 · 囚牛音乐工作室',
        'ollama_alive': alive,
        'model': _DEFAULT_MODEL,
        'db': os.path.exists(_DB),
        'timestamp': datetime.datetime.now().isoformat()
    })

@gobelin_music_bp.route('/genres')
def list_genres():
    return jsonify({
        'genres': GENRE_TAGS,
        'moods': MOODS,
        'structures': STRUCTURES,
        'instruments': INSTRUMENTS
    })

@gobelin_music_bp.route('/generate', methods=['POST'])
def generate():
    """完整歌曲生成"""
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get('title') or '').strip()
    idea = (data.get('core_idea') or '').strip()
    genre = data.get('genre') or '流行 Pop'
    mood = data.get('mood') or 'uplift'
    structure = data.get('structure_key') or 'pop_standard'
    bpm = int(data.get('bpm') or 0)
    key_sig = data.get('key_sig') or 'C'
    vocal = data.get('vocal_style') or '磁性女声'
    instruments = data.get('instruments') or '钢琴,吉他,合成器,架子鼓'
    model = data.get('model') or _DEFAULT_MODEL

    # 自动补 BPM
    if bpm <= 0:
        mood_obj = next((m for m in MOODS if m['key'] == mood), None)
        if mood_obj:
            bpm = int(mood_obj['bpm'].split('-')[0])
        else:
            bpm = 90

    # 解析 mood label
    mood_label = mood
    mood_obj = next((m for m in MOODS if m['key'] == mood), None)
    if mood_obj:
        mood_label = mood_obj['label']

    if not idea:
        return jsonify({'ok': False, 'error': '请输入核心创意'}), 400
    if not title:
        title = idea[:20]

    # 解析结构 pattern
    struct_pattern = structure
    struct_obj = next((s for s in STRUCTURES if s['key'] == structure), None)
    if struct_obj:
        struct_pattern = f"{struct_obj['label']} ({struct_obj['pattern']})"

    t0 = time.time()
    content, ok = _gen_full_track(title, idea, genre, mood_label, struct_pattern,
                                   bpm, key_sig, vocal, instruments, model)
    elapsed = time.time() - t0

    # 存库
    conn = _db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO mt_gobelin_music_project
        (title, core_idea, genre, mood, structure_key, bpm, key_sig,
         vocal_style, instruments, lyrics, melody_outline, arrangement, ai_prompt,
         model_used, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (title, idea, genre, mood_label, structure, bpm, key_sig,
         vocal, instruments, content[:2000], content[:1500], content[:1500], content[:500],
         model, 'completed' if ok else 'failed'))
    pid = cur.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        'ok': ok,
        'project_id': pid,
        'title': title,
        'genre': genre,
        'mood': mood_label,
        'bpm': bpm,
        'key': key_sig,
        'content': content,
        'elapsed': round(elapsed, 1),
        'error': None if ok else content,
        'ai_tools': ['Suno AI', 'Udio', 'MusicGen', 'Stable Audio', 'Riffusion', 'Magenta'],
        'note': '使用「AI 音乐生成 Prompt」章节喂给 Suno/Udio 即可出音频',
    })

@gobelin_music_bp.route('/projects')
def list_projects():
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT id,title,genre,mood,bpm,key_sig,status,created_at FROM mt_gobelin_music_project ORDER BY id DESC LIMIT 30')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'ok': True, 'projects': rows})

@gobelin_music_bp.route('/<int:pid>')
def get_project(pid):
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM mt_gobelin_music_project WHERE id=?', (pid,))
    p = cur.fetchone()
    if not p:
        conn.close()
        return jsonify({'ok': False, 'error': 'not found'}), 404
    cur.execute('SELECT * FROM mt_gobelin_music_section WHERE project_id=? ORDER BY section_order', (pid,))
    sections = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'ok': True, 'project': dict(p), 'sections': sections})

# ═══════════════════════════════════════════════════════════════

def register_gobelin_music_bp(app):
    _ensure_tables()
    app.register_blueprint(gobelin_music_bp)

print("✅ gobelin_music_bp 加载完成 — 古灵阁 · 囚牛音乐工作室")
