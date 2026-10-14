"""
workflow_registry.py — 去中心化工作流注册协议
==================================================

设计: 每个子系统包内放 workflows.py, 暴露 register_workflows(registry) 函数.
      andromeda_workflow_engine 启动时 import 所有子包 workflows.py 并调用注册.

registry dict 格式:
{
  "<workflow_id>": {
    "name":        str,        # 显示名
    "domain":      str,        # 所属域 (copy_studio / translation_studio / approval / iceberg / ...)
    "description": str,        # 用途说明
    "price_per_unit": float,   # 定价 (USD)
    "pricing_unit": str,       # 单位 (e.g. "1K chars", "item", "batch")
    "handler":     callable,   # 同步 handler(input:dict) -> dict (必须返回 status/output)
    "requires":    list[str],  # 可选: 前置依赖 (e.g. ["OLLAMA", "DB_PROD"])
    "tags":        list[str],  # 可选: 搜索标签
  }
}

handler 契约:
  def handler(input: dict) -> dict:
      # 返回 dict with keys: status, output, wall_ms, error(optional)
      # status: "SUCCESS" | "FAILED"
      # output: handler-specific result dict
      ...

自注册机制:
  _AUTO_DISCOVERY_SCAN_DIRS = ["engines/copy_studio", "engines/translation_studio", ...]
  启动时 scan 每个目录下的 workflows.py → importlib → register_workflows(registry)
"""
import os, sys, time, importlib.util, traceback
# [unused] from pathlib import Path

# 全局 registry — andromeda_workflow_engine 会 import 这个
WORKFLOW_REGISTRY: dict[str, dict] = {}

# 需要扫描的子系统目录 (相对 flask-app/)
_AUTO_DISCOVERY_DIRS = [
    "engines/_common",           # 引擎级基础 (6)
    "engines/copy_studio",       # 文案工作室 (2)
    "engines/translation_studio", # 翻译工作室 (1)
    "engines/approval",          # 审批域 (1)
    "engines/iceberg",           # 冰山系统 (12)
]


def register(workflow_id: str, spec: dict):
    """子系统 workflows.py 调这个注册一个工作流."""
    assert "handler" in spec and callable(spec["handler"]), f"{workflow_id}: handler 必须 callable"
    assert "name" in spec, f"{workflow_id}: 必须有 name"
    assert "domain" in spec, f"{workflow_id}: 必须有 domain"
    WORKFLOW_REGISTRY[workflow_id] = spec


def list_workflows() -> list[dict]:
    """返回所有已注册 workflow 元数据 (不含 handler 代码)."""
    out = []
    for wid, spec in WORKFLOW_REGISTRY.items():
        meta = {k: v for k, v in spec.items() if k != "handler"}
        meta["workflow_id"] = wid
        out.append(meta)
    return out


def get_handler(workflow_id: str):
    """获取 handler callable."""
    spec = WORKFLOW_REGISTRY.get(workflow_id)
    if not spec:
        return None
    return spec["handler"]


def run_handler(workflow_id: str, input: dict) -> dict:
    """执行 handler, 返回标准结果 {status, output, wall_ms, error?}."""
    handler = get_handler(workflow_id)
    if not handler:
        return {"status": "FAILED", "output": {}, "error": f"workflow {workflow_id} not found", "wall_ms": 0}
    t0 = time.time()
    try:
        result = handler(input or {})
        result.setdefault("wall_ms", int((time.time() - t0) * 1000))
        result.setdefault("status", "SUCCESS")
        return result
    except Exception as e:
        return {
            "status": "FAILED",
            "output": {},
            "error": f"{type(e).__name__}: {e}",
            "wall_ms": int((time.time() - t0) * 1000),
        }


def discover_and_register(project_root: str) -> dict[str, str]:
    """扫描所有 _AUTO_DISCOVERY_DIRS, import workflows.py 并调 register_workflows(registry).
    返回 {workflow_id: source_file} 映射 — 用于 dashboard 显示来源.
    """
    source_map: dict[str, str] = {}
    for rel_dir in _AUTO_DISCOVERY_DIRS:
        wf_file = os.path.join(project_root, rel_dir, "workflows.py")
        if not os.path.exists(wf_file):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"wf_{rel_dir.replace('/', '_')}", wf_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "register_workflows"):
                before = len(WORKFLOW_REGISTRY)
                mod.register_workflows(WORKFLOW_REGISTRY, register)
                delta = len(WORKFLOW_REGISTRY) - before
                # 记录新增的 workflow 来源
                for wid in list(WORKFLOW_REGISTRY.keys())[before:]:
                    source_map[wid] = wf_file
                print(f"[registry] ✅ {rel_dir}/workflows.py → +{delta} workflows")
        except Exception as e:
            print(f"[registry] ⚠️ {rel_dir}/workflows.py 加载失败: {e}")
            traceback.print_exc()
    return source_map


if __name__ == "__main__":
    # 自测试
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    print(f"discovering from: {root}")
    sm = discover_and_register(root)
    print(f"\n已注册 {len(WORKFLOW_REGISTRY)} 个 workflows:")
    for wid, spec in WORKFLOW_REGISTRY.items():
        print(f"  {wid:30s} [{spec['domain']:20s}] {spec['name']}  @ {sm.get(wid,'central')}")
