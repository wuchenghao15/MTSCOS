#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
屏幕监控守护 — Screen Monitor Daemon
定时截屏 + OCR 提取财经行情 + 异常检测 → 触发 AI 接管

模式:
  1. 📸 截屏 — macOS screencapture 定时全屏/区域截图
  2. 🔍 OCR — macOS Vision(优先) / PaddleOCR / pytesseract / tesseract CLI / 像素差异(降级)
  3. 📊 财经提取 — 正则匹配股票代码、价格、涨跌幅、成交量
  4. 🚨 异常检测 — 价格跳变 / 涨跌停 / 连续异动 / 屏幕冻结
  5. 🛰️ 事件推送 — 写 mt_screen_events → Flask /api/sandbox/ai-dispatch

用法:
  python3 screen_monitor_daemon.py &
  launchctl bootstrap gui/$(id -u) com.mtscos.screen-monitor.plist

环境变量:
  MTSCOS_DB_PATH        DB 路径 (默认 ../database/app.db)
  SCREEN_INTERVAL_SEC   截屏间隔秒 (默认 15)
  SCREEN_REGION         监控区域 "0,0,1920,1080" 或空=全屏
  INTEL_FLASK_URL       Flask 地址 (默认 http://127.0.0.1:5001)
  OCR_ENGINE            "vision" / "paddle" / "tesseract" / "tesseract_cli" / "pixel" (默认自动检测)
  SCREENSHOT_DIR        截图保存目录 (默认 /tmp/mtscos_screens)
"""
import os, sys, re, json, time, hashlib, threading, subprocess, sqlite3, logging, base64, tempfile, shutil
from datetime import datetime, timedelta
from pathlib import Path

# ═══ 日志 ═══
logging.basicConfig(
    level=logging.INFO,
    format="[Screen][%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("screen")

# ═══ 配置 ═══
_DB_PATH       = os.environ.get("MTSCOS_DB_PATH") or str(
    Path(__file__).resolve().parent.parent / "database" / "app.db"
)
_FLASK_URL     = os.environ.get("INTEL_FLASK_URL", "http://127.0.0.1:5001")
_INTERVAL_SEC  = int(os.environ.get("SCREEN_INTERVAL_SEC", "15"))
_REGION        = os.environ.get("SCREEN_REGION", "").strip()
_OCR_ENGINE    = os.environ.get("OCR_ENGINE", "auto").strip().lower()
_SHOT_DIR      = os.environ.get("SCREENSHOT_DIR", "/tmp/mtscos_screens")

# 创建截图目录
os.makedirs(_SHOT_DIR, exist_ok=True)

# 保留最近 N 张截图 (避免磁盘爆)
_MAX_SCREENSHOTS = 50
_MAX_SCREENSHOT_AGE_MIN = 60  # 超过 60min 的删掉

# ═══ 数据库表 ═══
_SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_screen_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    screen_name TEXT DEFAULT 'fullscreen',
    event_type TEXT,               -- PRICE_SPIKE, LIMIT_UP, LIMIT_DOWN, VOLUME_SURGE, SCREEN_FREEZE, OCR_TEXT
    content TEXT,                  -- OCR 提取的原始文本
    symbol TEXT,                   -- 提取的股票代码 (如有)
    value REAL,                    -- 关键数值 (价格/涨跌幅%)
    prev_value REAL,               -- 上一次的数值
    severity TEXT DEFAULT 'INFO',  -- INFO, WARN, CRITICAL
    snapshot_path TEXT,            -- 截图文件路径 (异常时存)
    trigger_action TEXT,            -- AI 接管后的动作描述
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_screen_time ON mt_screen_events(created_at);
CREATE INDEX IF NOT EXISTS idx_screen_type ON mt_screen_events(event_type);
"""

# ═══ 股票代码正则 ═══
# A 股: 600/601/603/605 (沪主板), 000/001/002/003 (深主板), 300 (创业板), 688 (科创板)
# 港股: 5 位数字 00001-99999
# 美股: 纯字母 1-5 位
_RE_A_SHARE  = re.compile(r'(?<![\d.])([36]\d{5})(?![\d.])')   # 排除 352000.0 这类小数/长数字
_RE_PRICE    = re.compile(r'(?:价格|现价|最新|收)[：:\s]*(\d+\.\d+)')
_RE_PCT      = re.compile(r'[+-]?(\d+\.\d+)\s*%')
_RE_CHG_PCT  = re.compile(r'[涨跌][幅]?[：:\s]*([+-]?\d+\.?\d*)\s*%')
_RE_VOLUME   = re.compile(r'(?:成交量|量)[：:\s]*(\d+(?:\.\d+)?)\s*([万亿手股])')


# ═══ OCR 引擎选择 ═══
def _vision_bin():
    """macOS 原生 Vision OCR 二进制 (离线/零依赖/中文准), 无则 None"""
    cands = [os.environ.get("VISION_OCR_BIN", ""),
             str(Path(__file__).resolve().parent / "bin" / "vision_ocr")]
    for p in cands:
        if p and os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return None


def _tesseract_cli():
    """返回系统 tesseract 可执行路径, 无则 None (PEP668 环境装不了 python 包, 走 CLI)"""
    for p in (shutil.which("tesseract"),
              "/opt/homebrew/bin/tesseract",
              "/usr/local/bin/tesseract"):
        if p and os.path.exists(p):
            return p
    return None


def _tessdata_has(lang: str) -> bool:
    """检查 tessdata 目录是否有指定语言包"""
    for d in (os.environ.get("TESSDATA_PREFIX"),
              "/opt/homebrew/share/tessdata",
              "/usr/local/share/tessdata",
              "/opt/homebrew/share/tesseract/tessdata"):
        if d and os.path.exists(os.path.join(d, f"{lang}.traineddata")):
            return True
    return False


def _detect_ocr_engine() -> str:
    """自动检测可用 OCR 引擎"""
    if _OCR_ENGINE in ("vision", "paddle", "tesseract", "tesseract_cli", "pixel"):
        return _OCR_ENGINE
    # 优先 macOS 原生 Vision: 离线、零依赖、中英混排识别准
    if _vision_bin():
        return "vision"
    # 尝试 PaddleOCR
    try:
        import paddleocr
        return "paddle"
    except Exception:
        pass
    # 尝试 pytesseract
    try:
        import pytesseract
        return "tesseract"
    except Exception:
        pass
    # 尝试系统 tesseract CLI (无需 python 包)
    if _tesseract_cli():
        return "tesseract_cli"
    log.warning("⚠️ 未检测到 OCR 引擎 (PaddleOCR/pytesseract/tesseract), 降级为像素差异模式")
    return "pixel"


_ocr_engine = None      # 全局 OCR 引擎实例
_ocr_engine_name = ""   # 当前引擎名


def _init_ocr():
    """初始化 OCR 引擎 (惰性, 只在第一次需要时加载)"""
    global _ocr_engine, _ocr_engine_name
    if _ocr_engine is not None:
        return _ocr_engine, _ocr_engine_name

    _ocr_engine_name = _detect_ocr_engine()
    log.info("🔍 OCR engine: %s", _ocr_engine_name)

    if _ocr_engine_name == "vision":
        binp = _vision_bin()
        if binp:
            _ocr_engine = binp
            log.info("✅ macOS Vision OCR ready: %s", binp)
        else:
            log.warning("vision_ocr 二进制缺失 — 降级检测下一引擎")
            _ocr_engine_name = "pixel"
            _ocr_engine = None

    elif _ocr_engine_name == "paddle":
        try:
            from paddleocr import PaddleOCR
            _ocr_engine = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
            log.info("✅ PaddleOCR ready")
        except Exception as e:
            log.warning("PaddleOCR init failed: %s — fallback to pixel", e)
            _ocr_engine_name = "pixel"
            _ocr_engine = None

    elif _ocr_engine_name == "tesseract":
        try:
            import pytesseract
            from PIL import Image
            _ocr_engine = (pytesseract, Image)
            log.info("✅ pytesseract ready (需要系统 tesseract: brew install tesseract tesseract-lang)")
        except Exception as e:
            log.warning("pytesseract init failed: %s — fallback to pixel", e)
            _ocr_engine_name = "pixel"
            _ocr_engine = None

    elif _ocr_engine_name == "tesseract_cli":
        binp = _tesseract_cli()
        if binp:
            _ocr_engine = binp
            log.info("✅ tesseract CLI ready: %s (chi_sim=%s)", binp, _tessdata_has("chi_sim"))
        else:
            log.warning("tesseract CLI 不存在 — fallback to pixel")
            _ocr_engine_name = "pixel"
            _ocr_engine = None

    else:
        _ocr_engine = None  # pixel 模式不需要引擎

    return _ocr_engine, _ocr_engine_name


def _do_ocr(image_path: str) -> str:
    """对图片执行 OCR, 返回识别文本"""
    eng, name = _init_ocr()
    try:
        if name == "vision":
            r = subprocess.run([eng, image_path],
                               capture_output=True, text=True, timeout=45)
            if r.returncode != 0:
                log.warning("vision_ocr rc=%s err=%s", r.returncode, (r.stderr or "")[:200])
                return ""
            return r.stdout or ""

        if name == "paddle":
            result = eng.ocr(image_path, cls=True)
            texts = []
            if result and result[0]:
                for line in result[0]:
                    if line and line[1]:
                        texts.append(line[1][0])
            return " ".join(texts)

        elif name == "tesseract":
            pyt, Image = eng
            img = Image.open(image_path)
            text = pyt.image_to_string(img, lang='chi_sim+eng')
            return text

        elif name == "tesseract_cli":
            lang = "chi_sim+eng" if _tessdata_has("chi_sim") else "eng"
            r = subprocess.run([eng, image_path, "stdout", "-l", lang, "--psm", "6"],
                               capture_output=True, text=True, timeout=45)
            if r.returncode != 0:
                log.warning("tesseract CLI rc=%s err=%s", r.returncode, (r.stderr or "")[:200])
                return ""
            return r.stdout or ""

    except Exception as e:
        log.warning("OCR err: %s", e)
    return ""


# ═══ 截屏 ═══
def _capture_screen() -> str | None:
    """macOS screencapture — 返回截图路径 (PNG) 或 None"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    shot_path = os.path.join(_SHOT_DIR, f"screen_{ts}.png")

    try:
        # screencapture 命令
        cmd = ["screencapture"]
        if _REGION:
            # -R x,y,w,h
            cmd.extend(["-R", _REGION])
        cmd.extend(["-x", shot_path])  # -x = 静音, -C = 包含光标
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            log.warning("screencapture err: %s", proc.stderr[:200])
            return None
        if os.path.exists(shot_path) and os.path.getsize(shot_path) > 100:
            return shot_path
        return None
    except Exception as e:
        log.warning("screencapture exception: %s", e)
        return None


# ═══ 像素差异检测 (降级模式) ═══
_last_screenshot_hash = None


def _pixel_diff(shot_path: str) -> dict:
    """计算当前截图和上一张的差异 (基于文件哈希)"""
    global _last_screenshot_hash
    result = {"changed": False, "hash": None, "change_pct": 0}

    try:
        with open(shot_path, "rb") as f:
            h = hashlib.md5(f.read()).hexdigest()
        result["hash"] = h
        if _last_screenshot_hash and h != _last_screenshot_hash:
            result["changed"] = True
            # 粗略估计变化: 字节大小差异比例
            result["change_pct"] = 15  # 简化: 有变化就算 15%
        _last_screenshot_hash = h
    except Exception:
        pass
    return result


# ═══ 财经内容提取 ═══
def _extract_finance(text: str) -> dict:
    """从 OCR 文本中提取股票代码、价格、涨跌幅"""
    result = {
        "a_shares": [],      # A 股代码列表
        "prices": [],        # 价格 (元)
        "pcts": [],          # 涨跌幅 (%)
        "volumes": [],       # 成交量
        "has_limit_up": False,
        "has_limit_down": False,
    }
    if not text:
        return result

    # A 股代码
    codes = _RE_A_SHARE.findall(text)
    result["a_shares"] = list(dict.fromkeys(codes))[:10]  # 去重, 最多 10 只

    # 价格
    result["prices"] = [float(p) for p in _RE_PRICE.findall(text)]

    # 涨跌幅
    for m in _RE_CHG_PCT.finditer(text):
        try:
            result["pcts"].append(float(m.group(1)))
        except ValueError:
            pass
    # 兜底: 找所有 X.X% 格式
    if not result["pcts"]:
        for m in _RE_PCT.finditer(text):
            try:
                result["pcts"].append(float(m.group(1)))
            except ValueError:
                pass

    # 成交量
    for m in _RE_VOLUME.finditer(text):
        val = float(m.group(1))
        unit = m.group(2)
        multiplier = {"万": 1e4, "亿": 1e8, "手": 100, "股": 1}.get(unit, 1)
        result["volumes"].append(val * multiplier)

    # 涨跌停检测 (主板 ±10%): 必须有带符号的涨跌幅数值, 不能只凭"涨停/跌停"字样
    # (代码/文档里出现这两个词就会误报, 必须数值兜底)
    result["has_limit_up"] = any(9.7 <= p <= 10.5 for p in result["pcts"])
    result["has_limit_down"] = any(-10.5 <= p <= -9.7 for p in result["pcts"])

    return result


# ═══ 异常检测引擎 ═══
_prev_extracted = {}   # {hash_key: {prices, pcts, ...}}
_frozen_count = 0       # 连续多少次像素没变化 → 屏幕冻结

_EVENT_COOLDOWN_SEC = 600   # 同类型事件冷却, 防止同一画面每轮重复刷 CRITICAL
_last_event_ts = {}


def _dedup_events(events: list) -> list:
    """同类型事件 10 分钟内只落库一次 (行情页面常驻时避免刷屏)"""
    now = time.time()
    out = []
    for ev in events:
        et = ev.get("event_type")
        if now - _last_event_ts.get(et, 0) < _EVENT_COOLDOWN_SEC:
            continue
        _last_event_ts[et] = now
        out.append(ev)
    return out


def _detect_anomalies(shot_path: str, extracted: dict, pixel_result: dict) -> list:
    """对比当前和前一次的提取结果, 返回异常事件列表"""
    global _frozen_count
    events = []
    now = time.time()
    key = pixel_result.get("hash") or shot_path

    # 1️⃣ 屏幕冻结检测: 连续 N 次像素完全一样
    if not pixel_result.get("changed") and _last_screenshot_hash:
        _frozen_count += 1
        if _frozen_count >= 5:
            events.append({
                "event_type": "SCREEN_FREEZE",
                "severity": "WARN",
                "content": f"屏幕连续 {_frozen_count * _INTERVAL_SEC}s 无变化 (可能行情卡死)",
                "value": _frozen_count,
            })
    else:
        if _frozen_count >= 3:
            log.info("✅ 屏幕恢复更新 (之前冻了 %d 轮)", _frozen_count)
        _frozen_count = 0

    # 2️⃣ 涨跌停检测
    if extracted.get("has_limit_up"):
        events.append({
            "event_type": "LIMIT_UP",
            "severity": "CRITICAL",
            "content": f"🚨 检测到涨停板! A股={extracted['a_shares']} pct={extracted['pcts']}",
            "value": max(extracted["pcts"]) if extracted["pcts"] else 10.0,
        })
    if extracted.get("has_limit_down"):
        events.append({
            "event_type": "LIMIT_DOWN",
            "severity": "CRITICAL",
            "content": f"🚨 检测到跌停板! A股={extracted['a_shares']} pct={extracted['pcts']}",
            "value": min(extracted["pcts"]) if extracted["pcts"] else -10.0,
        })

    # 3️⃣ 价格跳变 (对比上一轮)
    prev = _prev_extracted.get(key) or _prev_extracted.get("latest")
    if prev and extracted.get("pcts") and prev.get("pcts"):
        for i, cur_pct in enumerate(extracted["pcts"][:3]):
            if i < len(prev["pcts"]):
                diff = abs(cur_pct - prev["pcts"][i])
                if diff >= 3.0:  # 3% 以上跳变
                    events.append({
                        "event_type": "PRICE_SPIKE",
                        "severity": "HIGH" if diff >= 5 else "WARN",
                        "content": f"价格波动 {diff:.1f}% ({prev['pcts'][i]:.1f}% → {cur_pct:.1f}%)",
                        "value": cur_pct,
                        "prev_value": prev["pcts"][i],
                    })

    # 4️⃣ 成交量突变
    if extracted.get("volumes") and prev and prev.get("volumes"):
        for i, cur_vol in enumerate(extracted["volumes"][:2]):
            if i < len(prev["volumes"]) and prev["volumes"][i] > 0:
                ratio = cur_vol / prev["volumes"][i]
                if ratio >= 3.0:
                    events.append({
                        "event_type": "VOLUME_SURGE",
                        "severity": "WARN",
                        "content": f"成交量暴增 {ratio:.1f}x ({prev['volumes'][i]:.0f} → {cur_vol:.0f})",
                        "value": cur_vol,
                    })

    # 记住当前
    _prev_extracted["latest"] = {
        "prices": extracted.get("prices", []),
        "pcts": extracted.get("pcts", []),
        "volumes": extracted.get("volumes", []),
    }
    if key:
        _prev_extracted[key] = _prev_extracted["latest"]

    return events


# ═══ DB 操作 ═══
def _get_db():
    return sqlite3.connect(_DB_PATH, timeout=5, check_same_thread=False)


def _ensure_schema():
    try:
        conn = _get_db()
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("DB schema err: %s", e)


def _record_event(event: dict, shot_path: str | None = None) -> int | None:
    """写入屏幕事件, 返回 id"""
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO mt_screen_events
               (screen_name, event_type, content, symbol, value, prev_value,
                severity, snapshot_path)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                "fullscreen",
                event.get("event_type", ""),
                event.get("content", "")[:1000],
                event.get("symbol", "") or (event.get("a_shares", [])[0] if event.get("a_shares") else ""),
                float(event.get("value", 0) or 0),
                float(event.get("prev_value", 0) or 0),
                event.get("severity", "INFO"),
                shot_path if event.get("severity") in ("CRITICAL", "HIGH") else None,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        return cur.lastrowid
    except Exception as e:
        log.error("DB insert err: %s", e)
        return None


def _cleanup_old_screenshots():
    """清理过期截图"""
    try:
        now_min = time.time() / 60
        kept = []
        for f in sorted(os.listdir(_SHOT_DIR)):
            fp = os.path.join(_SHOT_DIR, f)
            age_min = (now_min - os.path.getmtime(fp) / 60) if os.path.exists(fp) else 999
            if age_min > _MAX_SCREENSHOT_AGE_MIN:
                os.remove(fp)
            else:
                kept.append(fp)
        # 如果保留的还太多, 删最老的
        if len(kept) > _MAX_SCREENSHOTS:
            for f in kept[:len(kept) - _MAX_SCREENSHOTS]:
                try: os.remove(f)
                except Exception: pass
    except Exception as e:
        log.debug("cleanup err: %s", e)


# ═══ AI 接管触发 ═══
def _trigger_ai(events: list, extracted: dict):
    """将屏幕异常推送给 AI 研判"""
    if not events:
        return
    try:
        import urllib.request
        for ev in events:
            payload = json.dumps({
                "agent": "screen_monitor",
                "action": "alert",
                "reason": ev.get("content", ""),
                "event_type": ev.get("event_type", ""),
                "severity": ev.get("severity", "INFO"),
                "a_shares": extracted.get("a_shares", []),
                "pcts": extracted.get("pcts", []),
            }, ensure_ascii=False)
            req = urllib.request.Request(
                f"{_FLASK_URL}/api/sandbox/ai-dispatch",
                data=payload.encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass
        log.info("🤖 AI 接管: %d 个屏幕异常事件已推送", len(events))
    except Exception as e:
        log.warning("AI trigger err: %s", e)


def _heartbeat():
    """写 daemon 心跳: warden 以此判断线程是否真活着(进程在 ≠ 线程在)"""
    try:
        conn = _get_db()
        cur = conn.execute(
            "UPDATE mt_daemon_registry SET status='ACTIVE', pid=?, "
            "last_heartbeat=datetime('now','localtime'), updated_at=datetime('now','localtime') "
            "WHERE process_name='screen_monitor'", (os.getpid(),))
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO mt_daemon_registry (process_name, duty, status, pid, interval_sec, "
                "last_heartbeat, updated_at, created_at) VALUES "
                "('screen_monitor','屏幕监控: 15s 截屏+像素差异+异常检测','ACTIVE',?,15,"
                "datetime('now','localtime'),datetime('now','localtime'),datetime('now','localtime'))",
                (os.getpid(),))
        conn.commit(); conn.close()
    except Exception as e:
        log.debug("heartbeat err: %s", e)


# ═══ 主循环 ═══
class ScreenMonitor:
    def __init__(self):
        self.running = False
        self.cycle = 0
        self._frozen_count = 0   # 画面无变化连续轮次 (pixel 模式下防止空转刷屏)

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()
        log.info("🚀 ScreenMonitor 启动 (interval=%ds, ocr=%s)", _INTERVAL_SEC, _ocr_engine_name or "auto")

    def _loop(self):
        _ensure_schema()
        # 启动时加载 OCR
        _init_ocr()

        # 先扫一次, 不等间隔
        self._cycle_once()
        _heartbeat()

        while self.running:
            self.cycle += 1
            try:
                self._cycle_once()
                _heartbeat()
            except Exception as e:
                log.error("cycle err: %s", e)
            time.sleep(_INTERVAL_SEC)

    def _cycle_once(self):
        t0 = time.time()
        # 1. 截屏
        shot_path = _capture_screen()
        if not shot_path:
            log.warning("🎬 截屏失败, 跳过本轮")
            return

        # 2. 像素差异
        pixel_result = _pixel_diff(shot_path)
        if not pixel_result.get("changed") and _ocr_engine_name == "pixel":
            # pixel 模式下如果画面没变就跳过 OCR/分析
            self._frozen_count += 1
            return

        # 3. OCR 提取
        extracted = {}
        if _ocr_engine_name != "pixel":
            text = _do_ocr(shot_path)
            if text:
                extracted = _extract_finance(text)
                # 周期性打印提取摘要
                if self.cycle % 20 == 0:
                    log.info("📊 OCR 提取: A股=%s 价格=%s 涨跌=%s",
                             extracted.get("a_shares", [])[:3],
                             extracted.get("prices", [])[:3],
                             extracted.get("pcts", [])[:3])
            else:
                log.debug("OCR 返回空文本")
        else:
            extracted = _extract_finance("")  # pixel 模式无 OCR

        # 4. 异常检测
        events = _dedup_events(_detect_anomalies(shot_path, extracted, pixel_result))

        # 5. 写 DB
        for ev in events:
            eid = _record_event(ev, shot_path)
            icon = {"CRITICAL": "🔴", "HIGH": "🟠", "WARN": "🟡", "INFO": "🔵"}.get(ev.get("severity", "INFO"), "⚪")
            log.info("%s [%s] %s", icon, ev.get("event_type"), ev.get("content", "")[:100])

        # 6. AI 接管 (CRITICAL/HIGH 必推, WARN 批量推)
        critical_events = [e for e in events if e.get("severity") in ("CRITICAL", "HIGH")]
        if critical_events or (events and self.cycle % 3 == 0):
            _trigger_ai(events, extracted)

        # 7. 定期清理截图
        if self.cycle % 100 == 0:
            _cleanup_old_screenshots()

        elapsed = time.time() - t0
        log.debug("cycle #%d done in %.2fs (ocr=%s)", self.cycle, elapsed, bool(extracted))

    def health_check(self) -> dict:
        return {
            "running": self.running,
            "cycle": self.cycle,
            "ocr_engine": _ocr_engine_name,
            "interval_sec": _INTERVAL_SEC,
            "frozen_count": _frozen_count,
            "last_hash": _last_screenshot_hash,
        }


# ═══ 入口 ═══
def run():
    monitor = ScreenMonitor()
    monitor.start()

    # 暴露 health endpoint 供外部调用
    import atexit, signal
    def _stop():
        monitor.running = False
        log.info("ScreenMonitor stopped")
    signal.signal(signal.SIGTERM, lambda *_: (_stop(), sys.exit(0)))
    signal.signal(signal.SIGINT, lambda *_: (_stop(), sys.exit(0)))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _stop()


if __name__ == "__main__":
    run()
