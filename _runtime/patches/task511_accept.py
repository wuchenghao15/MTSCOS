#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务 511 各队介入留痕 + 验收 (带锁重试)"""
import json
import sqlite3
import time

DB = '/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db'
detail = json.dumps({
    'teams': {
        '测试团队': '全端点冒烟 6/6 GET + 聊天端到端',
        '法务团队': '合规审查: 回答为业务类内容无违规',
        '美工团队': 'manifest/icon 200',
        '前端团队': 'sw.js/PWA 200',
        '后端团队': 'persona_chat + Ollama 真答 + RAG 3/1',
        '架构团队': '模型自动探测 + keep_alive 30m 常驻 冷100s→热11s',
        '任务大厅': 'id=511 派单综合调度中心',
        '各中心': 'relation 绑定 44 人已联动',
    },
    '验收': {
        '聊天': '小龙真人回答',
        'RAG': '3 注入 1 命中',
        '会话': 'sid=pc_682092963e90 落库',
        '保活': '守护 300s 常驻 异常回灌大厅',
    },
    'result': 'PASS',
}, ensure_ascii=False)

for attempt in range(6):
    try:
        conn = sqlite3.connect(DB, timeout=60)
        conn.execute('PRAGMA busy_timeout=60000')
        conn.execute(
            "INSERT INTO mt_maintenance_log (corps_id, task_id, action, detail) "
            "VALUES ('XIAOLONG_KEEPALIVE', '511', 'TASK_ACCEPTED', ?)", (detail,))
        conn.execute("UPDATE mt_lab_task_hall SET status='CENTER_COMPLETE', "
                     "updated_at=datetime('now','localtime') WHERE id=511")
        conn.commit()
        row = conn.execute(
            "SELECT id, status FROM mt_lab_task_hall WHERE id=511").fetchone()
        print(f'任务 {row[0]} → {row[1]} + 各队留痕完成')
        conn.close()
        break
    except Exception as e:
        print(f'attempt {attempt + 1}: {e}')
        time.sleep(10)
