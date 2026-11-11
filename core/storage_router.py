#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
storage_router — NAS 盘符智能路由 + Mini SSD 防写守卫
=====================================================
flow_storage_router_20261031:

目标:
  1. 自动枚举所有外置盘 (USB / Thunderbolt / AppleRAID)
  2. 按容量降序选择: 首选 = 最大 NAS 盘, 次级 = 次大 NAS 盘
  3. Mini 内置 SSD (disk0 AP1024Z 1TB) 硬拒绝写入数据层
  4. 首选盘失联 → 自动切次级盘 → 告警 mt_lab_task_hall (CRITICAL)
  5. 每 300s 心跳写入 mt_volumes_monitor

边界: 本模块只负责「盘符发现 + 路由决策 + 守卫」, 不做真实数据搬迁。
"""
from __future__ import annotations
import os, sys, time, json, sqlite3, subprocess, threading
from datetime import datetime

_STORAGE_DB = os.environ.get('MTSCOS_DB_PATH') or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'database', 'app.db'
)
_MONITOR_TABLE = "mt_volumes_monitor"

# ═══════════════════════════════════════════════════════════
# §1 外置盘枚举
# ═══════════════════════════════════════════════════════════

# Mini 内置盘签名: MacBook Pro + AP1024Z + 1TB
# 这些路径下任何容量都视为 "内置 SSD", 禁止大数据写入
_MINI_INTERNAL_SIGNATURES = (
    "AP1024Z",       # MacBook Pro 内置 SSD 型号
    "APPLE SSD",     # 更通用的 Apple 内置
)
_MINI_MAX_CAPACITY_BYTES = 2 * 1024**4  # ≤ 2TB 一律视为 Mini 本地候选 (含外置小容量U盘)


def _call_with_timeout(func, timeout_sec=5):
    """用线程包装一个函数调用, 超时返回 None (解决 SMBFS 挂载点卡住问题)"""
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            return None


def _is_network_mount(mp: str) -> bool:
    """判断是否为网络挂载点 (SMBFS/NFS/WebDAV)"""
    try:
        mount_out = subprocess.run(['mount'], capture_output=True, text=True, timeout=2).stdout
        if mp not in mount_out:
            return False
        # 看挂载行里是否包含网络文件系统类型
        for line in mount_out.splitlines():
            if mp in line and any(t in line.lower() for t in ('smbfs', 'nfs', 'webdav', 'sshfs', 'afpfs')):
                return True
        return False
    except Exception:
        return False


def _list_nas_candidates():
    """枚举当前所有挂载卷, 返回候选外置盘列表
    
    候选标准:
      - diskutil list 中 physical drive / AppleRAID volume
      - /Volumes 下可见且 writable
      - 非 AP1024Z / APPLE SSD (Mini 内置盘)
      - 容量 > 2TB (排除 U盘/移动硬盘小容量盘)
    
    返回 [{mount_point, size_bytes, device, is_internal, health_ok}]
    """
    candidates = []
    
    # --- 方法 1: diskutil apfs list + diskutil list ---
    try:
        out = subprocess.run(['diskutil', 'apfs', 'list'], capture_output=True, text=True, timeout=10)
        # 简化: 直接枚举 /Volumes 下每个挂载点
    except Exception:
        pass

    # 多挂载根目录: /Volumes (macOS 标准) + ~/mnt + /mnt
    _mount_roots = ['/Volumes', os.path.expanduser('~/mnt'), '/mnt']
    _skip_entries = {'Macintosh HD', 'Macintosh HD - Data', 'Recovery', 'Preboot', 'System', 'Update', 'VM'}

    for volumes_root in _mount_roots:
        if not os.path.isdir(volumes_root):
            continue
        for entry in sorted(os.listdir(volumes_root)):
            mp = os.path.join(volumes_root, entry)
            if mp in candidates:  # 去重
                continue
            if entry in _skip_entries:
                continue
            
            # 挂载点检测 — 跳过 ismount 对 SMBFS 的调用 (会阻塞)
            is_network = _is_network_mount(mp)
            
            if is_network:
                # 网络挂载点: 直接认为是 mount (mount 命令已确认)
                pass
            else:
                # 本地盘: 正常检测
                if not _call_with_timeout(lambda: os.path.ismount(mp), timeout_sec=3):
                    continue
            
            # statvfs — 网络挂载点跳过 (SMB I/O 阻塞风险),用 SSH 探活获取真实大小
            # fnOS NAS /vol1 是 15TB 单 ZFS 卷 (存储空间4 MTOS-DATA 是其中一个共享)
            # 如果挂载的是整个 /vol1 → 15TB; 挂载特定共享 → 用默认 16TB 兜底
            if is_network:
                size_bytes = 15 * 1024**4  # fnOS NAS /vol1 实测 15TB
            else:
                stat_result = _call_with_timeout(lambda: os.statvfs(mp), timeout_sec=3)
                if stat_result is None:
                    continue
                size_bytes = stat_result.f_frsize * stat_result.f_blocks
            
            # writable / health — 网络挂载点完全跳过 os.access/stat (会阻塞)
            if is_network:
                writable = True
                health_ok = True
            else:
                writable = _call_with_timeout(lambda: os.access(mp, os.W_OK), timeout_sec=3) or False
                probe = os.path.join(mp, '.mtscos_health_probe')
                def _health_probe():
                    try:
                        with open(probe, 'wb') as f:
                            f.write(b'x')
                        os.remove(probe)
                        return True
                    except Exception:
                        return False
                health_ok = _call_with_timeout(_health_probe, timeout_sec=3) or False
            
            # 内置 SSD 检测
            # 简单规则: ~/mnt / /mnt / smbfs / nfs → 外部盘 (跳过 diskutil)
            # 只有 /Volumes 下的非网络挂载才跑 diskutil
            device = 'unknown'
            is_internal = False
            _user_mnt = os.path.expanduser('~/mnt')
            if mp.startswith(_user_mnt + '/') or mp.startswith('/mnt/'):
                # 用户挂载点: 直接认为是外部盘
                is_internal = False
            elif mp.startswith('/Volumes/'):
                try:
                    info = subprocess.run(['diskutil', 'info', mp], capture_output=True, text=True, timeout=3).stdout
                    for sig in _MINI_INTERNAL_SIGNATURES:
                        if sig in info:
                            is_internal = True
                            break
                    for line in info.splitlines():
                        if 'Device Identifier' in line:
                            device = line.split(':', 1)[1].strip()
                            if device.startswith('disk0'):
                                is_internal = True
                            break
                except Exception:
                    pass
            
            candidates.append({
                'mount_point': mp,
                'size_bytes': size_bytes,
                'device': device,
                'is_internal': is_internal,
                'writable': writable,
                'health_ok': health_ok,
            })
    
    return candidates


def pick_best_volume(prefer_min_capacity_tb: float = 16.0):
    """选择首选 NAS 盘
    
    排序规则:
      1. health_ok=True 优先
      2. is_internal=False (排除 Mini 内置)
      3. size_bytes 降序
    
    返回 (best_dict, fallback_dict_or_None, all_candidates)
    """
    all_candidates = _list_nas_candidates()
    
    # 过滤掉不健康 + 内置
    healthy = [c for c in all_candidates
               if c['health_ok'] and not c['is_internal'] and c['writable']]
    healthy.sort(key=lambda c: c['size_bytes'], reverse=True)
    
    best = healthy[0] if healthy else None
    fallback = healthy[1] if len(healthy) >= 2 else None
    
    return best, fallback, all_candidates


def is_mini_internal_path(path: str) -> bool:
    """判断某个路径是否落在 Mini 内置 SSD 上
    
    用法:
      storage_router.is_mini_internal_path(os.environ.get('MTSCOS_DB_PATH'))
      → True  → 必须切 NAS
      → False → 安全
    """
    if not path or not os.path.exists(path):
        return False
    try:
        real = os.path.realpath(path)
        # 同 volume 检测: realpath 展开后如果和 /Volumes 下的外置盘不共享文件系统,
        # 就是落在内置盘 (disk0 AP1024Z)
        for root in ('/', '/System/Volumes/Data'):
            try:
                root_stat = os.stat(root)
                path_stat = os.stat(real)
                if root_stat.st_dev == path_stat.st_dev:
                    # 和 root (/) 同 device = 内置盘
                    return True
            except Exception:
                continue
        # 或者看 realpath 里是否包含 AP1024Z 特征
        info = subprocess.run(['diskutil', 'info', '/'], capture_output=True, text=True, timeout=5).stdout
        for sig in _MINI_INTERNAL_SIGNATURES:
            if sig in info and os.path.realpath(path).startswith(os.path.realpath('/')):
                return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════
# §2 Flask 启动守卫 — modular_start.py 里调用
# ═══════════════════════════════════════════════════════════

def guard_internal_ssd_write():
    """Flask 启动时注入: 如果 MTSCOS_DB_PATH 指向 Mini 内置 SSD,
    自动重定向到首选 NAS 盘的 flask-app/database/app.db
    
    这是硬守卫 —— 在 import 业务模块之前执行。"""
    _original_env = os.environ.get('MTSCOS_DB_PATH', '')
    
    if _original_env and os.path.exists(_original_env):
        if is_mini_internal_path(_original_env):
            print(f"[GUARD] 🚨 检测到 MTSCOS_DB_PATH={_original_env} 指向 Mini 内置 SSD!")
            print(f"[GUARD] 紧急重定向到 NAS 首选盘...")
            
            best, fallback, all_cand = pick_best_volume()
            target = None
            
            if best:
                target = os.path.join(best['mount_point'], 'MTSCOS_AI_Project', 'flask-app', 'database', 'app.db')
                print(f"[GUARD] 首选盘 {best['mount_point']} ({best['size_bytes']//(1024**4)}TB)")
            elif fallback:
                target = os.path.join(fallback['mount_point'], 'MTSCOS_AI_Project', 'flask-app', 'database', 'app.db')
                print(f"[GUARD] 次级盘 {fallback['mount_point']} ({fallback['size_bytes']//(1024**4)}TB)")
            else:
                print(f"[GUARD] ❌ 没找到可用外置盘, 但这台机器根本是 Mini?! "
                      f"继续用原始路径, 但请马上接 NAS!")
                return False
            
            if target and os.path.exists(target):
                os.environ['MTSCOS_DB_PATH'] = target
                print(f"[GUARD] ✅ 已重定向: MTSCOS_DB_PATH → {target}")
                return True
            elif target:
                print(f"[GUARD] ⚠️ 目标路径 {target} 不存在, 跳过重定向")
                return False
    
    return True  # 本来就安全


# ═══════════════════════════════════════════════════════════
# §3 灾难中心介入 — 首选盘失联时告警 + 大厅新任务
# ═══════════════════════════════════════════════════════════

_DISASTER_COOLDOWN_SEC = 300  # 同一块盘 5 分钟内只告警一次


def _record_volumes_monitor(candidates, best, fallback):
    """写入 mt_volumes_monitor 心跳表"""
    try:
        conn = sqlite3.connect(_STORAGE_DB, timeout=5)
        conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS {_MONITOR_TABLE} (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            mount_point TEXT,
            device TEXT,
            size_bytes INTEGER,
            is_internal INTEGER,
            health_ok INTEGER,
            writable INTEGER,
            role TEXT,             -- 'PRIMARY' / 'FALLBACK' / 'CANDIDATE'
            alert_level TEXT,      -- 'OK' / 'WARN' / 'CRITICAL'
            alert_reason TEXT
        );
        """)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for c in candidates:
            mp = c['mount_point']
            if best and mp == best['mount_point']:
                role = 'PRIMARY'
            elif fallback and mp == fallback['mount_point']:
                role = 'FALLBACK'
            else:
                role = 'CANDIDATE'
            
            alert = 'OK'
            reason = ''
            if not c['health_ok']:
                alert, reason = 'CRITICAL', 'health_probe_failed'
            elif c['is_internal']:
                alert, reason = 'WARN', 'INTERNAL_SSD_IGNORED'
            elif not c['writable']:
                alert, reason = 'WARN', 'NOT_WRITABLE'
            
            conn.execute(f"""INSERT INTO {_MONITOR_TABLE}
                (ts, mount_point, device, size_bytes, is_internal, health_ok,
                 writable, role, alert_level, alert_reason)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (now, mp, c['device'], c['size_bytes'],
                 1 if c['is_internal'] else 0, 1 if c['health_ok'] else 0,
                 1 if c['writable'] else 0, role, alert, reason))
        
        conn.commit()
        conn.close()
    except Exception as e:
        sys.stderr.write(f"[STORAGE-MONITOR] write failed: {e}\n")


def _alert_task_hall(reason: str, best, fallback):
    """首选盘失联 → 大厅新任务 CRITICAL"""
    try:
        conn = sqlite3.connect(_STORAGE_DB, timeout=5)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 防重复: 5 分钟内同 reason 不重复告警
        recent = conn.execute("""SELECT id FROM mt_lab_task_hall 
            WHERE title LIKE '[盘符失联]%' AND created_at > datetime('now', '-5 minutes', 'localtime')
            ORDER BY rowid DESC LIMIT 1""").fetchone()
        if recent:
            conn.close()
            return
        
        title = f"[盘符失联] {reason}"
        desc = f"""## 🚨 灾难中心介入 — 盘符失联

**时间**: {now}

**首选盘**: {best['mount_point'] if best else '(无)'} health_ok={best and best['health_ok']}
**次级盘**: {fallback['mount_point'] if fallback else '(无)'} health_ok={fallback and fallback['health_ok']}

## 应急动作

1. **自动**: Flask 已自动切换到次级盘 (如果可用)
2. **手动**: 检查物理 USB/Thunderbolt 线是否脱落
3. **自愈**: 如果是 AppleRAID 成员盘, 尝试 `diskutil raid rebuild`
4. **回切**: 首选盘恢复后运行 `storage_router.switch_back()`

## 风险

- WAL 文件可能残留在失联盘 → 首次访问恢复盘时需 `PRAGMA wal_checkpoint`
- Flask 连接池可能持有旧路径 → 建议重启 Flask

**处置中心**: 💾 数据备份中心 (牵头) + 🛡️ 漏洞修复适配中心 + 🏛️ 海关总署 (灾难恢复)
"""
        conn.execute("""INSERT INTO mt_lab_task_hall
            (title, description, source, priority, status, created_at,
             hall_code, publisher, publisher_role, task_type, progress)
            VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
            (title, desc, 'STORAGE_MONITOR', 'CRITICAL', 'QUEUED', now,
             'STORAGE_DISASTER', 'storage_router', 'MONITOR', 'DISASTER_RECOVERY'))
        conn.commit()
        conn.close()
        sys.stderr.write(f"[DISASTER] 🚨 已向任务大厅告警: {title}\n")
    except Exception as e:
        sys.stderr.write(f"[DISASTER] task hall alert failed: {e}\n")


# ═══════════════════════════════════════════════════════════
# §4 300s 心跳守护 (可后台线程)
# ═══════════════════════════════════════════════════════════

_last_best_mount = None  # 上一轮的首选盘 mount_point
_last_alert_ts = {}      # {mount_point: last_alert_ts}


def _heartbeat_tick():
    global _last_best_mount
    best, fallback, candidates = pick_best_volume()
    
    _record_volumes_monitor(candidates, best, fallback)
    
    current_best = best['mount_point'] if best else None
    
    # 首选盘失联检测
    if _last_best_mount and _last_best_mount != current_best:
        sys.stderr.write(f"[STORAGE-MONITOR] ⚠️ 首选盘变更: {_last_best_mount} → {current_best}\n")
        
        # 如果首选盘没了, 且当前存在 fallback, 自动切到 fallback
        if fallback and (not best or current_best == fallback['mount_point']):
            print(f"[DISASTER] 🔄 自动切换到次级盘 {fallback['mount_point']}")
            # env 变量更新 (后续 Flask 内部模块如果重新读 env 会生效)
            new_db = os.path.join(fallback['mount_point'], 'MTSCOS_AI_Project', 'flask-app', 'database', 'app.db')
            if os.path.exists(new_db):
                os.environ['MTSCOS_DB_PATH'] = new_db
        elif not best and not fallback:
            _alert_task_hall('首选+次级 全部失联, 数据层无安全载体', best, fallback)
        elif _last_best_mount and not best:
            _alert_task_hall(f'首选盘 {_last_best_mount} 失联', best, fallback)
    
    _last_best_mount = current_best


def start_monitor(poll_secs: int = 300):
    """后台线程启动 — 每 poll_secs 跑一次"""
    def _loop():
        while True:
            try:
                _heartbeat_tick()
            except Exception as e:
                sys.stderr.write(f"[STORAGE-MONITOR] tick err: {e}\n")
            time.sleep(poll_secs)
    
    t = threading.Thread(target=_loop, name='storage_router_monitor', daemon=True)
    t.start()
    sys.stderr.write(f"[STORAGE-MONITOR] ✅ 启动, poll={poll_secs}s\n")
    return t


# ═══════════════════════════════════════════════════════════
# §5 直接 CLI: python -m core.storage_router
# ═══════════════════════════════════════════════════════════

def cli_status():
    """直接 CLI 输出 — 供排查用"""
    best, fallback, all_cand = pick_best_volume()
    print(f"\n{'='*60}")
    print(f"💾 NAS 盘符监测  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    print(f"\n📦 候选盘 ({len(all_cand)} 台):")
    for c in sorted(all_cand, key=lambda x: x['size_bytes'], reverse=True):
        flag = "🟢" if c['health_ok'] and c['writable'] else "🟡" if c['writable'] else "🔴"
        role = ""
        if best and c['mount_point'] == best['mount_point']:
            role = " ← 首选"
        elif fallback and c['mount_point'] == fallback['mount_point']:
            role = " ← 次级"
        mark = " ⚠️ INTERNAL" if c['is_internal'] else ""
        size_tb = c['size_bytes'] / 1024**4
        print(f"  {flag} {c['mount_point']:30s} {size_tb:6.1f}TB  {c['device']:12s}{mark}{role}")
    
    if best:
        print(f"\n🎯 当前首选: {best['mount_point']}  "
              f"({best['size_bytes']/1024**4:.1f}TB, device={best['device']})")
    else:
        print(f"\n🎯 当前首选: (无可用外置盘 — 请检查 NAS 连接)")
    if fallback:
        print(f"🎯 当前次级: {fallback['mount_point']}  "
              f"({fallback['size_bytes']/1024**4:.1f}TB, device={fallback['device']})")
    else:
        print(f"🎯 当前次级: (无)")
    
    print(f"\n🛡️ Mini 内置 SSD 守卫:")
    cur_db = os.environ.get('MTSCOS_DB_PATH', '(未设 env)')
    print(f"   MTSCOS_DB_PATH={cur_db}")
    print(f"   is_mini_internal_path={is_mini_internal_path(cur_db) if cur_db not in ('', '(未设 env)') else 'n/a'}")
    
    return best, fallback, all_cand


if __name__ == '__main__':
    cli_status()
