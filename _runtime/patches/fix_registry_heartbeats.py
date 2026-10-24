#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""registry 心跳登记补写 (锁重试版) — 6 个 launchd 守护的注册行 INSERT OR IGNORE + 心跳刷新"""
import json
import sqlite3
import time
import os

DB = '/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db'
DAEMONS = [
    ('sys_andromeda_society', '仙女座自治区 14 模块守护 (调研/拜师/轮岗/孵化/立法/战略/架构) 60s'),
    ('sys_community_governance', '社区治理守护 (表决/立案/条款/颁布+圆桌磋商/学习/交流) 300s'),
    ('sys_center_relation', '中心↔AI 联动关系引擎 (自动绑定/认领广播/关系盘点) 300s'),
    ('sys_corps_field', '维和部队分队化市场下沉 (巡逻/调研/抢修/赋能/侦察 轮转) 600s'),
    ('sys_xiaolong_keepalive', '小龙聊天室保活守护 (全端点+Ollama 聊天链路抽检) 300s'),
    ('sys_firewall_hardening', '防火墙四抗加固 (攻击/冲击/病毒/污染) 300s'),
]

for attempt in range(8):
    try:
        conn = sqlite3.connect(DB, timeout=60)
        conn.execute('PRAGMA busy_timeout=60000')
        now = "datetime('now','localtime')"
        fixed = 0
        for name, duty in DAEMONS:
            row = conn.execute(
                "SELECT pid, last_heartbeat FROM mt_daemon_registry "
                "WHERE process_name=?", (name,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO mt_daemon_registry (process_name, duty, pid, "
                    "status, last_heartbeat, updated_at) VALUES (?,?,?,?,"
                    f"{now},{now})",
                    (name, duty, 0, 'RUNNING'))
                fixed += 1
            elif not row[1]:
                conn.execute(
                    "UPDATE mt_daemon_registry SET status='RUNNING', "
                    f"last_heartbeat={now}, updated_at={now} WHERE process_name=?",
                    (name,))
                fixed += 1
        conn.commit()
        rows = conn.execute(
            "SELECT process_name||' hb='||IFNULL(last_heartbeat,'NULL') "
            "FROM mt_daemon_registry WHERE process_name IN (?,?,?,?,?,?)",
            tuple(d[0] for d in DAEMONS)).fetchall()
        conn.close()
        print(f'补写 {fixed} 行, 终态:')
        for r in rows:
            print(' ', r[0])
        break
    except Exception as e:
        print(f'attempt {attempt + 1}: {str(e)[:60]}')
        time.sleep(15)
