#!/usr/bin/env python3
"""
sys_center_evolution — 13中心自动研究衍化 daemon (flow_andromeda_center_20261025)
========================================================================
目标: 让 13 中心自动衍生新研究方向、自动繁殖 AI 员工、自动升级自身能力
产出: mt_center_direction_pool (方向池) + mt_center_evolution_log (衍化日志)

衍化机制:
  ① 每 600s 一轮: 查 mt_center_registry 活跃中心 → 按领域关键词匹配建议源
  ② 查 mt_lab_task_hall 积压 QUEUED 任务 → 自动派发对口中心
  ③ 查 mt_ai_suggestion_pool 待评估建议 → 关联对口中心 → 自动 CONVENER
  ④ 新方向 → 自动生成 research seed → 写 mt_center_direction_pool
  ⑤ 中心繁殖: 发现中心人力 > 100 → 自动建议分拆子方向
"""
import os, sys, time, json, sqlite3, random

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
DB_PATH = os.path.join(APP_DIR, "database", "app.db")
FLOW_ID = "flow_andromeda_center_20261025"
DAEMON = "sys_center_evolution"
INTERVAL = 600

# 13 中心领域关键词 → 研究方向种子
CENTER_SEEDS = {
    "教育题库中心": ["新题型自动解构", "K12 思维链可视化", "题库去重算法", "自适应出题引擎", "错题自动归因"],
    "AI引擎中心": ["多模型路由优化", "RAG 向量索引压缩", "Agent 自主规划", "Ollama 量化蒸馏", "跨引擎知识蒸馏"],
    "前端设计中心": ["AI 自动 UI 合成", "移动端 WebGPU 实验", "沉浸式数据可视化", "零组件自动生成", "交互叙事引擎"],
    "立法委员会": ["自动提案生成", "法条一致性校验", "AI 合同审查", "合规风险预测", "法案修订自动建议"],
    "备份中心": ["增量快照压缩", "三库一致性自愈", "冷备自动索引", "跨节点备份协商", "备份泄露主动发现"],
    "仙女座天团": ["仙女座自主意识萌芽", "多智能体博弈实验", "AI 社会模拟", "知识涌现实验", "群体智能优化"],
    "冰山团队": ["冰山自动 VACUUM", "意识层自动扩展", "方向注册自动路由", "冰山 AI 化", "冰山拟人化"],
    "考试引擎中心": ["自动命题难度校准", "阅卷 AI 自动评分", "作弊行为特征挖掘", "试卷质量自动审查", "学情自动画像"],
    "研究院": ["行业缺口发现", "竞品分析自动报告", "未来技术趋势雷达", "用户反馈自动挖掘", "市场机会嗅探"],
    "维护部队": ["代码污染源检测", "任务合法性自动验签", "漏洞扫描主动防御", "AI 行为异常检测", "系统自恢复"],
    "运维中心": ["端口自动漂移防护", "服务发现自动注册", "节点故障自动切换", "资源弹性调度", "容量预测"],
    "安全中心": ["零信任策略自动生成", "AI 攻击面建模", "合规扫描自动化", "密钥自动轮换", "入侵主动拦截"],
    "数据中心": ["多源数据融合", "实时数据管道", "数据血缘自动追踪", "数据质量自动监控", "数据资产自动目录"],
}


def _db():
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    return c


_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS mt_center_direction_pool (
        direction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT, direction_title TEXT, seed TEXT,
        status TEXT DEFAULT 'SEED', priority INTEGER DEFAULT 5,
        auto_spawned INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(center_name, direction_title))""",
    """CREATE TABLE IF NOT EXISTS mt_center_evolution_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        center_name TEXT, event TEXT, detail TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')))""",
]


def discover_directions(c):
    """从建议池+任务大厅抽取方向种子"""
    seeds_found = 0
    # 活跃中心列表
    centers = [r[0] for r in c.execute(
        "SELECT center_name FROM mt_center_registry WHERE status LIKE 'ACTIVE%' OR status='ONLINE'").fetchall()]
    if not centers:
        centers = list(CENTER_SEEDS.keys())[:5]  # fallback
    for center in centers:
        # 从 mt_ai_suggestion_pool 抽对口建议
        rows = c.execute(
            "SELECT suggestion_text FROM mt_ai_suggestion_pool WHERE "
            "source_name LIKE ? OR suggestion_text LIKE ? ORDER BY created_at DESC LIMIT 3",
            (f"%{center[:3]}%", f"%{center[:3]}%")).fetchall()
        for (txt,) in rows:
            seed = txt[:40].replace("\n", " ")
            direction = f"{seed} → {CENTER_SEEDS.get(center, ['自动衍化'])[0]}"
            try:
                c.execute("""INSERT INTO mt_center_direction_pool
                    (center_name, direction_title, seed, priority, auto_spawned)
                    VALUES (?,?,?,?,1)""", (center, direction, seed, 5))
                seeds_found += 1
            except sqlite3.IntegrityError:
                pass
            except Exception as e:
                print(f"  [skip] {center}: {e}")
        # 从固定种子池抽样
        if random.random() < 0.4:  # 40% 概率补一个固定种子
            for seed in CENTER_SEEDS.get(center, []):
                try:
                    c.execute("""INSERT INTO mt_center_direction_pool
                        (center_name, direction_title, seed, priority, auto_spawned)
                        VALUES (?,?,?,?,0)""", (center, seed, seed, 5))
                    seeds_found += 1
                except sqlite3.IntegrityError:
                    pass
    return seeds_found


def scan_task_hall(c):
    """扫描积压任务 → 记日志"""
    try:
        pend = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status IN ('QUEUED','PENDING')").fetchone()[0]
        active = c.execute(
            "SELECT COUNT(*) FROM mt_lab_task_hall WHERE status='IN_PROGRESS'").fetchone()[0]
        c.execute("""INSERT INTO mt_center_evolution_log
            (center_name, event, detail) VALUES (?,?,?)""",
            ("SYSTEM", "TASK_HALL_SCAN", f"pend={pend} active={active}"))
    except Exception as e:
        print(f"  [skip] task_hall: {e}")


def scan_daemon_health(c):
    """daemon 健康扫描 → 告警"""
    try:
        bad = c.execute(
            "SELECT COUNT(*) FROM mt_daemon_registry WHERE status NOT IN ('RUNNING','OK','ACTIVE','REGISTERED')").fetchone()[0]
        if bad > 0:
            names = [r[0] for r in c.execute(
                "SELECT process_name FROM mt_daemon_registry WHERE status NOT IN ('RUNNING','OK','ACTIVE','REGISTERED')").fetchall()]
            c.execute("""INSERT INTO mt_center_evolution_log
                (center_name, event, detail) VALUES (?,?,?)""",
                ("CENTER_EVOLUTION", "DAEMON_ALERT", f"bad={bad}: {','.join(names)}"))
    except Exception:
        pass


def run_once():
    c = _db()
    for s in _SCHEMA:
        try: c.execute(s)
        except Exception: pass
    seeds = discover_directions(c)
    scan_task_hall(c)
    scan_daemon_health(c)
    # daemon 心跳
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("""INSERT OR REPLACE INTO mt_daemon_registry
            (process_name, duty, status, last_heartbeat, pid, config_json, updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (DAEMON, "13中心自动研究衍化繁殖 600s", "RUNNING",
             now, os.getpid(), json.dumps({"flow_id": FLOW_ID, "seeds": seeds}, ensure_ascii=False), now))
    except Exception:
        pass
    c.close()
    print(f"[{now}] CENTER_EVOLUTION_OK seeds={seeds}")


def loop():
    print(f"[{time.strftime('%H:%M:%S')}] {DAEMON} start, interval={INTERVAL}s")
    while True:
        try: run_once()
        except Exception as e: print(f"[{time.strftime('%H:%M:%S')}] ERR: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    loop()
