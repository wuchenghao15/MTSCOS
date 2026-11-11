#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 脑库投喂引擎 — 教育 + 证券交易 + 系统经验 统一入口

核心: 自动 CREATE TABLE mt_ai_brain_feed_log (如果不存在)
3 类投喂源:
  1. 教育数据 (错题/刷题/知识点)    → source="edu"
  2. 证券交易 (沙盘信号/交易/投票)  → source="sandbox"  
  3. 系统经验 (异常/运维/反思)      → source="system"

NAS 路由自动生效 (通过 nas_path_router), 投喂同时写:
  - SQLite mt_ai_brain_feed_log (权威查询入口)
  - JSONL 日文件 NAS/MTSCOS/brain_feed/YYYY-MM-DD.jsonl (归档)
"""

from __future__ import annotations

import os
import sys
import json
import sqlite3
import threading
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Any


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _gen_id(prefix: str = "BF") -> str:
    import time, random
    return f"{prefix}-{int(time.time())}{random.randint(1000,9999):04d}"


def _get_db_path() -> str:
    """统一 DB 路径 (PROD 优先 → 项目内 → 临时文件)"""
    from pathlib import Path as _P
    _prod = _P.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db"
    _dev = _P(__file__).resolve().parent.parent / "database" / "app.db"
    if _prod.exists() and _prod.stat().st_size > 100_000:
        return str(_prod)
    if _dev.exists():
        return str(_dev)
    # 兜底
    import tempfile
    return str(_P(tempfile.gettempdir()) / "mtos_app.db")


class BrainFeedEngine:
    """
    脑库投喂引擎 (单例 + 线程安全)
    
    用法:
        from engines.ai_brain_feed_engine import brain_feed
        
        # 教育错题投喂
        brain_feed.feed_edu_question(question_id, subject, content, user_answer, correct, is_correct)
        
        # 证券交易投喂 (沙盘自动调)
        brain_feed.feed_sandbox_signal(...)
        brain_feed.feed_sandbox_trade(...)
        brain_feed.feed_team_verdict(...)
        
        # 通用投喂
        brain_feed.feed(category="custom", source="manual", content="...", extra={})
        
        # 查询
        brain_feed.stats()
        brain_feed.recent(n=10)
    """
    
    _instance: Optional["BrainFeedEngine"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._db_path = _get_db_path()
        self._ensure_tables()
    
    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10)
    
    def _ensure_tables(self) -> None:
        """确保脑库核心表存在"""
        conn = self._conn()
        try:
            conn.executescript("""
                -- 核心投喂日志 (权威表)
                CREATE TABLE IF NOT EXISTS mt_ai_brain_feed_log (
                    feed_id        TEXT PRIMARY KEY,
                    feed_type      TEXT NOT NULL,     -- experience | signal | trade | verdict | question | error | insight
                    category       TEXT NOT NULL,     -- sandbox | edu | system | market | strategy
                    source         TEXT NOT NULL,     -- sandbox_signal | sandbox_trade | sandbox_team | edu_question | edu_error | auto_digest | manual
                    session_id     TEXT,              -- 关联 session (沙盘 session_id / 教育 session)
                    symbol         TEXT,              -- 证券代码 (教育用 subject 名)
                    content        TEXT NOT NULL,     -- 投喂内容 (主文本)
                    score          REAL DEFAULT 0,    -- 信号强度/重要性
                    is_correct     INTEGER DEFAULT 1, -- 教育场景: 用户答对错
                    extra          TEXT DEFAULT '{}', -- JSON 扩展字段
                    created_at     TEXT NOT NULL,
                    brain_marked   INTEGER DEFAULT 0  -- 是否已被脑库吸收 (0=未读 1=已吸收)
                );
                
                -- 索引 (加速按 category/source 查询)
                CREATE INDEX IF NOT EXISTS idx_brain_category ON mt_ai_brain_feed_log(category);
                CREATE INDEX IF NOT EXISTS idx_brain_source ON mt_ai_brain_feed_log(source);
                CREATE INDEX IF NOT EXISTS idx_brain_session ON mt_ai_brain_feed_log(session_id);
                CREATE INDEX IF NOT EXISTS idx_brain_created ON mt_ai_brain_feed_log(created_at);
                
                -- 经验回流矩阵 (每日统计)
                CREATE TABLE IF NOT EXISTS mt_brain_daily_stats (
                    stat_date      TEXT PRIMARY KEY,
                    total_feeds    INTEGER DEFAULT 0,
                    edu_feeds      INTEGER DEFAULT 0,
                    sandbox_feeds  INTEGER DEFAULT 0,
                    system_feeds   INTEGER DEFAULT 0,
                    sources_json   TEXT DEFAULT '{}',
                    notable_events TEXT DEFAULT '',
                    updated_at     TEXT NOT NULL
                );
            """)
            conn.commit()
            
            sys.stderr.write(
                f"[BRAIN] ✅ 脑库引擎就绪: db={Path(self._db_path).name}\n"
            )
        except Exception as e:
            sys.stderr.write(f"[BRAIN] ⚠️ 建表失败: {e}\n")
        finally:
            conn.close()
    
    # ── 通用投喂 ──
    
    def feed(self, content: str, category: str = "custom",
             feed_type: str = "insight", source: str = "manual",
             session_id: str = None, symbol: str = None,
             score: float = 0.0, is_correct: int = 1,
             extra: Dict = None) -> Dict[str, Any]:
        """通用投喂方法
        
        Args:
            content:    投喂主文本 (自动截断 2000 字符)
            category:   sandbox | edu | system | market | strategy | custom
            feed_type:  experience | signal | trade | verdict | question | error | insight
            source:     sandbox_signal | sandbox_trade | edu_question | auto_digest | manual ...
            score:      信号强度 0~100
            extra:      扩展 JSON (策略名/专家角色/交易金额等)
        
        Returns:
            {"ok": bool, "feed_id": str, "db": bool, "nas": bool}
        """
        feed_id = _gen_id("BF")
        ts = _now_iso()
        content_clean = (content or "")[:2000]
        
        db_ok = False
        nas_ok = False
        
        # 1. 写 SQLite (权威入口)
        try:
            conn = self._conn()
            conn.execute(
                """INSERT OR IGNORE INTO mt_ai_brain_feed_log
                   (feed_id, feed_type, category, source, session_id, symbol,
                    content, score, is_correct, extra, created_at, brain_marked)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
                (feed_id, feed_type, category, source, session_id, symbol,
                 content_clean, score, is_correct,
                 json.dumps(extra or {}, ensure_ascii=False)[:2000], ts)
            )
            conn.commit()
            conn.close()
            db_ok = True
        except Exception as e:
            sys.stderr.write(f"[BRAIN] DB 写入失败: {e}\n")
        
        # 2. 写 JSONL 日文件 (NAS 优先)
        try:
            from engines.nas_path_router import nas_router
            brain_dir = nas_router.get("brain_feed").path
            date_str = ts[:10]
            jsonl_file = brain_dir / f"{date_str}.jsonl"
            
            entry = {
                "feed_id": feed_id,
                "feed_type": feed_type,
                "category": category,
                "source": source,
                "session_id": session_id,
                "symbol": symbol,
                "content": content_clean,
                "score": score,
                "is_correct": is_correct,
                "extra": extra or {},
                "created_at": ts,
            }
            with open(jsonl_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            nas_ok = True
        except Exception as e:
            sys.stderr.write(f"[BRAIN] JSONL 写入失败: {e}\n")
        
        return {"ok": db_ok or nas_ok, "feed_id": feed_id, "db": db_ok, "nas": nas_ok}
    
    # ── 教育数据投喂 ──
    
    def feed_edu_question(self, question_id: str, subject: str,
                           content: str, user_answer: str,
                           correct_answer: str, is_correct: bool,
                           knowledge_points: List[str] = None,
                           difficulty: str = "medium") -> Dict[str, Any]:
        """
        错题/刷题 → 脑库
        
        feed_type="question", category="edu", source="edu_question"
        教育系统应在每次用户提交答案后调一次
        """
        return self.feed(
            content=f"[{subject}] {content[:100]}\n"
                   f"用户答案: {str(user_answer)[:80]}\n"
                   f"正确答案: {str(correct_answer)[:80]}\n"
                   f"结果: {'✅正确' if is_correct else '❌错误'}",
            category="edu",
            feed_type="question",
            source="edu_question",
            symbol=subject,
            is_correct=1 if is_correct else 0,
            extra={
                "question_id": question_id,
                "knowledge_points": knowledge_points or [],
                "difficulty": difficulty,
                "user_answer": str(user_answer)[:200],
                "correct_answer": str(correct_answer)[:200],
            },
        )
    
    def feed_edu_error(self, subject: str, error_chain: List[str],
                        question_id: str = None,
                        context: str = None) -> Dict[str, Any]:
        """
        错因分析 → 脑库 (比单独 question 更结构化)
        
        用户做题时如果连续错、同类题反复错, 应该调这个
        """
        chain_str = " → ".join(error_chain) if error_chain else context or "未知"
        return self.feed(
            content=f"[错因] {subject}: {chain_str}",
            category="edu",
            feed_type="error",
            source="edu_error_chain",
            symbol=subject,
            is_correct=0,
            extra={
                "question_id": question_id,
                "error_chain": error_chain,
            },
        )
    
    # ── 证券交易投喂 (沙盘自动调) ──
    
    def feed_sandbox_signal(self, session_id: str, symbol: str, name: str,
                             strategy: str, signal_type: str,
                             score: float, reason: str) -> Dict[str, Any]:
        """沙盘策略信号 → 脑库"""
        return self.feed(
            content=f"[{symbol} {name}] {strategy} → {signal_type} (分={score:.0f})\n理由: {reason[:150]}",
            category="sandbox",
            feed_type="signal",
            source="sandbox_signal",
            session_id=session_id,
            symbol=symbol,
            score=score,
            extra={
                "strategy": strategy,
                "signal_type": signal_type,
                "stock_name": name,
            },
        )
    
    def feed_sandbox_trade(self, session_id: str, symbol: str, name: str,
                            action: str, shares: int, price: float,
                            amount: float, team_verdict: str = "",
                            strategy: str = "", notes: str = "") -> Dict[str, Any]:
        """沙盘成交 → 脑库"""
        return self.feed(
            content=f"[交易] {action} {name}({symbol}) ×{shares} @¥{price:.2f} = ¥{amount:.2f}\n"
                   f"团队: {team_verdict} | 策略: {strategy}\n备注: {notes[:100]}",
            category="sandbox",
            feed_type="trade",
            source="sandbox_trade",
            session_id=session_id,
            symbol=symbol,
            score=100.0 if action == "BUY" else -100.0,
            extra={
                "action": action, "shares": shares, "price": price,
                "amount": amount, "team_verdict": team_verdict,
                "strategy": strategy, "stock_name": name,
            },
        )
    
    def feed_team_verdict(self, session_id: str, symbol: str,
                          expert_role: str, verdict: str,
                          reason: str, confidence: float = 0) -> Dict[str, Any]:
        """专家投票 → 脑库 (每个专家一票)"""
        role_map = {
            "VALUE_INVESTOR": "价值派",
            "TECH_ANALYST": "技术派",
            "QUANT_TRADER": "量化派",
            "RISK_MANAGER": "风控总监",
            "AUDITOR": "审计官",
        }
        role_cn = role_map.get(expert_role, expert_role)
        return self.feed(
            content=f"[{symbol}] {role_cn} → {verdict} (信心={confidence:.0f}%)\n理由: {reason[:150]}",
            category="sandbox",
            feed_type="verdict",
            source="sandbox_team",
            session_id=session_id,
            symbol=symbol,
            score=confidence,
            extra={
                "expert_role": expert_role,
                "verdict": verdict,
                "confidence": confidence,
            },
        )
    
    def feed_sandbox_summary(self, session_id: str, date: str,
                             nav: float, daily_return: float,
                             positions: List[Dict]) -> Dict[str, Any]:
        """沙盘每日净值快照 → 脑库 (每天一条)"""
        pos_str = ", ".join(
            f"{p.get('name','?')}×{p.get('shares',0)}"
            for p in (positions or [])
        )
        return self.feed(
            content=f"[日报] {date} nav=¥{nav:,.0f} 日收益={daily_return:+.2f}%\n持仓: {pos_str or '空仓'}",
            category="sandbox",
            feed_type="experience",
            source="sandbox_daily",
            session_id=session_id,
            score=abs(daily_return) * 10,
            extra={
                "nav": nav, "daily_return": daily_return,
                "position_count": len(positions or []),
            },
        )
    
    # ── 查询 ──
    
    def stats(self) -> Dict[str, Any]:
        """脑库统计"""
        try:
            conn = self._conn()
            total = conn.execute("SELECT COUNT(*) FROM mt_ai_brain_feed_log").fetchone()[0]
            
            by_cat = conn.execute(
                "SELECT category, COUNT(*) FROM mt_ai_brain_feed_log GROUP BY category"
            ).fetchall()
            
            by_src = conn.execute(
                "SELECT source, COUNT(*) FROM mt_ai_brain_feed_log GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()
            
            today = datetime.now().strftime("%Y-%m-%d")
            today_cnt = conn.execute(
                "SELECT COUNT(*) FROM mt_ai_brain_feed_log WHERE created_at >= ?",
                (today,)
            ).fetchone()[0]
            
            conn.close()
            return {
                "total": total,
                "today": today_cnt,
                "by_category": dict(by_cat),
                "top_sources": [{"source": s, "count": c} for s, c in by_src],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def recent(self, n: int = 10, category: str = None) -> List[Dict]:
        """最近 N 条投喂"""
        try:
            conn = self._conn()
            if category:
                rows = conn.execute(
                    "SELECT feed_id, category, source, symbol, content, score, created_at "
                    "FROM mt_ai_brain_feed_log WHERE category=? ORDER BY rowid DESC LIMIT ?",
                    (category, n)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT feed_id, category, source, symbol, content, score, created_at "
                    "FROM mt_ai_brain_feed_log ORDER BY rowid DESC LIMIT ?",
                    (n,)
                ).fetchall()
            conn.close()
            return [
                {
                    "feed_id": r[0], "category": r[1], "source": r[2],
                    "symbol": r[3], "content": r[4][:80], "score": r[5],
                    "created_at": r[6],
                }
                for r in rows
            ]
        except Exception:
            return []
    
    # ── 🆕 通用入厅方法 (所有中心复用) ──
    
    def submit_to_hall(self, task_type: str, task_title: str,
                       description: str = "", source: str = "brain_feed",
                       priority: int = 50, auto_done: bool = True,
                       extra: Dict = None) -> Optional[str]:
        """
        通用任务大厅提交 — 所有中心统一调用入口
        
        Args:
            task_type:   MEDICAL_EXAM | VERSION_BUMP | MARKET_FIX | EDU_REVIEW |
                        BRAIN_REVIEW | SANDBOX_TRADE | SYSTEM_FIX | SKILL_REGISTER ...
            task_title:  任务标题 (短)
            description: 任务详情 (长)
            source:      提交来源 (center / brain_feed / system ...)
            priority:    0~100 (越高越急, 默认 50)
            auto_done:   是否自动结案 (体检 OK / 复盘完成等不需要派单的)
        
        Returns:
            hall_code (如 "HALL-20261102-001") 或 None
        """
        try:
            conn = self._conn()
            # 确保 mt_task_hall 存在 + schema 足够新 (自动升级旧表)
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='mt_task_hall'"
            ).fetchone()
            
            if not tbl:
                # 全新建表
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS mt_task_hall (
                        hall_code    TEXT PRIMARY KEY,
                        task_title   TEXT NOT NULL,
                        task_type    TEXT NOT NULL,
                        description  TEXT,
                        source       TEXT,
                        priority     INTEGER DEFAULT 50,
                        status       TEXT DEFAULT 'QUEUED',
                        claimant     TEXT,
                        brain_feed_id TEXT,
                        created_at   TEXT NOT NULL,
                        claimed_at   TEXT,
                        done_at      TEXT,
                        notes        TEXT
                    )
                """)
                conn.commit()
            else:
                # 旧表: 检测缺失字段, 自动 ALTER TABLE 补
                existing_cols = {c[1] for c in conn.execute("PRAGMA table_info(mt_task_hall)").fetchall()}
                missing_cols = {
                    'priority': 'INTEGER DEFAULT 50',
                    'status': "TEXT DEFAULT 'QUEUED'",
                    'notes': 'TEXT',
                    'claimant': 'TEXT',
                    'brain_feed_id': 'TEXT',
                    'claimed_at': 'TEXT',
                    'done_at': 'TEXT',
                }
                for col, typ in missing_cols.items():
                    if col not in existing_cols:
                        try:
                            conn.execute(f"ALTER TABLE mt_task_hall ADD COLUMN {col} {typ}")
                        except Exception:
                            pass  # 字段已存在或 DB 不支持 ALTER, 跳过
                conn.commit()
                
                # 旧表用 hall_priority → 重命名为 priority (如果存在)
                if 'hall_priority' in existing_cols and 'priority' not in existing_cols:
                    try:
                        # SQLite 不支持 RENAME COLUMN 太旧版本, 用 workaround
                        conn.execute("ALTER TABLE mt_task_hall ADD COLUMN priority INTEGER DEFAULT 50")
                        conn.execute("UPDATE mt_task_hall SET priority = IFNULL(hall_priority, 50)")
                        conn.commit()
                    except Exception:
                        pass
            
            # 生成 hall_code: HALL-YYYYMMDD-NNN
            today = datetime.now().strftime("%Y%m%d")
            seq = conn.execute(
                "SELECT COUNT(*) FROM mt_task_hall WHERE hall_code LIKE ?",
                (f"HALL-{today}%",)
            ).fetchone()[0] + 1
            hall_code = f"HALL-{today}-{seq:03d}"
            
            conn.execute(
                """INSERT OR IGNORE INTO mt_task_hall
                   (hall_code, task_title, task_type, description, source, priority,
                    status, created_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (hall_code, task_title, task_type,
                 (description or "")[:1000], source, priority,
                 "DONE" if auto_done else "QUEUED",
                 _now_iso(), json.dumps(extra or {}, ensure_ascii=False)[:2000])
            )
            conn.commit()
            conn.close()
            
            sys.stderr.write(
                f"[BRAIN] 🏛️ 入厅: {hall_code} "
                f"[{task_type}] {task_title[:40]}"
                f"{' (自动结案)' if auto_done else ' (待派单)'}\n"
            )
            return hall_code
            
        except Exception as e:
            sys.stderr.write(f"[BRAIN] 入厅跳过 (非致命): {e}\n")
            return None
    
    # ── 协作总线事件 → 入厅映射 (高层策略) ──
    
    EVENT_TO_HALL_MAP: Dict[str, Dict[str, Any]] = {
        # 市场异动 → BRAIN_REVIEW 任务 (人工复盘异动原因)
        "MARKET_ANOMALY": {
            "task_type": "MARKET_REVIEW",
            "title_tpl": "市场异动复盘: {detail}",
            "auto_done": False,   # 需要派单给专家复盘
            "priority": 70,
        },
        # 版本变更 → VERSION_BUMP 记录
        "VERSION_CHANGE": {
            "task_type": "VERSION_BUMP",
            "title_tpl": "版本变更记录: {detail}",
            "auto_done": True,    # 版本变更已执行, 入厅备案
            "priority": 30,
        },
        # 严重运维故障 → SYSTEM_FIX 紧急派单
        "CRITICAL_ALERT": {
            "task_type": "SYSTEM_FIX",
            "title_tpl": "紧急修复: {detail}",
            "auto_done": False,
            "priority": 100,
        },
        # 沙盘熔断 → BRAIN_REVIEW 复盘
        "SANDBOX_HISTORY_COMPLETE": {
            "task_type": "BRAIN_REVIEW",
            "title_tpl": "沙盘回测复盘: {detail}",
            "auto_done": True,
            "priority": 40,
        },
    }


# ── 单例 ──
brain_feed = BrainFeedEngine()


def get_brain_feed() -> BrainFeedEngine:
    return brain_feed
