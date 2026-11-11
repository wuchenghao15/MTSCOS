#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAS 路径路由器 — 统一把大数据量指向 NAS, 自动降级本地

核心职责:
  1. NAS 就绪即用 (自动探测挂载点)
  2. 5 类数据全路由: 脑库投喂、沙盘历史缓存、临时文件、Ollama 模型、大体量备份
  3. NAS 不可用时自动降级本地, 绝不阻塞
  4. 大体量文件自动切片备份到 NAS

设计原则:
  - 显式比隐式好: 返回路径带 source='nas'/'local'/'fallback' 标记
  - 健康检查先做: 每次取路径前 try 写入探针文件
  - 失败即退: 任一环节失败立即降级本地, 不阻塞主流程
"""

from __future__ import annotations

import os
import sys
import json
import time
import shutil
import sqlite3
import tempfile
import hashlib
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List, Any, Tuple

# ═══════════════════════════════════════════════════════════════════
# §1 NAS 挂载探测 (按 macOS + Linux 常见路径优先级排序)
# ═══════════════════════════════════════════════════════════════════

# NAS 挂载候选路径 (按优先级降序)
# 优先级 0: fnOS hulk-nas (主力 NAS, 挂了后自动降级下面)
_NAS_CANDIDATES: List[Path] = [
    # ── 🏛️ fnOS hulk-nas (主力) ──
    Path("/Volumes/hulk-nas"),              # macOS SMB 挂载 (首选)
    Path("/Volumes/fnos-hulk"),             # fnOS 别名
    Path("/Volumes/MTSCOS_NAS"),           # 可能的重命名
    # ── macOS SMB 通用 ──
    Path("/Volumes/NAS"),
    Path("/Volumes/Synology"),
    Path("/Volumes/smbdata"),
    Path("/Volumes/AI_Data"),
    Path("/Volumes/hulk"),                  # HP ProLiant DL360 可能的别名
    # ── Linux /mnt ──
    Path("/mnt/nas"),
    Path("/mnt/NAS"),
    Path("/mnt/fnos"),
    Path("/mnt/hulk-nas"),
    Path("/mnt/synology"),
    Path("/mnt/smb"),
    Path("/mnt/nfs"),
    # ── 用户目录 ──
    Path.home() / "NAS",
    Path.home() / "nas",
    Path.home() / "SynologyDrive",
    Path.home() / "nas_data",
    Path.home() / "hulk-nas",
]

# fnOS hulk-nas 上的共享名 (SMB Share)
# fnOS 默认每个应用/共享单独挂载, 这里列所有可能的 Share 名
_FNOS_SHARE_NAMES = [
    "MTSCOS",        # 主共享
    "mtscos",
    "hulk_data",
    "AI_Data",
    "ai_data",
    "homes",         # fnOS 公共
    "Public",
]

# SMB 挂载命令模板 (手动挂载用)
# mount_smbfs //guest@hulk-nas.local/MTSCOS /Volumes/hulk-nas
_SMB_MOUNT_TEMPLATE = (
    'mount_smbfs //{user}@{host}/{share} {mount_point}'
)

# NAS 子目录结构 (MTSCOS 专属)
_NAS_SUBDIRS = {
    "brain_feed":     "MTSCOS/brain_feed",       # 脑库投喂数据
    "sandbox_cache":  "MTSCOS/sandbox_history",   # 沙盘历史 K 线缓存
    "tmp":            "MTSCOS/tmp",               # 临时文件 (视频/WAV/锁文件)
    "ollama_models":  "MTSCOS/ollama_models",     # Ollama 模型
    "backup":         "MTSCOS/backup",            # 大体量文件备份 (自动切片)
    "memory":         "MTSCOS/brain_memory",      # 脑库/复盘记忆
    "market_cache":   "MTSCOS/market_radar",      # 市场雷达缓存
    "logs":           "MTSCOS/logs",              # 守护进程日志
}

# 本地降级路径 (NAS 不可用时)
_LOCAL_FALLBACK = {
    "brain_feed":     Path.home() / "MTSCOS_LOCAL" / "brain_feed",
    "sandbox_cache":  Path.home() / "MTSCOS_LOCAL" / "sandbox_history",
    "tmp":            Path(tempfile.gettempdir()) / "mtscos_tmp",
    "ollama_models":  Path.home() / ".ollama",  # Ollama 模型保持原位
    "backup":         Path.home() / "MTSCOS_LOCAL" / "backup",
    "memory":         Path.home() / "MTSCOS_LOCAL" / "brain_memory",
    "market_cache":   Path.home() / "MTSCOS_LOCAL" / "market_radar",
    "logs":           Path.home() / "MTSCOS_LOCAL" / "logs",
}


class NASPathRouter:
    """
    单例 NAS 路由器
    
    用法:
        from engines.nas_path_router import nas_router
        
        # 沙盘历史缓存
        p = nas_router.get("sandbox_cache", secid="sh600519")
        db_path = p.path / "sandbox_history.db"
        print(f"数据源: {p.source}")  # 'nas' | 'local'
        
        # 临时文件
        tmp = nas_router.get_tmp_path(prefix="galaxy_video_", suffix=".wav")
        
        # 脑库投喂
        nas_router.feed_brain(content="新经验", category="error_chain")
        
        # 大体量文件自动切片备份
        nas_router.backup_large_file(src_path)
    """
    _instance: Optional["NASPathRouter"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._nas_root: Optional[Path] = None
        self._nas_available: bool = False
        self._last_check: float = 0.0
        self._check_interval: float = 60.0  # 60s 重检一次
        
        # 首次探测
        self._check_nas(force=True)
    
    # ── NAS 健康检查 ──
    
    def _check_nas(self, force: bool = False) -> None:
        """
        探测 NAS 挂载状态
        检查项: 挂载点存在 + 可写性探针 + 基础 I/O
        """
        now = time.time()
        if not force and (now - self._last_check) < self._check_interval:
            return
        self._last_check = now
        
        for candidate in _NAS_CANDIDATES:
            if not candidate.exists():
                continue
            
            # 探针: 写入临时文件验证可写
            try:
                probe = candidate / ".mtos_nas_probe"
                probe.write_text(str(now))
                probe.unlink()
                
                # I/O 可达性: stat 子目录
                (candidate / "MTSCOS").mkdir(exist_ok=True)
                (candidate / "MTSCOS" / ".write_test").write_text("ok")
                (candidate / "MTSCOS" / ".write_test").unlink()
                
                self._nas_root = candidate
                self._nas_available = True
                
                # 确保所有子目录存在
                for sub in _NAS_SUBDIRS.values():
                    (candidate / sub).mkdir(parents=True, exist_ok=True)
                
                sys.stderr.write(
                    f"[NAS] ✅ 挂载成功: {candidate}\n"
                    f"[NAS]    子目录已就绪: {list(_NAS_SUBDIRS.keys())}\n"
                )
                return
                
            except PermissionError:
                sys.stderr.write(f"[NAS] ⚠️ {candidate} 存在但不可写\n")
                continue
            except OSError as e:
                sys.stderr.write(f"[NAS] ⚠️ {candidate} I/O 错误: {e}\n")
                continue
        
        # 全部失败 → 降级本地
        self._nas_root = None
        self._nas_available = False
        
        # 确保本地降级目录存在
        for p in _LOCAL_FALLBACK.values():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        
        sys.stderr.write(f"[NAS] ⚠️ 未发现 NAS 挂载, 全部降级本地\n")
    
    def force_recheck(self) -> Dict[str, Any]:
        """强制重检 NAS 状态"""
        self._check_nas(force=True)
        return self.status()
    
    def status(self) -> Dict[str, Any]:
        """返回当前 NAS 状态"""
        self._check_nas()
        return {
            "nas_available": self._nas_available,
            "nas_root": str(self._nas_root) if self._nas_root else None,
            "candidates": [str(p) for p in _NAS_CANDIDATES],
            "local_fallback": {k: str(v) for k, v in _LOCAL_FALLBACK.items()},
        }
    
    # ── 路径获取核心 ──
    
    def get(self, category: str, **kwargs) -> "NASPathResult":
        """
        获取某类数据的路径
        
        Args:
            category: brain_feed | sandbox_cache | tmp | ollama_models | 
                     backup | memory | market_cache | logs
        
        Returns:
            NASPathResult(path=Path, source='nas'|'local', category=str)
        """
        self._check_nas()
        
        if self._nas_available and self._nas_root:
            subdir = _NAS_SUBDIRS.get(category, f"MTSCOS/{category}")
            full_path = self._nas_root / subdir
            source = "nas"
        else:
            full_path = _LOCAL_FALLBACK.get(category, Path.home() / "MTSCOS_LOCAL" / category)
            source = "local"
        
        # 确保路径存在
        try:
            full_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            sys.stderr.write(f"[NAS] 路径创建失败 {full_path}: {e}\n")
            # 最终兜底
            full_path = Path(tempfile.gettempdir()) / f"mtos_{category}"
            full_path.mkdir(parents=True, exist_ok=True)
            source = "fallback"
        
        return NASPathResult(path=full_path, source=source, category=category)
    
    def get_tmp_path(self, prefix: str = "mtscos_", suffix: str = "",
                     auto_create: bool = True) -> Path:
        """
        获取 NAS 上的临时文件路径
        
        NAS 可用时: 直接在 NAS tmp 目录下创建临时文件
        NAS 不可用: 走系统 tempfile
        """
        tmp_dir = self.get("tmp").path
        
        if auto_create:
            if suffix:
                fd, path = tempfile.mkstemp(
                    prefix=prefix, suffix=suffix, dir=str(tmp_dir)
                )
                os.close(fd)
                return Path(path)
            else:
                path = Path(tempfile.mktemp(prefix=prefix, dir=str(tmp_dir)))
                return path
        
        return tmp_dir / f"{prefix}{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"
    
    # ── 脑库投喂 (NAS 优先) ──
    
    def feed_brain(self, content: str, category: str = "auto",
                   source: str = "system", extra: Dict = None) -> Dict[str, Any]:
        """
        投喂一条经验到脑库
        
        NAS 路径: MTSCOS/brain_feed/YYYY-MM-DD.jsonl
        本地降级: ~/MTSCOS_LOCAL/brain_feed/YYYY-MM-DD.jsonl
        
        Returns:
            {"ok": bool, "path": str, "source": str, "bytes": int}
        """
        result = self.get("brain_feed")
        date_str = datetime.now().strftime("%Y-%m-%d")
        feed_file = result.path / f"{date_str}.jsonl"
        
        entry = {
            "ts": datetime.now().isoformat(),
            "content": content[:2000],
            "category": category,
            "source": source,
            "extra": extra or {},
        }
        
        try:
            with open(feed_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            
            # 同时写入 SQLite 脑库表 (如果存在 DB)
            try:
                from pathlib import Path as _P
                db_candidates = [
                    _P.home() / "MTSCOS_PROD" / "flask-app" / "database" / "app.db",
                    _P(__file__).resolve().parent.parent / "database" / "app.db",
                ]
                for db in db_candidates:
                    if db.exists():
                        conn = sqlite3.connect(str(db))
                        conn.execute(
                            "INSERT OR IGNORE INTO mt_ai_brain_feed_log "
                            "(content, category, source_type, feed_type, created_at) "
                            "VALUES (?,?,?,'experience',datetime('now','localtime'))",
                            (content[:500], category, source)
                        )
                        conn.commit()
                        conn.close()
                        break
            except Exception:
                pass  # SQLite 不可用不阻断文件写入
            
            return {
                "ok": True,
                "path": str(feed_file),
                "source": result.source,
                "bytes": len(content),
            }
        except Exception as e:
            sys.stderr.write(f"[NAS] 脑库投喂失败 {feed_file}: {e}\n")
            return {"ok": False, "error": str(e)}
    
    # ── 大体量文件自动切片备份 ──
    
    def backup_large_file(self, src: Path, max_size_mb: int = 50,
                          compress: bool = True) -> Dict[str, Any]:
        """
        大体量文件自动切片备份到 NAS
        
        规则:
          - 文件 > 10MB → 触发备份
          - 单块 ≤ max_size_mb MB (默认 50MB)
          - 自动压缩 gzip
          - 备份路径: NAS/MTSCOS/backup/YYYY-MM-DD/{filename}.part001.gz
          - 本地保留最近 3 天, NAS 永久
        
        Args:
            src: 源文件路径
            max_size_mb: 单块最大 MB
        
        Returns:
            {"ok": bool, "parts": int, "dest": str, "source": str, "size": int}
        """
        src = Path(src)
        if not src.exists():
            return {"ok": False, "error": f"源文件不存在: {src}"}
        
        file_size = src.stat().st_size
        if file_size < 10 * 1024 * 1024:  # < 10MB 不触发切片
            return {"ok": True, "skipped": True, "reason": "文件 < 10MB"}
        
        backup_result = self.get("backup")
        dest_dir = backup_result.path / datetime.now().strftime("%Y-%m-%d")
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        max_bytes = max_size_mb * 1024 * 1024
        part_count = (file_size + max_bytes - 1) // max_bytes
        
        try:
            # 切片
            with open(src, 'rb') as f:
                for i in range(part_count):
                    chunk = f.read(max_bytes)
                    if compress:
                        import gzip
                        dest = dest_dir / f"{src.name}.part{i+1:03d}.gz"
                        with gzip.open(dest, 'wb') as gf:
                            gf.write(chunk)
                    else:
                        dest = dest_dir / f"{src.name}.part{i+1:03d}"
                        dest.write_bytes(chunk)
            
            # 写 manifest
            manifest = {
                "source": str(src),
                "original_size": file_size,
                "parts": part_count,
                "compressed": compress,
                "created_at": datetime.now().isoformat(),
                "nas_source": backup_result.source,
                "reassemble_cmd": f"cat {dest_dir / src.name}.part*.gz | gunzip > {src.name}",
            }
            (dest_dir / f"{src.name}.manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            
            sys.stderr.write(
                f"[NAS] 📦 备份完成: {src.name} ({file_size/1024/1024:.1f}MB) "
                f"→ {part_count} 块 × {max_size_mb}MB → {backup_result.source}\n"
            )
            
            return {
                "ok": True,
                "parts": part_count,
                "dest": str(dest_dir),
                "source": backup_result.source,
                "size": file_size,
                "compressed": compress,
            }
        except Exception as e:
            sys.stderr.write(f"[NAS] 📦 备份失败 {src}: {e}\n")
            return {"ok": False, "error": str(e)}
    
    # ── Ollama 模型路径 (支持 NAS 迁移) ──
    
    def get_ollama_model_path(self) -> Path:
        """
        获取 Ollama 模型存储路径
        
        NAS 可用时: MTSCOS/ollama_models (需配合 OLLAMA_MODELS 环境变量)
        不可用: ~/.ollama (保持默认)
        """
        self._check_nas()
        if self._nas_available and self._nas_root:
            ollama_path = self._nas_root / _NAS_SUBDIRS["ollama_models"]
            ollama_path.mkdir(parents=True, exist_ok=True)
            return ollama_path
        return Path.home() / ".ollama"
    
    def get_ollama_env(self) -> Dict[str, str]:
        """
        返回 Ollama 应使用的环境变量
        
        用法: os.environ.update(nas_router.get_ollama_env())
        """
        model_path = self.get_ollama_model_path()
        return {"OLLAMA_MODELS": str(model_path)}
    
    # ── 市场雷达缓存 ──
    
    def get_market_cache_path(self) -> Path:
        return self.get("market_cache").path
    
    # ── 沙盘历史缓存 ──
    
    def get_sandbox_cache_path(self) -> Path:
        return self.get("sandbox_cache").path
    
    # ── 日志目录 ──
    
    def get_log_path(self) -> Path:
        return self.get("logs").path
    
    # ── 定时清理 (NAS 上不删, 本地只留 3 天) ──
    
    def cleanup_local_temp(self, keep_days: int = 3) -> Dict[str, Any]:
        """清理本地降级目录中过期的临时文件"""
        result = {"cleaned": 0, "freed_bytes": 0}
        
        if self._nas_available:
            # NAS 可用时, 清理本地 tmp
            local_tmp = _LOCAL_FALLBACK["tmp"]
            if local_tmp.exists():
                cutoff = time.time() - keep_days * 86400
                for f in local_tmp.iterdir():
                    if f.stat().st_mtime < cutoff:
                        try:
                            size = f.stat().st_size
                            f.unlink()
                            result["cleaned"] += 1
                            result["freed_bytes"] += size
                        except Exception:
                            pass
        
        return result


class NASPathResult:
    """路径结果 (带 source 标记)"""
    __slots__ = ("path", "source", "category")
    
    def __init__(self, path: Path, source: str, category: str):
        self.path = path
        self.source = source  # 'nas' | 'local' | 'fallback'
        self.category = category
    
    def __repr__(self):
        return f"NASPathResult(path={self.path}, source={self.source}, category={self.category})"
    
    @property
    def is_nas(self) -> bool:
        return self.source == "nas"


# ── 单例实例 ──
nas_router = NASPathRouter()


# ── 便捷函数 ──
def get_nas() -> NASPathRouter:
    return nas_router


def nas_status() -> Dict[str, Any]:
    return nas_router.status()


def ensure_ollama_env() -> None:
    """启动时注入 OLLAMA_MODELS 环境变量"""
    env = nas_router.get_ollama_env()
    for k, v in env.items():
        os.environ[k] = v
    sys.stderr.write(f"[NAS] Ollama models → {env.get('OLLAMA_MODELS', '(default)')}\n")
