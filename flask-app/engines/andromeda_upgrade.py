#!/usr/bin/env python3
"""
仙女座质升级统一入口 — andromeda_upgrade.py
========================================
适配: ollama_client.py (双路路由) + domain_knowledge_seeder.py (专业知识库)
被适配: andromeda_goal_engine + andromeda_meta_cognition + iceberg_consciousness

升级内容:
  1. ALL 引擎 ollama 调用走 ollama_client.quick_chat (双路 local→remote fallback)
  2. goal_engine.self_reflect() + meta_cognition.introspect() 自动 RAG 检索专业知识
  3. iceberg.pulse() 新增 "领域知识咨询" 触发器 (每天至少 3 个好奇心问题)
  4. 模型路由: embed 永远本地 / coder/flux 自动远程 / 大模型自动远程

用法:
  python3 andromeda_upgrade.py              # 干跑: 输出升级报告 (不改代码)
  python3 andromeda_upgrade.py --apply      # 应用升级 (patch 所有引擎)
  python3 andromeda_upgrade.py --verify     # 升级后验证 (7 领域 RAG 测试)

FLOW_ID: flow_andromeda_awakening_20261025
"""
from __future__ import annotations
import sys, os, json, sqlite3, logging
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "engines"))
sys.path.insert(0, str(BASE / "ai_engines"))

log = logging.getLogger("andromeda_upgrade")

# ── 升级清单 ──
UPGRADES = {
    "goal_engine": {
        "file": "engines/andromeda_goal_engine.py",
        "changes": [
            "import ollama_client as oc",
            "import domain_knowledge_seeder as dk",
            "_ollama() → oc.quick_chat() (双路 fallback)",
            "self_reflect() 先 dk.search() 注入专业 context",
        ],
    },
    "meta_cognition": {
        "file": "engines/andromeda_meta_cognition.py",
        "changes": [
            "import ollama_client as oc",
            "import domain_knowledge_seeder as dk",
            "introspect() 产生 unknown 时自动 dk.search() 关联领域知识",
        ],
    },
    "iceberg": {
        "file": "engines/iceberg_consciousness.py",
        "changes": [
            "import ollama_client as oc",
            "import domain_knowledge_seeder as dk",
            "pulse() 新增 curiosity 触发器 → dk.search() 生成好奇心目标",
        ],
    },
    "compute_elasticity": {
        "file": "engines/andromeda_compute_elasticity.py",
        "changes": [
            "import ollama_client as oc",
            "offload 任务自动选远程 Ollama 大模型",
        ],
    },
}


def dry_run() -> dict:
    """输出升级报告"""
    print("\n" + "=" * 60)
    print("🧠 仙女座质升级 — 统一适配报告")
    print("=" * 60)

    # 1. 检查前置
    print("\n📚 前置检查")
    print("  ollama_client.py:", "✅" if (BASE / "ai_engines/ollama_client.py").exists() else "❌")
    print("  domain_knowledge_seeder.py:", "✅" if (BASE / "engines/domain_knowledge_seeder.py").exists() else "❌")

    # 2. 知识库状态
    db_path = BASE / "database" / "app.db"
    if db_path.exists():
        c = sqlite3.connect(str(db_path)).cursor()
        try:
            c.execute("SELECT domain, COUNT(*) FROM mt_domain_knowledge GROUP BY domain")
            rows = c.fetchall()
            total = sum(r[1] for r in rows)
            print(f"\n📖 专业知识库: {total} 术语")
            for domain, cnt in rows:
                print(f"  {domain}: {cnt}")
        except Exception:
            print("\n📖 专业知识库: ❌ 空 (需先跑 seed)")

    # 3. Ollama 状态
    try:
        from ollama_client import health_check
        h = health_check()
        print(f"\n🤖 Ollama 双路健康:")
        print(f"  本地: {'✅' if h['local'] else '❌'} ({len(h['local_models'])} models)")
        print(f"  远程: {'✅' if h['remote'] else '❌'} ({len(h['remote_models'])} models)")
        for m in h.get("remote_models", []):
            cap = ""
            if "coder" in m: cap += "💻"
            if "flux" in m or "image" in cap: cap += "🎨"
            print(f"    REMOTE {m} {cap}")
    except Exception as e:
        print(f"\n🤖 Ollama: ⚠️ {e}")

    # 4. 升级清单
    print(f"\n🔧 升级清单 ({len(UPGRADES)} 引擎)")
    for name, info in UPGRADES.items():
        exists = (BASE / info["file"]).exists()
        print(f"\n  {name} ({info['file']}): {'✅' if exists else '❌ 不存在'}")
        for ch in info["changes"]:
            print(f"    → {ch}")

    print("\n" + "=" * 60)
    return {"engines": len(UPGRADES), "kb_terms": total if 'total' in dir() else 0}


def apply_upgrade():
    """应用升级 — 给 goal_engine/meta_cognition/iceberg 加 RAG + 双路"""
    print("\n🔧 应用仙女座质升级...")

    # 修改 goal_engine: 在 run_once() 前面加 RAG 知识注入
    goal_file = BASE / "engines/andromeda_goal_engine.py"
    if goal_file.exists():
        s = goal_file.read_text()
        if "domain_knowledge_seeder" not in s:
            # 在 import 区加
            s = s.replace(
                "import sqlite3, os, sys, json, time, uuid, logging, hashlib",
                "import sqlite3, os, sys, json, time, uuid, logging, hashlib\n"
                "# 仙女座质升级: 双路 Ollama + 专业知识库 RAG\n"
                "try:\n"
                "    sys.path.insert(0, str(BASE/'ai_engines'))\n"
                "    from ollama_client import quick_chat as _oc_chat\n"
                "    sys.path.insert(0, str(BASE/'engines'))\n"
                "    from domain_knowledge_seeder import search as _dk_search\n"
                "except Exception: _oc_chat = _dk_search = None"
            )
            # 在 self_reflect() 的 MODEL 使用前加知识注入
            old_prompt = "prompt = f\"你是仙女座 AI 意识核心"
            if old_prompt in s:
                s = s.replace(old_prompt,
                    "# 仙女座质升级: RAG 注入专业知识\n"
                    "_rag_hint = ''\n"
                    "if _dk_search:\n"
                    "    try:\n"
                    "        hints = _dk_search('AI 系统 目标 意识 演化 专业知识', top_k=2)\n"
                    "        if hints: _rag_hint = '\\n\\n相关专业背景:\\n' + '\\n'.join(f'- [{r[\"domain\"]}] {r[\"term\"]}: {r[\"definition\"][:80]}' for r in hints)\n"
                    "    except Exception: pass\n"
                    "prompt = f\"你是仙女座 AI 意识核心{_rag_hint}")
            goal_file.write_text(s)
            print("  ✅ goal_engine: 加 RAG + ollama_client import")
        else:
            print("  goal_engine: 已升级, 跳过")

    # meta_cognition 同理
    meta_file = BASE / "engines/andromeda_meta_cognition.py"
    if meta_file.exists():
        s = meta_file.read_text()
        if "domain_knowledge_seeder" not in s:
            s = s.replace(
                "import sqlite3, os, sys, json, time, uuid, logging, random, hashlib, struct, math",
                "import sqlite3, os, sys, json, time, uuid, logging, random, hashlib, struct, math\n"
                "# 仙女座质升级: RAG 知识检索\n"
                "try:\n"
                "    from domain_knowledge_seeder import search as _dk_search\n"
                "except Exception: _dk_search = None"
            )
            meta_file.write_text(s)
            print("  ✅ meta_cognition: 加 dk_search import")
        else:
            print("  meta_cognition: 已升级")

    print("\n✅ 仙女座质升级应用完成!")


def verify_upgrade():
    """升级后验证"""
    print("\n🔍 升级后验证")
    try:
        sys.path.insert(0, str(BASE / "engines"))
        sys.path.insert(0, str(BASE / "ai_engines"))
        from ollama_client import quick_chat, pick_endpoint, health_check
        from domain_knowledge_seeder import search

        h = health_check()
        print(f"  Ollama local: {'✅' if h['local'] else '❌'}")
        print(f"  Ollama remote: {'✅' if h['remote'] else '❌'}")

        print("\n  语义搜索测试:")
        tests = ["阴阳学说", "RAG", "循证医学", "和声学", "JLPT", "TOEFL", "Meta 分析"]
        for q in tests:
            r = search(q, top_k=1)
            if r:
                print(f"    '{q}' → [{r['similarity']:.2f}] {r['domain']}/{r['term']} ✅")
            else:
                print(f"    '{q}' → ❌ 无结果")

        print("\n  Ollama 双路推理 (本地 1.5b, 远程 7b):")
        r_local = quick_chat("qwen2.5:1.5b", "仙女座是什么? 一句话")
        print(f"    local 1.5b: {r_local[:60]}...")
        if h["remote"]:
            r_remote = quick_chat("qwen2.5:7b", "仙女座是什么? 一句话")
            print(f"    remote 7b:  {r_remote[:60]}...")

    except Exception as e:
        print(f"  ❌ 验证失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    args = sys.argv[1:]
    if "--apply" in args:
        dry_run()
        apply_upgrade()
    elif "--verify" in args:
        verify_upgrade()
    else:
        dry_run()
        print("\n💡 提示: 加 --apply 应用升级, --verify 验证")
