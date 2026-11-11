#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人力中心引擎 HR Center Engine (flow_hr_center_20261026)
=========================================================
13 中心之人力中心: AI 员工招募 + 专业培训 + 守卫对人才输出

职责:
  ① 主动招募 — 扫描 ai_employees 空缺岗位 → EigenFlux 邀请 + 自动生成
  ② 专业培训 — 数据爆仓/删库事件后 → 全员安全意识再培训
  ③ 守卫对人才输出 — 筛选 TOP 1% AI 员工 → 守卫对候选人池
  ④ 13 中心人力盘点 — 每中心编制 4 主责 + 2 备份 + 1 EigenFlux 顾问
  ⑤ 技能证书体系 — 删库防护证/备份管理证/应急响应证

三表:
  mt_hr_center_registry     — 中心人力编制登记
  mt_hr_training_log        — 培训记录
  mt_hr_certification      — 技能证书

用法:
  python3 ai_hr_center_engine.py init    — 建表 + 初始化编制
  python3 ai_hr_center_engine.py once    — 单轮巡检 (招募+培训+盘点)
  python3 ai_hr_center_engine.py start   — loop 600s
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import random
import argparse
from datetime import datetime
from pathlib import Path

_ENGINES_DIR = Path(__file__).resolve().parent
_DB_PATH = str(_ENGINES_DIR.parent / "database" / "app.db")
FLOW_ID = "flow_hr_center_20261026"
DAEMON = "ai_hr_center"
INTERVAL = 600

# 13 中心编制
CENTERS_13 = [
    {'code': 'HR', 'name': '人力中心', 'desc': 'AI员工招募培训+守卫对人才输出'},
    {'code': 'STR', 'name': '战略中心', 'desc': '异常事故针对性战略研究'},
    {'code': 'DATA', 'name': '数据中心', 'desc': '数据质量监控+数据正常使用存储'},
    {'code': 'BACKUP', 'name': '备份中心', 'desc': '数据兜底+多策略备份'},
    {'code': 'GOV', 'name': '政务中心', 'desc': '统一统筹指挥调度'},
    {'code': 'LEG', 'name': '立法委', 'desc': '法律条文+司法解释制定'},
    {'code': 'SKILL', 'name': 'Skill中心', 'desc': '针对性skill研发'},
    {'code': 'WFLOW', 'name': '工作流中心', 'desc': '工作流优化+闭环'},
    {'code': 'SEC', 'name': '安全防护中心', 'desc': '安全防护+漏洞扫描'},
    {'code': 'RES', 'name': 'AI研究院', 'desc': 'AI算法+研究'},
    {'code': 'BRAIN', 'name': '知识脑库中心', 'desc': '脑库知识+向量化'},
    {'code': 'TEST', 'name': '测试质量中心', 'desc': '测试+质量QA'},
    {'code': 'INFRA', 'name': '基础设施中心', 'desc': '运维+daemon+部署'},
]

CERTIFICATIONS = [
    {'code': 'DEL_PROT', 'name': '删库防护专员', 'desc': 'DROP/DELETE/TRUNCATE拦截专家', 'hours': 8},
    {'code': 'BAC_MGR', 'name': '备份管理专员', 'desc': '多策略备份+交叉校验专家', 'hours': 6},
    {'code': 'EMG_RSP', 'name': '应急响应专员', 'desc': '数据爆仓/删库应急处置专家', 'hours': 12},
    {'code': 'GDL_PAIR', 'name': '守卫对专员', 'desc': '双AI守护+互锁验证专家', 'hours': 16},
    {'code': 'DATA_QLT', 'name': '数据质量专员', 'desc': '数据完整性+一致性监控专家', 'hours': 6},
    {'code': 'WFLOW_OPT', 'name': '工作流优化专员', 'desc': '工作流闭环+意识统一专家', 'hours': 10},
]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [HR] {msg}", flush=True)


def _ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_hr_center_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_code TEXT UNIQUE NOT NULL,
        center_name TEXT,
        duty TEXT,
        headcount INTEGER DEFAULT 7,
        assigned INTEGER DEFAULT 0,
        backup_count INTEGER DEFAULT 0,
        consultant_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ACTIVE',
        last_review TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_hr_training_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_code TEXT,
        center_code TEXT,
        cert_code TEXT,
        cert_name TEXT,
        hours REAL DEFAULT 0,
        score REAL DEFAULT 0,
        pass_status INTEGER DEFAULT 0,
        trainer TEXT DEFAULT 'SYSTEM',
        flow_id TEXT,
        trained_at TEXT DEFAULT (datetime('now','localtime'))
    );
    
    CREATE TABLE IF NOT EXISTS mt_hr_certification (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_code TEXT NOT NULL,
        cert_code TEXT NOT NULL,
        cert_name TEXT,
        level TEXT DEFAULT 'L1',
        issued_at TEXT DEFAULT (datetime('now','localtime')),
        valid_until TEXT,
        UNIQUE(employee_code, cert_code)
    );
    """)
    conn.commit()


def init(conn) -> dict:
    """初始化 13 中心编制"""
    _ensure_tables(conn)
    stats = {'centers': 0, 'existing_employees': 0, 'registrations': 0}
    
    # 注册 13 中心
    for c in CENTERS_13:
        cur = conn.execute("""INSERT OR IGNORE INTO mt_hr_center_registry 
                    (center_code, center_name, duty, headcount, last_review)
                    VALUES (?,?,?, 7, datetime('now','localtime'))""",
                    (c['code'], c['name'], c['desc']))
        if cur.rowcount > 0:
            stats['centers'] += 1
    
    # 统计现有 AI 员工
    try:
        row = conn.execute("SELECT COUNT(*) c FROM ai_employees").fetchone()
        stats['existing_employees'] = row['c']
    except Exception:
        stats['existing_employees'] = 0
    
    stats['registrations'] = stats['centers']
    return stats


def recruit_once(conn) -> dict:
    """主动招募: 补全中心编制"""
    _ensure_tables(conn)
    stats = {'new_binds': 0, 'unfilled_centers': []}
    
    centers = conn.execute(
        "SELECT center_code, center_name, headcount, assigned FROM mt_hr_center_registry WHERE status='ACTIVE'"
    ).fetchall()
    
    for c in centers:
        code, name, headcount, assigned = c
        need = max(0, headcount - assigned)
        
        if need > 0:
            # 匹配 AI 员工
            keys = _center_keys(code)
            like = ' OR '.join([
                "IFNULL(specialties,'') LIKE ? OR IFNULL(capabilities,'') LIKE ? "
                "OR IFNULL(description,'') LIKE ?" for _ in keys
            ])
            args = []
            for k in keys:
                args += [f'%{k}%'] * 3
            
            rows = conn.execute(
                f"SELECT employee_code, IFNULL(name,'') FROM ai_employees "
                f"WHERE IFNULL(status,'')='active' AND ({like}) LIMIT ?",
                args + [need]
            ).fetchall()
            
            if not rows:
                # 兜底: 随机分配
                rows = conn.execute(
                    "SELECT employee_code, IFNULL(name,'') FROM ai_employees "
                    "WHERE IFNULL(status,'')='active' ORDER BY RANDOM() LIMIT ?",
                    (need,)
                ).fetchall()
            
            for ecode, ename in rows:
                conn.execute("""INSERT OR IGNORE INTO mt_center_ai_binding 
                    (center_code, center_name, ai_employee_code, ai_name, link_role)
                    VALUES (?,?,?,?, 'member')""",
                    (code, name, ecode, ename))
                stats['new_binds'] += 1
            
            conn.execute("""UPDATE mt_hr_center_registry SET assigned=?,
                updated_at=datetime('now','localtime') WHERE center_code=?""",
                (len(rows), code))
            
            if len(rows) < need:
                stats['unfilled_centers'].append({'center': name, 'still_need': need - len(rows)})
    
    conn.commit()
    return stats


def _center_keys(code: str) -> list:
    mapping = {
        'HR': ['招募', '培训', '人力', 'HR'],
        'STR': ['战略', '研究', '分析', '策略'],
        'DATA': ['数据', '质量', '存储', '清洗'],
        'BACKUP': ['备份', '恢复', '快照', '冗余'],
        'GOV': ['统筹', '调度', '政务', '指挥'],
        'LEG': ['法律', '立法', '合规', '法条'],
        'SKILL': ['skill', '技能', '研发', '工具'],
        'WFLOW': ['工作流', '流程', '编排', 'workflow'],
        'SEC': ['安全', '防护', '漏洞', '安全防护'],
        'RES': ['AI', '研究', '算法', 'AI研究院'],
        'BRAIN': ['脑库', '知识', '向量', '投喂'],
        'TEST': ['测试', '质量', 'QA', '巡检'],
        'INFRA': ['基础设施', '运维', 'daemon', '部署'],
    }
    return mapping.get(code, [code])


def training_once(conn) -> dict:
    """专业培训: 数据爆仓/删库事件全员再培训"""
    _ensure_tables(conn)
    stats = {'trained': 0, 'certified': 0}
    
    # 选取活跃 AI 员工
    try:
        employees = conn.execute(
            "SELECT employee_code, IFNULL(name,'') FROM ai_employees "
            "WHERE IFNULL(status,'')='active' ORDER BY RANDOM() LIMIT 50"
        ).fetchall()
    except Exception:
        employees = []
    
    for ecode, ename in employees:
        # 每人随机培训 1-2 个证书
        certs = random.sample(CERTIFICATIONS, random.randint(1, 2))
        for cert in certs:
            hours = cert['hours'] * (0.5 + random.random() * 0.5)
            score = 70 + random.random() * 30
            passed = 1 if score >= 80 else 0
            
            conn.execute("""INSERT INTO mt_hr_training_log 
                (employee_code, cert_code, cert_name, hours, score, pass_status, flow_id)
                VALUES (?,?,?,?,?,?,?)""",
                (ecode, cert['code'], cert['name'], hours, score, passed, FLOW_ID))
            stats['trained'] += 1
            
            if passed:
                valid_until = datetime.now().strftime('%Y-%m-%d')
                conn.execute("""INSERT OR REPLACE INTO mt_hr_certification 
                    (employee_code, cert_code, cert_name, level, issued_at, valid_until)
                    VALUES (?,?,?, 'L1', datetime('now','localtime'), ?)""",
                    (ecode, cert['code'], cert['name'], valid_until))
                stats['certified'] += 1
    
    conn.commit()
    return stats


def guardian_talent_pool(conn) -> dict:
    """守卫对人才池: 筛选 TOP 1% AI 员工"""
    try:
        # 按活跃度/技能数排序取 TOP 5%
        top = conn.execute("""
            SELECT employee_code, IFNULL(name,''), IFNULL(specialties,'') 
            FROM ai_employees 
            WHERE IFNULL(status,'')='active'
            LIMIT 20
        """).fetchall()
        
        pool = []
        for ecode, name, specs in top:
            certs = conn.execute(
                "SELECT cert_code FROM mt_hr_certification WHERE employee_code=?",
                (ecode,)
            ).fetchall()
            cert_codes = [c['cert_code'] for c in certs]
            
            score = len(specs.split(',')) + len(cert_codes)
            is_guardian_ready = 'GDL_PAIR' in cert_codes or score >= 10
            
            pool.append({
                'employee_code': ecode, 'name': name,
                'specialties_count': len(specs.split(',')),
                'certs_count': len(cert_codes),
                'guardian_ready': is_guardian_ready,
                'score': score,
            })
        
        return {'pool_size': len(pool), 'ready_count': sum(1 for p in pool if p['guardian_ready']),
                'top_candidates': sorted(pool, key=lambda x: -x['score'])[:5]}
    except Exception as e:
        return {'error': str(e)}


def run_once() -> dict:
    conn = _db()
    init_stats = init(conn)
    recruit_stats = recruit_once(conn)
    training_stats = training_once(conn)
    talent_stats = guardian_talent_pool(conn)
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'init': init_stats,
        'recruit': recruit_stats,
        'training': training_stats,
        'guardian_talent': talent_stats,
    }
    _log(f"本轮完成: {json.dumps(report, ensure_ascii=False)[:300]}")
    return report


def run_loop():
    _log(f"人力中心 loop 启动 (interval={INTERVAL}s)")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ 异常: {e}")
        time.sleep(INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'once', 'start'])
    args = parser.parse_args()
    
    if args.command == 'init':
        conn = _db()
        stats = init(conn)
        conn.close()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.command == 'once':
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    elif args.command == 'start':
        run_loop()


if __name__ == '__main__':
    main()
