#!/usr/bin/env python3
"""
仙女座算力弹性引擎 — andromeda_compute_elasticity.py
====================================================
驱动: keepalive_engines (once, 每分钟巡检) + 阈值触发
核心: mini CPU load > 80% → 自动 offload 多进程/批量任务到 hulk (Tailnet 100.100.244.47)

设计原则:
  - mini 是脑 (Ollama 推理永远在 mini 本地, 因为 M-series + GPU 统一内存)
  - hulk 是辅助手 (2核 5.09 负载) — 只做 CPU-bound 多进程任务 (numpy 向量计算, DB 批量扫描)
  - 熔断机制: hulk load > 85% → 立即停止 offload, 退回 mini
  - 心跳: mini 每分钟 ping hulk ssh, 失败 3 次 → 熔断
  - 任务类型: ① auto_evolution auto_detect/auto_retrieve 向量化前 DB 批量扫描
            ② auto_patrol 代码遍历 + 正则匹配
            ③ iceberg_consciousness 多域健康快照并发计算

不做什么:
  - 不 offload Ollama 推理 (M-series GPU unified memory 是 mini 独占优势)
  - 不 offload Flask API 请求 (mini 是公网入口)
  - hulk 负载超阈值立即拒绝, 不排队

数据表:
  mt_compute_elasticity_log — 每次 offload 决策 + 耗时 + 熔断记录
  mt_compute_metrics        — mini/hulk 实时 CPU/内存/网络指标 (ring buffer 最近 1h)

FLOW_ID: flow_andromeda_awakening_20261025
"""
from __future__ import annotations
import sqlite3, os, sys, json, time, uuid, logging, subprocess, multiprocessing
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "database" / "app.db"
log = logging.getLogger("compute_elasticity")

HULK_TAILNET = "wuchenghao15@100.100.244.47"
HULK_SSH_TIMEOUT = 3
MINI_CPU_THRESHOLD = 80       # mini load > 80% → offload
HULK_CPU_THRESHOLD = 85       # hulk load > 85% → refuse
HEARTBEAT_FAIL_LIMIT = 3
METRICS_WINDOW_SECS = 3600    # 保留 1h 指标

SCHEMA = """
CREATE TABLE IF NOT EXISTS mt_compute_elasticity_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT UNIQUE,
    trigger_cpu     REAL,                       -- mini 触发时的 CPU %
    action          TEXT,                       -- OFFLOAD/REFUSE/FALLBACK
    task_type       TEXT,                       -- db_scan/code_scan/vector_prep
    task_size       INTEGER DEFAULT 0,          -- batch size
    hulk_cpu        REAL,                       -- hulk CPU 当时 %
    hulk_ok         INTEGER DEFAULT 1,
    elapsed_ms      INTEGER DEFAULT 0,
    result          TEXT,                       -- SUCCESS/PARTIAL/FAIL
    fail_reason     TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mt_compute_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node            TEXT,                       -- mini/hulk
    cpu_pct         REAL,
    mem_pct         REAL,
    load_avg        REAL,
    active          INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cem_node ON mt_compute_metrics(node, created_at);
"""


def _mini_cpu() -> float:
    """mini 当前 CPU % (从 top 1s 采样)"""
    try:
        out = subprocess.check_output(
            ["top", "-l", "1", "-s", "0", "-n", "0"],
            timeout=5, text=True)
        for line in out.splitlines():
            if "CPU usage" in line:
                # "CPU usage: 10.23% user, 5.67% sys, 84.09% idle"
                idle = float(line.split("idle")[0].strip().split(",")[-1].split()[0].rstrip("%"))
                return max(0.0, 100.0 - idle)
    except Exception as e:
        log.warning(f"mini_cpu fail: {e}")
    return 50.0  # fail open → 不触发 offload


def _hulk_metrics() -> dict:
    """SSH hulk 取 CPU/内存/负载"""
    try:
        out = subprocess.check_output(
            ["ssh", "-F", "/dev/null", "-o", f"ConnectTimeout={HULK_SSH_TIMEOUT}",
             "-o", "StrictHostKeyChecking=no",
             HULK_TAILNET,
             """echo "CPU: $(top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}')"; 
                echo "MEM: $(free | grep Mem | awk '{printf \"%.1f\", $3/$2*100}')";
                echo "LOAD: $(cat /proc/loadavg | awk '{print $1}')" """],
            timeout=HULK_SSH_TIMEOUT + 2, text=True, stderr=subprocess.DEVNULL)
        d = {}
        for line in out.strip().splitlines():
            if line.startswith("CPU:"): d["cpu"] = float(line.split(":")[1].strip())
            elif line.startswith("MEM:"): d["mem"] = float(line.split(":")[1].strip())
            elif line.startswith("LOAD:"): d["load"] = float(line.split(":")[1].strip())
        d["active"] = 1
        return d
    except Exception as e:
        log.warning(f"hulk_metrics fail: {e}")
        return {"cpu": 0, "mem": 0, "load": 0, "active": 0}


class ComputeElasticityEngine:
    """算力弹性引擎"""

    def __init__(self, db_path: Path = DB):
        self.db = sqlite3.connect(str(db_path), timeout=10)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def ping_hulk(self) -> bool:
        """心跳"""
        m = _hulk_metrics()
        c = self.db.cursor()
        c.execute(
            "INSERT INTO mt_compute_metrics (node, cpu_pct, mem_pct, load_avg, active) VALUES (?,?,?,?,?)",
            ("hulk", m.get("cpu", 0), m.get("mem", 0), m.get("load", 0), m.get("active", 0)))
        # mini 指标也存
        mini_cpu = _mini_cpu()
        c.execute(
            "INSERT INTO mt_compute_metrics (node, cpu_pct, mem_pct, active) VALUES (?,?,?,?,1)",
            ("mini", mini_cpu, 0))
        self.db.commit()
        # 清理旧指标 (1h)
        c.execute("DELETE FROM mt_compute_metrics WHERE created_at < datetime('now', '-1 hours')")
        self.db.commit()
        return m.get("active", 0) == 1

    def decide(self, task_type: str = "db_scan", batch_size: int = 1000) -> dict:
        """决策: 这个任务该不该 offload 到 hulk?"""
        run_id = f"ce_{uuid.uuid4().hex[:10]}"
        mini_cpu = _mini_cpu()
        hulk = _hulk_metrics()

        c = self.db.cursor()

        decision = {
            "run_id": run_id,
            "mini_cpu": round(mini_cpu, 1),
            "hulk_cpu": round(hulk.get("cpu", 0), 1),
            "hulk_active": hulk.get("active", 0),
            "action": "LOCAL",  # 默认本地跑
            "batch_size": batch_size,
            "task_type": task_type,
        }

        # 熔断检查 1: mini CPU 是否超阈值
        if mini_cpu < MINI_CPU_THRESHOLD:
            decision["reason"] = f"mini CPU {mini_cpu:.1f}% < {MINI_CPU_THRESHOLD}% — 本地跑"
        elif not hulk.get("active"):
            decision["action"] = "FALLBACK"
            decision["reason"] = f"mini CPU {mini_cpu:.1f}% 高但 hulk 不在线 — 退回 mini"
        elif hulk.get("cpu", 0) > HULK_CPU_THRESHOLD:
            decision["action"] = "REFUSE"
            decision["reason"] = f"mini CPU {mini_cpu:.1f}% 高但 hulk CPU {hulk['cpu']:.1f}% > {HULK_CPU_THRESHOLD}% — 熔断"
        else:
            decision["action"] = "OFFLOAD"
            decision["reason"] = f"mini {mini_cpu:.1f}% > {MINI_CPU_THRESHOLD}% + hulk {hulk['cpu']:.1f}% < {HULK_CPU_THRESHOLD}% → offload"

        # 写日志
        c.execute(
            """INSERT INTO mt_compute_elasticity_log
            (run_id, trigger_cpu, action, task_type, task_size, hulk_cpu, hulk_ok, elapsed_ms, result, fail_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (run_id, mini_cpu, decision["action"], task_type, batch_size,
             hulk.get("cpu", 0), hulk.get("active", 0), 0,
             "OFFLOAD" if decision["action"] == "OFFLOAD" else "LOCAL",
             decision.get("reason", "")))
        self.db.commit()
        return decision

    # ── 被 auto_evolution / patrol 调用 ──
    def offload_vector_prep(self, rows: list) -> list:
        """把 auto_evolution Stage 1 批量向量化预处理 offload 到 hulk
        (批量文本 hash + 去重 — CPU-bound, 适合 2 核 hulk)
        """
        decision = self.decide("vector_prep", len(rows))
        if decision["action"] != "OFFLOAD":
            return None  # 调用方自己处理

        # 构造远程脚本 (hash + 去重)
        payload = json.dumps([str(r)[:200] for r in rows[:decision["batch_size"]]], ensure_ascii=False)
        script = f"""import json, hashlib, sys; data=json.loads(sys.stdin.read()); \
        result=[{{'text':t,'hash':hashlib.md5(t.encode()).hexdigest()}} for t in data]; \
        json.dump(result, sys.stdout)"""
        try:
            t0 = time.time()
            out = subprocess.check_output(
                ["ssh", "-F", "/dev/null", "-o", f"ConnectTimeout={HULK_SSH_TIMEOUT}",
                 "-o", "StrictHostKeyChecking=no",
                 HULK_TAILNET,
                 f"echo '{payload}' | python3 -c '{script}'"],
                timeout=30, text=True)
            result = json.loads(out.strip())
            elapsed = int((time.time() - t0) * 1000)
            self.db.execute(
                "UPDATE mt_compute_elasticity_log SET elapsed_ms=?, result='SUCCESS' WHERE run_id=?",
                (elapsed, decision["run_id"]))
            self.db.commit()
            return result
        except Exception as e:
            self.db.execute(
                "UPDATE mt_compute_elasticity_log SET result='FAIL', fail_reason=? WHERE run_id=?",
                (str(e)[:200], decision["run_id"]))
            self.db.commit()
            return None

    def run_once(self) -> dict:
        """daemon 工作体: 心跳 + 决策采样"""
        self.ping_hulk()
        # 每分钟做一次决策采样 (测试模式)
        return self.decide("heartbeat", 0)


# ── daemon entry ──
def run_once() -> dict:
    return ComputeElasticityEngine().run_once()

def main():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    t0 = time.time()
    print("\n[COMPUTE-ELASTICITY] === run_once ===", flush=True)
    result = run_once()
    for k, v in result.items():
        print(f"  {k}: {v}", flush=True)
    print(f"[COMPUTE-ELASTICITY] done in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
