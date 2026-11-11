#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古灵阁 · 青龙影视传媒视频制作系统 (gobelin_video_bp.py)
=========================================================
文生视频全管线: 创意 → 分镜脚本 → 画面描述 → 旁白/配音 → 音乐节奏建议
输出: 短视频脚本 / 电影分镜 / 广告脚本 / 短视频剧本 (抖音/视频号/TikTok)

依赖: Ollama (127.0.0.1:11434) 本地推理
注册: register_gobelin_video_bp(app)
"""
from __future__ import annotations
import os, json, sqlite3, time, uuid, datetime
from flask import Blueprint, jsonify, request, current_app

gobelin_video_bp = Blueprint('gobelin_video', __name__, url_prefix='/api/video')

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'database', 'app.db')
_OLLAMA = 'http://127.0.0.1:11434'
_DEFAULT_MODEL = os.environ.get('GOBELIN_MODEL', 'qwen2.5:7b')

# ═══════════════════════════════════════════════════════════════
# 影视模板库
# ═══════════════════════════════════════════════════════════════

VIDEO_FORMATS = [
    {'key':'douyin_vertical','label':'📱 抖音竖屏','ratio':'9:16','dur':'15-60s','shots':'5-10'},
    {'key':'tiktok_vertical','label':'🎵 TikTok 竖屏','ratio':'9:16','dur':'15-60s','shots':'5-10'},
    {'key':'video_hort','label':'👁️ 视频号横屏','ratio':'16:9','dur':'1-5min','shots':'10-20'},
    {'key':'reel','label':'📸 Instagram Reel','ratio':'9:16','dur':'15-30s','shots':'3-6'},
    {'key':'youtube_short','label':'▶️ YouTube Shorts','ratio':'9:16','dur':'60s','shots':'5-8'},
    {'key':'film_trailer','label':'🎬 电影预告片','ratio':'2.39:1','dur':'1.5-2.5min','shots':'15-25'},
    {'key':'tv_pilot','label':'📺 电视剧试播集','ratio':'16:9','dur':'20-45min','shots':'40-80'},
    {'key':'commercial','label':'📢 品牌广告','ratio':'16:9','dur':'15-60s','shots':'5-12'},
    {'key':'documentary','label':'📹 纪录片','ratio':'16:9','dur':'5-30min','shots':'30-60'},
    {'key':'mukbang','label':'🍜 美食探店','ratio':'16:9','dur':'5-10min','shots':'20-40'},
    {'key':'tutorial','label':'📚 知识教程','ratio':'16:9','dur':'3-10min','shots':'15-30'},
    {'key':'vlog','label':'🎥 个人Vlog','ratio':'16:9','dur':'3-15min','shots':'20-50'},
]

VISUAL_STYLES = [
    '电影感胶片', '高饱和霓虹', '日系小清新', '赛博朋克', '复古港风',
    '水墨中国风', '扁平化简约', '3D渲染写实', '像素复古', '手绘动画',
    '暗黑哥特', '北欧极简', '街头运动风', '青春校园', '商业大片质感',
    '恐怖悬疑低光', '婚礼浪漫柔焦', '科技未来感', '自然纪录片', '时尚杂志大片',
]

EMOTION_CURVES = [
    {'key':'joy_rush','label':'爽感飙升','curve':'平→升→爆','peak_end':True},
    {'key':'heartwarm','label':'温暖治愈','curve':'低→缓升→稳','peak_end':False},
    {'key':'tension_release','label':'紧张释放','curve':'平→悬念→反转','peak_end':True},
    {'key':'melancholy','label':'细腻伤感','curve':'高→降→余韵','peak_end':False},
    {'key':'shock','label':'惊悚震撼','curve':'平→平→炸','peak_end':True},
    {'key':'laugh','label':'喜剧爆笑','curve':'笑点密集','peak_end':True},
    {'key':'awe','label':'史诗震撼','curve':'缓升→壮阔→留白','peak_end':True},
    {'key':'inspire','label':'励志燃情','curve':'低谷→挣扎→逆袭','peak_end':True},
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
    cur.execute('''CREATE TABLE IF NOT EXISTS mt_gobelin_video_project (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, core_idea TEXT, format_key TEXT, format_label TEXT,
        style TEXT, emotion TEXT, target_dur INTEGER DEFAULT 60,
        model_used TEXT, status TEXT DEFAULT 'created',
        shot_list TEXT, voiceover TEXT, bgm_mood TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS mt_gobelin_video_shot (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER, shot_no INTEGER,
        duration_sec REAL, camera_angle TEXT, movement TEXT,
        subject_prompt TEXT, visual_desc TEXT, audio_prompt TEXT,
        subtitle TEXT, sfx_hint TEXT, transition_in TEXT, transition_out TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(project_id) REFERENCES mt_gobelin_video_project(id)
    )''')
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════════
# Ollama 调用
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
# 管线: 创意 → 分镜 → 画面 → 旁白
# ═══════════════════════════════════════════════════════════════

_SHOT_PROMPT = """你是好莱坞 A-list 分镜师。根据以下项目需求, 生成详细分镜表。

标题: {title}
核心创意: {idea}
视频格式: {format}
视觉风格: {style}
情绪曲线: {emotion}
目标时长: {dur}秒

输出 JSON 数组, 每个元素是一个分镜 shot, 包含字段:
- shot_no: 镜头序号
- duration_sec: 时长(秒)
- camera_angle: 机位 (特写/中景/全景/航拍/低角度/过肩/POV)
- movement: 运动方式 (固定/推/拉/摇/移/跟/手持/稳定器)
- subject_prompt: 画面主体 (给 AI 视频生成的 prompt, 英文或中文详细描述)
- visual_desc: 视觉描述 (灯光/构图/色彩/氛围)
- audio_prompt: 音效/环境音提示
- subtitle: 字幕/对白 (如有)
- transition_in: 入场过渡 (硬切/淡入/叠化/匹配剪辑)
- transition_out: 出场过渡

要求:
1. 分镜数量匹配目标时长 (约 {shot_count} 个)
2. 情绪曲线严格遵循 {emotion} 的节奏
3. subject_prompt 要足够详细, 可直接用于 AI 视频/图片生成
4. 画面之间要有视觉连贯性

直接输出 JSON, 不要解释: """

def _gen_shots(title, idea, fmt_label, style, emotion, dur, model=None):
    estimated = max(3, min(30, int(dur / 5)))
    prompt = _SHOT_PROMPT.format(
        title=title, idea=idea, format=fmt_label,
        style=style, emotion=emotion, dur=dur, shot_count=estimated
    )
    raw, ok = _call_ollama(prompt, model=model, num_predict=5000, temp=0.7)
    if not ok:
        return None, raw
    # 尝试从输出里提取 JSON
    import re
    json_str = raw
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if m:
        json_str = m.group()
    try:
        shots = json.loads(json_str)
        return shots, None
    except json.JSONDecodeError as e:
        return None, f'JSON 解析失败: {e}'

_VO_PROMPT = """你是金牌配音导演 + 作词家。根据以下视频项目, 生成配音脚本。

标题: {title}
核心创意: {idea}
情绪基调: {emotion}
分镜摘要: {shots_summary}

请生成:
1. 旁白/对白脚本 (分段标注在哪个镜头说)
2. 建议的 BGM 情绪/风格/节奏描述
3. 可选的片头/片尾金句 (适合做标题党或结尾彩蛋)
4. 整体配音语速/音色建议 (如: 低沉磁性女声, 语速舒缓)

直接输出 Markdown 格式, 分四个部分。"""

def _gen_voiceover(title, idea, emotion, shots, model=None):
    summary = ''
    for s in (shots or [])[:8]:
        summary += f"  镜头{s.get('shot_no','?')} ({s.get('duration_sec','?')}s): {s.get('subject_prompt','')[:60]}\n"
    prompt = _VO_PROMPT.format(title=title, idea=idea, emotion=emotion, shots_summary=summary or 'N/A')
    return _call_ollama(prompt, model=model, num_predict=2000, temp=0.6)

# ═══════════════════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════════════════

@gobelin_video_bp.route('/health')
def health():
    alive = _ollama_available()
    return jsonify({
        'service': '古灵阁 · 青龙影视传媒',
        'ollama_alive': alive,
        'model': _DEFAULT_MODEL,
        'db': os.path.exists(_DB),
        'timestamp': datetime.datetime.now().isoformat()
    })

@gobelin_video_bp.route('/formats')
def list_formats():
    return jsonify({
        'formats': VIDEO_FORMATS,
        'styles': VISUAL_STYLES,
        'emotions': EMOTION_CURVES
    })

@gobelin_video_bp.route('/generate', methods=['POST'])
def generate():
    """完整视频脚本生成: 创意 → 分镜 → 配音"""
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get('title') or '').strip()
    idea = (data.get('core_idea') or '').strip()
    fmt_key = data.get('format_key') or 'douyin_vertical'
    style = data.get('style') or '电影感胶片'
    emotion = data.get('emotion') or '爽感飙升'
    dur = int(data.get('target_dur') or 60)
    model = data.get('model') or _DEFAULT_MODEL
    skip_vo = data.get('skip_voiceover', False)

    if not idea:
        return jsonify({'ok': False, 'error': '请输入核心创意'}), 400
    if not title:
        title = idea[:20]

    fmt_label = next((f['label'] for f in VIDEO_FORMATS if f['key'] == fmt_key), fmt_key)

    t0 = time.time()
    shots, err = _gen_shots(title, idea, fmt_label, style, emotion, dur, model)
    vo_text, vo_err = '', None
    if shots and not skip_vo:
        vo_text, vo_ok = _gen_voiceover(title, idea, emotion, shots, model)
        vo_err = None if vo_ok else vo_text

    elapsed = time.time() - t0

    # 存库
    shots_json = json.dumps(shots or [], ensure_ascii=False)
    conn = _db()
    cur = conn.cursor()
    cur.execute('''INSERT INTO mt_gobelin_video_project
        (title, core_idea, format_key, format_label, style, emotion, target_dur,
         model_used, status, shot_list, voiceover)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (title, idea, fmt_key, fmt_label, style, emotion, dur,
         model, 'completed' if shots else 'failed',
         shots_json, vo_text))
    pid = cur.lastrowid

    if shots:
        for s in shots:
            cur.execute('''INSERT INTO mt_gobelin_video_shot
                (project_id, shot_no, duration_sec, camera_angle, movement,
                 subject_prompt, visual_desc, audio_prompt, subtitle, transition_in, transition_out)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (pid, s.get('shot_no'), s.get('duration_sec'),
                 s.get('camera_angle'), s.get('movement'),
                 s.get('subject_prompt'), s.get('visual_desc'),
                 s.get('audio_prompt'), s.get('subtitle'),
                 s.get('transition_in'), s.get('transition_out')))
    conn.commit()
    conn.close()

    return jsonify({
        'ok': shots is not None,
        'project_id': pid,
        'title': title,
        'format': fmt_label,
        'style': style,
        'emotion': emotion,
        'target_dur': dur,
        'shot_count': len(shots) if shots else 0,
        'shots': shots or [],
        'voiceover': vo_text,
        'elapsed': round(elapsed, 1),
        'error': err or vo_err,
        'note': 'subject_prompt 可直接喂给 AI 视频生成工具 (Runway/Kling/Sora 等)' if shots else None,
    })

@gobelin_video_bp.route('/projects')
def list_projects():
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT id,title,format_label,style,emotion,target_dur,shot_count,status,created_at FROM mt_gobelin_video_project ORDER BY id DESC LIMIT 30')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'ok': True, 'projects': rows})

@gobelin_video_bp.route('/<int:pid>')
def get_project(pid):
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM mt_gobelin_video_project WHERE id=?', (pid,))
    p = cur.fetchone()
    if not p:
        conn.close()
        return jsonify({'ok': False, 'error': 'not found'}), 404
    cur.execute('SELECT * FROM mt_gobelin_video_shot WHERE project_id=? ORDER BY shot_no', (pid,))
    shots = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'ok': True, 'project': dict(p), 'shots': shots})

@gobelin_video_bp.route('/<int:pid>/shots.json')
def export_shots(pid):
    """导出分镜为 JSON, 供 AI 视频生成管线使用"""
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM mt_gobelin_video_project WHERE id=?', (pid,))
    p = cur.fetchone()
    if not p:
        conn.close()
        return jsonify({'ok': False}), 404
    cur.execute('SELECT * FROM mt_gobelin_video_shot WHERE project_id=? ORDER BY shot_no', (pid,))
    shots = [dict(r) for r in cur.fetchall()]
    conn.close()
    out = {
        'project': {k: p[k] for k in p.keys() if k != 'shot_list' and k != 'voiceover'},
        'shots': shots,
        'exported_at': datetime.datetime.now().isoformat(),
        'ai_video_tools': ['Runway Gen-3', 'Kling AI', 'Sora', 'Pika', 'Veo', 'Stable Video Diffusion'],
    }
    return jsonify(out)

# ═══════════════════════════════════════════════════════════════

def register_gobelin_video_bp(app):
    _ensure_tables()
    app.register_blueprint(gobelin_video_bp)

print("✅ gobelin_video_bp 加载完成 — 古灵阁 · 青龙影视传媒视频制作系统")
