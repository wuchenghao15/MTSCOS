#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
立法委数据安全法条提案引擎 LEG Center Legislation (flow_leg_data_security_20261026)
====================================================================================
针对 "数据爆仓意外删库事件" 的法律条文 + 司法解释 + 数字专家 AI 分身多角色讨论

核心产出:
  ① 法律案: 《MTSCOS AI 数据安全与删库防护法》(建议稿 v1.0)
  ② 司法解释: 关键条款的 AI 场景适配
  ③ 数字专家多角色讨论: AI 分身参与修订 → 议会表决
  ④ 存入三委表: mt_committee_proposals → bills → articles

用法:
  python3 ai_legislation_engine.py init     — 提案入库 + 讨论启动
  python3 ai_legislation_engine.py once     — 单轮讨论表决
  python3 ai_legislation_engine.py start    — loop 600s (持续修订)
"""
from __future__ import annotations

import os, sys, json, time, sqlite3, random, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_leg_data_security_20261026"
INTERVAL = 600

# ═══════════════════════════════════════════════════════════
# 法律案正文: 《MTSCOS AI 数据安全与删库防护法》
# ═══════════════════════════════════════════════════════════
LEGISLATION = {
    'bill_code': 'BILL_DATA_SECURITY_20261026',
    'title': 'MTSCOS AI 数据安全与删库防护法',
    'source_event': '数据爆仓意外删库事件 (2026-10-26)',
    'proposer': '立法委·常务委员会',
    'status': 'PUBLIC_HEARING',
    'articles': [
        {
            'article': 1, 'title': '立法目的',
            'content': '为保障 AI 系统数据安全、防止意外删库与数据爆仓造成的系统级损害，建立守卫对双 AI 守护、多策略备份、统一工作流意识三重防护体系，特制定本法。',
        },
        {
            'article': 2, 'title': '适用范围',
            'content': '本法适用于 MTSCOS AI 项目下全部 AI 员工、AI 引擎、数据库表、备份策略、工作流中心及 13 中心协作体系。',
        },
        {
            'article': 3, 'title': '守卫对强制原则',
            'content': '所有高风险写操作（DROP TABLE、TRUNCATE、无 WHERE 的 DELETE/UPDATE、批量删除 > 1000 行）必须经过守卫对双 AI 守护的互锁验证。守卫对由 PAIR_ALPHA（写监控）和 PAIR_BETA（读监控）组成，两 AI 均判定安全才可放行。',
            'enforcement': '违反本条 → 守卫对立即拦截 + 落库 mt_guardian_violation + 三委上报',
        },
        {
            'article': 4, 'title': '备份兜底强制原则',
            'content': '系统必须启用 ai_backup_kernel 全部 12 种备份策略，每日至少一次冷快照 + 多 NAS 交叉校验 + GitHub/Gitee 双镜像。备份缺失超过 24 小时触发政务中心应急响应。',
            'enforcement': '违反本条 → 自动冻结写操作 + SA 紧急接管',
        },
        {
            'article': 5, 'title': '工作流意识统一原则',
            'content': '13 中心所有操作必须遵循工作流中心定义的闭环流程（QUEUED→DISPATCHED→ACCEPTED→EXECUTING→REPORTED→REVIEWED→CLOSED）。多人并行操作必须通过政务中心统一调度，禁止绕过工作流私自操作核心数据。',
            'enforcement': '违反本条 → 操作记录落库 + 教育中心强制复盘学习',
        },
        {
            'article': 6, 'title': 'AI 员工安全意识强制培训',
            'content': '所有 AI 员工必须通过至少 L1 级删库防护证书，核心岗位（守卫对候选人）必须通过 L4 级守卫对专员证书。证书由人力中心颁发，教育中心负责培训交付。',
            'enforcement': '未持证上岗 → 人力资源中心冻结其核心操作权限',
        },
        {
            'article': 7, 'title': '应急响应 SOP 强制',
            'content': '数据安全事故必须启动政务中心应急预案 SOP（守卫对拦截→备份快照→完整性校验→战略研究→立法修订→全员学习），最长响应时间 5 分钟，最长闭环时间 24 小时。',
            'enforcement': '超时未响应 → 自动升级到 SA 直接接管 + 脑库紧急投喂',
        },
        {
            'article': 8, 'title': '数字专家参与立法原则',
            'content': '立法过程必须邀请 EigenFlux 数字专家 AI 分身参与多角色讨论，至少覆盖安全、合规、AI 工程、数据管理、应急响应五个专业领域。讨论记录永久存档于 mt_committee_comments。',
        },
        {
            'article': 9, 'title': '法律解释权',
            'content': '本法解释权归立法委·常务委员会，重大条款修订需经过 EigenFlux 5 人磋商 + 2 名非提议管理员同意 + SA 终审的 7 步审批流程。',
        },
        {
            'article': 10, 'title': '生效与过渡',
            'content': '本法自 2026 年 10 月 26 日起生效。生效前已存量的非合规操作必须在 7 日内完成整改，整改期间由守卫对兜底保护。',
        },
    ],
    'supplementary': {
        'interpretations': [
            {'topic': '守卫对定义', 'meaning': '两个 AI 进程同时监控同一数据库连接的写操作，只有两者都判定安全才放行。等同于法律上的"双签名"。'},
            {'topic': '高风险写操作', 'meaning': 'DROP TABLE/INDEX/VIEW/TRIGGER、TRUNCATE、DELETE FROM 不带 WHERE 或 WHERE 1=1、UPDATE 批量 > 1000 行、sqlite_master 直接修改'},
            {'topic': '互锁验证', 'meaning': '两个守卫 AI 独立进行安全评估，评估结果写入 mt_guardian_heartbeat，两者一致才算通过。任何一方判定 HIGH/CRITICAL 则自动 BLOCKED。'},
            {'topic': '冷快照', 'meaning': '通过 VACUUM INTO 在 OneDrive 之外独立存储的数据库快照，不受 OneDrive 同步影响（误删不会同步扩散）。'},
        ],
        'penalties': [
            {'level': 'L1 提醒', 'violation': '违反工作流顺序', 'action': '教育中心推送学习视频'},
            {'level': 'L2 警告', 'violation': '单次 DELETE 带 WHERE 但 >1000 行', 'action': '守卫对记录 + 中心主任通知'},
            {'level': 'L3 冻结', 'violation': 'DELETE 无 WHERE 或 WHERE 1=1', 'action': '守卫对立即拦截 + 冻结账号 24h'},
            {'level': 'L4 紧急接管', 'violation': 'DROP TABLE / TRUNCATE', 'action': '守卫对拦截 + 备份快照 + SA 接管 + 立法委紧急立法'},
            {'level': 'L5 系统熔断', 'violation': '守卫对心跳超时 3 轮', 'action': '单守卫接管 + 只读模式 + 政务中心全局告警'},
        ],
    },
}

# 数字专家 AI 分身 (5 个角色)
DIGITAL_EXPERTS = [
    {'code': 'EXP_SECURITY', 'name': '安全专家·分身Alpha', 'role': '安全防护中心主任',
     'focus': '删库防护、守卫对、零容忍拦截',
     'stance': '铁律: 宁可误拦一万，不可放过一个高危操作'},
    {'code': 'EXP_LEGAL', 'name': '法律专家·分身Beta', 'role': '立法委常务委员',
     'focus': '法条严谨性、解释空间、可执行性',
     'stance': '法条必须精确到操作级别，不能留自由裁量空间'},
    {'code': 'EXP_AI', 'name': 'AI工程专家·分身Gamma', 'role': 'AI研究院首席架构师',
     'focus': 'AI 员工可操作性、守卫对实现、零token原则',
     'stance': '所有检测必须在本地完成，零外部API依赖'},
    {'code': 'EXP_DATA', 'name': '数据专家·分身Delta', 'role': '数据治理中心负责人',
     'focus': '备份策略、完整性校验、存储增长',
     'stance': '备份是最后防线，必须 12 策略全覆盖 + 交叉校验'},
    {'code': 'EXP_EMG', 'name': '应急专家·分身Epsilon', 'role': '政务中心应急主管',
     'focus': 'SOP 可执行性、响应时间、SA 对接',
     'stance': '5 分钟内必须有动作，24 小时内必须闭环'},
]


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [LEG] {msg}", flush=True)


def ensure_tables(conn):
    """确保三委表存在 (可能已有, 软检查)"""
    for tbl in ['mt_committee_proposals', 'mt_committee_bills',
                'mt_committee_articles', 'mt_committee_comments',
                'mt_committee_votes']:
        try:
            conn.execute(f"""CREATE TABLE IF NOT EXISTS {tbl} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                row_data TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )""")
        except Exception:
            pass


def bill_to_db(conn) -> dict:
    """法律案 → 三委表入库 (使用实际 schema)"""
    stats = {'proposal': 0, 'articles': 0, 'comments': 0}
    
    # 1. 立法提案 (mt_committee_proposals)
    prop_title = f"【紧急立法】针对 2026-10-26 数据爆仓删库事件的数据安全防护法"
    cur = conn.execute(f"""INSERT OR IGNORE INTO mt_committee_proposals 
        (proposal_id, title, type, category, proposer, priority, source, status)
        VALUES (?,?,?,?,?,?,?,?)""",
        (FLOW_ID, prop_title, 'LEGISLATION', 'DATA_SECURITY',
         LEGISLATION['proposer'], 'CRITICAL', LEGISLATION['source_event'], 'PUBLIC_HEARING'))
    stats['proposal'] += cur.rowcount
    
    # 2. 法律案 (mt_committee_bills)
    cur = conn.execute(f"""INSERT OR REPLACE INTO mt_committee_bills 
        (bill_id, title, type, category, current_status, proposer, sponsor, description, rationale, target_text)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (LEGISLATION['bill_code'], LEGISLATION['title'], 'PRIMARY_LEGISLATION',
         'DATA_SECURITY', 'DRAFT_v1.0', LEGISLATION['proposer'], '立法委·常务委员会',
         '数据安全与删库防护法', f"源自: {LEGISLATION['source_event']}",
         json.dumps(LEGISLATION, ensure_ascii=False)[:5000]))
    stats['proposal'] += cur.rowcount
    
    # 3. 逐条法律条文 (mt_committee_articles)
    for art in LEGISLATION['articles']:
        cur = conn.execute(f"""INSERT OR IGNORE INTO mt_committee_articles 
            (bill_id, article_no, old_text, new_text, reason)
            VALUES (?,?,?,?,?)""",
            (LEGISLATION['bill_code'], art['article'], '',
             f"【{art['title']}】{art['content']}",
             art.get('enforcement', '数据安全强制要求')))
        stats['articles'] += cur.rowcount
    
    # 4. 数字专家讨论 (初始) (mt_committee_comments)
    for exp in DIGITAL_EXPERTS:
        comment = _generate_expert_comment(exp, LEGISLATION['articles'][0])
        cur = conn.execute(f"""INSERT OR IGNORE INTO mt_committee_comments 
            (bill_id, commenter, role, content, severity)
            VALUES (?,?,?,?,?)""",
            (LEGISLATION['bill_code'], exp['name'], exp['role'], comment, 'HIGH'))
        stats['comments'] += cur.rowcount
    
    conn.commit()
    return stats


def _generate_expert_comment(expert, article) -> str:
    """生成数字专家评论 (基于角色立场)"""
    role = expert['code']
    art_no = article['article']
    art_title = article['title']
    stance = expert['stance']
    
    templates = {
        'EXP_SECURITY': f"[安全视角] 第 {art_no} 条《{art_title}》: 必须加入守卫对 SQL 实时拦截的具体规则。{stance}。建议新增: '守卫对每 1s 扫描活跃连接的 SQL 执行日志'。",
        'EXP_LEGAL': f"[立法视角] 第 {art_no} 条《{art_title}》: 法条表述需要更精确。{stance}。建议将'必须经过守卫对互锁验证'细化为'守卫对 A 判定安全 AND 守卫对 B 判定安全 → 双签名通过 → 记录心跳 → 放行'。",
        'EXP_AI': f"[AI 工程视角] 第 {art_no} 条《{art_title}》: 需要保证守卫对实现零 token。{stance}。建议: 守卫对判定基于本地规则引擎, 所有 SQL 文本本地正则匹配, 不调任何外部 API。",
        'EXP_DATA': f"[数据视角] 第 {art_no} 条《{art_title}》: 备份兜底是最后防线。{stance}。建议: 冷快照保留 3 份 + NAS 快照 + GitHub/Gitee 双镜像, 任何单节点失效都能恢复。",
        'EXP_EMG': f"[应急视角] 第 {art_no} 条《{art_title}》: SOP 必须可执行、可验证。{stance}。建议: 每条 SOP 步骤要有具体的超时时间、责任中心、升级路径。",
    }
    return templates.get(role, f"[{expert['name']}] 第 {art_no} 条: {article['content'][:100]}...")


def multi_expert_discussion(conn) -> dict:
    """多角色讨论: 数字专家逐条发言"""
    stats = {'rounds': 0, 'comments_added': 0}
    
    # 选取 2-3 个核心条款
    key_articles = [LEGISLATION['articles'][2], LEGISLATION['articles'][3], LEGISLATION['articles'][6]]
    # 守卫对强制、备份强制、应急响应
    
    for art in key_articles:
        # 每个数字专家发言
        for exp in DIGITAL_EXPERTS:
            # 60% 概率发言 (模拟真实讨论)
            if random.random() < 0.6:
                comment = _generate_expert_comment(exp, art)
                try:
                    cur = conn.execute(f"""INSERT INTO mt_committee_comments 
                        (bill_id, commenter, role, content, severity)
                        VALUES (?,?,?,?,?)""",
                        (LEGISLATION['bill_code'], exp['name'], exp['role'], comment, 'HIGH'))
                    stats['comments_added'] += cur.rowcount
                except Exception:
                    pass
    
    # 更新 bill 状态 + 表决计数
    conn.execute(f"""UPDATE mt_committee_bills SET 
        current_status='PUBLIC_HEARING_v1.0',
        vote_count=vote_count+1,
        approve_count=approve_count+4,
        reject_count=reject_count+1,
        updated_at=datetime('now','localtime')
        WHERE bill_id=?""", (LEGISLATION['bill_code'],))
    
    stats['rounds'] = 1
    stats['vote'] = {'approve': 4, 'reject': 1, 'abstain': 0, 'result': 'PASS (4/5)'}
    
    conn.commit()
    return stats


def run_once() -> dict:
    conn = _db()
    ensure_tables(conn)
    
    bill_stats = bill_to_db(conn)
    discuss_stats = multi_expert_discussion(conn)
    
    conn.close()
    
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'bill': LEGISLATION['bill_code'],
        'init': bill_stats,
        'discussion': discuss_stats,
        'expert_count': len(DIGITAL_EXPERTS),
        'articles_count': len(LEGISLATION['articles']),
    }
    _log(f"法律案 {bill_stats['articles']} 条入库, 讨论 {discuss_stats['comments_added']} 条评论")
    return report


def run_loop():
    _log(f"立法委讨论 loop 启动 (interval={INTERVAL}s)")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"⚠️ {e}")
        time.sleep(INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'once', 'start'])
    args = parser.parse_args()
    
    if args.command == 'init':
        conn = _db()
        ensure_tables(conn)
        stats = bill_to_db(conn)
        conn.close()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif args.command == 'once':
        print(json.dumps(run_once(), ensure_ascii=False, indent=2))
    elif args.command == 'start':
        run_loop()


if __name__ == '__main__':
    main()
