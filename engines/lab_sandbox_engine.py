#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧪 LabSandboxEngine — 完全隔离的金融团队实验沙盘

设计原则:
  1. ISOLATION: 所有表前缀 mt_lab_*, 绝不读写 mt_sandbox_trades / mt_vault_* 等真实交易表
  2. MARKET: 腾讯行情 API 拉实时行情 https://qt.gtimg.cn/q=sh600519
  3. AI_MENTOR: Ollama qwen2.5:3b 实时点评每笔交易 + 复盘报告
  4. MULTI_PARTY: 36 AI 员工 + 人类可同时参与同一实验 session
  5. BRAIN_FEED: 实验教训自动写入 mt_fm_brain_feed + mt_center_knowledge_points (category=LAB_LESSON)

Usage:
  python3 lab_sandbox_engine.py --init                         # 建表
  python3 lab_sandbox_engine.py --create "2026-11-09 周一复盘" --type review --market SIDE
  python3 lab_sandbox_engine.py --join-all  <exp_id>           # 所有 AI 员工自动加入
  python3 lab_sandbox_engine.py --join      <exp_id> <name>    # 人类/指定加入
  python3 lab_sandbox_engine.py --trade     <exp_id> <part_id> sh600519 BUY 100 "理由"
  python3 lab_sandbox_engine.py --review    <exp_id>           # AI 复盘
  python3 lab_sandbox_engine.py --feed      <exp_id>           # 复盘+脑库投喂
  python3 lab_sandbox_engine.py --status    <exp_id>           # 实验状态
"""
from __future__ import annotations
import os
import sys
import json
import uuid
import time
import sqlite3
import logging
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from typing import Optional

# ── 路径: 确保从 flask-app/ 下正确定位 DB ──
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_FLASK_APP = os.path.dirname(_BASE_DIR)
_DB_PATH_DEFAULT = os.path.join(_FLASK_APP, 'database', 'app.db')


def _get_db_path():
    """优先 MTSCOS_DB_PATH env, 否则 flask-app/database/app.db"""
    env_p = os.environ.get('MTSCOS_DB_PATH', '')
    if env_p and os.path.exists(env_p):
        return env_p
    if os.path.exists(_DB_PATH_DEFAULT):
        return _DB_PATH_DEFAULT
    # 兜底: modular_start.py 里的 PROD
    prod = os.path.expanduser('~/MTSCOS_PROD/flask-app/database/app.db')
    if os.path.exists(prod):
        return prod
    return _DB_PATH_DEFAULT


DB_PATH = _get_db_path()

logger = logging.getLogger('lab_sandbox')
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter('[LAB] %(message)s'))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)


# =====================================================================
# ISOLATION SAFETY NET — 禁止访问真实交易表
# =====================================================================
_REAL_TRADING_TABLES = {
    'mt_sandbox_trades', 'mt_sandbox_portfolio', 'mt_sandbox_cash',
    'mt_vault_orders', 'mt_vault_positions', 'mt_vault_cash',
    'mt_trade_log', 'mt_real_trades', 'mt_positions',
}


class _IsolationViolation(Exception):
    pass


def _isolation_check_sql(sql: str) -> None:
    """检查 SQL 里是否含有真实交易表名"""
    import re as _re
    tokens = _re.findall(r'"?([a-zA-Z_][a-zA-Z0-9_]*)"?', sql)
    suspicious = [t for t in tokens if t in _REAL_TRADING_TABLES]
    if suspicious:
        raise _IsolationViolation(
            f"⛔ ISOLATION VIOLATION: SQL 试图访问真实交易表 {suspicious}\n  SQL: {sql[:200]}")


class _SafeConnWrapper:
    """包装 sqlite3.Connection, 在 execute 前做隔离检查 (Python 3.14 兼容, 不 monkey-patch)"""
    def __init__(self, real_conn: sqlite3.Connection):
        self._c = real_conn
        # 透明代理所有未知属性到真实连接
        self.__sqlite = real_conn

    def execute(self, sql, params=None):
        _isolation_check_sql(sql)
        if params is not None:
            return self._c.execute(sql, params)
        return self._c.execute(sql)

    def executemany(self, sql, seq):
        _isolation_check_sql(sql)
        return self._c.executemany(sql, seq)

    def __getattr__(self, name):
        # 除 execute/executemany 外全部透传
        return getattr(self._c, name)


def _open_conn(extra_safe=True, timeout: float = 30.0) -> sqlite3.Connection:
    """打开沙盒 DB 连接, 默认启用表级隔离安全网
    
    Args:
        extra_safe: 是否启用 SQL 级隔离检查 (CLI 默认 True, Flask bp 内部写默认 False 以免递归拦截)
        timeout: sqlite3.connect timeout (秒), 大一点让 WAL 清道夫能释放锁
    """
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(timeout*1000)}")
    conn.execute("PRAGMA foreign_keys=ON")
    if extra_safe:
        return _SafeConnWrapper(conn)  # type: ignore[return-value]
    return conn


# =====================================================================
# LAB SCHEMAS — 完全隔离, 仅 mt_lab_* 前缀
# =====================================================================
LAB_SCHEMAS: dict = {
    'mt_lab_experiment': """
        CREATE TABLE IF NOT EXISTS mt_lab_experiment (
            exp_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            type TEXT DEFAULT 'review',              -- review/practice/backtest/challenge
            status TEXT DEFAULT 'active',            -- active/paused/completed
            initial_cash REAL DEFAULT 1000000,
            start_date TEXT,
            end_date TEXT,
            market_condition TEXT,                   -- BULL/BEAR/SIDE/CRASH/RALLY
            created_by TEXT DEFAULT 'ollama',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT
        )""",

    'mt_lab_participant': """
        CREATE TABLE IF NOT EXISTS mt_lab_participant (
            part_id TEXT PRIMARY KEY,
            exp_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'trader',              -- trader/mentor/observer
            is_ai INTEGER DEFAULT 0,
            ai_employee_id TEXT,
            current_cash REAL,
            initial_cash REAL,
            score REAL DEFAULT 0,
            join_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(exp_id, name)
        )""",

    'mt_lab_trade': """
        CREATE TABLE IF NOT EXISTS mt_lab_trade (
            trade_id TEXT PRIMARY KEY,
            exp_id TEXT NOT NULL,
            part_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            stock_name TEXT,
            action TEXT,                             -- BUY/SELL
            qty INTEGER,
            price REAL,
            reason TEXT,
            ollama_feedback TEXT,
            feedback_score REAL,
            market_price REAL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",

    'mt_lab_portfolio': """
        CREATE TABLE IF NOT EXISTS mt_lab_portfolio (
            port_id TEXT PRIMARY KEY,
            exp_id TEXT NOT NULL,
            part_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            qty INTEGER DEFAULT 0,
            avg_cost REAL DEFAULT 0,
            UNIQUE(exp_id, part_id, symbol)
        )""",

    'mt_lab_chat': """
        CREATE TABLE IF NOT EXISTS mt_lab_chat (
            chat_id TEXT PRIMARY KEY,
            exp_id TEXT NOT NULL,
            part_id TEXT,
            role TEXT,                               -- user/assistant/mentor/system
            message TEXT NOT NULL,
            context_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",

    'mt_lab_report': """
        CREATE TABLE IF NOT EXISTS mt_lab_report (
            report_id TEXT PRIMARY KEY,
            exp_id TEXT NOT NULL,
            report_type TEXT,                        -- daily_review/trade_review/team_summary
            content TEXT,
            lessons_json TEXT,
            brain_feed_ids TEXT,
            created_by TEXT DEFAULT 'ollama',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )""",
}


def ensure_lab_tables(conn: sqlite3.Connection) -> None:
    """幂等建表 + 索引"""
    for name, ddl in LAB_SCHEMAS.items():
        conn.execute(ddl)
    # 索引 (查询加速)
    _idx = [
        "CREATE INDEX IF NOT EXISTS idx_lab_trade_exp ON mt_lab_trade(exp_id)",
        "CREATE INDEX IF NOT EXISTS idx_lab_trade_part ON mt_lab_trade(part_id)",
        "CREATE INDEX IF NOT EXISTS idx_lab_port_exp ON mt_lab_portfolio(exp_id)",
        "CREATE INDEX IF NOT EXISTS idx_lab_port_part ON mt_lab_portfolio(part_id)",
        "CREATE INDEX IF NOT EXISTS idx_lab_part_exp ON mt_lab_participant(exp_id)",
        "CREATE INDEX IF NOT EXISTS idx_lab_chat_exp ON mt_lab_chat(exp_id)",
        "CREATE INDEX IF NOT EXISTS idx_lab_report_exp ON mt_lab_report(exp_id)",
    ]
    for i in _idx:
        try: conn.execute(i)
        except Exception: pass
    conn.commit()


# =====================================================================
# ID 生成器
# =====================================================================
def _make_id(prefix: str = 'LAB') -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# =====================================================================
# 腾讯行情 API
# =====================================================================
def get_realtime_quote(symbol: str, timeout: float = 6.0) -> dict:
    """拉取腾讯行情, 解析返回; 失败返回 error 字段"""
    # 统一 symbol: sh/sz 前缀已正确
    url = f"https://qt.gtimg.cn/q={symbol}"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 MTSCOS-LabSandbox/1.0',
            'Referer': 'https://gu.qq.com/',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('gbk', errors='replace')
    except Exception as e:
        return {'symbol': symbol, 'ok': False, 'error': f'network: {e}'}

    # 返回格式: v_sh600519="1~贵州茅台~600519~1600.00~1590.00~1605.00~...";
    try:
        eq_pos = raw.index('=')
        val = raw[eq_pos + 1:].strip().strip('"').strip(';').strip('"')
        parts = val.split('~')
        if len(parts) < 50:
            return {'symbol': symbol, 'ok': False, 'error': f'parse: only {len(parts)} fields'}
        return {
            'symbol': symbol,
            'ok': True,
            'stock_name': parts[1],
            'code': parts[2],
            'current_price': float(parts[3]) if parts[3] else 0.0,
            'yesterday_close': float(parts[4]) if parts[4] else 0.0,
            'open': float(parts[5]) if parts[5] else 0.0,
            'volume': int(parts[6]) if parts[6] else 0,
            'turnover': float(parts[37]) if len(parts) > 37 and parts[37] else 0.0,
            'high': float(parts[33]) if len(parts) > 33 and parts[33] else 0.0,
            'low': float(parts[34]) if len(parts) > 34 and parts[34] else 0.0,
            'change_pct': round(
                (float(parts[3]) - float(parts[4])) / float(parts[4]) * 100, 2
            ) if parts[3] and parts[4] and float(parts[4]) != 0 else 0.0,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    except Exception as e:
        return {'symbol': symbol, 'ok': False, 'error': f'parse error: {e}'}


# =====================================================================
# OLLAMA — AI 老师调用 (qwen2.5:3b)
# =====================================================================
_OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')
_OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen2.5:3b')


def call_ollama(prompt: str, system: str = '', timeout: int = 120) -> str:
    """调用 Ollama, 返回生成文本; 失败返回空字符串"""
    payload = {
        'model': _OLLAMA_MODEL,
        'prompt': prompt,
        'system': system,
        'stream': False,
        'options': {'temperature': 0.5, 'num_predict': 400},
    }
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{_OLLAMA_URL}/api/generate",
            data=data, headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode('utf-8'))
        return body.get('response', '').strip()
    except Exception as e:
        logger.warning(f"[OLLAMA] 调用失败: {e}")
        return ''


def ollama_trade_feedback(trade: dict, quote: dict, exp_context: dict) -> str:
    """实时点评一笔交易"""
    system_prompt = (
        "你是一位资深金融导师, 在 MTSCOS 隔离沙盘里点评团队成员的交易练习。"
        "请用中文给出专业、简洁、有建设性的点评 (200-400 字)。"
        "要求包含: ①决策逻辑点评 ②风险提示 ③改进建议 ④1-5 星评分"
    )
    sym = trade.get('symbol', '')
    action = trade.get('action', '')
    qty = trade.get('qty', 0)
    price = quote.get('current_price', trade.get('price', 0))
    name = quote.get('stock_name', sym)
    chg = quote.get('change_pct', 0)
    cond = exp_context.get('market_condition', 'SIDE')
    reason = trade.get('reason', '')[:200]

    prompt = f"""【沙盘实时点评】

股票: {sym} ({name})
动作: {action} {qty} 股 @ {price:.2f}
当日涨跌: {chg:+.2f}%
实验大盘: {cond} (BULL/BEAR/SIDE)
交易理由: {reason}

请点评这笔交易。"""
    return call_ollama(prompt, system=system_prompt, timeout=90)


def ollama_review(experiment: dict, trades: list, participants: list,
                  portfolio_summary: dict) -> str:
    """AI 复盘整个实验"""
    system_prompt = (
        "你是 MTSCOS 沙盘 AI 老师, 请对整个实验 session 做深度复盘。"
        "用中文输出, 结构化、专业、500-800 字。"
        "必须包含: ①实验概览 ②关键指标 (胜率/盈亏/Sharpe估算) "
        "③最佳与最差交易 ④团队表现排名 ⑤核心教训列表 ⑥下阶段建议"
    )
    # 压缩 trades 历史, 只保留关键字段
    trade_lines = []
    for t in trades[:50]:  # 最多 50 笔
        trade_lines.append(
            f"  - {t.get('symbol')} {t.get('action')} {t.get('qty')}@{t.get('price')} "
            f"理由={str(t.get('reason',''))[:40]}")
    trades_text = "\n".join(trade_lines) if trade_lines else "  (无交易)"

    part_text = "\n".join(
        f"  - {p.get('name')} ({'AI' if p.get('is_ai') else '人类'}): score={p.get('score',0):.1f}"
        for p in participants[:20]
    ) or "  (无参与者)"

    prompt = f"""【沙盘复盘报告】

实验标题: {experiment.get('title')}
类型: {experiment.get('type')}  大盘: {experiment.get('market_condition')}
初始资金: {experiment.get('initial_cash')}
参与人数: {len(participants)}
交易笔数: {len(trades)}

【交易明细 (前50)】
{trades_text}

【参与者】
{part_text}

【组合概览】
{json.dumps(portfolio_summary, ensure_ascii=False, indent=2)[:2000]}

请生成完整复盘报告。"""
    return call_ollama(prompt, system=system_prompt, timeout=180)


def ollama_extract_lessons(review_text: str, trades_count: int,
                           win_rate: float, pnl_pct: float) -> list:
    """从复盘文本 + 指标中提取可写入脑库的教训 (3-8 条)"""
    system_prompt = (
        "你是金融脑库蒸馏器, 从沙盒复盘中提取结构化教训。"
        "输出 JSON 数组, 每项: title (15字内), body (100字内), category (LESSON/INSIGHT/WARNING/STRATEGY)"
        "严格输出 JSON, 不要任何额外说明或 markdown 代码块符号。"
    )
    prompt = f"""复盘摘要指标: 交易={trades_count}, 胜率={win_rate:.1%}, 盈亏={pnl_pct:+.2%}

复盘文本:
{review_text[:3000]}

请提取 3-8 条关键教训, 输出 JSON 数组。"""
    raw = call_ollama(prompt, system=system_prompt, timeout=90)
    if not raw:
        return []
    # 去除可能的 ```json ... ``` 包裹
    clean = raw.strip()
    if clean.startswith('```'):
        clean = '\n'.join(clean.split('\n')[1:-1]) if '\n' in clean else clean[clean.index(']'):clean.rindex(']')+1] if ']' in clean else ''
    # 直接找 [ ... ]
    start = clean.find('[')
    end = clean.rfind(']')
    if start >= 0 and end > start:
        clean = clean[start:end+1]
    try:
        data = json.loads(clean)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and d.get('title')]
    except json.JSONDecodeError:
        pass
    return []


# =====================================================================
# LabSandboxEngine — 主引擎
# =====================================================================
class LabSandboxEngine:
    """🧪 隔离实验学习沙盘"""

    def __init__(self, db_path: Optional[str] = None, check_isolation: bool = True,
                 lazy_check: bool = False):
        self.db_path = db_path or DB_PATH
        self.check_isolation = check_isolation
        # lazy_check=True → 跳过 Ollama/quote 健康检查 (init_db/list 等只读操作快启)
        if lazy_check:
            self._ollama_ok = None
            self._quote_ok = None
        else:
            self._ollama_ok = self._check_ollama()
            self._quote_ok = self._check_quote()
        logger.info(
            f"🧪 LabSandboxEngine 初始化 | DB={self.db_path} | "
            f"Ollama={'lazy' if lazy_check else ('✅' if self._ollama_ok else '❌')} | "
            f"TencentQuote={'lazy' if lazy_check else ('✅' if self._quote_ok else '❌')}"
        )

    @property
    def ollama_ok(self) -> bool:
        if self._ollama_ok is None:
            self._ollama_ok = self._check_ollama()
        return self._ollama_ok

    @property
    def quote_ok(self) -> bool:
        if self._quote_ok is None:
            self._quote_ok = self._check_quote()
        return self._quote_ok

    # ─── 健康检查 ───────────────────────────────────────────
    def _check_ollama(self) -> bool:
        try:
            req = urllib.request.Request(f"{_OLLAMA_URL}/api/tags")
            with urllib.request.urlopen(req, timeout=4) as r:
                return r.status == 200
        except Exception:
            return False

    def _check_quote(self) -> bool:
        q = get_realtime_quote('sh600519', timeout=4)
        return bool(q.get('ok'))

    # ─── 建表入口 ───────────────────────────────────────────
    def init_db(self) -> dict:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            ensure_lab_tables(conn)
            # 确保脑库表也存在 (投喂时需要)
            self._ensure_brain_tables(conn)
            conn.commit()
            return {'success': True, 'db_path': self.db_path,
                    'tables_created': list(LAB_SCHEMAS.keys())}
        finally:
            conn.close()

    def _ensure_brain_tables(self, conn: sqlite3.Connection) -> None:
        """幂等确保脑库写入目标表存在"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_center_knowledge_points (
                kp_id INTEGER PRIMARY KEY AUTOINCREMENT,
                center_name TEXT, kp_type TEXT, source_table TEXT,
                source_row_id INTEGER, knowledge_title TEXT, knowledge_body TEXT,
                confidence REAL, applied INTEGER DEFAULT 0,
                applied_at TEXT, created_at TEXT DEFAULT (datetime('now','localtime'))
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mt_fm_brain_feed (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_name TEXT, category TEXT, asr_text TEXT,
                trigger_keywords TEXT, emotion TEXT, emotion_score REAL,
                has_price_info INTEGER DEFAULT 0, has_policy INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )""")
        conn.commit()

    # ─── 创建实验 ───────────────────────────────────────────
    def create_experiment(self, title: str, exp_type: str = 'review',
                          initial_cash: float = 1_000_000.0,
                          market_condition: str = 'SIDE',
                          description: str = '',
                          auto_join_ai: bool = True) -> dict:
        conn = self._open()
        try:
            exp_id = _make_id('LAB')
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            start_date = now.split(' ')[0]
            conn.execute(
                """INSERT INTO mt_lab_experiment
                   (exp_id, title, description, type, initial_cash,
                    start_date, market_condition, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (exp_id, title, description, exp_type, initial_cash,
                 start_date, market_condition, 'ollama')
            )
            conn.commit()
            logger.info(f"🧪 实验已创建: {exp_id} | {title} | 初始={initial_cash:,.0f} | {market_condition}")

            if auto_join_ai:
                self.auto_join_all_active_ai_employees(conn, exp_id, initial_cash)

            return {
                'success': True, 'exp_id': exp_id, 'title': title,
                'initial_cash': initial_cash, 'market_condition': market_condition,
                'participants_count': self._count_participants(conn, exp_id),
            }
        finally:
            conn.close()

    # ─── 获取活跃 AI 员工并自动加入 ──────────────────────────
    def auto_join_all_active_ai_employees(self, conn: sqlite3.Connection,
                                          exp_id: str,
                                          initial_cash: float) -> int:
        """从 mtscos_ai_employees 或旧表 mt_ai_employees 取 active AI 员工"""
        employees = []
        for tbl in ['mtscos_ai_employees', 'mt_ai_employees']:
            try:
                cur = conn.execute(
                    f"SELECT uid, name, role, dept FROM {tbl} "
                    f"WHERE is_active=1 AND status IN ('active', 'hired', 'onboarded') "
                    f"LIMIT 50"
                )
                rows = cur.fetchall()
                for uid, name, role, dept in rows:
                    if uid and name:
                        employees.append({'uid': uid, 'name': name,
                                          'role': role or 'trader',
                                          'dept': dept or 'general'})
                if employees:
                    break
            except sqlite3.Error:
                continue

        # 如果没从任何表取到, 用兜底种子 (确保至少有 36 个 AI 名字)
        if not employees:
            employees = self._fallback_ai_seeds()

        n_joined = 0
        for emp in employees:
            try:
                part_id = _make_id('PART')
                conn.execute(
                    """INSERT OR IGNORE INTO mt_lab_participant
                       (part_id, exp_id, name, role, is_ai, ai_employee_id,
                        current_cash, initial_cash)
                       VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                    (part_id, exp_id, emp['name'], emp['role'],
                     emp['uid'], initial_cash, initial_cash)
                )
                n_joined += 1
            except sqlite3.IntegrityError:
                continue
        conn.commit()
        logger.info(f"🤖 {n_joined} AI 员工已加入实验 {exp_id}")
        return n_joined

    def _fallback_ai_seeds(self) -> list:
        """兜底 AI 员工种子 (36 个)"""
        names = [
            ('吴分析', 'analyst'), ('赵波段', 'trader'), ('孙价值', 'trader'),
            ('钱量化', 'quant'), ('周风控', 'risk'), ('陈择时', 'trader'),
            ('林基本面', 'analyst'), ('金技术派', 'trader'), ('王消息灵通', 'analyst'),
            ('冯盘面', 'trader'), ('邓套利', 'quant'), ('曹高频', 'trader'),
            ('彭期权', 'trader'), ('张期货', 'trader'), ('刘债券', 'trader'),
            ('沈选股', 'analyst'), ('韩指数', 'trader'), ('杨打板', 'trader'),
            ('唐价值投', 'trader'), ('黄成长', 'trader'), ('马蓝筹', 'trader'),
            ('朱题材', 'trader'), ('郭抄底', 'trader'), ('何追涨', 'trader'),
            ('邹白马', 'trader'), ('梁微盘', 'trader'), ('宋研究', 'analyst'),
            ('谢研报', 'analyst'), ('唐数据', 'quant'), ('方模型', 'quant'),
            ('秦信号', 'quant'), ('尤回测', 'quant'), ('许操盘', 'trader'),
            ('傅大户', 'trader'), ('苏小散', 'trader'), ('潘老师', 'mentor'),
        ]
        return [{'uid': f'AI-{i:03d}', 'name': n, 'role': r}
                for i, (n, r) in enumerate(names, 1)]

    def _count_participants(self, conn: sqlite3.Connection, exp_id: str) -> int:
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM mt_lab_participant WHERE exp_id=?", (exp_id,)
            ).fetchone()[0]
        except Exception:
            return 0

    # ─── 人类加入 ───────────────────────────────────────────
    def join_experiment(self, exp_id: str, name: str, role: str = 'trader',
                        initial_cash: Optional[float] = None) -> dict:
        conn = self._open()
        try:
            exp = self._get_experiment(conn, exp_id)
            if not exp:
                return {'success': False, 'error': f'实验 {exp_id} 不存在'}
            if exp['status'] != 'active':
                return {'success': False, 'error': f'实验已 {exp["status"]}'}
            cash = initial_cash or exp['initial_cash']
            part_id = _make_id('PART')
            conn.execute(
                """INSERT INTO mt_lab_participant
                   (part_id, exp_id, name, role, is_ai, current_cash, initial_cash)
                   VALUES (?, ?, ?, ?, 0, ?, ?)""",
                (part_id, exp_id, name, role, cash, cash)
            )
            conn.commit()
            logger.info(f"👤 {name} 加入实验 {exp_id}")
            return {'success': True, 'part_id': part_id, 'name': name}
        except sqlite3.IntegrityError:
            return {'success': False, 'error': f'{name} 已在实验中'}
        finally:
            conn.close()

    # ─── 模拟下单 (核心) ─────────────────────────────────────
    def place_trade(self, exp_id: str, part_id: str, symbol: str,
                    action: str, qty: int, reason: str = '') -> dict:
        """模拟下单 + 腾讯行情 + AI 点评 + 资金/组合更新"""
        action = action.upper()
        if action not in ('BUY', 'SELL'):
            return {'success': False, 'error': f'非法 action: {action}, 必须 BUY/SELL'}
        if qty <= 0 or qty % 100 != 0:
            return {'success': False, 'error': f'qty 必须是正整数且 100 的倍数, 但得到 {qty}'}

        conn = self._open()
        try:
            exp = self._get_experiment(conn, exp_id)
            if not exp:
                return {'success': False, 'error': f'实验 {exp_id} 不存在'}
            if exp['status'] != 'active':
                return {'success': False, 'error': f'实验已 {exp["status"]}'}

            part = self._get_participant(conn, part_id)
            if not part:
                return {'success': False, 'error': f'参与者 {part_id} 不存在'}

            # 1. 拉行情
            quote = get_realtime_quote(symbol)
            if not quote.get('ok'):
                # 行情失败 → 用 fallback price (上次实验或 0)
                fallback = conn.execute(
                    "SELECT price FROM mt_lab_trade WHERE symbol=? ORDER BY created_at DESC LIMIT 1",
                    (symbol,)).fetchone()
                price = fallback[0] if fallback and fallback[0] else 0.0
                logger.warning(f"⚠️ 行情失败, 用 fallback price={price} for {symbol}")
                quote['current_price'] = price
                quote['ok'] = True
            else:
                price = quote['current_price']

            if price <= 0:
                return {'success': False, 'error': f'价格无效 (0 或缺失)'}

            # 2. 资金/持仓校验
            trade_value = price * qty
            if action == 'BUY':
                if part['current_cash'] < trade_value:
                    return {'success': False, 'error':
                            f'现金不足: 需 {trade_value:,.0f}, 仅有 {part["current_cash"]:,.0f}'}
            else:  # SELL
                port_row = conn.execute(
                    "SELECT qty FROM mt_lab_portfolio WHERE exp_id=? AND part_id=? AND symbol=?",
                    (exp_id, part_id, symbol)
                ).fetchone()
                hold = port_row[0] if port_row else 0
                if hold < qty:
                    return {'success': False, 'error':
                            f'持仓不足: 持有 {hold}, 想卖 {qty}'}

            # 3. AI 老师实时点评
            trade_for_ai = {'symbol': symbol, 'action': action, 'qty': qty,
                            'price': price, 'reason': reason}
            feedback = ''
            feedback_score = 0.0
            if self.ollama_ok:
                feedback = ollama_trade_feedback(trade_for_ai, quote, exp)
                # 从 AI 回复中尝试提取 1-5 分评分
                import re
                score_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:星|分|★|评分)', feedback)
                if score_match:
                    try: feedback_score = float(score_match.group(1))
                    except Exception: pass
                if feedback_score > 5: feedback_score = feedback_score / 20.0  # 百分比转星级
                feedback_score = round(min(5.0, max(0.0, feedback_score)), 1)

            # 4. 更新资金
            new_cash = part['current_cash'] - trade_value if action == 'BUY' \
                else part['current_cash'] + trade_value
            conn.execute(
                "UPDATE mt_lab_participant SET current_cash=? WHERE part_id=?",
                (new_cash, part_id)
            )

            # 5. 更新组合 (加权平均成本 / T+0 直接卖)
            port_row = conn.execute(
                "SELECT port_id, qty, avg_cost FROM mt_lab_portfolio "
                "WHERE exp_id=? AND part_id=? AND symbol=?",
                (exp_id, part_id, symbol)
            ).fetchone()
            if action == 'BUY':
                if port_row:
                    port_id, old_qty, old_cost = port_row
                    new_qty = old_qty + qty
                    new_cost = (old_cost * old_qty + price * qty) / new_qty if new_qty else 0
                    conn.execute(
                        "UPDATE mt_lab_portfolio SET qty=?, avg_cost=? WHERE port_id=?",
                        (new_qty, new_cost, port_id)
                    )
                else:
                    port_id = _make_id('PORT')
                    conn.execute(
                        """INSERT INTO mt_lab_portfolio
                           (port_id, exp_id, part_id, symbol, qty, avg_cost)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (port_id, exp_id, part_id, symbol, qty, price)
                    )
            else:  # SELL — T+0, 直接减
                if port_row:
                    port_id, old_qty, old_cost = port_row
                    new_qty = old_qty - qty
                    if new_qty <= 0:
                        conn.execute("DELETE FROM mt_lab_portfolio WHERE port_id=?", (port_id,))
                    else:
                        conn.execute(
                            "UPDATE mt_lab_portfolio SET qty=? WHERE port_id=?",
                            (new_qty, port_id)
                        )

            # 6. 写交易记录
            trade_id = _make_id('TRADE')
            conn.execute(
                """INSERT INTO mt_lab_trade
                   (trade_id, exp_id, part_id, symbol, stock_name, action, qty,
                    price, reason, ollama_feedback, feedback_score, market_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, exp_id, part_id, symbol, quote.get('stock_name', symbol),
                 action, qty, price, reason, feedback, feedback_score, price)
            )

            # 7. AI 反馈同时写 mt_lab_chat
            if feedback:
                chat_id = _make_id('CHAT')
                conn.execute(
                    """INSERT INTO mt_lab_chat
                       (chat_id, exp_id, part_id, role, message)
                       VALUES (?, ?, ?, 'mentor', ?)""",
                    (chat_id, exp_id, part_id, feedback)
                )

            conn.commit()
            logger.info(
                f"✅ {part['name']} {action} {symbol} x{qty} @ {price:.2f} | "
                f"余额 {new_cash:,.0f} | AI评分 {feedback_score}")

            return {
                'success': True, 'trade_id': trade_id,
                'symbol': symbol, 'stock_name': quote.get('stock_name'),
                'action': action, 'qty': qty, 'price': price,
                'new_cash': round(new_cash, 2),
                'feedback': feedback,
                'feedback_score': feedback_score,
            }
        finally:
            conn.close()

    # ─── AI 复盘 ────────────────────────────────────────────
    def run_experiment_review(self, exp_id: str) -> dict:
        conn = self._open()
        try:
            exp = self._get_experiment(conn, exp_id)
            if not exp:
                return {'success': False, 'error': f'实验 {exp_id} 不存在'}
            trades = [dict(r) for r in conn.execute(
                "SELECT * FROM mt_lab_trade WHERE exp_id=? ORDER BY created_at ASC",
                (exp_id,)
            ).fetchall()]
            participants = [dict(r) for r in conn.execute(
                "SELECT * FROM mt_lab_participant WHERE exp_id=?",
                (exp_id,)
            ).fetchall()]
            portfolios = self._get_portfolios(conn, exp_id)

            if not trades:
                return {'success': False, 'error': '实验无交易, 无法复盘'}

            # 统计指标
            metrics = self._calc_metrics(trades, participants)

            # 组合概览 (按参与者)
            port_summary = self._portfolio_summary(conn, exp_id, participants, portfolios)

            # AI 复盘
            review_text = ollama_review(exp, trades, participants, port_summary)
            if not review_text:
                review_text = "[AI老师离线] 复盘报告生成失败"

            # 写报告表
            report_id = _make_id('REPORT')
            lessons = ollama_extract_lessons(review_text, len(trades),
                                             metrics.get('win_rate', 0),
                                             metrics.get('pnl_pct', 0))
            conn.execute(
                """INSERT INTO mt_lab_report
                   (report_id, exp_id, report_type, content, lessons_json, created_by)
                   VALUES (?, ?, 'team_summary', ?, ?, 'ollama')""",
                (report_id, exp_id, review_text, json.dumps(lessons, ensure_ascii=False))
            )
            # 更新实验 updated_at
            conn.execute(
                "UPDATE mt_lab_experiment SET updated_at=datetime('now','localtime') WHERE exp_id=?",
                (exp_id,)
            )
            conn.commit()
            logger.info(f"📊 AI 复盘完成: {report_id} | 交易={len(trades)} | 教训={len(lessons)}")

            return {
                'success': True, 'report_id': report_id,
                'review_text': review_text, 'lessons': lessons,
                'metrics': metrics, 'participants_count': len(participants),
                'trades_count': len(trades),
            }
        finally:
            conn.close()

    # ─── 指标计算 ────────────────────────────────────────────
    def _calc_metrics(self, trades: list, participants: list) -> dict:
        """计算简易绩效指标 (胜率/盈亏比/Sharpe/MaxDD)"""
        if not trades:
            return {}
        # 配对 round-trip (同参与者同 symbol 的 BUY 后 SELL)
        # 简化: 假设每次卖出对应最早买入 (FIFO)
        buy_queues = {}  # (part_id, symbol) -> [price, qty] list
        realized = []    # (part_id, symbol, pnl_pct)
        for t in trades:
            key = (t['part_id'], t['symbol'])
            if t['action'] == 'BUY':
                buy_queues.setdefault(key, []).append([t['price'], t['qty']])
            else:  # SELL
                qty_left = t['qty']
                pnl_list = []
                for item in buy_queues.get(key, []):
                    if qty_left <= 0: break
                    b_price, b_qty = item
                    matched = min(qty_left, b_qty)
                    pnl = (t['price'] - b_price) / b_price * matched
                    pnl_pct = (t['price'] - b_price) / b_price
                    realized.append({'part_id': t['part_id'], 'symbol': t['symbol'],
                                     'pnl_pct': pnl_pct, 'amount': pnl})
                    pnl_list.append(pnl_pct)
                    item[1] -= matched
                    qty_left -= matched
                buy_queues[key] = [i for i in buy_queues.get(key, []) if i[1] > 0]

        if not realized:
            return {'trades': len(trades), 'round_trips': 0, 'note': '无完整 round-trip'}

        wins = [r for r in realized if r['pnl_pct'] > 0]
        losses = [r for r in realized if r['pnl_pct'] <= 0]
        win_rate = len(wins) / len(realized)
        avg_win = sum(r['pnl_pct'] for r in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(r['pnl_pct'] for r in losses) / len(losses)) if losses else 0.0001
        if avg_loss == 0 and len(losses) > 0:
            profit_factor = 999.0
        elif avg_loss > 0 and len(losses) > 0:
            profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses))
        else:
            profit_factor = 999.0 if losses else 0.0

        pnls = [r['pnl_pct'] for r in realized]
        mean_pnl = sum(pnls) / len(pnls)
        var_pnl = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
        std_pnl = var_pnl ** 0.5
        sharpe = mean_pnl / std_pnl * (252 ** 0.5) if std_pnl > 0 else 0  # 年化近似

        # MaxDD: 累计 PnL 曲线的最大回撤
        cum = 0.0; peak = 0.0; max_dd = 0.0
        for p in pnls:
            cum += p
            if cum > peak: peak = cum
            dd = peak - cum
            if dd > max_dd: max_dd = dd

        # 整体 PnL% (用所有 round-trip 平均)
        overall_pnl_pct = mean_pnl * 100

        return {
            'round_trips': len(realized), 'trades': len(trades),
            'wins': len(wins), 'losses': len(losses),
            'win_rate': round(win_rate, 4),
            'avg_win_pct': round(avg_win * 100, 3),
            'avg_loss_pct': round(avg_loss * 100, 3),
            'profit_factor': round(profit_factor, 3) if profit_factor != float('inf') else 999.0,
            'sharpe_ratio': round(sharpe, 3),
            'max_drawdown_pct': round(max_dd * 100, 3),
            'pnl_pct': round(overall_pnl_pct, 3),
        }

    def _get_portfolios(self, conn, exp_id) -> list:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM mt_lab_portfolio WHERE exp_id=?", (exp_id,)
        ).fetchall()]

    def _portfolio_summary(self, conn, exp_id, participants, portfolios) -> dict:
        per_part = {}
        for p in participants:
            per_part[p['part_id']] = {
                'name': p['name'], 'ai': bool(p['is_ai']),
                'cash': p['current_cash'], 'holdings': [],
                'total_value': p['current_cash'],
            }
        for port in portfolios:
            pid = port['part_id']
            if pid in per_part:
                # 拉实时价
                q = get_realtime_quote(port['symbol'])
                pv = q.get('current_price', port['avg_cost']) if q.get('ok') else port['avg_cost']
                mv = pv * port['qty']
                per_part[pid]['holdings'].append({
                    'symbol': port['symbol'], 'qty': port['qty'],
                    'avg_cost': port['avg_cost'], 'market_price': pv,
                    'market_value': mv,
                })
                per_part[pid]['total_value'] += mv
        return per_part

    # ─── 教训投喂脑库 ────────────────────────────────────────
    def feed_lessons_to_brain(self, exp_id: str) -> dict:
        """把实验教训写入 mt_fm_brain_feed + mt_center_knowledge_points"""
        conn = self._open()
        try:
            # 找最新 report
            row = conn.execute(
                "SELECT report_id, lessons_json FROM mt_lab_report "
                "WHERE exp_id=? ORDER BY created_at DESC LIMIT 1",
                (exp_id,)
            ).fetchone()
            if not row:
                # 自动先跑复盘
                rev = self.run_experiment_review(exp_id)
                if not rev.get('success'):
                    return {'success': False, 'error': rev.get('error', '无法复盘')}
                lessons = rev.get('lessons', [])
                report_id = rev.get('report_id')
            else:
                report_id = row[0]
                try:
                    lessons = json.loads(row[1]) if row[1] else []
                except Exception:
                    lessons = []

            if not lessons:
                return {'success': False, 'error': '报告里没有可提取的教训'}

            self._ensure_brain_tables(conn)

            # 脑库里已有多少 LAB_LESSON — 用于去重
            existing = set(r[0] for r in conn.execute(
                "SELECT knowledge_title FROM mt_center_knowledge_points "
                "WHERE center_name='lab_sandbox'"
            ).fetchall())

            bf_ids = []
            kp_ids = []
            for ls in lessons:
                title = str(ls.get('title', '')).strip()[:60]
                body = str(ls.get('body', ls.get('content', ''))).strip()[:500]
                cat = str(ls.get('category', 'LESSON')).strip()
                if not title or title in existing:
                    continue

                # 写 mt_fm_brain_feed
                cur = conn.execute(
                    """INSERT INTO mt_fm_brain_feed
                       (stream_name, category, asr_text, trigger_keywords,
                        emotion, emotion_score, has_price_info, has_policy)
                       VALUES (?, ?, ?, ?, 'neutral', 0.5, 0, 0)""",
                    ('lab_sandbox', f'LAB_LESSON:{cat}',
                     f"[EXP-{exp_id}] {title}\n{body}", title)
                )
                bf_ids.append(cur.lastrowid)

                # 写 mt_center_knowledge_points
                cur = conn.execute(
                    """INSERT INTO mt_center_knowledge_points
                       (center_name, kp_type, source_table, source_row_id,
                        knowledge_title, knowledge_body, confidence)
                       VALUES ('lab_sandbox', ?, 'mt_lab_report', ?, ?, ?, 0.85)""",
                    (f'LAB_LESSON_{cat}', report_id, title, body)
                )
                kp_ids.append(cur.lastrowid)
                existing.add(title)

            # 回写 brain_feed_ids 到 report
            conn.execute(
                "UPDATE mt_lab_report SET brain_feed_ids=? WHERE report_id=?",
                (json.dumps(bf_ids, ensure_ascii=False), report_id)
            )
            conn.commit()
            logger.info(f"🧠 已投喂 {len(bf_ids)} 条教训 → brain_feed + knowledge_points")
            return {
                'success': True,
                'lessons_count': len(lessons),
                'brain_feed_inserted': len(bf_ids),
                'knowledge_points_inserted': len(kp_ids),
                'report_id': report_id,
            }
        finally:
            conn.close()

    # ─── 实验状态 ────────────────────────────────────────────
    def get_experiment_state(self, exp_id: str) -> dict:
        conn = self._open()
        try:
            exp = self._get_experiment(conn, exp_id)
            if not exp:
                return {'success': False, 'error': f'实验 {exp_id} 不存在'}
            participants = [dict(r) for r in conn.execute(
                "SELECT * FROM mt_lab_participant WHERE exp_id=?", (exp_id,)
            ).fetchall()]
            trades = [dict(r) for r in conn.execute(
                "SELECT * FROM mt_lab_trade WHERE exp_id=? ORDER BY created_at DESC",
                (exp_id,)
            ).fetchall()]
            portfolios = [dict(r) for r in conn.execute(
                "SELECT * FROM mt_lab_portfolio WHERE exp_id=?", (exp_id,)
            ).fetchall()]
            # 排名: 按总资产 (现金 + 持仓估值)
            rankings = self._compute_rankings(participants, portfolios)
            return {
                'success': True, 'experiment': exp,
                'participants': participants,
                'trades_count': len(trades), 'trades': trades[:20],
                'portfolios': portfolios,
                'rankings': rankings,
            }
        finally:
            conn.close()

    def _compute_rankings(self, participants, portfolios) -> list:
        # 拉实时行情估算总资产
        pf_by_part = {}
        for p in portfolios:
            pf_by_part.setdefault(p['part_id'], []).append(p)
        out = []
        for p in participants:
            total = p['current_cash'] or 0
            holdings = []
            for port in pf_by_part.get(p['part_id'], []):
                q = get_realtime_quote(port['symbol'], timeout=3)
                pv = q.get('current_price', port['avg_cost']) if q.get('ok') else port['avg_cost']
                mv = pv * port['qty']
                total += mv
                holdings.append({'symbol': port['symbol'], 'qty': port['qty'],
                                 'market_value': mv, 'avg_cost': port['avg_cost']})
            pnl_pct = (total - (p['initial_cash'] or 1)) / (p['initial_cash'] or 1) * 100
            out.append({
                'part_id': p['part_id'], 'name': p['name'], 'is_ai': bool(p['is_ai']),
                'cash': p['current_cash'], 'total_assets': round(total, 2),
                'pnl_pct': round(pnl_pct, 2), 'score': p.get('score', 0),
                'holdings': holdings,
            })
        out.sort(key=lambda x: -x['total_assets'])
        for i, r in enumerate(out, 1):
            r['rank'] = i
        return out

    # ─── 内部工具 ────────────────────────────────────────────
    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _get_experiment(self, conn, exp_id) -> Optional[dict]:
        row = conn.execute(
            "SELECT * FROM mt_lab_experiment WHERE exp_id=?", (exp_id,)
        ).fetchone()
        return dict(row) if row else None

    def _get_participant(self, conn, part_id) -> Optional[dict]:
        row = conn.execute(
            "SELECT * FROM mt_lab_participant WHERE part_id=?", (part_id,)
        ).fetchone()
        return dict(row) if row else None

    # ─── 实验列表 ────────────────────────────────────────────
    def list_experiments(self, status: str = '', limit: int = 20) -> list:
        conn = self._open()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM mt_lab_experiment WHERE status=? "
                    "ORDER BY created_at DESC LIMIT ?", (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM mt_lab_experiment ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d['participants_count'] = self._count_participants(conn, d['exp_id'])
                d['trades_count'] = conn.execute(
                    "SELECT COUNT(*) FROM mt_lab_trade WHERE exp_id=?",
                    (d['exp_id'],)).fetchone()[0]
                out.append(d)
            return out
        finally:
            conn.close()

    # ─── AI 聊天 ────────────────────────────────────────────
    def ai_chat(self, exp_id: str, part_id: str, message: str) -> dict:
        conn = self._open()
        try:
            exp = self._get_experiment(conn, exp_id)
            if not exp:
                return {'success': False, 'error': f'实验 {exp_id} 不存在'}
            # 写用户消息
            chat_id = _make_id('CHAT')
            conn.execute(
                """INSERT INTO mt_lab_chat
                   (chat_id, exp_id, part_id, role, message)
                   VALUES (?, ?, ?, 'user', ?)""",
                (chat_id, exp_id, part_id, message)
            )
            # AI 老师回应
            system_prompt = (
                "你是 MTSCOS 沙盘 AI 老师, 正在辅导团队成员的交易练习。"
                "请用中文、专业、简洁、有建设性地回答 (150-300 字)。"
                "结合当前实验的市场环境和可用的行情数据给出建议。"
            )
            # 上下文: 最近 3 条交易
            recent = conn.execute(
                """SELECT symbol, action, qty, price, reason, ollama_feedback
                   FROM mt_lab_trade WHERE part_id=? ORDER BY created_at DESC LIMIT 3""",
                (part_id,)
            ).fetchall()
            context = f"当前大盘: {exp['market_condition']}\n最近交易:"
            for r in recent:
                context += f"\n  {r['symbol']} {r['action']} {r['qty']}@{r['price']:.2f}"
            prompt = f"{context}\n\n成员提问: {message}\n\n请回复:"
            reply = call_ollama(prompt, system=system_prompt, timeout=60)
            if not reply:
                reply = "[AI 老师暂时离线]"
            chat_id2 = _make_id('CHAT')
            conn.execute(
                """INSERT INTO mt_lab_chat
                   (chat_id, exp_id, part_id, role, message)
                   VALUES (?, ?, ?, 'assistant', ?)""",
                (chat_id2, exp_id, part_id, reply)
            )
            conn.commit()
            return {'success': True, 'reply': reply, 'chat_id': chat_id2}
        finally:
            conn.close()

    def get_chat_history(self, exp_id: str, limit: int = 100) -> list:
        conn = self._open()
        try:
            rows = conn.execute(
                "SELECT * FROM mt_lab_chat WHERE exp_id=? ORDER BY created_at DESC LIMIT ?",
                (exp_id, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()

    # ─── 实验状态切换 ────────────────────────────────────────
    def update_experiment_status(self, exp_id: str, status: str) -> dict:
        if status not in ('active', 'paused', 'completed'):
            return {'success': False, 'error': 'status 必须是 active/paused/completed'}
        conn = self._open()
        try:
            cur = conn.execute(
                "UPDATE mt_lab_experiment SET status=?, updated_at=datetime('now','localtime') "
                "WHERE exp_id=?", (status, exp_id)
            )
            conn.commit()
            return {'success': True, 'updated': cur.rowcount}
        finally:
            conn.close()


# =====================================================================
# CLI — standalone main
# =====================================================================
def _cli():
    parser = argparse.ArgumentParser(description='🧪 LabSandboxEngine 隔离沙盘 CLI')
    sub = parser.add_subparsers(dest='cmd')

    sub.add_parser('init', help='建表 + 确保脑库表存在')

    p_create = sub.add_parser('create', help='创建实验')
    p_create.add_argument('title')
    p_create.add_argument('--type', default='review')
    p_create.add_argument('--market', default='SIDE',
                          choices=['BULL', 'BEAR', 'SIDE', 'CRASH', 'RALLY'])
    p_create.add_argument('--cash', type=float, default=1_000_000)
    p_create.add_argument('--no-auto', action='store_true',
                          help='禁用 AI 员工自动加入')
    p_create.add_argument('--desc', default='')

    p_join = sub.add_parser('join', help='人类加入实验')
    p_join.add_argument('exp_id')
    p_join.add_argument('name')
    p_join.add_argument('--role', default='trader')

    p_join_all = sub.add_parser('join-all', help='自动加入所有 AI 员工 (create 时已自动)')
    p_join_all.add_argument('exp_id')
    p_join_all.add_argument('--cash', type=float, default=1_000_000)

    p_trade = sub.add_parser('trade', help='模拟下单')
    p_trade.add_argument('exp_id')
    p_trade.add_argument('part_id')
    p_trade.add_argument('symbol')
    p_trade.add_argument('action', choices=['BUY', 'SELL'])
    p_trade.add_argument('qty', type=int)
    p_trade.add_argument('reason', nargs='?', default='')

    p_review = sub.add_parser('review', help='AI 复盘')
    p_review.add_argument('exp_id')

    p_feed = sub.add_parser('feed', help='教训投喂脑库')
    p_feed.add_argument('exp_id')

    p_status = sub.add_parser('status', help='实验状态')
    p_status.add_argument('exp_id')

    p_list = sub.add_parser('list', help='实验列表')
    p_list.add_argument('--status', default='')

    p_quote = sub.add_parser('quote', help='拉实时行情')
    p_quote.add_argument('symbol')

    p_chat = sub.add_parser('chat', help='AI 聊天')
    p_chat.add_argument('exp_id')
    p_chat.add_argument('part_id')
    p_chat.add_argument('message')

    p_stop = sub.add_parser('stop', help='结束实验 (状态改 completed)')
    p_stop.add_argument('exp_id')

    args = parser.parse_args()
    # lazy_check: 只读/轻量命令跳过 AI/quote 健康检查 (秒启)
    _LAZY_CMDS = {'init', 'status', 'list', 'stop', 'join-all'}
    eng = LabSandboxEngine(lazy_check=(args.cmd in _LAZY_CMDS))

    if args.cmd == 'init':
        print(json.dumps(eng.init_db(), ensure_ascii=False, indent=2))

    elif args.cmd == 'create':
        r = eng.create_experiment(
            title=args.title, exp_type=args.type,
            initial_cash=args.cash, market_condition=args.market,
            description=args.desc, auto_join_ai=not args.no_auto,
        )
        print(json.dumps(r, ensure_ascii=False, indent=2))

    elif args.cmd == 'join':
        print(json.dumps(eng.join_experiment(args.exp_id, args.name, args.role),
                         ensure_ascii=False, indent=2))

    elif args.cmd == 'join-all':
        # 自动拿 experiment 的 initial_cash
        conn = eng._open()
        try:
            exp = eng._get_experiment(conn, args.exp_id)
            cash = exp['initial_cash'] if exp else args.cash
        finally:
            conn.close()
        n = eng.auto_join_all_active_ai_employees(eng._open(), args.exp_id, cash)
        print(f"✅ 已自动加入 {n} 个 AI 员工 → {args.exp_id}")

    elif args.cmd == 'trade':
        r = eng.place_trade(args.exp_id, args.part_id, args.symbol,
                            args.action, args.qty, args.reason)
        print(json.dumps(r, ensure_ascii=False, indent=2))

    elif args.cmd == 'review':
        r = eng.run_experiment_review(args.exp_id)
        if r.get('success'):
            print(f"\n📊 复盘报告 ({r['report_id']})")
            print("=" * 50)
            print(r.get('review_text', '')[:2000])
            print(f"\n📈 教训提取: {len(r.get('lessons', []))} 条")
            for ls in r.get('lessons', [])[:5]:
                print(f"  • [{ls.get('category','LESSON')}] {ls.get('title','')}: {ls.get('body','')[:60]}")
            print(f"\n📐 指标: {json.dumps(r.get('metrics', {}), ensure_ascii=False, indent=2)}")
        else:
            print(json.dumps(r, ensure_ascii=False, indent=2))

    elif args.cmd == 'feed':
        print(json.dumps(eng.feed_lessons_to_brain(args.exp_id),
                         ensure_ascii=False, indent=2))

    elif args.cmd == 'status':
        r = eng.get_experiment_state(args.exp_id)
        if r.get('success'):
            exp = r['experiment']
            print(f"\n🧪 {exp['title']} ({exp['exp_id']})")
            print(f"  类型={exp['type']}  状态={exp['status']}  大盘={exp['market_condition']}")
            print(f"  初始资金={exp['initial_cash']:,.0f}  交易={r['trades_count']}笔  参与者={len(r['participants'])}人")
            print(f"\n🏆 Top 5 排名:")
            for rank in r.get('rankings', [])[:5]:
                tag = '🤖' if rank.get('is_ai') else '👤'
                print(f"  {rank['rank']:>2}. {tag} {rank['name']:12s}  总资产={rank['total_assets']:>12,.0f}  PnL={rank['pnl_pct']:+.2f}%")
            print(f"\n💼 持仓 (前 10 笔):")
            for port in r.get('portfolios', [])[:10]:
                print(f"  {port['symbol']} x{port['qty']} @成本{port['avg_cost']:.2f}")
        else:
            print(json.dumps(r, ensure_ascii=False, indent=2))

    elif args.cmd == 'list':
        items = eng.list_experiments(status=args.status)
        print(f"\n🧪 共 {len(items)} 个实验:")
        for e in items:
            print(f"  {e['exp_id']}  [{e['status']:9s}] {e['title'][:40]:40s} "
                  f"💰{e['initial_cash']:,.0f}  🤝{e['participants_count']:>3}  💹{e['trades_count']:>3}笔")

    elif args.cmd == 'quote':
        print(json.dumps(get_realtime_quote(args.symbol), ensure_ascii=False, indent=2))

    elif args.cmd == 'chat':
        print(json.dumps(eng.ai_chat(args.exp_id, args.part_id, args.message),
                         ensure_ascii=False, indent=2))

    elif args.cmd == 'stop':
        print(json.dumps(eng.update_experiment_status(args.exp_id, 'completed'),
                         ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == '__main__':
    _cli()
