#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_multi_layer_backup.py — MTSCOS 多层备份矩阵 (flow_backup_layers_20261029)
════════════════════════════════════════════════════════════════════════════
数据备份中心 7 层备份矩阵, 全部在 Flask tick 内执行 (锁安全, 幂等):

  L1 SQLite 快照      — sys_center_evolution.run_backup_center_once (已有, 3 份轮转)
  L2 NAS/第二卷双备份 — 快照 → 双目标目录; 真网络 NAS 未挂载 → 上报大厅
  L3 影子系统         — git 代码镜像: 本地 git → github + gitee 双远端
  L4 沙箱备份         — _git_quarantine 隔离区 zip 归档
  L5 白名单备份       — ~/.mtscos* 安全白名单/握手配置 zip 归档
  L6 ISO 备份         — hdiutil 光盘镜像级冷备 (代码+配置, 每周一)
  L7 RAR/ZIP 归档     — 代码+配置压缩归档 (rar 缺失自动 zip 替代并上报)

失败/缺失 → BACKUP_LAYER_FAIL 自动上报大厅 (24h 去重), 中心认领闭环。
"""
import os
import time
import shutil
import zipfile
import subprocess
import sqlite3
from datetime import datetime

DB_PATH = "/Users/wuchenghao/MTSCOS_AI_Project/flask-app/database/app.db"
PROJECT = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project"
BACKUP_DIR = "/Users/wuchenghao/MTSCOS_BACKUPS"

# L2: 双备份目标 (本地第二卷 × 2; 真网络 NAS 挂载点自动发现)
_L2_TARGETS = ["/Volumes/MyData 1/MTSCOS_BACKUPS", "/Volumes/MyBackups/MTSCOS_BACKUPS"]
# flow_nas_reconnect_20261030: NAS 重启后自动重连 — HULK-NAS (keychain: wuchenghao15@smb)
_NAS_CANDIDATES = ["/Volumes/feiniu", "/Volumes/飞牛", "/Volumes/NAS", "/Volumes/trim", "/Volumes/Truenas",
                   "/Volumes/HULK-NAS", "/Volumes/backup", "/Volumes/MyBackups 1"]
_NAS_HOST = "HULK-NAS.local"
_NAS_IP = "192.168.31.140"   # flow_nas_ip_20261030: 跨网段 mDNS 不可用, IP 经 hulk-server subnet router
_NAS_USER = "wuchenghao15"
_NAS_SHARES = ("backup", "MyBackups", "public", "backups")   # 依次尝试的 share 名

# L3: 影子系统 (git → github + gitee)
GIT_REMOTE_GITHUB = os.environ.get("MTSCOS_GIT_GITHUB", "")
GIT_REMOTE_GITEE = os.environ.get("MTSCOS_GIT_GITEE", "")
_GITIGNORE = """database/
*.db
*.db-wal
*.db-shm
_runtime/
_backups/
__pycache__/
*.pyc
.venv/
venv/
node_modules/
.git_quarantine/
*.log
.DS_Store
"""

_layers_state = {}


def _log_layer(c, layer, ok, detail):
    """每层结果: 先打 stderr 日志 (永不因 DB 锁吞掉), 再落 evolution_log (5s 快速失败)"""
    _layers_state[layer] = {"ok": ok, "detail": detail, "ts": time.time()}
    print(f"  [backup-L{layer}] {'✅' if ok else '❌'} {detail}", flush=True)
    try:
        c.execute("INSERT INTO mt_center_evolution_log (center_name, event, detail) VALUES (?,?,?)",
                  ("数据备份中心", f"LAYER_{layer}", f"{'✅' if ok else '❌'} {detail}"))
        c.commit()
    except Exception as e:
        print(f"  [backup-L{layer}] ⚠️ log落库失败: {e}", flush=True)


def _hall_alert(c, title, description):
    """层失败 → 大厅上报 (24h 去重)"""
    try:
        recent = c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE source='BACKUP_LAYER_FAIL' AND title LIKE ?
            AND created_at > datetime('now','localtime','-24 hours')""", (f"%{title[:30]}%",)).fetchone()[0]
        if recent:
            return
        c.execute("""INSERT INTO mt_lab_task_hall
            (title, description, source, priority, status,
             hall_code, approval_status, publisher, publisher_role, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (title, description, "BACKUP_LAYER_FAIL", "HIGH", "QUEUED",
             f"HALL-BKLAYER-{datetime.now():%Y%m%d%H%M%S}", "APPROVED",
             "backup_center", "hall_ingest"))
    except Exception:
        pass


def _layer2_nas_dual(c, today_snapshot):
    """L2: 快照双备份到第二卷 × 2 + 真网络 NAS 检测
    flow_backup_l2_async_20261029: MyData 1 是休眠唤醒极慢的卷 (stat 都可能挂 30s+),
    tick 线程绝不能直接碰 — 全部卷 IO 打包进后台 sh 脚本, tick 只写本地标记秒回。
    后台脚本完成后写 .l2_result 标记, 下 tick 读结果落库。"""
    if not today_snapshot or not os.path.exists(today_snapshot):
        _log_layer(c, 2, False, "无当日快照可复制")
        return
    return _layer2_dispatch(c, today_snapshot)


def _layer2_dispatch(c, today_snapshot):
    import json as _json
    day = datetime.now().strftime("%Y%m%d")
    dispatch_flag = os.path.join(BACKUP_DIR, f".l2_dispatch_{day}")
    result_flag = os.path.join(BACKUP_DIR, ".l2_result")

    # 上次后台任务结果落库 (一次性)
    if os.path.exists(result_flag):
        try:
            with open(result_flag) as f:
                res = _json.load(f)
            ok = res.get("ok", False)
            detail = res.get("detail", "")[:150]
            _log_layer(c, 2, ok, f"后台结果: {detail}")
            if not ok:
                _hall_alert(c, "[备份L2] 双备份目标部分失败",
                            f"NAS 双备份层后台结果: {detail}。"
                            "请认领处置: 1)MyBackups root 权限需 sudo chown 或换目标 "
                            "2)真 NAS 挂载 feiniu 候选路径。")
            os.remove(result_flag)
        except Exception:
            os.remove(result_flag)

    # 今日未派发 → 派发后台脚本 (tick 线程零卷 IO)
    if not os.path.exists(dispatch_flag):
        nas_mounts = " ".join(f"'{p}'" for p in _NAS_CANDIDATES)
        nas_shares = " ".join(_NAS_SHARES)
        # flow_nas_ip_20261030: 先 IP 直连 (跨网经 subnet router), 再 mDNS 兜底
        nas_probe = f"ping -c 1 -t 3 '{_NAS_IP}' || ping -c 1 -t 3 '{_NAS_HOST}'"
        nas_mount_cmd = f"mount_smbfs //'{_NAS_USER}'@'{_NAS_IP}'/\"$SH\" \"$MNT\" || mount_smbfs //'{_NAS_USER}'@'{_NAS_HOST}'/\"$SH\" \"$MNT\""
        script = f"""#!/bin/sh
SRC='{today_snapshot}'
SZ=$(stat -f%z "$SRC")
DETAIL=""
OK=1
for TGT_DIR in {' '.join("'%s'" % d for d in _L2_TARGETS)}; do
  TGT="$TGT_DIR/$(basename "$SRC")"
  if [ -f "$TGT" ] && [ "$(stat -f%z "$TGT" 2>/dev/null)" = "$SZ" ]; then
    DETAIL="$DETAIL $TGT_DIR=已就位;"
    continue
  fi
  mkdir -p "$TGT_DIR" 2>/dev/null
  if cp -f "$SRC" "$TGT.copying" && [ "$(stat -f%z "$TGT.copying" 2>/dev/null)" = "$SZ" ]; then
    mv -f "$TGT.copying" "$TGT"
    DETAIL="$DETAIL $TGT_DIR=✅;"
  else
    DETAIL="$DETAIL $TGT_DIR=❌复制失败;"
    OK=0
  fi
done
# ── NAS 自动重连 (flow_nas_reconnect_20261030) ──
NAS_OK=0
NAS_MOUNTED=""
for p in {nas_mounts}; do
  if [ -d "$p" ] && mount | grep -q "on $p "; then NAS_OK=1; NAS_MOUNTED="$p"; break; fi
done
if [ $NAS_OK = 0 ] && {nas_probe} > /dev/null 2>&1; then
  for SH in {nas_shares}; do
    MNT="/Volumes/HULK-NAS"
    mkdir -p "$MNT" 2>/dev/null
    if {nas_mount_cmd} 2>/dev/null; then
      NAS_OK=1; NAS_MOUNTED="$MNT/$SH"
      break
    fi
  done
  [ $NAS_OK = 0 ] && DETAIL="$DETAIL HULK-NAS在线但share挂载失败;"
elif [ $NAS_OK = 0 ]; then
  DETAIL="$DETAIL HULK-NAS未上线;"
fi
if [ $NAS_OK = 1 ] && [ -n "$NAS_MOUNTED" ]; then
  NDIR="$NAS_MOUNTED/MTSCOS_BACKUPS"
  mkdir -p "$NDIR" 2>/dev/null
  NTGT="$NDIR/$(basename "$SRC")"
  if [ -f "$NTGT" ] && [ "$(stat -f%z "$NTGT" 2>/dev/null)" = "$SZ" ]; then
    DETAIL="$DETAIL NAS=已同步;"
  elif cp -f "$SRC" "$NTGT.copying" 2>/dev/null && [ "$(stat -f%z "$NTGT.copying" 2>/dev/null)" = "$SZ" ]; then
    mv -f "$NTGT.copying" "$NTGT"
    DETAIL="$DETAIL NAS($NAS_MOUNTED)=✅同步;"
  else
    DETAIL="$DETAIL NAS=❌同步失败;"
    OK=0
  fi
fi
printf '{{"ok": %s, "detail": "NAS=%s(%s);%s"}}' "$OK" "$([ $NAS_OK = 1 ] && echo 已连接 || echo 未连接)" "$NAS_MOUNTED" "$DETAIL" > '{result_flag}'
rm -f '{dispatch_flag}'
"""
        sf = os.path.join(BACKUP_DIR, f".l2_script_{day}.sh")
        with open(sf, "w") as f:
            f.write(script)
        os.chmod(sf, 0o755)
        subprocess.Popen(["sh", sf], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
        with open(dispatch_flag, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        _log_layer(c, 2, True, f"已派发后台双备份 ({len(_L2_TARGETS)} 目标, 含 NAS 检测), 下 tick 读结果")
    else:
        _log_layer(c, 2, True, f"后台双备份进行中 (派发于 {open(dispatch_flag).read()})")


def _layer3_git_shadow(c):
    """L3: 影子系统 — git init (限定 flask-app 代码, OneDrive 全项目 add 巨慢会卡死 tick)
    + github/gitee 双远端 commit+push"""
    try:
        code_root = os.path.join(PROJECT, "flask-app")
        git_dir = os.path.join(code_root, ".git")
        env = dict(os.environ, GIT_AUTHOR_NAME="mtscos-backup",
                   GIT_AUTHOR_EMAIL="backup@mtscos.local",
                   GIT_COMMITTER_NAME="mtscos-backup", GIT_COMMITTER_EMAIL="backup@mtscos.local")
        if not os.path.isdir(git_dir):
            subprocess.run(["git", "init", "-b", "main"], cwd=code_root, check=True,
                           capture_output=True, timeout=30)
            with open(os.path.join(code_root, ".gitignore"), "w") as f:
                f.write(_GITIGNORE)
        r = subprocess.run(["git", "add", "-A"], cwd=code_root, env=env,
                           capture_output=True, timeout=120)
        if r.returncode != 0:
            _log_layer(c, 3, False, f"git add 失败: {r.stderr.decode()[:120]}")
            return
        r = subprocess.run(["git", "commit", "-m",
                            f"MTSCOS shadow backup {datetime.now():%Y-%m-%d %H:%M}"],
                           cwd=code_root, env=env, capture_output=True, timeout=60)
        changed = r.returncode == 0
        if not changed and b"nothing to commit" not in r.stdout:
            _log_layer(c, 3, False, f"git commit 失败: {r.stderr.decode()[:120]}")
            return
        # 双远端
        remotes = {}
        for name, url in (("github", GIT_REMOTE_GITHUB), ("gitee", GIT_REMOTE_GITEE)):
            if not url:
                continue
            subprocess.run(["git", "remote", "remove", name], cwd=code_root, capture_output=True)
            rr = subprocess.run(["git", "remote", "add", name, url], cwd=code_root,
                                capture_output=True, timeout=15)
            if rr.returncode == 0:
                pr = subprocess.run(["git", "push", "-u", name, "main"], cwd=code_root,
                                    capture_output=True, timeout=180, env=env)
                remotes[name] = (pr.returncode == 0, pr.stderr.decode()[:100])
        if not GIT_REMOTE_GITHUB and not GIT_REMOTE_GITEE:
            _hall_alert(c, "[备份L3] 影子系统远端未配置",
                        "git 本地镜像已就绪, 但 github/gitee 远端未配置。"
                        "请认领: 设置 MTSCOS_GIT_GITHUB / MTSCOS_GIT_GITEE 环境变量后, 下个 tick 自动推送。")
            _log_layer(c, 3, True, f"本地 git 镜像就绪{'(有新提交)' if changed else '(无变更)'}; 远端待配置→已上报")
        else:
            ok_all = all(ok for ok, _ in remotes.values()) if remotes else False
            _log_layer(c, 3, ok_all,
                       f"commit={'新' if changed else '无变更'}; 推送: " +
                       "; ".join(f"{k}={'✅' if ok else '❌ ' + msg}" for k, (ok, msg) in remotes.items()))
    except Exception as e:
        _log_layer(c, 3, False, f"异常: {e}")


def _zip_dir(src, dst, skip_ext=((".db", ".db-wal", ".db-shm", ".log"))):
    """目录 zip 归档 (排除数据库与日志)"""
    if os.path.exists(dst):
        return dst
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".venv", "node_modules", ".git")]
            for fn in files:
                if any(fn.endswith(ext) for ext in skip_ext):
                    continue
                fp = os.path.join(root, fn)
                try:
                    zf.write(fp, os.path.relpath(fp, src))
                except Exception:
                    pass
    return dst


def _layer4_sandbox(c):
    """L4: 沙箱 (_git_quarantine) 备份"""
    q = os.path.join(PROJECT, "_git_quarantine")
    if not os.path.isdir(q) or not os.listdir(q):
        _log_layer(c, 4, True, "沙箱隔离区为空, 无需备份")
        return
    dst = os.path.join(BACKUP_DIR, f"sandbox_quarantine_{datetime.now():%Y%m%d}.zip")
    try:
        _zip_dir(q, dst)
        _log_layer(c, 4, True, f"{os.path.basename(dst)} {os.path.getsize(dst)/1e3:.0f}KB")
    except Exception as e:
        _log_layer(c, 4, False, f"zip 失败: {e}")


def _layer5_whitelist(c):
    """L5: 白名单 (~/.mtscos* 安全配置) 备份"""
    dst = os.path.join(BACKUP_DIR, f"whitelist_sec_{datetime.now():%Y%m%d}.zip")
    try:
        count = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in ("/Users/wuchenghao/.mtscos", "/Users/wuchenghao/.mtscos_pack_alt",
                      "/Users/wuchenghao/.mtscos_fernet_key", "/Users/wuchenghao/.mtscos_handshake.sh"):
                if os.path.isfile(p):
                    zf.write(p, os.path.basename(p)); count += 1
                elif os.path.isdir(p):
                    for root, dirs, files in os.walk(p):
                        dirs[:] = [d for d in dirs if d != "__pycache__"]
                        for fn in files:
                            if fn.endswith(".log"):
                                continue
                            fp = os.path.join(root, fn)
                            zf.write(fp, os.path.relpath(fp, os.path.dirname(p))); count += 1
        _log_layer(c, 5, True, f"{count} 个安全文件 → {os.path.basename(dst)}")
    except Exception as e:
        _log_layer(c, 5, False, f"失败: {e}")


def _layer6_iso(c):
    """L6: ISO 冷备 (代码+配置, 每周一)"""
    today = datetime.now()
    dst = os.path.join(BACKUP_DIR, f"mtscos_iso_{today:%Y%GW%V}.iso")
    if os.path.exists(dst):
        _layers_state.setdefault(6, {"ok": True, "detail": "本周 ISO 已存在", "ts": time.time()})
        return
    if today.weekday() != 0:
        _layers_state.setdefault(6, {"ok": True, "detail": "非周一, ISO 层待命", "ts": time.time()})
        return
    src = os.path.join(BACKUP_DIR, "iso_stage")
    try:
        os.makedirs(src, exist_ok=True)
        _zip_dir(os.path.join(PROJECT, "flask-app"), os.path.join(src, "project_code.zip"))
        r = subprocess.run(["hdiutil", "makehybrid", "-o", dst, "-iso", "-joliet", src],
                           capture_output=True, timeout=600)
        if r.returncode == 0:
            _log_layer(c, 6, True, f"{os.path.basename(dst)} {os.path.getsize(dst)/1e6:.0f}MB")
            shutil.rmtree(src, ignore_errors=True)
        else:
            _log_layer(c, 6, False, f"hdiutil 失败: {r.stderr.decode()[:120]}")
    except Exception as e:
        _log_layer(c, 6, False, f"异常: {e}")


def _layer7_archive(c):
    """L7: RAR/ZIP 每日归档 (flask-app 代码+配置, 排除 DB; OneDrive 全项目遍历会卡死 tick)"""
    dst = os.path.join(BACKUP_DIR, f"mtscos_daily_{datetime.now():%Y%m%d}.zip")
    try:
        if not os.path.exists(dst):
            _zip_dir(os.path.join(PROJECT, "flask-app"), dst)
        size = os.path.getsize(dst) / 1e6
        rar_ok = shutil.which("rar") is not None
        if not rar_ok:
            _hall_alert(c, "[备份L7] rar 未安装 (zip 替代运行)",
                        "RAR 归档层: 系统 rar 命令缺失, 已用 zip 替代。"
                        "如需真 RAR (恢复记录/分卷), 请认领安装: brew install rar")
        _log_layer(c, 7, True, f"{os.path.basename(dst)} {size:.0f}MB (格式={'rar' if rar_ok else 'zip替代'})")
    except Exception as e:
        _log_layer(c, 7, False, f"失败: {e}")


def run_layers_once(today_snapshot=None):
    """多层备份矩阵主入口 — backup_center 轨道调用, L1 快照完成后传 today_snapshot"""
    out = {"layers": {}, "alerts": 0}
    c = None
    try:
        c = sqlite3.connect(DB_PATH, timeout=5)   # 5s 快速失败, 绝不挂死 tick 轨道
        _layer2_nas_dual(c, today_snapshot) if today_snapshot else _log_layer(c, 2, False, "今日快照未就绪, L2 待 L1")
        _layer3_git_shadow(c)
        _layer4_sandbox(c)
        _layer5_whitelist(c)
        _layer6_iso(c)
        _layer7_archive(c)
        try:
            c.commit()
        except Exception:
            pass
        out["layers"] = {k: v["ok"] for k, v in _layers_state.items()}
        out["alerts"] = c.execute("""SELECT COUNT(*) FROM mt_lab_task_hall
            WHERE source='BACKUP_LAYER_FAIL' AND created_at > datetime('now','localtime','-5 minutes')""").fetchone()[0]
    except Exception as e:
        print(f"  [backup-layers] ERR: {e}")
        out["error"] = str(e)
    finally:
        if c:
            c.close()
    return out


if __name__ == "__main__":
    snaps = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("app_backup_") and f.endswith(".db"))
    today = os.path.join(BACKUP_DIR, f"app_backup_{datetime.now():%Y%m%d}.db")
    print(run_layers_once(today if os.path.exists(today) else None))
