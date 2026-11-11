#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⛓️ MTSCOS AI 社区区块链引擎

轻量 PoA 链 (proof-of-authority), 每 tick 出一块 (≈60s):
  - 打包 PENDING 交易 → mt_blockchain (每块最多 20 tx)
  - 更新 mt_consensus (19 中心 = 19 验证节点, 全票过即共识)
  - 触发神经元 fire (块确认 → 相关神经元 fire_count++)
  - 神经元权重动态调整 (fire_count 增长 → weight↑, 长期不 fire → weight↓)

挂点: daemon_skill_lab_bp tick 轨道末轨 (blockchain_neurons)
"""
import os, json, hashlib, sqlite3, random, time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'app.db')

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mt_blockchain (
        height INTEGER PRIMARY KEY,
        block_hash TEXT UNIQUE NOT NULL,
        prev_hash TEXT NOT NULL,
        timestamp TEXT DEFAULT (datetime('now','localtime')),
        tx_count INTEGER DEFAULT 0,
        proposer TEXT,
        validator_count INTEGER DEFAULT 0,
        merkle_root TEXT,
        data_json TEXT)""",
    """CREATE TABLE IF NOT EXISTS mt_tx_pool (
        tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tx_hash TEXT UNIQUE NOT NULL,
        tx_type TEXT NOT NULL,
        sender TEXT,
        payload TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        status TEXT DEFAULT 'PENDING',
        block_height INTEGER)""",
    """CREATE TABLE IF NOT EXISTS mt_neuron (
        neuron_id INTEGER PRIMARY KEY AUTOINCREMENT,
        neuron_type TEXT NOT NULL,
        ref_id INTEGER,
        name TEXT,
        domain TEXT,
        weight REAL DEFAULT 1.0,
        connected_to TEXT,
        fire_count INTEGER DEFAULT 0,
        last_fired_at TEXT,
        status TEXT DEFAULT 'ACTIVE',
        created_at TEXT DEFAULT (datetime('now','localtime')))""",
    """CREATE TABLE IF NOT EXISTS mt_consensus (
        round INTEGER PRIMARY KEY AUTOINCREMENT,
        block_height INTEGER,
        proposer TEXT,
        validators TEXT,
        votes_for INTEGER DEFAULT 0,
        votes_against INTEGER DEFAULT 0,
        consensus_reached INTEGER DEFAULT 0,
        reached_at TEXT)""",
]

CENTER_NAMES = [
    "部署运维中心","安全审计中心","开发流程中心","AI 引擎中心",
    "人力统一调配中心","专家团队中心","规则治理中心","监察大队",
    "数据备份中心","升级演进中心","数据研究中心","前端设计中心",
    "教育题库中心","Skill研发中心","仙女座同步中心","战略中心",
    "法务合规中心","漏洞修复适配中心","工作流研究中心"
]

def _db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    for s in SCHEMA:
        try: conn.execute(s)
        except Exception: pass
    conn.commit()
    return conn

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _hash(*parts):
    """SHA256 联合哈希"""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode())
    return h.hexdigest()

def _merkle_root(tx_hashes):
    """简化 Merkle: 所有 tx_hash 拼接后 SHA256"""
    return _hash("|".join(tx_hashes)) if tx_hashes else _hash("empty")

def produce_block(conn=None):
    """出一块 — tick 每轮调用一次"""
    close_after = conn is None
    conn = conn or _db()
    result = {"height": 0, "tx_count": 0, "consensus": False, "neurons_fired": 0}
    try:
        # 1. 取最新高度
        row = conn.execute("SELECT height FROM mt_blockchain ORDER BY height DESC LIMIT 1").fetchone()
        prev_height = row["height"] if row else 0
        new_height = prev_height + 1
        prev_hash_row = conn.execute("SELECT block_hash FROM mt_blockchain WHERE height=?", (prev_height,)).fetchone()
        prev_hash = prev_hash_row["block_hash"] if prev_hash_row else _hash("GENESIS")

        # 2. 取 PENDING 交易 (最多 20)
        txs = conn.execute("""
            SELECT tx_id, tx_hash, tx_type, sender, payload FROM mt_tx_pool
            WHERE status='PENDING' ORDER BY rowid ASC LIMIT 20
        """).fetchall()

        tx_hashes = [t["tx_hash"] for t in txs]
        merkle = _merkle_root(tx_hashes)

        # 3. PoA: 19 中心轮流提议 (round robin by height mod 19)
        proposer = CENTER_NAMES[new_height % 19]

        # 4. 共识模拟: 19 中心全票过 (PoA 权威节点)
        votes_for = 19
        consensus = True

        # 5. 算块哈希
        block_hash = _hash(new_height, prev_hash, merkle, proposer, _now())

        # 6. 写块
        conn.execute("""INSERT OR IGNORE INTO mt_blockchain
            (height, block_hash, prev_hash, tx_count, proposer, validator_count, merkle_root, data_json)
            VALUES (?,?,?,?,?,?,?,?)""",
            (new_height, block_hash, prev_hash, len(txs), proposer, 19, merkle,
             json.dumps({"tx_types": [t["tx_type"] for t in txs]}, ensure_ascii=False)))

        # 7. 交易打包
        conn.execute("UPDATE mt_tx_pool SET status='CONFIRMED', block_height=? WHERE tx_id IN ({})".format(
            ",".join("?"*len(txs))),
            [new_height] + [t["tx_id"] for t in txs])

        # 8. 共识记录
        conn.execute("""INSERT INTO mt_consensus
            (block_height, proposer, validators, votes_for, votes_against, consensus_reached, reached_at)
            VALUES (?,?,?,?,?,?,?)""",
            (new_height, proposer, ",".join(CENTER_NAMES), votes_for, 0, 1 if consensus else 0, _now()))

        # 9. 神经元 fire (块确认 → 相关神经元 fire_count++)
        fired = 0
        for t in txs:
            sender = t["sender"] or ""
            tp = t["tx_type"] or ""
            # 按 sender 匹配中心神经元
            neurons = conn.execute("""SELECT neuron_id FROM mt_neuron
                WHERE status='ACTIVE' AND (name=? OR domain LIKE ?)""",
                (sender, f"%{sender[:4]}%")).fetchall()
            for n in neurons:
                conn.execute("""UPDATE mt_neuron SET fire_count=fire_count+1, last_fired_at=?
                    WHERE neuron_id=?""", (_now(), n["neuron_id"]))
                fired += 1

        # 10. 神经元权重衰减 (长期不 fire → weight 降)
        conn.execute("""UPDATE mt_neuron SET weight=MAX(0.5, weight*0.999)
            WHERE status='ACTIVE' AND last_fired_at < datetime('now','localtime','-2 hours')""")
        # fire 过 → weight 升
        conn.execute("""UPDATE mt_neuron SET weight=MIN(2.0, weight*1.01)
            WHERE last_fired_at >= datetime('now','localtime','-5 minutes')""")

        conn.commit()
        result.update({"height": new_height, "tx_count": len(txs), "consensus": consensus, "neurons_fired": fired})
    except Exception as e:
        result["error"] = str(e)[:200]
    finally:
        if close_after: conn.close()
    return result


def run_once():
    """tick 轨入口"""
    conn = _db()
    # 确保所有中心/AI员工/Skill 都有神经元
    try:
        conn.execute("""INSERT OR IGNORE INTO mt_neuron (neuron_type, ref_id, name, domain)
            SELECT 'CENTER', id, name, domain FROM mt_lab_centers WHERE status='ACTIVE'""")
        conn.execute("""INSERT OR IGNORE INTO mt_neuron (neuron_type, ref_id, name, domain)
            SELECT 'AI_EMPLOYEE', employee_id, name, role FROM mt_ai_employees WHERE status='ACTIVE'""")
        conn.execute("""INSERT OR IGNORE INTO mt_neuron (neuron_type, ref_id, name, domain)
            SELECT 'SKILL', direction_id, direction_title, center_name
            FROM mt_center_direction_pool WHERE status='ACTIVE'""")
        conn.commit()
    except Exception: pass

    result = produce_block(conn)
    conn.close()
    return result


if __name__ == "__main__":
    r = run_once()
    print(f"⛓️ blockchain: height={r.get('height')} tx={r.get('tx_count')} consensus={r.get('consensus')} neurons_fired={r.get('neurons_fired')}")
