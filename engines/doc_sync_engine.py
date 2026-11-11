# -*- coding: utf-8 -*-
"""
DOC-SYNC — 同步中心·文档配套引擎
新功能落地 → 自动生成说明书条目(功能/路径/启动/使用方法) → docs/FEATURES.txt
mt_doc_registry 防重(文件+mtime指纹); launchd StartInterval 900 轻量调度

用法: python3 doc_sync_engine.py [--once]
"""
import sqlite3
import hashlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # flask-app/
DB = ROOT / "database" / "app.db"
DOC = ROOT / "docs" / "FEATURES.txt"
VER = ROOT / "docs" / "VERSION.txt"

# ── 功能注册表: (文件路径, 名称, 一句话功能, 启动方式, 使用方法) ──
FEATURES = [
    ("engines/edu_flywheel_engine.py", "教育飞轮 P0",
     "诊断→组卷→作答→错题本→掌握度→学习路径→每日练习→复测 6步自驱闭环",
     "launchd com.mtscos.edu-flywheel (600s/轮)",
     "自动运转; 查数据: exam_sessions/exam_results/wrong_book/user_knowledge_mastery/learning_paths/daily_practice"),
    ("engines/edu_p1_smart_engine.py", "教育智能 P1",
     "AI错因讲解(三段式) / 薄弱点变体题生成(qwen2.5-coder) / 难度自动校准(错误率>70%降档)",
     "launchd com.mtscos.edu-p1-smart (900s/轮)",
     "自动运转; 讲解在 wrong_book.ai_explanation, 变体题 question_bank.source='ai_variant'"),
    ("engines/chat_toolbox.py", "聊天工具链",
     "18个沙箱工具(读文件/grep/写文件/命令执行/测试/仙女座桥接/主题/用户动作) + tool-use循环 + SSE on_event",
     "Flask tick 内懒加载, 无需独立启动",
     "聊天说'查XX/修bug/换主题/改昵称'即触发; /api/sa-prime/chat/stream 流式"),
    ("blueprints/sa_prime_bp.py", "SA Prime 指挥官",
     "黑金三栏指挥官台: 工具直通聊天+全模型池+大厅面板+多租户+审计流",
     "浏览器开 /sa-prime (SA 身份)",
     "POST /api/sa-prime/tenants 建租户; /tenants/<id>/members 挂成员; /audit?tenant= 审计过滤"),
    ("blueprints/xiaolong_app_bp.py", "小龙 App",
     "移动端主聊天引擎: /api/xiaolong/chat + /chat/stream SSE + 反馈闭环",
     "小龙 App / 小龙iOS / /api/xiaolong/*",
     "点踩自动入质量工单(CQ-*)→learner吸收; /api/chat-feedback 两版共用"),
    ("ios_app/README_BUILD.txt", "小龙 iOS 原生版",
     "iPhone 原生 SwiftUI App: SSE流式+工具事件胶囊+👍👎反馈+主题色+5档模型+服务器可配(Tailscale)",
     "XcodeGen: cd flask-app/ios_app && xcodegen generate && open (详见 README_BUILD.txt)",
     "登录(X-XL-Token)→聊天(SSE实时)→反馈→设置页切服务器/模型; 真机调试7天免费证书"),
    ("engines/user_space_engine.py", "用户数据空间",
     "泛化指令路由: 17字段修改/三级安全闸(low直执/medium备案/high审批)/专属数据文件夹",
     "聊天触发 (modify_setting 工具)",
     "数据在 _runtime/user_spaces/{user_id}/; 载入 GET /api/user-context"),
    ("engines/chat_theme_engine.py", "个性化主题",
     "用户说'换粉色'→主题引擎→按user_id存储→登录自动载入专属CSS",
     "聊天触发 (set_theme 工具)",
     "GET/POST /api/user-theme; 5预设+动态合成任意颜色"),
    ("engines/sys_blockchain_engine.py", "区块链引擎",
     "PoA轻量链: 每tick一块, round-robin提议人, GAP/FIX/RND三源交易, 神经元fire机制",
     "Flask tick 第21轨 blockchain_neurons",
     "查 mt_blockchain 链高/mt_tx_pool 交易池/mt_neuron 神经元权重"),
    ("engines/sys_center_autonomous_learner.py", "自治学习器",
     "9步闭环: DONE吸收/分级反哺(按KP类型)/方向孵化/派单/产出三通道分配",
     "Flask tick 第17轨 center_learner",
     "自动运转; 方向池 mt_center_direction_pool, 产出 mt_center_knowledge_points"),
    ("engines/edu_flywheel_engine.py|daily_practice", "每日练习",
     "错题重练+薄弱新题自动组单, streak连击统计, 复测达标错题毕业",
     "飞轮Step5/6 自动",
     "daily_practice 表: practice_date/accuracy/streak_days"),
]


def _db():
    conn = sqlite3.connect(str(DB), timeout=10)
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


def _ensure_registry(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS mt_doc_registry(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feature_key TEXT UNIQUE, name TEXT, file_path TEXT,
        doc_line TEXT, fingerprint TEXT, last_synced_at TEXT)""")
    conn.commit()


def sync_once() -> dict:
    conn = _db()
    _ensure_registry(conn)
    known = {r[0]: r[4] for r in
             conn.execute("SELECT feature_key, name, file_path, doc_line, fingerprint FROM mt_doc_registry").fetchall()}
    new, updated = 0, 0
    lines = []
    if DOC.exists():
        # 读正文时跳过旧头部 (═ 开头行), 防累积重复
        lines = [l for l in DOC.read_text(encoding="utf-8").splitlines()
                 if not l.startswith("════")]
    header_len = sum(1 for l in lines if not l.startswith("  ") and l.strip())  # 粗略

    for fp, name, desc, boot, usage in FEATURES:
        key = fp  # 完整 fp 作 key (同文件可挂多功能条目)
        absf = ROOT / fp.split("|")[0]
        mtime = int(absf.stat().st_mtime) if absf.exists() else 0
        fp_now = f"{fp}|{mtime}"
        if known.get(key) == fp_now:
            continue  # 未变更
        entry = f"  ■ {name} [{Path(fp.split('|')[0]).name}]\n" \
                f"    功能: {desc}\n    启动: {boot}\n    使用: {usage}\n"
        if key in known:
            # 原位替换旧条目 (功能名行起, 到下一个 ■ 或文件尾)
            out, i, replaced = [], 0, False
            while i < len(lines):
                if not replaced and lines[i].strip() == f"■ {name} [{Path(fp.split('|')[0]).name}]":
                    out.append(entry.rstrip("\n"))
                    replaced = True
                    i += 1
                    while i < len(lines) and not lines[i].strip().startswith("■ "):
                        i += 1
                    continue
                out.append(lines[i]); i += 1
            lines = out if replaced else lines + [entry.rstrip("\n")]
            updated += 1
        else:
            lines.append(entry.rstrip("\n"))
            new += 1
        conn.execute("""INSERT INTO mt_doc_registry(feature_key,name,file_path,doc_line,fingerprint,last_synced_at)
                        VALUES(?,?,?,?,?,datetime('now','localtime'))
                        ON CONFLICT(feature_key) DO UPDATE SET
                        fingerprint=excluded.fingerprint, doc_line=excluded.doc_line,
                        last_synced_at=datetime('now','localtime')""",
                     (key, name, fp, entry.splitlines()[0], fp_now))
        lines = [l for l in lines if l is not None]

    # 重写文件 (带头部; 只去首尾空行, 保留条目缩进)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    body = "\n".join(l for l in lines if l is not None)
    header = (f"════ MTSCOS 功能说明书 (自动生成·doc-sync 同步中心轨道) ════\n"
              f"════ 最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')} · 共 "
              f"{sum(1 for l in body.splitlines() if l.strip().startswith('■ '))} 个功能 ════\n")
    DOC.parent.mkdir(exist_ok=True)
    DOC.write_text(header + body + "\n", encoding="utf-8")
    conn.commit()
    conn.close()
    return {"new": new, "updated": updated}


def sync_version() -> dict:
    """同步中心·版本快照轨道: 版本中心的信息和参数 → docs/VERSION.txt (随 rsync 同步 mini)
    数据源: system_version_history / mt_version_registry / system_upgrade_records /
           mt_release_feature_flags / upgrade_trigger_configs"""
    out = [f"════ MTSCOS 版本快照 (自动生成·doc-sync 同步中心轨道) ════",
           f"════ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} ════", ""]
    changed = False
    conn = _db()
    try:
        # 当前版本
        rows = conn.execute("""SELECT version_number, release_date, substr(description,1,80)
                               FROM system_version_history WHERE is_current=1
                               ORDER BY release_date DESC LIMIT 1""").fetchall()
        for v, rd, desc in rows:
            out.append(f"■ 当前版本: {v}" + (f"  (发布 {rd})" if rd else "") + (f"\n    {desc}" if desc else ""))
            changed = True
        # 版本注册表 (活跃)
        regs = conn.execute("""SELECT version_code, version_name, version_number, description
                               FROM mt_version_registry WHERE is_active=1
                               ORDER BY milestone_date DESC LIMIT 3""").fetchall()
        if regs:
            out.append("■ 版本注册 (活跃):")
            for code, name, num, desc in regs:
                out.append(f"    {code} [{num}] {name} — {(desc or '')[:60]}")
            changed = True
        # 最近升级记录
        ups = conn.execute("""SELECT version_from, version_to, status, datetime(completed_at,'unixepoch','localtime')
                              FROM system_upgrade_records ORDER BY completed_at DESC LIMIT 3""").fetchall()
        if ups:
            out.append("■ 最近升级:")
            for vf, vt, st, at in ups:
                out.append(f"    {vf} → {vt}  {st}  {at or ''}")
            changed = True
        # 版本参数: 功能开关
        try:
            flags = conn.execute("""SELECT flag_name, enabled, rollout_pct, scope FROM mt_release_feature_flags
                                    ORDER BY updated_at DESC LIMIT 10""").fetchall()
            if flags:
                out.append("■ 版本参数 (功能开关):")
                for name, enabled, pct, scope in flags:
                    out.append(f"    {name} = {'ON' if enabled else 'OFF'} (灰度{pct}%, {scope})")
                changed = True
        except Exception:
            pass
        # 版本参数: 升级触发配置 (按 scope 汇总)
        try:
            cfgs = conn.execute("""SELECT scope, config_key, config_value FROM upgrade_trigger_configs
                                   ORDER BY scope, config_key LIMIT 15""").fetchall()
            if cfgs:
                out.append("■ 版本参数 (升级触发配置):")
                cur_scope = None
                for scope, k, v in cfgs:
                    if scope != cur_scope:
                        out.append(f"    [{scope}]")
                        cur_scope = scope
                    out.append(f"      {k} = {str(v)[:60]}")
                changed = True
        except Exception:
            pass
    finally:
        conn.close()
    if changed or not VER.exists():
        VER.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"sections": sum(1 for l in out if l.startswith("■"))}


if __name__ == "__main__":
    try:
        r1 = sync_once()
        r2 = sync_version()
        print(f"[DOC-SYNC] {datetime.now().strftime('%H:%M:%S')} features={r1} version={r2}")
        print(f"  → {DOC}\n  → {VER}")
    except Exception as __e:
        print(f"[DOC-SYNC] degraded (schema mismatch, skipped): {__e}", flush=True)
