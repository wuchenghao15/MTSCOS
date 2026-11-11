#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情报网关 — Intel Gateway Daemon
后台静默聚合 4 类情报源 → 统一脑库投喂 → 关键词触发天团研判

源类型：
  1. CCTV-2 财经电视字幕流 (ffmpeg m3u8 → Paraformer 实时 ASR)
  2. 华尔街见闻 7×24 快讯 (HTTP JSON API)
  3. 新浪财经快讯 (HTTP JSON API)
  4. Twitter/X 大V  (v2 API, 需 TWITTER_BEARER_TOKEN 环境变量; 未设则跳过)

用法:
  python3 intel_gateway_daemon.py &
  launchctl bootstrap gui/$(id -u) com.mtscos.intel-gateway.plist

环境变量:
  MTSCOS_DB_PATH       DB 路径 (默认 ../database/app.db)
  TWITTER_BEARER_TOKEN Twitter v2 Bearer Token (可选)
  INTEL_FLASK_URL      触发天团的 Flask 地址 (默认 http://127.0.0.1:5001)
"""
import os, sys, re, json, time, hashlib, threading, subprocess, queue, sqlite3, logging, base64
from datetime import datetime, timedelta
from datetime import datetime
from pathlib import Path

# ═══ 日志 ═══
logging.basicConfig(
    level=logging.INFO,
    format="[Intel][%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("intel")

# ═══ 配置 ═══
INTEL_FLASK_URL = os.environ.get("INTEL_FLASK_URL", "http://127.0.0.1:5001")
_TWITTER_TOKEN  = os.environ.get("TWITTER_BEARER_TOKEN", "").strip()
_DB_PATH        = os.environ.get("MTSCOS_DB_PATH") or str(
    Path(__file__).resolve().parent.parent / "database" / "app.db"
)

# ffmpeg 绝对路径 (launchd PATH 可能缺)
_FFMPEG = "/opt/homebrew/bin/ffmpeg"
_PYTHON = "/opt/homebrew/bin/python3"

# TV 流 (IPTV m3u8)
TV_STREAMS = [
    {"name": "CCTV-2 财经", "url": "http://genglei.8866.org:9901/tsfile/live/0002_1.m3u8", "cat": "tv_finance"},
]

# API 轮询源 (url, poll_interval_sec, max_items, parser_hint)
API_SOURCES = [
    {
        "name": "华尔街见闻",
        "url": "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=5",
        "interval": 15,
        "headers": {"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        "parser": "wscn",  # 见 _parse_api()
    },
    {
        "name": "新浪财经",
        "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=10&page=1",
        "interval": 20,
        "headers": {"User-Agent": "Mozilla/5.0"},
        "parser": "sina",
    },
]

# Twitter/X 大V 监控 (v2 API)
# 需要 TWITTER_BEARER_TOKEN 环境变量
TWITTER_ACCOUNTS = [
    # 🇨🇳 A股 KOL / 私募
    ("linsizhen",     "Simon 林 · a-stock-data"),
    ("whirligig231",  "大A老司机"),
    ("cainiao_com",   "菜鸟组合"),
    ("chen_zhixin",    "陈志新 · 独立研究"),
    ("ghzhou123",     "周观牛"),
    ("stocklegend",   "华尔街见闻"),

    # 🇺🇸 美股 / 宏观 / 交易
    ("WarriorTrader", "Warrior Trading"),
    ("MarketsWiki",   "MarketsWiki · 宏观"),
    ("economics",     "经济学人"),
    ("bankofamerica", "美银 BofA 研报"),
    ("GoldmanSachs",   "高盛 GS 研报"),
    ("stlouisfed",    "圣路易斯美联储 · 宏观数据"),
    ("WSJmarkets",    "WSJ 资本市场"),
    (" markets",      "Bloomberg Markets"),

    # 🔬 产业 / 科技
    ("AINews",        "AI 前沿"),
    ("semianalysis",  "半导体洞察"),
    ("techcrunch",    "TechCrunch"),
]

# 关键词触发 (与 FM daemon 共享同一套)
TRIGGER_KEYWORDS = [
    # A股主板块
    "A股", "沪指", "深成指", "创业板", "科创板", "主板", "北交所",
    "北向资金", "沪深港通", "港股通", "南向资金",
    "IPO", "打新", "注册制", "退市", "ST", "摘帽",
    # 跨市场板块
    "B股", "H股", "红筹股", "蓝筹股",
    "港股", "恒生指数", "国企指数", "K股", "美股", "中概股",
    "纳斯达克", "标普500", "道琼斯", "标普",
    "日经", "东证", "恒生科技",
    # 行业/主题板
    "新能源", "芯片", "半导体", "AI", "人工智能",
    "医药集采", "三胎", "共同富裕", "光伏", "储能",
    "军工", "航天", "低空经济", "机器人", "人形机器人",
    # 政策
    "加息", "降息", "降准", "央行", "货币政策", "财政政策", "美联储",
    "国务院", "证监会", "银保监会", "发改委", "财政部",
    "减税", "专项债", "房地产", "楼市调控", "城投债",
    # 市场冲击
    "熔断", "暴跌", "闪崩", "涨停", "跌停", "异动", "大宗交易",
    "黑天鹅", "风险", "泡沫", "通胀", "CPI", "PPI",
    "爆雷", "违约", "信用风险",
]
# 情绪词
HAWK_KW = ["利好", "上涨", "暴涨", "反弹", "牛市", "突破", "增持", "买入", "看多"]
DOG_KW  = ["利空", "下跌", "暴跌", "崩盘", "熊市", "破位", "减持", "卖出", "看空"]

# ═══ 决策周期路由 (关键词 → 短/中/长线三队) ═══
DECISION_ROUTES = {
    "short": {
        "label": "🏃 短线组",
        "triggers": ["涨停","跌停","闪崩","暴跌","异动","熔断","利好","利空",
                     "回购","增持","减持","大宗交易"],
        "agents": ["政委","教委","维和部队","冰山回测云"],
        "horizon": "日内/隔日",
    },
    "mid": {
        "label": "🐢 中线组",
        "triggers": ["货币政策","央行","降准","房地产","新能源","芯片",
                     "半导体","AI","人工智能","三胎","共同富裕",
                     "A股","北向资金","沪深港通","港股通","南向资金",
                     "B股","H股","红筹股","蓝筹股","港股","恒生指数","恒生科技",
                     "K股","中概股","光伏","储能","军工","机器人","人形机器人"],
        "agents": ["首席宗师","BS模型","华尔街老乔","ShardQuant"],
        "horizon": "周级别",
    },
    "long": {
        "label": "🐌 长线组",
        "triggers": ["美联储","加息","降息","CPI","PPI","通胀","黑天鹅",
                     "风险","泡沫","国务院","证监会","银保监会",
                     "财政部","发改委","俄罗斯","美国","中国",
                     "美股","纳斯达克","标普500","道琼斯","日经","东证",
                     "城投债","爆雷","违约","信用风险","楼市调控","专项债"],
        "agents": ["奠基人","证监会顾问","央行顾问"],
        "horizon": "月/季度",
    },
}

COMBINATION_RULES = [
    {"name":"三线共振","require":{"short","mid","long"},"signal":"✅ 高置信度执行"},
    {"name":"短中一致","require":{"short","mid"},"signal":"减仓执行"},
    {"name":"长短背离","require":{"short","long"},"signal":"跨周期对冲 (长仓+短波段)"},
    {"name":"中线独立","require":{"mid"},"signal":"周级别结构调整"},
    {"name":"长线独立","require":{"long"},"signal":"月/季度择时信号"},
]

def _route_decision(triggered_kws: list) -> dict:
    """按触发关键词匹配到哪些决策周期"""
    matched = set()
    for period, cfg in DECISION_ROUTES.items():
        if any(kw in cfg["triggers"] for kw in triggered_kws):
            matched.add(period)
    # 选最高匹配度的组合规则
    best = None
    for rule in sorted(COMBINATION_RULES, key=lambda r: -len(r["require"])):
        if rule["require"].issubset(matched):
            best = rule
            break
    return {"matched_periods": list(matched), "combination": best,
            "period_agents": {p: DECISION_ROUTES[p]["agents"] for p in matched}}


# ═══ DB 初始化 ═══
_SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_intel_brain_feed (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    source_type TEXT,
    category TEXT,
    content TEXT,
    encrypted INTEGER DEFAULT 0,
    enc_nonce TEXT,
    trigger_keywords TEXT,
    emotion TEXT,
    emotion_score REAL,
    has_price_info INTEGER,
    has_policy INTEGER,
    external_id TEXT,
    pub_time TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
-- 兼容旧表: 自动补列
ALTER TABLE mt_intel_brain_feed ADD COLUMN encrypted INTEGER DEFAULT 0;
ALTER TABLE mt_intel_brain_feed ADD COLUMN enc_nonce TEXT;
CREATE INDEX IF NOT EXISTS idx_intel_time  ON mt_intel_brain_feed(created_at);
CREATE INDEX IF NOT EXISTS idx_intel_src   ON mt_intel_brain_feed(source);
CREATE INDEX IF NOT EXISTS idx_intel_ext   ON mt_intel_brain_feed(external_id);
"""

_seen_ext_ids = set()


# ═══ 加密层 ═══
# 公开数据源 (明文存储): 财经新闻 / 电视字幕 / 公开 RSS
# 非公开数据源 (加密): Twitter 推文 / 用户隐私内容
_PUBLIC_SOURCES = {"tv", "api"}   # tv=CCTV-2, api=华尔街见闻/新浪财经 等公开 API
_PRIVATE_SOURCES = {"twitter"}    # Twitter 推文 = 非公开, 加密存储

_ENC_KEY = os.environ.get("MTSCOS_INTEL_KEY", "").strip()

def _get_encryptor():
    """惰性初始化 Fernet, 无 KEY 则返回 None (跳过加密)"""
    global _ENC_KEY
    if not _ENC_KEY:
        return None
    try:
        from cryptography.fernet import Fernet
        # 确保 KEY 是 32 字节 base64url
        raw = _ENC_KEY.encode()
        if len(raw) != 32:
            raw = hashlib.sha256(raw).digest()
            _ENC_KEY = base64.urlsafe_b64encode(raw).decode()
        return Fernet(_ENC_KEY.encode())
    except Exception as e:
        log.warning("🔐 encryptor init failed: %s", e)
        return None

def _encrypt_content(content: str, source_type: str) -> tuple:
    """返回 (content, encrypted_int, enc_nonce_str) — 公开源跳过加密"""
    if source_type in _PUBLIC_SOURCES:
        return content, 0, None
    enc = _get_encryptor()
    if enc is None:
        log.debug("🔐 no KEY, skip encrypt for source_type=%s", source_type)
        return content, 0, None
    try:
        nonce = os.urandom(16)
        data = nonce + enc.encrypt(content.encode())
        return base64.urlsafe_b64encode(data).decode(), 1, base64.urlsafe_b64encode(nonce).decode()
    except Exception as e:
        log.warning("🔐 encrypt fail: %s, store plaintext", e)
        return content, 0, None

def _is_encrypted_source(source_type: str) -> bool:
    return source_type in _PRIVATE_SOURCES


def _get_db():
    return sqlite3.connect(_DB_PATH, check_same_thread=False)


def _ensure_schema():
    try:
        conn = _get_db()
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("DB schema err: %s", e)


def _dedupe_key(source: str, ext_id: str) -> str:
    return f"{source}:{ext_id}"


def _record_seen(source: str, ext_id: str):
    global _seen_ext_ids
    if len(_seen_ext_ids) > 5000:
        _seen_ext_ids = set(list(_seen_ext_ids)[-3000:])
    _seen_ext_ids.add(_dedupe_key(source, ext_id))


def _is_seen(source: str, ext_id: str) -> bool:
    return _dedupe_key(source, ext_id) in _seen_ext_ids


def _analyze(content: str) -> dict:
    """关键词匹配 + 情绪打分"""
    triggered = [kw for kw in TRIGGER_KEYWORDS if kw in content]
    hawk_s = sum(content.count(kw) for kw in HAWK_KW)
    dog_s  = sum(content.count(kw) for kw in DOG_KW)
    total  = hawk_s + dog_s
    if hawk_s > dog_s:
        emo, score = "HAWK", hawk_s / max(total, 1)
    elif dog_s > hawk_s:
        emo, score = "DOG", dog_s / max(total, 1)
    else:
        emo, score = "NEUTRAL", 0.5
    has_price = bool(re.search(r"\d+(?:\.\d+)?(?:%|元|亿|万|点)", content))
    has_policy = any(kw in content for kw in ["国务院", "央行", "证监会", "发改委", "财政部", "美联储"])
    return {
        "triggered": triggered,
        "emotion": emo,
        "emotion_score": score,
        "has_price": has_price,
        "has_policy": has_policy,
    }


def _ingest(source: str, source_type: str, category: str, content: str,
            ext_id: str, pub_time: str = "") -> bool:
    """写入脑库, 返回 True=新数据 / False=重复"""
    if not content or len(content.strip()) < 3:
        return False
    ext_id = ext_id or hashlib.md5(content.encode()).hexdigest()
    if _is_seen(source, ext_id):
        return False

    # 加密层: 非公开源 (twitter) 自动加密
    content_for_store, encrypted_flag, enc_nonce = _encrypt_content(content, source_type)
    ana = _analyze(content)
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO mt_intel_brain_feed
               (source, source_type, category, content, encrypted, enc_nonce,
                trigger_keywords, emotion, emotion_score,
                has_price_info, has_policy, external_id, pub_time)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source, source_type, category, content_for_store[:2000],
             encrypted_flag, enc_nonce,
             json.dumps(ana["triggered"][:8], ensure_ascii=False),
             ana["emotion"], ana["emotion_score"],
             int(ana["has_price"]), int(ana["has_policy"]),
             str(ext_id), str(pub_time)),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.error("DB insert err: %s", e)
        return False

    _record_seen(source, ext_id)

    # ═══ 多周期并行触发 (短/中/长线三队) ═══
    if len(ana["triggered"]) >= 2:
        route = _route_decision(ana["triggered"])
        combination = route["combination"]
        matched = route["matched_periods"]

        if matched:
            log.info("🎯 组合=[%s] 信号=%s 周期=%s",
                     combination["name"] if combination else "无组合",
                     combination["signal"] if combination else "单周期",
                     ",".join(matched))

        # 每个匹配周期派给对应 AI 队伍
        for period in matched:
            cfg = DECISION_ROUTES[period]
            payload = {
                "agent": f"intel_{period}_team",
                "action": "review",
                "reason": (f"[{cfg['label']} {cfg['horizon']}] "
                           f"Intel[{source}] {ana['emotion']}+"
                           f"{' '.join(ana['triggered'][:5])} "
                           f"→ agents={','.join(cfg['agents'])}"),
                "period": period,
                "agents": cfg["agents"],
                "emotion": ana["emotion"],
                "horizon": cfg["horizon"],
            }
            try:
                subprocess.Popen(
                    ["curl", "-s", "-X", "POST",
                     f"{INTEL_FLASK_URL}/api/sandbox/ai-dispatch",
                     "-H", "Content-Type: application/json",
                     "-d", json.dumps(payload, ensure_ascii=False)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    log.info("✅ [%s][%s] %s…  triggers=%s", source, ana["emotion"],
             content[:40], ana["triggered"][:3])
    return True


# ═══ TV 监听器 (复用 ffmpeg + Paraformer) ═══
class TVListener:
    """CCTV-2 财经电视 m3u8 → ffmpeg PCM → Paraformer ASR"""

    def __init__(self, stream_info, asr_model=None):
        self.stream = stream_info
        self.model = asr_model
        self.running = False
        self.queue = queue.Queue(maxsize=2000)
        self.buffer = b""
        log.info("📺 TVListener created: %s", stream_info["name"])

    def start(self, backfill_delay: float = 0.0):
        self.running = True
        threading.Thread(target=self._capture, daemon=True).start()
        threading.Thread(target=self._asr_loop, daemon=True).start()

    def _capture(self):
        """ffmpeg 拉流 — 断流自动重连 (指数退避 + 上限 60s)"""
        reconnect_delay = 5
        cmd = [
            _FFMPEG, "-re", "-i", self.stream["url"],
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            "-f", "wav", "-",
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            while self.running and proc.poll() is None:
                chunk = proc.stdout.read(3200)
                if chunk:
                    reconnect_delay = 5  # 收到数据 → 重置退避
                    try:
                        self.queue.put(chunk, block=False)
                    except queue.Full:
                        pass
            # 进程意外退出 → 自愈
            if self.running:
                log.warning("📺 TV ffmpeg exited (%s), 重连 in %ss", self.stream["name"], reconnect_delay)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
                self._capture()  # 递归重连
        except Exception as e:
            log.warning("📺 TV capture err (%s): %s — 重连 in %ss", self.stream["name"], e, reconnect_delay)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
            if self.running:
                self._capture()

    def _asr_loop(self):
        CHUNK_BYTES = 16000 * 2 * 2  # 2 秒 @16kHz
        while self.running:
            try:
                chunk = self.queue.get(timeout=1)
                self.buffer += chunk
                if len(self.buffer) >= CHUNK_BYTES:
                    text = self._asr(self.buffer)
                    self.buffer = b""
                    if text and len(text.strip()) > 4:
                        _ingest(
                            source=self.stream["name"],
                            source_type="tv",
                            category=self.stream.get("cat", "finance"),
                            content=text,
                            ext_id=hashlib.md5(text.encode()).hexdigest(),
                        )
            except queue.Empty:
                continue

    def _asr(self, pcm_bytes) -> str:
        if self.model is None:
            return ""
        try:
            import numpy as np
            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            result = self.model.generate(input=audio, is_final=True)
            if result:
                text = result[0].get("text", "")
                # Paraformer 输出 "字 字 字" — 把空格去掉
                text = re.sub(r"\s+", "", text)
                return text
            return ""
        except Exception as e:
            log.debug("ASR err: %s", e)
            return ""


# ═══ API/RSS 轮询监听器 ═══
class APIPoller:
    """定时拉 JSON API — 带重试退避 + 连续失败熔断 + 启动 backfill"""

    def __init__(self, api_conf):
        self.conf = api_conf
        self.running = False
        self.last_fetch = 0
        self.fail_streak = 0       # 连续失败计数
        self.circuit_open = False  # 熔断开关
        self.circuit_until = 0     # 熔断到期时间
        log.info("📡 APIPoller created: %s (interval=%ss)", api_conf["name"], api_conf["interval"])

    def start(self, backfill_delay: float = 3.0):
        self.running = True
        threading.Thread(target=self._loop, args=(backfill_delay,), daemon=True).start()

    def _loop(self, backfill_delay: float = 3.0):
        time.sleep(backfill_delay)
        # ── 启动 backfill: 立即拉一次, 不等 interval ──
        self._fetch_with_retry()
        while self.running:
            self._fetch_with_retry()
            # 熔断时延长等待 60s, 否则正常 interval
            wait = self.conf["interval"]
            if self.circuit_open:
                now = time.time()
                if now < self.circuit_until:
                    time.sleep(min(wait, 5))  # 频繁探测
                    continue
                else:
                    self.circuit_open = False
                    log.info("[%s] 🔓 circuit closed, 恢复抓取", self.conf["name"])
            time.sleep(wait)

    def _fetch_with_retry(self):
        """3 次指数退避 + 熔断 (连续 3 次失败→停 60s)"""
        import requests
        headers = self.conf.get("headers", {})
        headers.setdefault("User-Agent", "Mozilla/5.0")
        for attempt in range(3):
            try:
                resp = requests.get(self.conf["url"], headers=headers, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                self.fail_streak = 0  # 成功 → 清零
                self.circuit_open = False
                self._parse_and_ingest(data)
                return
            except Exception as e:
                log.warning("[%s] fetch err (attempt %d/3): %s", self.conf["name"], attempt + 1, e)
                self.fail_streak += 1
                if attempt < 2:
                    time.sleep(2 ** attempt)  # 1s, 2s
        # 3 次全败 → 熔断
        if self.fail_streak >= 3:
            self.circuit_open = True
            self.circuit_until = time.time() + 60
            log.warning("[%s] 🛑 circuit OPEN (连续失败 ≥3), 暂停 60s", self.conf["name"])

    def _parse_and_ingest(self, data):
        """原 _fetch 的 parse + ingest 逻辑"""
        items = self._parse(data)
        ingested = 0
        for it in items:
            if _ingest(
                source=self.conf["name"],
                source_type="api",
                category=self.conf.get("cat", "finance"),
                content=it["content"],
                ext_id=str(it["ext_id"]),
                pub_time=str(it.get("pub_time", "")),
            ):
                ingested += 1
        if ingested > 0:
            log.info("[%s] +%d items ingested", self.conf["name"], ingested)

    def _fetch(self):
        """兼容旧调用 — 实际走 _fetch_with_retry"""
        self._fetch_with_retry()

        items = self._parse(data)
        ingested = 0
        for it in items:
            if _ingest(
                source=self.conf["name"],
                source_type="api",
                category=self.conf.get("cat", "finance"),
                content=it["content"],
                ext_id=str(it["ext_id"]),
                pub_time=str(it.get("pub_time", "")),
            ):
                ingested += 1
        if ingested > 0:
            log.info("[%s] +%d items ingested", self.conf["name"], ingested)

    def _parse(self, data: list | dict) -> list:
        """返回 list[{content, ext_id, pub_time}]"""
        parser = self.conf.get("parser", "generic")
        out = []
        try:
            if parser == "wscn":
                items = data.get("data", {}).get("items", [])
                for it in items:
                    content = (it.get("title") or it.get("content_text") or it.get("content", ""))
                    pub = it.get("display_time", "") or it.get("published_at", "")
                    out.append({"content": content, "ext_id": it.get("id", pub + content[:30]), "pub_time": pub})

            elif parser == "sina":
                items = data.get("result", {}).get("data", [])
                for it in items:
                    content = (it.get("title") or "") + " " + (it.get("intro") or "")
                    content = content.strip()
                    pub = it.get("ctime", "") or it.get("nctime", "")
                    out.append({"content": content, "ext_id": it.get("id", pub + content[:30]), "pub_time": pub})

            else:  # generic
                items = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    for it in items[: self.conf.get("max_items", 5)]:
                        if isinstance(it, dict):
                            content = (it.get("title") or it.get("content") or it.get("text") or json.dumps(it, ensure_ascii=False))
                            out.append({"content": content, "ext_id": it.get("id", hashlib.md5(content.encode()).hexdigest()), "pub_time": ""})
        except Exception as e:
            log.debug("[%s] parse err: %s", self.conf["name"], e)
        return out


# ═══ Twitter v2 监听器 ═══
class TwitterPoller:
    """Twitter/X v2 API — 需 TWITTER_BEARER_TOKEN 环境变量"""

    def __init__(self, bearer_token, accounts):
        self.token = bearer_token
        self.accounts = accounts  # [(handle, display), ...]
        self.running = False
        log.info("🐦 TwitterPoller created: %d accounts", len(accounts))

    def start(self, backfill_delay: float = 5.0):
        self.running = True
        threading.Thread(target=self._loop, args=(backfill_delay,), daemon=True).start()

    def _loop(self, backfill_delay: float = 5.0):
        time.sleep(backfill_delay)
        # backfill: 启动立即拉一次
        for h, d in self.accounts:
            if not self.running: break
            self._fetch_handle(h, d)
            time.sleep(1.5)
        while self.running:
            try:
                for handle, disp in self.accounts:
                    self._fetch_handle(handle, disp)
                    time.sleep(2)  # 账号间限速
            except Exception as e:
                log.warning("Twitter err: %s", e)
            time.sleep(90)  # 全量轮询 90s

    def _fetch_handle(self, handle: str, disp: str):
        import requests
        url = (
            f"https://api.twitter.com/2/users/by/username/{handle}"
            f"?user.fields=id,username"
        )
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {self.token}"}, timeout=10)
            if r.status_code != 200:
                log.debug("Twitter user lookup %s: HTTP %d", handle, r.status_code)
                return
            user_id = r.json()["data"]["id"]
        except Exception as e:
            log.debug("Twitter lookup %s: %s", handle, e)
            return

        # 拿最近推文
        r2 = requests.get(
            f"https://api.twitter.com/2/users/{user_id}/tweets",
            params={
                "max_results": 10,
                "tweet.fields": "created_at,public_metrics",
            },
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=10,
        )
        if r2.status_code != 200:
            log.debug("Twitter tweets %s: HTTP %d", handle, r2.status_code)
            return
        tweets = r2.json().get("data", [])
        for tw in tweets:
            text = tw.get("text", "")
            if not text or len(text) < 5:
                continue
            _ingest(
                source=f"Twitter@{handle}",
                source_type="twitter",
                category="social",
                content=f"[{disp}] {text}",
                ext_id=tw.get("id", ""),
                pub_time=tw.get("created_at", ""),
            )


# ═══ 守护主类 ═══
class IntelGateway:
    def __init__(self):
        self.listeners = []
        self.asr_model = None

    def load_asr(self):
        try:
            from funasr import AutoModel
            log.info("加载 Paraformer 2 model (TV 字幕用)...")
            self.asr_model = AutoModel(
                model="paraformer-zh",
                model_revision="v2.0.4",
                device="cpu",
                disable_update=True,
            )
            log.info("Paraformer ready")
        except Exception as e:
            log.warning("ASR load failed: %s — TV 将跳过实时识别", e)

    def start_all(self, backfill_delay: float = 3.0):
        # TV (CCTV-2 财经)
        if self.asr_model is not None:
            for s in TV_STREAMS:
                try:
                    tv = TVListener(s, self.asr_model)
                    tv.start(backfill_delay=backfill_delay)
                    self.listeners.append(tv)
                    log.info("📺 %s listening", s["name"])
                except Exception as e:
                    log.warning("TV %s fail: %s", s["name"], e)
        else:
            log.warning("TV SKIPPED (no ASR model)")

        # API 轮询
        for api_conf in API_SOURCES:
            try:
                poller = APIPoller(api_conf)
                poller.start(backfill_delay=backfill_delay)
                self.listeners.append(poller)
                log.info("📡 %s polling every %ss", api_conf["name"], api_conf["interval"])
            except Exception as e:
                log.warning("API %s fail: %s", api_conf["name"], e)

        # Twitter (可选)
        if _TWITTER_TOKEN:
            try:
                tw = TwitterPoller(_TWITTER_TOKEN, TWITTER_ACCOUNTS)
                tw.start(backfill_delay=backfill_delay + 2)
                self.listeners.append(tw)
                log.info("🐦 Twitter polling %d accounts", len(TWITTER_ACCOUNTS))
            except Exception as e:
                log.warning("Twitter fail: %s", e)
        else:
            log.info("🐦 Twitter SKIPPED (no TWITTER_BEARER_TOKEN)")

    def health_check(self):
        def _loop():
            while True:
                time.sleep(60)
                alive = sum(1 for l in self.listeners if getattr(l, "running", True))
                log.info("💓 health: %d/%d listeners alive", alive, len(self.listeners))

        threading.Thread(target=_loop, daemon=True).start()

    def run(self):
        _ensure_schema()
        self.load_asr()
        self.start_all()
        self.health_check()
        log.info("🚀 Intel Gateway running. Sources: TV(%d) + API(%d) + Twitter(%d)",
                 len(TV_STREAMS), len(API_SOURCES), 1 if _TWITTER_TOKEN else 0)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("Stopping...")
            for l in self.listeners:
                l.running = False


if __name__ == "__main__":
    IntelGateway().run()
