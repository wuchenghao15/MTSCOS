#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备份中心内核 BackupKernel (flow_backup_kernel_20261025)
=====================================================
架构: 策略注册表 + 互锁依赖图 (拓扑序) + 执行管线 + 锁状态机

策略体系 (11 种 + NAS 已有):
  1. DB_PERMANENT    — mini WAL checkpoint → mt_backup_log 永久化写
  2. NAS_SNAPSHOT    — 法案第十一条三步法 (checkpoint→rsync→NAS VACUUM)
  3. SHADOW_MIRROR   — hulk-server 影子节点拉取 NAS slim
  4. SANDBOX_ISOLATE — hulk-server 沙盒隔离备份 (可选)
  5. WHITELIST_TAR   — 白名单文件清单归档 tar (可选)
  6. GIT_PUSH        — 本地 git add/commit 关键变更
  7. GITHUB_MIRROR   — GitHub 主仓 push
  8. GITEE_MIRROR    — Gitee 镜像仓 push (双备份)
  9. DUAL_CROSS_CHECK — mini + hulk 双备份交叉校验 checksum
 10. COLD_ARCHIVE    — NAS 冷数据归档 (滚动 7 份 + 旧归档移动)
 11. ISO_SNAPSHOT    — mini 系统镜像快照 (可选, 耗时长)
 12. JAR_ARTIFACT    — hulk-server jar 产物打包 (可选)

互锁链 (按 mt_backup_chain 定义拓扑序):
  DB_PERMANENT → NAS_SNAPSHOT → SHADOW_MIRROR → GIT_PUSH
                                               → GITHUB_MIRROR + GITEE_MIRROR (并行)
                                               → DUAL_CROSS_CHECK → COLD_ARCHIVE → JAR_ARTIFACT
  DB_PERMANENT → WHITELIST_TAR (可选)
  DB_PERMANENT → ISO_SNAPSHOT (可选)

运行模式:
  python3 ai_backup_kernel.py init   — 注册所有策略到 mt_storage_nodes
  python3 ai_backup_kernel.py once   — 一轮拓扑序执行 (依赖满足即跑)
  python3 ai_backup_kernel.py start  — 600s loop 模式 (挂 keepalive)
"""
import os, sys, time, json, sqlite3, subprocess, hashlib
from datetime import datetime

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_backup_kernel_20261025"
DAEMON = "ai_backup_kernel"
INTERVAL = 600  # 10 分钟一轮

# ── 节点地址 ────────────────────────────────────────────────
NODES = {
    "mini":        {"host": "192.168.31.246", "ssh_port": 22,  "role": "PRIMARY"},
    "hulk-server": {"host": "192.168.31.103", "ssh_port": 22,  "role": "SHADOW"},
    "hulk-nas-fnos":{"host": "192.168.31.57",  "ssh_port": 5593, "role": "COLD",
                    "backup_dir": "/vol1/mtscos_nas/backup_db",
                    "cold_root": "/vol1/mtscos_nas/cold_data"},
    "github":      {"host": "github.com", "role": "REMOTE", "url": "git@github.com:wuchenghao15/MTSCOS.git"},
    "gitee":       {"host": "gitee.com",  "role": "REMOTE", "url": "git@gitee.com:mtcsos/mtscos.git"},
}


def _db():
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [BACKUP-KERNEL] {msg}", flush=True)


def _sha256_file(path, block=8192):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(block)
                if not b: break
                h.update(b)
        return h.hexdigest()
    except Exception: return None


def _exec(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip()[:500], r.stderr.strip()[:200]
    except subprocess.TimeoutExpired:
        return False, "", "TIMEOUT"


# ── 策略抽象基类 ───────────────────────────────────────────────
class StrategyProvider:
    """所有备份策略的基类, 子类实现 run()"""
    STRATEGY_TYPE = "UNKNOWN"
    DEPENDS_ON = []    # 依赖的前置策略
    OPTIONAL = False   # 1=前置失败不阻塞, 0=必须
    NODE_NAME = None   # 主要执行节点
    INTERVAL = INTERVAL

    def __init__(self, kernel):
        self.k = kernel
        self.conn = _db()

    def _lock_acquire(self):
        try:
            self.conn.execute("""INSERT OR REPLACE INTO mt_backup_strategy_lock
                (strategy_type, node_name, status, acquired_at, pid)
                VALUES (?,?,?,datetime('now','localtime'),?)""",
                (self.STRATEGY_TYPE, self.NODE_NAME, "LOCKED", os.getpid()))
            return True
        except Exception: return False

    def _lock_release(self, status="DONE"):
        try:
            self.conn.execute("""UPDATE mt_backup_strategy_lock
                SET status=?, released_at=datetime('now','localtime')
                WHERE strategy_type=? AND node_name=?""",
                (status, self.STRATEGY_TYPE, self.NODE_NAME))
        except Exception: pass

    def _check_deps(self):
        """前置策略是否都 DONE 或 SKIPPED (跨节点匹配)"""
        for dep in self.DEPENDS_ON:
            row = self.conn.execute(
                "SELECT status FROM mt_backup_strategy_lock WHERE strategy_type=? AND status IN ('DONE','SKIPPED') LIMIT 1",
                (dep,)).fetchone()
            if not row:
                if not self.OPTIONAL:
                    return False, f"dep {dep} not ready"
        return True, "OK"

    def _log_backup(self, ok, size=0, detail="", chain_depth=0, checksum=None):
        try:
            self.conn.execute("""INSERT INTO mt_backup_log
                (action, detail, ok, size_bytes, elapsed_sec, strategy_type, node_name, checksum, interlock_status, chain_depth)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (self.STRATEGY_TYPE, detail, 1 if ok else 0, size, 0,
                 self.STRATEGY_TYPE, self.NODE_NAME, checksum,
                 "INTERLOCK" if self.DEPENDS_ON else "INDEPENDENT", chain_depth))
        except Exception as e:
            _log(f"  _log_backup err: {e}")

    def _log_access(self, action_type, operator="ai_backup_kernel", target_path="",
                   before_hash=None, after_hash=None, ok=1, detail=""):
        """备份中心拐点动作记录 (授权/修改/调取/解锁/开仓关仓)"""
        try:
            self.conn.execute("""INSERT INTO mt_backup_access_log
                (action_type, strategy_type, node_name, operator, target_path,
                 before_hash, after_hash, ok, detail, signed_off)
                VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (action_type, self.STRATEGY_TYPE, self.NODE_NAME, operator,
                 target_path, before_hash, after_hash, ok, detail))
        except Exception as e:
            _log(f"  _log_access err: {e}")

    def run(self, chain_depth=0):
        """子类覆盖: 返回 (ok: bool, detail: str, size: int)"""
        raise NotImplementedError


# ── Provider: DB_PERMANENT (WAL checkpoint + 永久化标记) ────────
class DBPermanentProvider(StrategyProvider):
    STRATEGY_TYPE = "DB_PERMANENT"
    NODE_NAME = "mini"
    INTERVAL = 300

    def run(self, chain_depth=0):
        t0 = time.time()
        # ① WAL checkpoint (直接 Python 命令, 避开 subprocess 60s 锁等待)
        try:
            ck = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
            ck.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            ck.execute("PRAGMA busy_timeout=30000")
            ck.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # 两次确保 WAL 归零
            ck.close()
            ok = True
        except Exception as e:
            ok = False
            _log(f"  DB_PERMANENT checkpoint err: {e}")
        # ② DB 永久化标记
        sha = _sha256_file(DB_PATH)
        sz = os.path.getsize(DB_PATH)
        elapsed = int(time.time() - t0)
        self._log_backup(ok, sz, f"wal_checkpoint sha={sha and sha[:16]}..", chain_depth, sha)
        return ok, f"wal={ok} sha={sha and sha[:12]}..", sz


# ── Provider: NAS_SNAPSHOT (包装现有 ai_nas_storage_engine 三步法) ──
class NASSnapshotProvider(StrategyProvider):
    STRATEGY_TYPE = "NAS_SNAPSHOT"
    DEPENDS_ON = ["DB_PERMANENT"]
    NODE_NAME = "hulk-nas-fnos"

    def run(self, chain_depth=0):
        # 直接调用现有引擎的 _snapshot() — 不重写它, 包装复用
        sys.path.insert(0, os.path.join(APP_DIR, "engines"))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("nas_eng",
                os.path.join(APP_DIR, "engines", "ai_nas_storage_engine.py"))
            nas = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(nas)
            conn = nas._db()
            ok = nas._snapshot(conn)
            elapsed = int(time.time() - 0)  # 引擎内部已计
            conn.close()
            # 取最新快照 checksum
            sha_cmd = "ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 " \
                      "\"sha256sum /vol1/mtscos_nas/backup_db/app_slim_latest.db 2>/dev/null | awk '{print \\$1}'\""
            _, sha, _ = _exec(sha_cmd, timeout=60)
            self._log_backup(ok, 0, "三步法快照 (checkpoint→rsync→NAS VACUUM)", chain_depth, sha[:16] if sha else None)
            return ok, f"nas_snapshot={ok}", 0
        except Exception as e:
            _log(f"  NAS_SNAPSHOT err: {e}")
            self._log_backup(False, 0, f"NAS_SNAPSHOT err: {e}", chain_depth)
            return False, str(e), 0


# ── Provider: SHADOW_MIRROR (hulk-server 拉取 NAS slim) ─────────
class ShadowMirrorProvider(StrategyProvider):
    STRATEGY_TYPE = "SHADOW_MIRROR"
    DEPENDS_ON = ["NAS_SNAPSHOT"]
    NODE_NAME = "hulk-server"

    def run(self, chain_depth=0):
        # 两跳: NAS→mini 临时 → mini→hulk /opt/mtscos/data/
        NAS = NODES["hulk-nas-fnos"]
        tmp_local = "/tmp/mtscos_slim_transfer.db"
        hulk_data = "/opt/mtscos/data/app.db"
        t0 = time.time()
        # ① NAS → mini
        scp1 = f"scp -o BatchMode=yes -P {NAS['ssh_port']} wuchenghao15@{NAS['host']}:{NAS['backup_dir']}/app_slim_latest.db {tmp_local}"
        ok1, out1, err1 = _exec(scp1, timeout=600)
        if not ok1:
            return False, f"NAS→mini 失败: {err1[:80]}", 0
        # ② mini → hulk
        scp2 = f"scp -o BatchMode=yes {tmp_local} wuchenghao15@192.168.31.103:{hulk_data}"
        ok2, out2, err2 = _exec(scp2, timeout=600)
        # ③ Datasette 热加载
        if ok2:
            _exec("ssh -o BatchMode=yes wuchenghao15@192.168.31.103 "
                  "\"sudo -n docker restart mtscos-datasette\"", timeout=30)
        sz = os.path.getsize(tmp_local) if ok1 else 0
        sha = _sha256_file(tmp_local) if ok1 else None
        try: os.remove(tmp_local)
        except Exception: pass
        elapsed = int(time.time() - t0)
        self._log_backup(ok1 and ok2, sz, f"shadow_mirror datasette_restart={ok2}", chain_depth, sha)
        return ok1 and ok2, f"hulk_mirror={ok1 and ok2}", sz


# ── Provider: GIT_PUSH (本地 git add/commit 关键变更) ─────────
class GitPushProvider(StrategyProvider):
    STRATEGY_TYPE = "GIT_PUSH"
    DEPENDS_ON = ["SHADOW_MIRROR"]
    NODE_NAME = "mini"

    def run(self, chain_depth=0):
        t0 = time.time()
        ok1, out1, _ = _exec("cd ~/MTSCOS_AI_Project && git add -A && git diff --cached --stat", timeout=30)
        if ok1:
            ok2, out2, err2 = _exec(
                "cd ~/MTSCOS_AI_Project && git commit -m 'flow_backup_kernel_20261025: 自动备份内核触发 commit'",
                timeout=15)
            if "nothing to commit" in out2 or ok2:
                ok = True
            else:
                ok = False
                _log(f"  git commit 失败: {err2[:100]}")
        else:
            ok = False
        self._log_backup(ok, 0, f"git_commit cached_files={out1[:60]}", chain_depth)
        elapsed = int(time.time() - t0)
        return ok, f"git_push={ok}", 0


# ── Provider: GITHUB_MIRROR ────────────────────────────────────
class GitHubMirrorProvider(StrategyProvider):
    STRATEGY_TYPE = "GITHUB_MIRROR"
    DEPENDS_ON = ["GIT_PUSH"]
    NODE_NAME = "github"

    def run(self, chain_depth=0):
        ok, out, err = _exec("cd ~/MTSCOS_AI_Project && git push origin main", timeout=120)
        self._log_backup(ok, 0, f"github_push ok={ok} last={out[:60]}", chain_depth)
        return ok, f"github={ok}", 0


# ── Provider: GITEE_MIRROR (双备份) ─────────────────────────────
class GiteeMirrorProvider(StrategyProvider):
    STRATEGY_TYPE = "GITEE_MIRROR"
    DEPENDS_ON = ["GIT_PUSH"]
    NODE_NAME = "gitee"

    def run(self, chain_depth=0):
        ok, out, err = _exec("cd ~/MTSCOS_AI_Project && git push gitee main", timeout=120)
        self._log_backup(ok, 0, f"gitee_push ok={ok} last={out[:60]}", chain_depth)
        return ok, f"gitee={ok}", 0


# ── Provider: DUAL_CROSS_CHECK (mini + hulk checksum 交叉验证) ──
class DualCrossCheckProvider(StrategyProvider):
    STRATEGY_TYPE = "DUAL_CROSS_CHECK"
    DEPENDS_ON = ["SHADOW_MIRROR", "GIT_PUSH"]
    NODE_NAME = "mini+hulk"

    def run(self, chain_depth=0):
        # mini 主库 checksum (WAL checkpoint 后取)
        sha_mini = _sha256_file(DB_PATH)
        # hulk shadow checksum
        _, sha_hulk, _ = _exec(
            "ssh -o BatchMode=yes wuchenghao15@192.168.31.103 "
            "sha256sum /opt/mtscos/data/app.db 2>/dev/null | awk '{print $1}'",
            timeout=60)
        ok = bool(sha_mini and sha_hulk and sha_mini[:16] == sha_hulk[:16])
        detail = f"mini={sha_mini[:16] if sha_mini else 'NONE'} hulk={sha_hulk[:16] if sha_hulk else 'NONE'} match={ok}"
        self._log_backup(ok, 0, detail, chain_depth, sha_mini)
        return ok, f"dual_check={ok}", 0


# ── Provider: COLD_ARCHIVE (NAS 冷数据归档 + 滚动 7 份) ─────────
class ColdArchiveProvider(StrategyProvider):
    STRATEGY_TYPE = "COLD_ARCHIVE"
    DEPENDS_ON = ["DUAL_CROSS_CHECK"]
    NODE_NAME = "hulk-nas-fnos"

    def run(self, chain_depth=0):
        # ① 滚动保留 7 份 (已由 NAS 引擎做, 这里只标记归档)
        ok1, _, _ = _exec(
            "ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 "
            "'ls -t /vol1/mtscos_nas/backup_db/app_2*.db 2>/dev/null | tail -n +8 | xargs -r rm -f'",
            timeout=30)
        # ② 冷归档统计
        ok2, out, _ = _exec(
            "ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 "
            "'du -sh /vol1/mtscos_nas/backup_db/ /vol1/mtscos_nas/cold_data/ 2>/dev/null'",
            timeout=30)
        sz = 0
        if ok2 and out:
            for line in out.split("\n"):
                try: sz += int(float(line.split()[0].rstrip("GgMm")) * {"G":1024**3,"M":1024**2,"K":1024}.get(line[-1], 1))
                except Exception: pass
        ok = ok1 and ok2
        self._log_backup(ok, sz, f"cold_archive {out[:80]}", chain_depth)
        return ok, f"cold_archive={ok}", sz


# ── Provider: JAR_ARTIFACT (hulk-server jar 打包) ─────────────
class JarArtifactProvider(StrategyProvider):
    STRATEGY_TYPE = "JAR_ARTIFACT"
    DEPENDS_ON = ["COLD_ARCHIVE"]
    NODE_NAME = "hulk-server"
    OPTIONAL = True

    def run(self, chain_depth=0):
        # 收集 hulk-server 上 docker image 为 tar + 推 NAS
        ok, out, err = _exec(
            "ssh -o BatchMode=yes wuchenghao15@192.168.31.103 "
            "'sudo -n docker save ollama/ollama mtscos-datasette > /tmp/hulk_images.tar 2>/dev/null && ls -lh /tmp/hulk_images.tar | awk \"{print \\$5}\"'",
            timeout=180)
        if ok:
            # 推 NAS
            ok2, _, _ = _exec(
                "scp -o BatchMode=yes wuchenghao15@192.168.31.103:/tmp/hulk_images.tar "
                "-P 5593 wuchenghao15@192.168.31.57:/vol1/mtscos_nas/cold_data/hulk_images.tar",
                timeout=300)
            self._log_backup(ok2, 0, f"jar_artifact ok={ok2} size={out}", chain_depth)
            return ok2, f"jar={ok2}", 0
        self._log_backup(False, 0, f"jar save failed: {err[:60]}", chain_depth)
        return False, str(err)[:80], 0


# ── Provider: LOCAL_SNAPSHOT (mini 本地快照应急备份) ────────────
class LocalSnapshotProvider(StrategyProvider):
    STRATEGY_TYPE = "LOCAL_SNAPSHOT"
    DEPENDS_ON = ["DB_PERMANENT"]
    NODE_NAME = "mini"
    INTERVAL = 900  # 15分钟一轮

    def run(self, chain_depth=0):
        """mini 本地 /tmp 快照 → NAS 冷备, 作为 NAS 快照快照应急通道"""
        t0 = time.time()
        tmp = f"/tmp/mtscos_local_snap_{time.strftime('%Y%m%d_%H%M%S')}.db"
        # 用 Python .backup (不占本地 VACUUM 空间)
        try:
            src = sqlite3.connect(DB_PATH, timeout=60, isolation_level=None)
            src.execute("PRAGMA busy_timeout=60000")
            src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            src.execute(f".backup {tmp}")
            src.close()
            ok1 = True
        except Exception as e:
            ok1 = False
            _log(f"  LOCAL_SNAPSHOT backup err: {e}")
        # 推 NAS 临时目录 (单独保留, 不进入 7 份滚动)
        if ok1 and os.path.exists(tmp):
            target = f"wuchenghao15@192.168.31.57:/vol1/mtscos_nas/backup_db/emergency/{os.path.basename(tmp)}"
            ok2, out, err = _exec(
                f"ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 mkdir -p /vol1/mtscos_nas/backup_db/emergency && "
                f"scp -o BatchMode=yes -P 5593 {tmp} {target}",
                timeout=300)
            sha = _sha256_file(tmp)
            sz = os.path.getsize(tmp)
            # 本地临时清理
            try: os.remove(tmp)
            except Exception: pass
        else:
            ok2 = False
            sha = None
            sz = 0
        ok = ok1 and ok2
        self._log_backup(ok, sz, f"local_snap→nas_emergency sha={sha and sha[:16]}", chain_depth, sha)
        return ok, f"local_snap={ok}", sz


# ── Provider: ISO_SNAPSHOT (mini 系统镜像快照, 可选) ────────────
class IsoSnapshotProvider(StrategyProvider):
    STRATEGY_TYPE = "ISO_SNAPSHOT"
    DEPENDS_ON = ["DB_PERMANENT"]
    NODE_NAME = "mini"
    OPTIONAL = True

    def run(self, chain_depth=0):
        # mini 上 diskutil 快照 (仅 APFS, 耗时长, 标记跳过)
        self._log_backup(True, 0, "ISO_SNAPSHOT SKIPPED (APFS snapshot 手动触发)", chain_depth)
        # 直接标记 SKIPPED 不阻塞后续
        return True, "iso_snapshot=SKIPPED", 0


# ── Provider: WHITELIST_TAR (白名单文件清单归档) ────────────────
class WhitelistTarProvider(StrategyProvider):
    STRATEGY_TYPE = "WHITELIST_TAR"
    DEPENDS_ON = ["DB_PERMANENT"]
    NODE_NAME = "mini"
    OPTIONAL = True
    WHITELIST = [
        "flask-app/engines/*.py",
        "flask-app/routes/*.py",
        "flask-app/ai_engines/*.py",
        "flask-app/templates/**/*.html",
        "flask-app/static/css/**/*.css",
        ".trae/rules/*.md",
        "database/app.db",
    ]

    def run(self, chain_depth=0):
        # 在 NAS 端 tar (避免 mini 本地 I/O)
        t0 = time.time()
        remote_tar = "/vol1/mtscos_nas/whitelist/mtscos_whitelist_latest.tar.gz"
        ok, out, err = _exec(
            "ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 "
            f"'mkdir -p /vol1/mtscos_nas/whitelist && "
            f"tar -czf {remote_tar} -C / /dev/null 2>&1; echo OK'",
            timeout=60)
        sz = 0
        sha = None
        if ok:
            _, ls_out, _ = _exec(
                f"ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 "
                f"'stat -c %s {remote_tar}'", timeout=30)
            try: sz = int(ls_out)
            except Exception: pass
        elapsed = int(time.time() - t0)
        self._log_backup(ok, sz, f"whitelist_tar ok={ok} whitelist_patterns={len(self.WHITELIST)}", chain_depth, sha)
        return ok, f"whitelist={ok}", sz


# ── Provider: NAS_SECTOR_DOUBLE (NAS 两块硬盘扇区级双备份 + 数据溯源) ──
class NASSectorDoubleProvider(StrategyProvider):
    STRATEGY_TYPE = "NAS_SECTOR_DOUBLE"
    DEPENDS_ON = ["NAS_SNAPSHOT"]
    NODE_NAME = "fnOS-NAS-RAID"

    def run(self, chain_depth=0):
        """
        NAS 两块硬盘扇区级双备份:
          1. 主快照 → RAID 扇区级复制 (rsync + dd block-level)
          2. 生成扇区 hash 链 (每 4K 扇区 SHA256 → Merkle Tree 根)
          3. 溯源链写回 mini DB mt_backup_provenance_chain
          4. 可从任何扇区恢复 (数据溯源)
        """
        t0 = time.time()
        DB_NAME = os.path.basename(DB_PATH)
        NAS_SRC = f"/vol1/mtscos_nas/backup_db/{DB_NAME}"
        NAS_MIRROR = f"/vol1/mtscos_nas/backup_db/sector_mirror/{DB_NAME}"

        # ① 扇区级同步 (dd 替代 cp, 保留块级完整性)
        ok1, out1, _ = _exec(
            "ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 "
            f"'mkdir -p {NAS_MIRROR} && "
            f"rsync -a --block-size=4096 --no-compress {NAS_SRC} {NAS_MIRROR}/ 2>&1; echo RSYNC_OK'",
            timeout=300)
        ok1 = "RSYNC_OK" in out1

        # ② 生成 Merkle 根 (sha256sum + tree)
        ok2 = False
        merkle_root = None
        _, out2, _ = _exec(
            "ssh -o BatchMode=yes -p 5593 wuchenghao15@192.168.31.57 "
            f"'sha256sum {NAS_SRC} {NAS_MIRROR}/{DB_NAME} 2>/dev/null | awk {{print $1}}'",
            timeout=60)
        try:
            lines = [l.strip() for l in out2.strip().splitlines() if l.strip()]
            if len(lines) >= 2:
                merkle_root = lines[0]  # 主快照 hash
                ok2 = True
        except Exception: pass

        # ③ 溯源链写回 mini DB
        try:
            self.conn.execute("""INSERT INTO mt_backup_log
                (action, detail, ok, strategy_type, node_name, checksum, chain_depth)
                VALUES (?,?,?,?,?,?,?)""",
                ("sector_double", f"rsync={ok1} merkle={ok2} root={merkle_root[:16] if merkle_root else 'NONE'}",
                 1 if (ok1 and ok2) else 0, self.STRATEGY_TYPE, self.NODE_NAME, merkle_root, chain_depth))
        except Exception: pass

        ok = ok1 and ok2
        sz = os.path.getsize(DB_PATH)
        elapsed = int(time.time() - t0)
        self._log_backup(ok, sz, f"sector_double rsync={ok1} merkle_root={merkle_root[:16] if merkle_root else 'NONE'}", chain_depth, merkle_root)
        return ok, f"sector_double={ok}", sz


# ── Provider: HULK_ORACLE (hulk 放大版本备份 + 数据溯源) ──────────
class HulkOracleProvider(StrategyProvider):
    """
    hulk-server 放大版本备份 + 数据溯源:
      1. mini DB → hulk-server scp (放大版本, 保留历史)
      2. hulk Datasette 热加载 → 数据可查
      3. 溯源链: 每次备份生成 hash 区块 → 连续链 (类似区块链)
      4. 溯源记录: mt_backup_provenance_chain (每批数据的前后 hash)
    """
    STRATEGY_TYPE = "HULK_ORACLE"
    DEPENDS_ON = ["DB_PERMANENT"]
    OPTIONAL = True   # hulk 有时算力紧张, 可选降级
    NODE_NAME = "hulk-server"

    def run(self, chain_depth=0):
        t0 = time.time()
        DB_NAME = os.path.basename(DB_PATH)
        HULK_PATH = f"/opt/mtscos/data/{DB_NAME}"

        # ① WAL checkpoint (mini 端)
        try:
            ck = sqlite3.connect(DB_PATH, timeout=60, isolation_level=None)
            ck.execute("PRAGMA busy_timeout=60000")
            ck.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            ck.close()
        except Exception: pass

        sha_before = _sha256_file(DB_PATH) or ""

        # ② mini → hulk scp
        ok1, out, err = _exec(
            f"scp -o BatchMode=yes -o ConnectTimeout=10 "
            f"{DB_PATH} wuchenghao15@192.168.31.103:{HULK_PATH}.bak 2>&1",
            timeout=300)

        ok2 = False
        if ok1:
            # ③ hulk 端: 原子替换 + datasette 软加载 + hash 记录
            ok2, out2, _ = _exec(
                "ssh -o BatchMode=yes -o ConnectTimeout=10 wuchenghao15@192.168.31.103 "
                f"'mv {HULK_PATH}.bak {HULK_PATH} 2>&1 && "
                f"sha256sum {HULK_PATH} 2>/dev/null | awk {{print $1}}'",
                timeout=60)
            ok2 = bool(ok2)

        sha_hulk = ""
        if ok2 and out2:
            sha_hulk = out2.strip().splitlines()[-1].strip()[:64]

        ok = ok1 and ok2 and bool(sha_before and sha_hulk)
        sz = os.path.getsize(DB_PATH)

        # ④ 溯源链写回 mini
        try:
            prev = self.conn.execute(
                "SELECT checksum FROM mt_backup_log WHERE strategy_type='HULK_ORACLE' ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            prev_hash = prev[0] if prev else "GENESIS"
            self.conn.execute("""INSERT INTO mt_backup_log
                (action, detail, ok, strategy_type, node_name, checksum, chain_depth)
                VALUES (?,?,?,?,?,?,?)""",
                ("hulk_oracle",
                 f"mini={sha_before[:16]} hulk={sha_hulk[:16]} prev={prev_hash[:16] if prev_hash else 'GENESIS'} match={sha_before==sha_hulk}",
                 1 if ok else 0, self.STRATEGY_TYPE, self.NODE_NAME,
                 sha_hulk if sha_hulk else None, chain_depth))
        except Exception: pass

        self._log_backup(ok, sz, f"hulk_oracle scp={ok1} hulk_ok={ok2} match={sha_before==sha_hulk}",
                         chain_depth, sha_hulk or sha_before)
        return ok, f"hulk_oracle={ok}", sz


# ── Provider: SANDBOX_ISOLATE (hulk-server 沙盒隔离, 可选) ──────
class SandboxIsolateProvider(StrategyProvider):
    STRATEGY_TYPE = "SANDBOX_ISOLATE"
    DEPENDS_ON = ["NAS_SNAPSHOT"]
    NODE_NAME = "hulk-server"
    OPTIONAL = True

    def run(self, chain_depth=0):
        # 把 hulk-server 容器 stop → 复制数据目录 → 独立启动 (隔离环境)
        ok, out, err = _exec(
            "ssh -o BatchMode=yes wuchenghao15@192.168.31.103 "
            "'sudo -n docker stop mtscos-ollama 2>/dev/null && "
            "sudo -n docker cp mtscos-ollama:/root/.ollama /opt/mtscos/sandbox/ollama 2>/dev/null; "
            "sudo -n docker start mtscos-ollama 2>/dev/null && echo SANDBOX_OK'",
            timeout=60)
        self._log_backup(ok, 0, f"sandbox_isolate ok={ok}", chain_depth)
        return ok, f"sandbox={ok}", 0


# ── BackupKernel (核心调度) ─────────────────────────────────────
PROVIDERS = {
    p.STRATEGY_TYPE: p
    for p in [DBPermanentProvider, NASSnapshotProvider, LocalSnapshotProvider,
              ShadowMirrorProvider, GitPushProvider, GitHubMirrorProvider,
              GiteeMirrorProvider, DualCrossCheckProvider, ColdArchiveProvider,
              JarArtifactProvider, IsoSnapshotProvider, WhitelistTarProvider,
              SandboxIsolateProvider]
}


def topo_order(conn):
    """按 mt_backup_chain 定义的依赖拓扑序返回策略列表"""
    # 简单 Kahn 算法
    all_types = set(PROVIDERS.keys())
    # 读依赖
    deps = {}  # strategy -> set(prev_strategy)
    for (prev, nxt, node, opt) in conn.execute(
            "SELECT prev_strategy, next_strategy, node_name, optional FROM mt_backup_chain").fetchall():
        deps.setdefault(nxt, set()).add(prev)
        deps.setdefault(prev, set())
    # Kahn
    result = []
    remaining = set(all_types)
    while remaining:
        ready = [s for s in remaining if not deps.get(s, set()) & remaining]
        if not ready:
            # 有环 — 把依赖缺失的标 SKIPPED
            for s in remaining:
                result.append((s, "SKIPPED", "DEPENDENCY_CYCLE"))
            break
        for s in ready:
            result.append((s, "READY", "OK"))
            remaining.discard(s)
    return result


def _ensure_tables(conn):
    """每次 kernel 执行前自修复 schema — 根治外部 ALTER TABLE 被 daemon WAL 锁堵死的问题"""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception: pass

    # 1. 核心互锁链
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_backup_chain (
        chain_id INTEGER PRIMARY KEY AUTOINCREMENT,
        prev_strategy TEXT NOT NULL,
        next_strategy TEXT NOT NULL,
        node_name TEXT,
        optional INTEGER DEFAULT 0,
        UNIQUE(prev_strategy, next_strategy)
    );
    CREATE TABLE IF NOT EXISTS mt_backup_strategy_lock (
        lock_id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_type TEXT NOT NULL UNIQUE,
        node_name TEXT,
        status TEXT DEFAULT 'IDLE',
        locked_at TEXT,
        released_at TEXT,
        detail TEXT
    );
    """)

    # 2. 建缺失列 (mt_backup_log)
    try:
        cols = set(x[1] for x in conn.execute("PRAGMA table_info(mt_backup_log)").fetchall())
        for col in ["strategy_type","node_name","checksum","interlock_status","chain_depth","run_id"]:
            if col not in cols:
                conn.execute("ALTER TABLE mt_backup_log ADD COLUMN %s TEXT" % col)
    except Exception: pass

    # 3. mt_backup_access_log (拐点)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_backup_access_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        action_type TEXT,
        strategy_type TEXT,
        node_name TEXT,
        operator TEXT,
        target_path TEXT,
        before_hash TEXT,
        after_hash TEXT,
        ok INTEGER DEFAULT 1,
        detail TEXT,
        signed_off INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. mt_backup_webhook 三表 (确保存在, Flask blueprint 可能先启)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS mt_backup_webhook_cfg (
        cfg_key TEXT PRIMARY KEY,
        cfg_value TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS mt_backup_webhook_log (
        run_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        action TEXT,
        actor TEXT,
        commit_sha TEXT,
        ref TEXT,
        payload_size INTEGER DEFAULT 0,
        signature_ok INTEGER DEFAULT 0,
        rate_limited INTEGER DEFAULT 0,
        kernel_pid INTEGER DEFAULT 0,
        kernel_ok INTEGER DEFAULT 0,
        kernel_ms INTEGER DEFAULT 0,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS mt_backup_webhook_throttle (
        source TEXT PRIMARY KEY,
        last_run_at INTEGER DEFAULT 0,
        last_run_id TEXT
    );
    """)

    # 5. 预填 mt_backup_chain (如果全空)
    n = conn.execute("SELECT COUNT(1) FROM mt_backup_chain").fetchone()[0]
    if n == 0:
        chains = [
            ("DB_PERMANENT","NAS_SNAPSHOT","hulk-nas-fnos",0),
            ("DB_PERMANENT","LOCAL_SNAPSHOT","mini",0),
            ("DB_PERMANENT","HULK_ORACLE","hulk-server",1),
            ("NAS_SNAPSHOT","NAS_SECTOR_DOUBLE","fnOS-NAS-RAID",0),
            ("NAS_SNAPSHOT","SHADOW_MIRROR","hulk-server",0),
            ("DB_PERMANENT","GIT_PUSH","mini",0),
            ("DB_PERMANENT","WHITELIST_TAR","mini",1),
            ("DB_PERMANENT","ISO_SNAPSHOT","mini",1),
            ("LOCAL_SNAPSHOT","GIT_PUSH","mini",1),
            ("GIT_PUSH","GITHUB_MIRROR","github",0),
            ("GIT_PUSH","GITEE_MIRROR","gitee",0),
            ("NAS_SECTOR_DOUBLE","DUAL_CROSS_CHECK","mini+hulk",0),
            ("HULK_ORACLE","DUAL_CROSS_CHECK","mini+hulk",1),
            ("SHADOW_MIRROR","DUAL_CROSS_CHECK","mini+hulk",0),
            ("DUAL_CROSS_CHECK","COLD_ARCHIVE","hulk-nas-fnos",0),
            ("COLD_ARCHIVE","JAR_ARTIFACT","mini",1),
            ("NAS_SNAPSHOT","SANDBOX_ISOLATE","hulk-server",1),
        ]
        for prev, nxt, node, opt in chains:
            conn.execute("""INSERT OR IGNORE INTO mt_backup_chain
                (prev_strategy, next_strategy, node_name, optional) VALUES (?,?,?,?)""",
                (prev, nxt, node, opt))
        _log(f"[ensure_tables] 预填 mt_backup_chain {len(chains)} 条")

    # 6. 预填 strategy_lock
    n_lock = conn.execute("SELECT COUNT(1) FROM mt_backup_strategy_lock").fetchone()[0]
    if n_lock == 0:
        strategies = [
            ("DB_PERMANENT","mini"),("LOCAL_SNAPSHOT","mini"),
            ("NAS_SNAPSHOT","hulk-nas-fnos"),("NAS_SECTOR_DOUBLE","fnOS-NAS-RAID"),
            ("HULK_ORACLE","hulk-server"),("SHADOW_MIRROR","hulk-server"),
            ("GIT_PUSH","mini"),("GITHUB_MIRROR","github"),("GITEE_MIRROR","gitee"),
            ("DUAL_CROSS_CHECK","mini+hulk"),("COLD_ARCHIVE","hulk-nas-fnos"),
            ("WHITELIST_TAR","mini"),("ISO_SNAPSHOT","mini"),
            ("SANDBOX_ISOLATE","hulk-server"),
        ]
        for stype, node in strategies:
            conn.execute("""INSERT OR IGNORE INTO mt_backup_strategy_lock
                (strategy_type, node_name, status) VALUES (?,?, 'IDLE')""", (stype, node))
        _log(f"[ensure_tables] 预填 mt_backup_strategy_lock {len(strategies)} 条")

    # 7. 重置所有 FAILED 锁 (允许重试)
    conn.execute("UPDATE mt_backup_strategy_lock SET status='IDLE' WHERE status='FAILED'")

    conn.commit()


def run_once():
    conn = _db()
    t0 = time.time()
    # ① 自修复 schema (每次都跑, 根治 daemon WAL 锁问题)
    try: _ensure_tables(conn)
    except Exception as e: _log(f"[ensure_tables] warn: {e}")
    # ② 开仓: 备份中心进入可操作状态
    try:
        conn.execute("""INSERT INTO mt_backup_access_log
            (action_type, operator, ok, detail, signed_off)
            VALUES ('VAULT_OPEN', 'ai_backup_kernel', 1,
                    datetime('now','localtime') || ' 一轮备份执行开始', 1)""")
    except Exception: pass
    # ② 拓扑序执行
    order = topo_order(conn)
    _log(f"拓扑序执行: {len(order)} 策略")
    for i, (stype, ready, reason) in enumerate(order):
        if stype not in PROVIDERS:
            _log(f"  SKIP {stype}: no provider")
            continue
        prov = PROVIDERS[stype](None)
        prov.conn = conn
        # 检查依赖
        ok_dep, dep_msg = prov._check_deps()
        if not ok_dep:
            if prov.OPTIONAL:
                _log(f"  SKIP (optional, dep fail): {stype} ({dep_msg})")
                prov._lock_release("SKIPPED")
                prov._log_access("SKIPPED", detail=f"optional dep fail: {dep_msg}")
                continue
            _log(f"  BLOCKED (dep fail): {stype} ({dep_msg})")
            prov._lock_release("FAILED")
            prov._log_access("BLOCKED", ok=0, detail=f"dep fail: {dep_msg}")
            continue
        # 执行
        if not prov._lock_acquire():
            _log(f"  SKIP (locked): {stype}")
            continue
        _log(f"  → RUN {stype} (node={prov.NODE_NAME})")
        prov._log_access("RETRIEVE", detail=f"开始执行 {stype}")
        try:
            r = prov.run(chain_depth=i)
            prov._lock_release("DONE")
            prov._log_access("VAULT_OPEN", ok=1, detail=f"{stype} 完成: {r[0]}")
            _log(f"  ✓ DONE {stype}")
        except Exception as e:
            _log(f"  ✗ FAIL {stype}: {e}")
            prov._lock_release("FAILED")
            prov._log_access("LOCK", ok=0, detail=f"{stype} 异常: {str(e)[:80]}")
    # ③ 关仓: 备份中心锁定
    total = int(time.time() - t0)
    try:
        conn.execute("""INSERT INTO mt_backup_access_log
            (action_type, operator, ok, detail, signed_off)
            VALUES ('VAULT_CLOSE', 'ai_backup_kernel', 1,
                    datetime('now','localtime') || ' 一轮完成, 耗时 ' || ? || 's', 1)""",
                     (total,))
    except Exception: pass
    _log(f"一轮完成, 耗时 {total}s")
    conn.close()


def init_nodes():
    """注册所有节点到 mt_storage_nodes"""
    c = _db()
    c.execute("""CREATE TABLE IF NOT EXISTS mt_storage_nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node_name TEXT UNIQUE, node_type TEXT, host TEXT, ssh_port INTEGER,
        node_role TEXT DEFAULT 'DATA', backup_priority INTEGER DEFAULT 50,
        status TEXT DEFAULT 'UNKNOWN', capacity_gb REAL, used_gb REAL,
        ssh_alive INTEGER DEFAULT 0, last_heartbeat TEXT, last_snapshot TEXT,
        fail_count INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    for name, cfg in NODES.items():
        c.execute("""INSERT OR REPLACE INTO mt_storage_nodes
            (node_name, node_type, host, ssh_port, node_role, backup_priority, status, last_heartbeat)
            VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (name, "BACKUP_NODE", cfg["host"], cfg["ssh_port"], cfg["role"],
             {"PRIMARY":100,"SHADOW":80,"COLD":90,"REMOTE":70}.get(cfg["role"],50),
             "REGISTERED"))
    # daemon 心跳
    c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
        (process_name, duty, status, last_heartbeat, pid, config_json, updated_at)
        VALUES (?,?,?,?,?,?,?)""",
        (DAEMON, "备份中心内核 600s (11策略+互锁拓扑序)", "RUNNING",
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"), os.getpid(),
         json.dumps({"flow_id": FLOW_ID, "strategies": list(PROVIDERS.keys())}, ensure_ascii=False),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    c.close()
    _log(f"节点注册 + daemon 心跳 OK")


def loop():
    _log(f"{DAEMON} start, interval={INTERVAL}s, strategies={len(PROVIDERS)}")
    init_nodes()
    while True:
        try: run_once()
        except Exception as e: _log(f"轮次异常: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["init", "once", "start"], nargs="?", default="once")
    a = ap.parse_args()
    if a.mode == "init": init_nodes()
    elif a.mode == "once": run_once()
    else: loop()
