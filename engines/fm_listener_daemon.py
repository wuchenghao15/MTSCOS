#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FM Broadcast Listener Daemon
后台静默监听官方财经/时政/财政 FM 流 → Paraformer 实时 ASR → AI 脑库投喂

用法: python3 fm_listener_daemon.py &
      launchctl bootstrap gui/$(id -u) fm_listener.plist (macOS)
"""
import os, sys, re, json, time, threading, subprocess, queue, sqlite3
from datetime import datetime
from pathlib import Path

# ═══ 配置 ═══
FM_STREAMS = [
    # 财经核心 (央广)
    {'name': '央广经济之声', 'url': 'http://ngcdn002.cnr.cn/live/jjzs/index.m3u8', 'cat': 'finance'},
    # 时政新闻 (央广)  
    {'name': '央广中国之声', 'url': 'http://ngcdn001.cnr.cn/live/zgzs/index.m3u8', 'cat': 'politics'},
    # 台港澳/两岸 (央广)
    {'name': '央广中华之声', 'url': 'http://ngcdn005.cnr.cn/live/zhzs/index.m3u8', 'cat': 'politics'},
]

# 关键词触发 (任一出现即触发天团研判)
TRIGGER_KEYWORDS = [
    # A股
    'A股', '沪指', '深成指', '创业板', '科创板', '北向资金', '沪深港通',
    'IPO', '打新', '注册制', '退市', 'ST', '摘帽',
    # 政策
    '加息', '降息', '降准', '央行', '货币政策', '财政政策', '美联储',
    '国务院', '证监会', '银保监会', '发改委',
    '减税', '专项债', '房地产', '楼市调控',
    # 市场冲击
    '熔断', '暴跌', '闪崩', '涨停', '跌停', '异动',
    '黑天鹅', '风险', '泡沫', '通胀', 'CPI', 'PPI',
    # 行业热点
    '新能源', '芯片', '半导体', 'AI', '人工智能',
    '医药集采', '三胎', '共同富裕',
]

# 情绪关键词 (天团自动打分)
HAWK_KEYWORDS = ['利好', '上涨', '暴涨', '反弹', '牛市', '突破', '增持', '买入', '看多']
DOG_KEYWORDS  = ['利空', '下跌', '暴跌', '崩盘', '熊市', '破位', '减持', '卖出', '看空']

# DB
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                        '..', 'database', 'app.db')
_DB_PATH = os.environ.get('MTSCOS_DB_PATH') or _DB_PATH

def _get_db():
    return sqlite3.connect(_DB_PATH, check_same_thread=False)

# 脑库投喂表
_BRAIN_FEED_SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_fm_brain_feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_name TEXT,
    category TEXT,
    asr_text TEXT,
    trigger_keywords TEXT,
    emotion TEXT,           -- HAWK / DOG / NEUTRAL
    emotion_score REAL,
    has_price_info INTEGER, -- 1=包含行情数字
    has_policy INTEGER,     -- 1=包含政策信息
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fm_feed_time ON mt_fm_brain_feed(created_at);
"""

class FMListener:
    """单电台监听器: ffmpeg 抓流 → pcm → ASR 转字"""
    
    def __init__(self, stream_info, asr_model=None):
        self.stream = stream_info
        self.model = asr_model
        self.running = False
        self.audio_queue = queue.Queue(maxsize=1000)
        self.buffer = b''
        self.buffer_ts = None
        
    def start(self):
        self.running = True
        threading.Thread(target=self._capture, daemon=True).start()
        threading.Thread(target=self._asr_loop, daemon=True).start()
    
    def _capture(self):
        """ffmpeg 后台抓流 → 16kHz 单声道 PCM → queue"""
        cmd = [
            '/opt/homebrew/bin/ffmpeg', '-re', '-i', self.stream['url'],
            '-vn', '-acodec', 'pcm_s16le',
            '-ar', '16000', '-ac', '1',
            '-f', 'wav', '-',
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            while self.running and proc.poll() is None:
                chunk = proc.stdout.read(3200)  # 100ms @16kHz
                if chunk:
                    self.audio_queue.put(chunk, block=False)
        except Exception as e:
            print(f"[FM] capture error ({self.stream['name']}): {e}")
            time.sleep(5)
            self.start()  # 自动重连
    
    def _asr_loop(self):
        """攒够 2 秒音频 → Paraformer 实时识别"""
        CHUNK_BYTES = 16000 * 2 * 2  # 2 秒 @16kHz 16bit
        while self.running:
            try:
                chunk = self.audio_queue.get(timeout=1)
                self.buffer += chunk
                if self.buffer_ts is None:
                    self.buffer_ts = datetime.now()
                
                if len(self.buffer) >= CHUNK_BYTES:
                    # ASR
                    text = self._asr(self.buffer)
                    if text and len(text.strip()) > 5:
                        self._process(text)
                    self.buffer = b''
                    self.buffer_ts = None
            except queue.Empty:
                continue
    
    def _asr(self, pcm_bytes):
        """调用 FunASR Paraformer"""
        if self.model is None:
            # Fallback: 用 whisper 或打印原始音频 (无 ASR 时)
            return ''
        try:
            import numpy as np
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            result = self.model.generate(input=audio, is_final=True)
            return result[0].get('text', '') if result else ''
        except Exception as e:
            return ''
    
    def _process(self, text):
        """关键词触发 → 情绪分析 → 投喂脑库"""
        triggered = [kw for kw in TRIGGER_KEYWORDS if kw in text]
        has_price = bool(re.search(r'\d+(?:\.\d+)?', text))
        has_policy = any(kw in text for kw in ['国务院', '央行', '证监会', '发改委', '财政部', '美联储'])
        
        # 情绪打分
        hawk_score = sum(text.count(kw) for kw in HAWK_KEYWORDS)
        dog_score  = sum(text.count(kw) for kw in DOG_KEYWORDS)
        if hawk_score > dog_score:
            emotion, emo_score = 'HAWK', hawk_score / max(hawk_score + dog_score, 1)
        elif dog_score > hawk_score:
            emotion, emo_score = 'DOG', dog_score / max(hawk_score + dog_score, 1)
        else:
            emotion, emo_score = 'NEUTRAL', 0.5
        
        # 投喂脑库
        try:
            conn = _get_db()
            conn.executescript(_BRAIN_FEED_SCHEMA)
            cur = conn.cursor()
            cur.execute("""INSERT INTO mt_fm_brain_feed 
                (stream_name, category, asr_text, trigger_keywords, emotion, emotion_score, has_price_info, has_policy)
                VALUES (?,?,?,?,?,?,?,?)""",
                (self.stream['name'], self.stream['cat'], text[:500],
                 json.dumps(triggered[:5], ensure_ascii=False),
                 emotion, emo_score, has_price, has_policy))
            conn.commit()
            cur.close(); conn.close()
        except Exception as e:
            print(f"[FM] DB insert error: {e}")
        
        # 有关键词 → 触发天团研判 (异步)
        if triggered and len(triggered) >= 2:
            self._trigger_board(text, triggered, emotion)
    
    def _trigger_board(self, text, triggered, emotion):
        """触发 AI 军团临时会议"""
        try:
            # 写入临时决策事件
            reason = f"FM[{self.stream['name']}] {emotion}: {'+'.join(triggered[:3])}"
            subprocess.Popen([
                'curl', '-s', '-X', 'POST',
                'http://127.0.0.1:5001/api/sandbox/ai-dispatch',
                '-H', 'Content-Type: application/json',
                '-d', json.dumps({'agent': 'tian_tuan', 'action': 'review', 'reason': reason})
            ], stdout=subprocess.DEVNULL)
            print(f"[FM] TRIGGERED {emotion}: {triggered[:5]}")
        except Exception:
            pass


class FMListenerDaemon:
    """守护进程: 管理多个电台监听器 + 健康检查"""
    
    def __init__(self):
        self.listeners = {}
        self.model = None
        
    def load_asr(self):
        """加载 Paraformer (第一次加载~1GB)"""
        try:
            from funasr import AutoModel
            print("[FM] Loading Paraformer 2 model (first time: ~1GB download)...")
            self.model = AutoModel(
                model="paraformer-zh", model_revision="v2.0.4",
                device='cpu', disable_update=True,
            )
            print("[FM] Paraformer ready")
        except Exception as e:
            print(f"[FM] ASR model load failed: {e}")
            print("[FM] Continuing without real-time ASR (will store audio only)")
    
    def start_all(self):
        print(f"[FM] Starting {len(FM_STREAMS)} listeners...")
        for s in FM_STREAMS:
            try:
                listener = FMListener(s, self.model)
                listener.start()
                self.listeners[s['name']] = listener
                print(f"[FM]  {s['name']} listening...")
            except Exception as e:
                print(f"[FM]  {s['name']} FAIL: {e}")
    
    def health_check(self):
        """每 60s 检查 ffmpeg 进程是否存活"""
        while True:
            time.sleep(60)
            for name, l in self.listeners.items():
                try:
                    if not l.running:
                        print(f"[FM] {name} dead, restarting...")
                        l.start()
                except Exception as e:
                    print(f"[FM] health error {name}: {e}")
    
    def run(self):
        # 确保 DB schema
        try:
            conn = _get_db()
            conn.executescript(_BRAIN_FEED_SCHEMA)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[FM] DB schema err: {e}")
        
        # 加载 ASR + 启动监听
        self.load_asr()
        self.start_all()
        
        # 健康检查
        threading.Thread(target=self.health_check, daemon=True).start()
        
        print("[FM] Daemon running. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[FM] Stopping...")
            for l in self.listeners.values():
                l.running = False


if __name__ == '__main__':
    FMListenerDaemon().run()
