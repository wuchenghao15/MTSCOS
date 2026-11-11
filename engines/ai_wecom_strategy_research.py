#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
战略中心: 企业微信对接方案研究 (flow_wecom_strategy_20261026)
================================================================
#600 任务 — 战略中心针对企业微信对接的完整方案研究

执行方式:
  python3 ai_wecom_strategy_research.py run   # 生成研究报告 → mt_strategy_research
  python3 ai_wecom_strategy_research.py show  # 显示报告
"""
from __future__ import annotations
import os, json, sqlite3, argparse
from datetime import datetime
from pathlib import Path

_DB_PATH = str(Path(__file__).resolve().parent.parent / "database" / "app.db")
FLOW_ID = "flow_wecom_strategy_20261026"

# ═══════════════════════════════════════════════════════════
# 战略研究报告: 企业微信对接方案
# ═══════════════════════════════════════════════════════════
RESEARCH_REPORT = {
    'research_id': 'RES_WECOM_INTEGRATION_20261026',
    'title': '企业微信对接完整方案研究',
    'category': 'TECH_INTEGRATION_RESEARCH',
    'severity': 'HIGH',
    'executive_summary': (
        'MTSCOS AI 已具备企微「推送通道」完整基础设施 (wecom_hub_bp + wecom_client + 指令桥), '
        '但缺失「双向通道」(用户发消息→AI回复)。本研究提出 P0→P3 四阶段演进: '
        '先打通回调协议 (验签+加解密+被动回复), 再接入本地零token推理引擎, '
        '最后扩展到外部客户/客户联系。'
    ),
    
    # ── Part 1: 现状盘点 ──
    'current_state': {
        'existing_assets': [
            {'file': 'blueprints/wecom_hub_bp.py', 'capability': '群机器人 webhook 推送 + 自动开会 + 中心事件钩子 + 指令桥白名单', 'maturity': '⭐⭐⭐⭐', 'coverage': '上行推送 OK, 下行指令桥 OK'},
            {'file': 'core/services/wecom_client.py', 'capability': 'WeComClient API 客户端 (access_token/消息/通讯录/审批/日程/会议/文档/客户联系/机器人)', 'maturity': '⭐⭐⭐⭐', 'coverage': 'API 封装完整'},
            {'file': 'ai_engines/wecom_ai_employee.py', 'capability': '企微 AI 员工体系', 'maturity': '⭐⭐⭐', 'coverage': '初始化阶段'},
            {'file': 'mt_wecom_config', 'capability': '配置中心化 (webhook/secret/agentId 存DB, 禁止硬编码)', 'maturity': '⭐⭐⭐⭐⭐'},
            {'file': 'mt_wecom_send_log + mt_lab_audit_log', 'capability': '全量双轨审计', 'maturity': '⭐⭐⭐⭐⭐'},
            {'file': 'mt_wecom_commands (指令桥)', 'capability': '企微上行指令白名单执行器 (daemon_status/hall/patrol/meeting/exam/approve/reject)', 'maturity': '⭐⭐⭐', 'coverage': '回调入口缺失 → 指令只能 API 触发'},
        ],
        'missing_pieces': [
            {'gap': '回调协议 (用户→AI 双向)', 'severity': 'CRITICAL', 'impact': '用户无法在企微直接与 AI 对话, 只能被动接收推送'},
            {'gap': '消息验签 + 加解密', 'severity': 'CRITICAL', 'impact': '不实现则企微回调 URL 无法验证通过, 安全风险'},
            {'gap': '被动回复 XML 构造', 'severity': 'CRITICAL', 'impact': '企微回调要求 5s 内返回加密 XML, 否则重试3次后丢弃'},
            {'gap': '本地零token推理对接', 'severity': 'HIGH', 'impact': '企微消息 → 云端 LLM 会消耗大量 token, 违反本地推理优先原则'},
            {'gap': '会话状态管理', 'severity': 'MEDIUM', 'impact': '多轮对话无上下文'},
            {'gap': '外部客户/客户联系接入', 'severity': 'MEDIUM', 'impact': '目前仅覆盖企微内部成员, 外部客户无法接入'},
        ],
    },
    
    # ── Part 2: 接入模式选型 ──
    'integration_modes': {
        'modes': [
            {
                'mode': '自建应用 + 回调 (推荐 P0 先做)',
                'description': '创建企微自建应用 → 配置回调 URL → 接收成员消息事件 → 本地推理 → 被动回复',
                'prerequisites': ['企微管理员权限', '公网 HTTPS 可访问域名', 'Flask 应用监听 /wecom/callback'],
                'protocol_flow': [
                    'GET /wecom/callback?msg_signature=&timestamp=&nonce=&echostr=',
                    '  → 验签 → 解密 echostr → 返回明文 echostr',
                    'POST /wecom/callback (加密 XML)',
                    '  → 验签 (msg_signature=SHA1(token+timestamp+nonce+加密串))',
                    '  → AES-256-CBC 解密 → 明文 XML (ToUserName/FromUserName/Content/MsgType)',
                    '  → 本地推理处理 (零token)',
                    '  → 构造回复 XML → AES 加密 → 返回 (必须 5s 内)',
                ],
                'key_config': {
                    'WECOM_CORPID': '企业 ID (管理后台顶部)',
                    'WECOM_AGENTID': '自建应用 ID',
                    'WECOM_CORPSECRET': '应用 Secret',
                    'WECOM_CALLBACK_TOKEN': '回调 URL 校验 Token (自定义)',
                    'WECOM_CALLBACK_AESKEY': '消息加密 Key (43位, Base64 encoded AES-256-CBC)',
                },
                'implementation_sketch': {
                    'dependencies': ['Flask (已有)', 'pycryptodome (pip install pycryptodome)'],
                    'files_to_create': [
                        'blueprints/wecom_callback_bp.py (回调路由 + 验签 + 加解密 + 被动回复)',
                        'core/services/wecom_crypto.py (验签 + AES 加解密工具)',
                        'ai_engines/wecom_message_router.py (消息路由: user → intent → engine)',
                    ],
                },
            },
            {
                'mode': '群机器人 Webhook (已实现)',
                'description': '单向推送, 无接收能力',
                'maturity': '✅ 已有 (wecom_hub_bp.wecom_push)',
                'limitations': '只能推送 markdown, 不能接收消息, 无双向对话',
            },
            {
                'mode': '应用消息 API (已部分实现)',
                'description': '主动推送应用消息给指定成员 (通过 WeComClient.send_app_message)',
                'maturity': '✅ 已有 (wecom_client.py)',
                'limitations': '主动推送, 成员回复消息需要回调入口才能接收',
            },
            {
                'mode': '外部客户/客户联系 (P2)',
                'description': '接待外部客户咨询, 需要企微「客户联系」权限',
                'prerequisites': ['企微升级到专业版', '客户联系权限开通', '客户群/外部联系人'],
                'flow': '外部客户 → 企微客户联系消息 → 回调 → AI 客服回复',
            },
        ],
        'recommendation': 'P0 立即实现「自建应用 + 回调」, 打通用户↔AI 双向通道; 然后 P1 接入本地推理引擎实现零token; P2 扩展外部客户',
    },
    
    # ── Part 3: 技术架构 ──
    'architecture': {
        'target_state': 'wecom_hub_bp (推送) + wecom_callback_bp (回调) + wecom_client.py (API) + local_ai_inference_engine (推理)',
        'data_flow': [
            '企微用户发消息 → 企微服务器 POST /wecom/callback (加密 XML)',
            '→ wecom_callback_bp 验签 + AES 解密',
            '→ wecom_message_router 解析意图',
            '→ local_ai_inference_engine 本地推理 (零token, qwen2.5:14b)',
            '→ wecom_crypto 加密回复 XML',
            '→ 5s 内返回企微服务器',
            '→ mt_wecom_send_log 审计 + mt_ai_brain_feed_log 脑库投喂',
        ],
        'session_management': {
            'session_store': 'SQLite (新增 mt_wecom_session 表)',
            'session_key': 'FromUserName + AgentId',
            'context_ttl': '30min 无对话自动过期',
            'multi_turn': '保留最近 10 轮对话历史',
        },
    },
    
    # ── Part 4: 零 token 实现 ──
    'zero_token_approach': {
        'principle': '所有企微消息处理走本地 Ollama, 零外部 API 消耗',
        'engine': 'local_ai_inference_engine (已存在, 支持 chat/classify/review/bug_analysis)',
        'router_strategy': [
            {'intent': 'chat', 'engine': 'ollama', 'model': 'qwen2.5:14b', 'template': 'wecom_chat'},
            {'intent': 'question', 'engine': 'ollama', 'model': 'qwen2.5:14b', 'template': 'wecom_qa'},
            {'intent': 'command', 'engine': '本地规则匹配', 'action': '白名单指令桥 (daemon_status/hall/patrol...)'},
            {'intent': 'help', 'engine': '规则匹配', 'action': '返回可用指令列表'},
            {'intent': 'system_query', 'engine': 'SQL 查询', 'action': '直查 mt_daemon_registry/mt_lab_task_hall 等'},
        ],
    },
    
    # ── Part 5: 安全合规 ──
    'security_compliance': {
        'crypto': 'AES-256-CBC + SHA1 验签 (企微官方协议, 禁止自定义)',
        'config': 'corpId/secret/agentId/aesKey/token 全部走 mt_wecom_config + 环境变量, 禁止硬编码',
        'audit': '每条消息 → mt_wecom_send_log (发送) + mt_lab_audit_log (审计) + mt_ai_brain_feed_log (脑库)',
        'rate_limit': '单用户 20 msg/min, 超限返回 "消息过于频繁"',
        'permission': '指令桥严格白名单 (daemon_status/hall/patrol/meeting/exam/approve/reject), 禁止任意代码执行',
        'data_safety': '本地推理零token → 用户消息不经过外部 API, 数据不出域',
        'veto': '所有企微上行指令必须经过任务大厅入口 + SA 否决权覆盖',
    },
    
    # ── Part 6: 分阶段路线图 ──
    'roadmap': [
        {'phase': 'P0 回调协议打通', 'priority': 'CRITICAL', 'duration': '3天', 'tasks': [
            '① 创建自建应用 + 配置回调 URL + Token + EncodingAESKey',
            '② 实现 wecom_crypto.py (SHA1验签 + AES加解密)',
            '③ 实现 wecom_callback_bp.py (GET验证 + POST解密 + 被动回复)',
            '④ Flask 注册蓝图 + 公网可达 (Tunnel 或 ngrok)',
            '⑤ 手动测试: 企微发消息 → Flask 接收 → 被动回复',
        ]},
        {'phase': 'P1 本地推理对接', 'priority': 'HIGH', 'duration': '2天', 'tasks': [
            '① wecom_message_router 解析意图 → local_ai_inference_engine',
            '② 会话状态管理 (mt_wecom_session)',
            '③ 白名单指令桥增强 (企微消息 → mt_wecom_commands)',
            '④ 零token验证: 确认全部推理走本地 Ollama',
        ]},
        {'phase': 'P2 外部客户扩展', 'priority': 'MEDIUM', 'duration': '5天', 'tasks': [
            '① 企微升级专业版 + 开通客户联系',
            '② 外部客户消息回调 (需要额外回调 URL)',
            '③ 智能客服分流 (客户 → AI / 内部成员 → AI)',
            '④ welcome_code 欢迎语',
        ]},
        {'phase': 'P3 增强', 'priority': 'LOW', 'duration': '持续迭代', 'tasks': [
            '① 应用消息 API 主动推送增强 (模板卡片/小程序卡片)',
            '② 企微日程/会议/文档集成',
            '③ 多自建应用 (不同 AI 引擎对应不同应用)',
            '④ 语音/图片消息处理',
        ]},
    ],
    
    # ── Part 7: 治理铁律 ──
    'governance': {
        'gatekeeper': '所有指令桥扩展/修改 → 任务大厅唯一入口 (#600)',
        'approval': '企微配置变更 (webhook/secret/token) → 多层审批',
        'veto': 'SA 一票否决可覆盖任何企微指令/配置',
        'legislation': '《数据安全与删库防护法》第5条 (工作流意识统一) 适用于企微指令桥',
    },
}


def _db():
    c = sqlite3.connect(_DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _ensure_tables(conn):
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_strategy_research (
        id INTEGER PRIMARY KEY AUTOINCREMENT, research_id TEXT UNIQUE,
        title TEXT, category TEXT, severity TEXT,
        root_causes TEXT, lessons_learned TEXT, mitigations TEXT,
        risk_level TEXT DEFAULT 'MEDIUM', status TEXT DEFAULT 'PUBLISHED',
        flow_id TEXT, published_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    # 企微会话表 (P1 需要)
    conn.execute(f"""CREATE TABLE IF NOT EXISTS mt_wecom_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_key TEXT UNIQUE,
        wecom_user_id TEXT, agent_id INTEGER,
        last_message TEXT, context_json TEXT,
        message_count INTEGER DEFAULT 0,
        last_active TEXT DEFAULT (datetime('now','localtime')),
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    conn.commit()


def run(conn=None) -> dict:
    save_conn = False
    if conn is None:
        conn = _db()
        save_conn = True
    
    _ensure_tables(conn)
    
    r = RESEARCH_REPORT
    cur = conn.execute("""INSERT OR IGNORE INTO mt_strategy_research 
        (research_id, title, category, severity, 
         root_causes, lessons_learned, mitigations, risk_level, flow_id)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (r['research_id'], r['title'], r['category'], r['severity'],
         json.dumps(r['current_state']['missing_pieces'], ensure_ascii=False)[:3000],
         r['executive_summary'],
         json.dumps(r['roadmap'], ensure_ascii=False)[:3000],
         'HIGH', FLOW_ID))
    
    result = {'research_id': r['research_id'], 'title': r['title'], 'saved': cur.rowcount > 0}
    
    if save_conn:
        conn.commit()
        conn.close()
    
    return result


def show():
    r = RESEARCH_REPORT
    print(f"{'='*60}")
    print(f"🔬 战略研究: {r['title']}")
    print(f"{'='*60}")
    print(f"\n📌 摘要: {r['executive_summary']}\n")
    
    print("┌─ 现状盘点 ─────────────────────────────────────────────────┐")
    for a in r['current_state']['existing_assets']:
        print(f"  ✅ {a['capability'][:50]:<50} [{a['maturity']}]")
    for g in r['current_state']['missing_pieces']:
        print(f"  ❌ {g['gap']:<40} [{g['severity']}] {g['impact']}")
    print("└──────────────────────────────────────────────────────────────┘")
    
    print("\n┌─ 路线图 ─────────────────────────────────────────────────────┐")
    for p in r['roadmap']:
        print(f"  {p['phase']:<25} [{p['priority']}] {p['duration']}")
        for t in p['tasks']:
            print(f"    {t}")
    print("└──────────────────────────────────────────────────────────────┘")
    
    print(f"\n💡 推荐方案: {r['integration_modes']['recommendation']}")
    print(f"🔐 安全要点: AES-256-CBC + SHA1验签 + 本地零token + 全量审计 + SA否决权覆盖")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['run', 'show'])
    args = parser.parse_args()
    
    if args.command == 'run':
        print(json.dumps(run(), ensure_ascii=False, indent=2))
    elif args.command == 'show':
        show()


if __name__ == '__main__':
    main()
