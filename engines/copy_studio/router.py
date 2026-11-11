#!/usr/bin/env python3
"""
📝 copy_studio — router (v26.0 Step4)
=====================================
多模型智能路由: 根据 purpose + genre/sub_genre 选 Ollama 模型.

当前可用模型 (11435):
  qwen2.5:14b-q5      — 大纲/规划 (架构能力强)
  qwen2.5-coder:14b   — 正文写作 (指令跟随强, 结构化好)
  qwen2.5:7b          — 润色/巡检 (任务简单, 速度快)
  qwen2.5-coder:7b    — 备选写作模型 (14b 不可用时)

降级链: 最优匹配 → 次优 → 第一个可用模型 → generator 默认模型
"""
from __future__ import annotations
import json, os, re, urllib.request, urllib.error, subprocess as _sp
from typing import Optional, Dict, List

# ═══════════════════════════════════════════════════════════
# 模型发现 (与 generator 对齐, 但专注 Ollama tags)
# ═══════════════════════════════════════════════════════════
_STATIC_OLLAMA = os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434')
_OLLAMA_PORTS = [11435, 11434, 11436]

_backend_base: Optional[str] = None
_models_cache: List[str] = []


def _scan_ollama_port() -> Optional[str]:
    """ps grep + 端口扫描 → 找到 Ollama serve 端点."""
    try:
        out = _sp.run(['ps', 'aux'], capture_output=True, text=True, timeout=3).stdout
        for line in out.splitlines():
            if 'ollama serve' in line:
                m = re.search(r'--port\s+(\d+)', line) or re.search(r'--port=(\d+)', line)
                if m:
                    return f"http://127.0.0.1:{m.group(1)}"
    except Exception:
        pass
    for port in [_STATIC_OLLAMA] + [f"http://127.0.0.1:{p}" for p in _OLLAMA_PORTS]:
        try:
            resp = urllib.request.urlopen(f"{port}/api/tags", timeout=2)
            d = json.loads(resp.read())
            if d.get('models'):
                return port
        except Exception:
            continue
    return None


def _discover_models(force: bool = False) -> List[str]:
    """返回当前 Ollama 上所有可用模型名. 缓存 30s."""
    global _backend_base, _models_cache
    if not force and _models_cache:
        return _models_cache
    _backend_base = _scan_ollama_port()
    if not _backend_base:
        _models_cache = []
        return _models_cache
    try:
        resp = urllib.request.urlopen(f"{_backend_base}/api/tags", timeout=5)
        d = json.loads(resp.read())
        _models_cache = [m['name'] for m in d.get('models', [])
                         if 'embed' not in m['name'].lower()]  # 排除 embedding
    except Exception:
        _models_cache = []
    return _models_cache


# ═══════════════════════════════════════════════════════════
# 路由规则
# ═══════════════════════════════════════════════════════════

# purpose → 优先匹配模式 (按优先级从高到低)
_ROUTE_RULES: Dict[str, List[Dict[str, str]]] = {
    'outline': [
        {'size': '14b', 'coder': 'no'},    # 大纲用 14b 普通 (架构能力最强)
        {'size': '14b', 'coder': 'any'},
        {'size': '7b', 'coder': 'no'},
        {'size': 'any', 'coder': 'no'},
        {'size': 'any', 'coder': 'any'},
    ],
    'write': [
        {'size': '14b', 'coder': 'yes'},   # 正文用 coder 14b (指令跟随强)
        {'size': '14b', 'coder': 'no'},
        {'size': '7b', 'coder': 'yes'},
        {'size': 'any', 'coder': 'any'},
    ],
    'polish': [
        {'size': '7b', 'coder': 'any'},    # 润色用 7b (任务简单, 快)
        {'size': '14b', 'coder': 'any'},
        {'size': 'any', 'coder': 'any'},
    ],
    'check': [
        {'size': '7b', 'coder': 'any'},    # 一致性巡检 → 7b
        {'size': 'any', 'coder': 'any'},
    ],
    'default': [
        {'size': 'any', 'coder': 'any'},
    ],
}


def _model_matches(model_name: str, rule: Dict[str, str]) -> bool:
    """检查模型名是否匹配一条路由规则."""
    lower = model_name.lower()
    # size 匹配
    size = rule.get('size', 'any')
    if size != 'any':
        if size not in lower:
            return False
    # coder 匹配
    coder = rule.get('coder', 'any')
    if coder == 'yes' and 'coder' not in lower:
        return False
    if coder == 'no' and 'coder' in lower:
        return False
    return True


def route_model(purpose: str, genre: str = '', sub_genre: str = '') -> Optional[str]:
    """根据 purpose 选最优模型. 失败返回 None (让调用方用默认).

    purpose: outline / write / polish / check
    genre / sub_genre: 预留 (当前路由规则未用, 将来可按体裁细调)
    """
    models = _discover_models()
    if not models:
        return None
    rules = _ROUTE_RULES.get(purpose, _ROUTE_RULES['default'])
    for rule in rules:
        for m in models:
            if _model_matches(m, rule):
                return m
    return models[0] if models else None


def route_available() -> bool:
    """Ollama 有可用生成模型?"""
    return len(_discover_models()) > 0


# CLI 自检
if __name__ == '__main__':
    print("models:", _discover_models(force=True))
    for p in ['outline', 'write', 'polish', 'check', 'default', 'unknown']:
        print(f"  {p:10s} → {route_model(p)}")
    print(f"  available: {route_available()}")
