#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_game_theory_engine — 大厅协作博弈论评估引擎 (flow_game_theory_20261028)
==========================================================================
三大维度:
  ① 边际贡献 (Marginal Contribution) — 每个中心加入协作的增量收益
  ② 夏普里值 (Shapley Value)         — 公平分配协作成果的核心指标
  ③ 博弈论均衡 (Nash Equilibrium)    — 中心最优协作策略组合

零 token, 纯本地 SQL + math + itertools.

核心价值函数 v(S):
  输入 S = 中心子集 (协作方)
  输出 = 历史上 S 组合交付任务的平均成功分 (DONE/DELIVERED 的质量)
  无历史 → 单中心基础分 × 协作增效 α = 1.1^( |S|-1 )

Shapley Value:
  φ_i = Σ_{S⊆N\{i}} [ |S|! (n-|S|-1)! / n! ] × [ v(S∪{i}) - v(S) ]

边际贡献:
  MC(i|S) = v(S∪{i}) - v(S)   (在 S 组合下 i 的增量)
  avg_MC(i) = 所有 S 上的平均边际贡献

博弈论 (协同博弈 N, v):
  - 核 (Core): 无 coalition 能单独获益, 判定是否存在核
  - 纳什均衡: 中心之间协作策略的均衡点
  - 占优策略: 某些中心的协作/单干占优

落库: mt_game_theory_scores
  (center_id, center_name, shapley_value, avg_marginal, 
   solo_score, top_coalition, n_coalitions, n_delivered, 
   core_member, nash_mix, calculated_at)
"""
import sqlite3, math, os, sys, json, time
from datetime import datetime
from itertools import combinations
from collections import defaultdict

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(APP_DIR, "database", "app.db")

# 协作增效: 每多一个协作方, 交付质量 × α (调保守让博弈有张力)
_COLLAB_ALPHA = 1.03


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=15); c.row_factory = sqlite3.Row
    return c


def ensure_tables() -> None:
    c = _db()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS mt_game_theory_scores (
            center_id       INTEGER PRIMARY KEY,
            center_name     TEXT NOT NULL,
            shapley_value   REAL DEFAULT 0,
            avg_marginal    REAL DEFAULT 0,
            solo_score      REAL DEFAULT 0,
            top_coalition   TEXT,
            n_coalitions    INTEGER DEFAULT 0,
            n_delivered     INTEGER DEFAULT 0,
            core_member     INTEGER DEFAULT 0,
            nash_mix        TEXT,
            calculated_at   REAL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS mt_game_theory_coalitions (
            coalition_hash  TEXT PRIMARY KEY,
            members         TEXT NOT NULL,     -- "1,4,106"
            member_names    TEXT,              -- JSON array
            n_delivered     INTEGER DEFAULT 0,
            total_score     REAL DEFAULT 0,
            v_value         REAL DEFAULT 0,    -- 价值函数 v(S)
            marginal_list   TEXT,              -- JSON: {center_id: MC}
            calculated_at   REAL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_gts_shapley ON mt_game_theory_scores(shapley_value DESC)")
        c.commit()
    finally:
        c.close()


# ────────────────────────────────────────────────────────────────────
# Step 1: 构建价值函数 v(S) = 中心子集 S 的历史交付质量
# ────────────────────────────────────────────────────────────────────

def _center_set() -> list[tuple[int, str]]:
    """返回参与博弈的中心列表 [(id, name), ...]"""
    c = _db()
    try:
        rows = c.execute("""SELECT id, name FROM mt_lab_centers
                             WHERE status = 'ACTIVE'
                             ORDER BY id""").fetchall()
        return [(r['id'], r['name']) for r in rows]
    finally:
        c.close()


def _build_coalition_history() -> dict[tuple[int, ...], tuple[int, float]]:
    """从 DONE/DELIVERED 任务提取协作组合 → (交付数, 累计分)"""
    c = _db()
    try:
        rows = c.execute("""
            SELECT h.id, h.center_id, h.status
            FROM mt_lab_task_hall h
            WHERE h.status IN ('DONE','DELIVERED','UNDER_REVIEW')
              AND h.center_id IS NOT NULL
            ORDER BY h.id DESC LIMIT 500
        """).fetchall()
    finally:
        c.close()

    # 先收集有效中心 id 集合 (过滤字符串 code)
    valid_ids = {cid for cid, _ in _center_set()}

    hist: dict[tuple[int, ...], list[tuple[int, str]]] = defaultdict(list)
    for r in rows:
        cid = r['center_id']
        if not isinstance(cid, int) or cid not in valid_ids:
            continue  # 跳过字符串 code 脏数据
        hist[(cid,)].append((r['id'], r['status']))

    # 从 mt_proposal_intel 提取"参与中心"字段 (如果存在)
    c = _db()
    try:
        cols = {row[1] for row in c.execute("PRAGMA table_info(mt_proposal_intel)").fetchall()}
        for joined in ('collab_centers', 'participating_centers'):
            if joined not in cols:
                continue
            for row in c.execute(f"SELECT task_id, {joined} FROM mt_proposal_intel WHERE {joined} IS NOT NULL LIMIT 300").fetchall():
                raw = row[joined]
                try:
                    ids = tuple(sorted({int(x.strip()) for x in str(raw).split(',') if x.strip().isdigit() and int(x.strip()) in valid_ids}))
                    task_row = _db().execute("SELECT center_id FROM mt_lab_task_hall WHERE id=?", (row['task_id'],)).fetchone()
                    if task_row and task_row['center_id'] in valid_ids:
                        full = tuple(sorted(set(ids + (task_row['center_id'],))))
                        if len(full) >= 2:
                            hist[full].append((row['task_id'], 'DONE'))
                except (ValueError, AttributeError):
                    continue
    finally:
        c.close()

    # 汇总 → (交付数, 平均分)
    result: dict[tuple[int, ...], tuple[int, float]] = {}
    for combo, items in hist.items():
        n = len(items)
        # 交付分 = 主中心交付历史质量 (这里简化: 每个 DONE 记 10 分)
        total = 10.0 * n
        result[combo] = (n, total / max(1, n))
    return result


def _solo_score(center_id: int, history: dict) -> float:
    """单中心交付质量分 — 有区分度: 历史交付数归一 + 基础分"""
    key = (center_id,)
    if key in history:
        ncnt = history[key][0]
        return min(10.0, 2.0 + ncnt * 0.15)  # 交付数→分: 2分基础 + 0.15/单, 封顶10
    # 无历史 → 基础分 3.0 (让无经验中心的 MC 更显著)
    return 3.0


def v(S: tuple[int, ...], history: dict) -> float:
    """价值函数: 中心子集 S 的协作价值
    v(S) = Σ 单中心分 × 协作增效 α^( |S|-1 )
       + 历史实际交付贡献 (有历史时优先用)"""
    if len(S) == 0:
        return 0.0
    S = tuple(sorted(S))
    n = len(S)

    # 历史协作数据: 精确匹配或子集匹配
    exact = history.get(S)
    if exact and exact[0] > 0:
        # 有历史交付 → 用实际分 + 协作增效奖励
        base_avg = exact[1]
        bonus = _COLLAB_ALPHA ** (n - 1)
        return base_avg * bonus

    # 子集匹配: 找所有包含于 S 的协作, 取最高分
    best_subset = 0.0
    for combo, (cnt, avg) in history.items():
        if set(combo).issubset(set(S)) and len(combo) >= 1:
            val = avg * (_COLLAB_ALPHA ** (len(combo) - 1))
            best_subset = max(best_subset, val)

    # 单中心基础分
    solo_sum = sum(_solo_score(c, history) for c in S)

    # 综合: 子集匹配 (如果有) × 增效, 否则 solo_sum × 增效
    if best_subset > 0:
        return max(solo_sum, best_subset * (_COLLAB_ALPHA ** (n - 1)))

    return solo_sum * (_COLLAB_ALPHA ** (n - 1))


# ────────────────────────────────────────────────────────────────────
# Step 2: Shapley Value 计算
# ────────────────────────────────────────────────────────────────────

def shapley_value(i: int, all_centers: list[int], history: dict) -> float:
    """夏普里值 φ_i = Σ [ |S|!(n-|S|-1)!/n! ] × [ v(S∪{i}) - v(S) ]"""
    n = len(all_centers)
    others = [c for c in all_centers if c != i]
    total = 0.0
    for r in range(len(others) + 1):
        for S in combinations(others, r):
            coeff = math.factorial(r) * math.factorial(n - r - 1) / math.factorial(n)
            v_without = v(S, history)
            v_with = v(tuple(sorted(S + (i,))), history)
            marginal = v_with - v_without
            total += coeff * marginal
    return total


def avg_marginal(i: int, all_centers: list[int], history: dict) -> float:
    """平均边际贡献: 所有可能 S⊆N\\{i} 上的平均 MC(i|S)"""
    others = [c for c in all_centers if c != i]
    mc_sum = 0.0; count = 0
    for r in range(len(others) + 1):
        for S in combinations(others, r):
            v_without = v(S, history)
            v_with = v(tuple(sorted(S + (i,))), history)
            mc_sum += (v_with - v_without); count += 1
    return mc_sum / max(1, count)


# ────────────────────────────────────────────────────────────────────
# Step 3: 博弈论 — 核 (Core) 与纳什均衡
# ────────────────────────────────────────────────────────────────────

def check_core(all_centers: list[int], history: dict, shapley_map: dict) -> dict:
    """核 (Core) 判定: 是否存在 coalition 能获得 > Σ_{i∈S} φ_i?
    如果 ∀S ⊆ N, v(S) ≥ Σ_{i∈S} φ_i → 核非空 (当前支付在核内)"""
    n = len(all_centers)
    core_blocking = []  # 阻塞联盟: v(S) < Σφ_i, 即该联盟可通过集体获得更多
    for r in range(1, n + 1):
        for S in combinations(all_centers, r):
            vS = v(S, history)
            phi_sum = sum(shapley_map.get(i, 0) for i in S)
            if vS > phi_sum * 1.001:  # 允许 0.1% 浮点误差
                core_blocking.append({"coalition": list(S), "v_S": vS, "phi_sum": phi_sum})

    # 核心成员: 在核判定中从未出现在阻塞联盟的中心
    blocked_ids = set()
    for b in core_blocking:
        blocked_ids.update(b["coalition"])
    core_members = [i for i in all_centers if i not in blocked_ids]

    return {
        "core_non_empty": len(core_blocking) == 0,
        "blocking_count": len(core_blocking),
        "core_member_ids": core_members,
        "top_blocking": sorted(core_blocking, key=lambda x: -x["v_S"] + x["phi_sum"])[:3],
    }


def nash_equilibrium_mix(all_centers: list[int], history: dict) -> dict[int, float]:
    """中心之间协作策略的混合纳什均衡 (简化版)
    每个中心有两种纯策略: {solo, collab}
    收益矩阵: 
      协作收益 = Σ_{S包含i} MC(i|S) × 出现概率
      单干收益 = v((i,))
    用简单迭代求均衡: 初始均匀分布 → 每次对其他中心的平均策略求最优响应"""
    n = len(all_centers)
    # 初始混合策略: 均匀
    mix = {i: 0.5 for i in all_centers}  # 50% 概率协作

    # 迭代 30 轮 (收敛很快)
    for _ in range(30):
        new_mix = {}
        for i in all_centers:
            # 算协作 vs 单干的期望收益
            collab_payoff = 0.0; solo_payoff = v((i,), history)
            others = [c for c in all_centers if c != i]
            for r in range(1, len(others) + 1):
                for S in combinations(others, r):
                    # 其他中心正好以概率 mix 参与这个组合
                    prob = 1.0
                    for c in others:
                        prob *= mix[c] if c in S else (1 - mix[c])
                    v_before = v(S, history)
                    v_after = v(tuple(sorted(S + (i,))), history)
                    collab_payoff += (v_after - v_before) * prob

            # 最优响应: 收益高的策略占更大权重
            if collab_payoff > solo_payoff:
                new_mix[i] = min(1.0, mix[i] + 0.05)
            elif collab_payoff < solo_payoff:
                new_mix[i] = max(0.0, mix[i] - 0.05)
            else:
                new_mix[i] = mix[i] * 0.9  # 无差异 → 趋近 0
        mix = new_mix

    # 归一化到 [0, 1]
    return {i: round(p, 3) for i, p in mix.items()}


# ────────────────────────────────────────────────────────────────────
# Step 4: 找每个中心的最佳协作组合 (top_coalition)
# ────────────────────────────────────────────────────────────────────

def best_coalition_for(i: int, all_centers: list[int], history: dict, top_k: int = 3) -> list[dict]:
    """对每个中心 i, 找能让 v(S∪{i}) - v(S) 最大的前 k 个 S"""
    others = [c for c in all_centers if c != i]
    pairs: list[tuple[float, tuple[int, ...]]] = []
    for r in range(min(len(others), 5) + 1):  # 最多 5 人协作
        for S in combinations(others, r):
            v_mc = v(tuple(sorted(S + (i,))), history) - v(S, history)
            pairs.append((v_mc, tuple(sorted(S + (i,)))))
    pairs.sort(reverse=True)
    results = []
    for score, combo in pairs[:top_k]:
        results.append({"members": list(combo), "marginal": round(score, 3), "v_S": round(v(combo, history), 3)})
    return results


# ────────────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────────────

def compute_all() -> dict:
    """完整博弈论计算 + 落库"""
    t0 = time.time()
    ensure_tables()

    centers = _center_set()
    if len(centers) < 2:
        return {"ok": True, "reason": "中心数不足 2", "n_centers": len(centers)}

    center_ids = [cid for cid, _ in centers]
    id_name = {cid: cname for cid, cname in centers}
    history = _build_coalition_history()
    n = len(center_ids)

    # Step 1: 单中心基础分
    solo_map = {cid: _solo_score(cid, history) for cid in center_ids}

    # ★ 预计算 v(S): v(S) = Σ solo_score + 协作奖励 (√边际递减)
    COLLAB_BONUS = 1.5  # 每多一个协作方固定奖励
    print(f"  预计算 v(S): 2^{n} = {2**n} 个子集...", flush=True)
    v_cache: dict[frozenset[int], float] = {}
    v_cache[frozenset()] = 0.0
    hist_fz = {frozenset(k): v for k, v in history.items()}
    for r in range(1, n + 1):
        for combo in combinations(center_ids, r):
            key = frozenset(combo)
            exact = hist_fz.get(key)
            if exact and exact[0] > 0:
                v_cache[key] = exact[1] + COLLAB_BONUS * (r - 1) ** 0.5
            else:
                solo_sum = sum(solo_map[c] for c in combo)
                max_exp = max(0.0, *(history.get((c,), (0, 0))[0] for c in combo))
                bonus = COLLAB_BONUS * (r - 1) ** 0.5 * (1 + 0.03 * min(max_exp, 20))
                v_cache[key] = solo_sum + bonus

    # 覆盖旧的 v 函数用缓存
    def _v_cached(S_tuple):
        return v_cache.get(frozenset(S_tuple), 0.0)

    # Step 2: Shapley Value (采样 nash 用 O(n!) 不可行, 用 3000 随机 permutation)
    import random; random.seed(42)
    N_SAMPLES = 3000
    shapley_map = {cid: 0.0 for cid in center_ids}
    avg_mc_map = {cid: 0.0 for cid in center_ids}
    for _ in range(N_SAMPLES):
        pi = random.sample(center_ids, n)
        prefix_set = set()
        prefix_v = 0.0
        for i in pi:
            # MC: v(prefix ∪ {i}) - v(prefix)
            cur_v = _v_cached(tuple(sorted(prefix_set | {i})))
            mc = cur_v - prefix_v
            shapley_map[i] += mc / N_SAMPLES
            avg_mc_map[i] += mc / N_SAMPLES
            prefix_set.add(i)
            prefix_v = cur_v

    # Step 3: 博弈论 — 核判定 (子集数 O(2^n), 但 n=16 可接受, 每个子集查 cache O(1))
    core_blocking = []
    for r in range(1, n + 1):
        for combo in combinations(center_ids, r):
            key = frozenset(combo)
            vS = v_cache.get(key, 0.0)
            phi_sum = sum(shapley_map.get(i, 0) for i in combo)
            if vS > phi_sum * 1.001:
                core_blocking.append({"coalition": list(combo), "v_S": vS, "phi_sum": phi_sum})
    blocked_ids = set()
    for b in core_blocking:
        blocked_ids.update(b["coalition"])
    core_members = [i for i in center_ids if i not in blocked_ids]
    core_info = {"core_non_empty": len(core_blocking) == 0,
                 "blocking_count": len(core_blocking),
                 "core_member_ids": core_members,
                 "top_blocking": sorted(core_blocking, key=lambda x: -x["v_S"] + x["phi_sum"])[:3]}

    # Step 4: 混合纳什均衡
    mix = {i: 0.5 for i in center_ids}
    for _ in range(25):
        new_mix = {}
        for i in center_ids:
            collab_payoff = 0.0; solo_payoff = solo_map[i]
            others = [c for c in center_ids if c != i]
            for r in range(len(others) + 1):
                for S in combinations(others, r):
                    prob = 1.0
                    for c in others:
                        prob *= mix[c] if c in S else (1 - mix[c])
                    v_before = v_cache.get(frozenset(S), 0.0)
                    v_after = v_cache.get(frozenset(S + (i,)), 0.0)
                    collab_payoff += (v_after - v_before) * prob
            if collab_payoff > solo_payoff * 1.02:
                new_mix[i] = min(1.0, mix[i] + 0.05)
            elif collab_payoff < solo_payoff * 0.98:
                new_mix[i] = max(0.0, mix[i] - 0.05)
            else:
                new_mix[i] = mix[i] * 0.95 if mix[i] > 0.05 else 0.0
        mix = new_mix
    nash_mix = {i: round(p, 3) for i, p in mix.items()}

    # Step 4: top_coalition
    top_coalitions = {cid: best_coalition_for(cid, center_ids, history, top_k=1)[0] for cid in center_ids}

    # Step 5: 落库
    now_ts = time.time()
    c = _db()
    try:
        for cid, cname in centers:
            tc = top_coalitions[cid]
            c.execute("""INSERT OR REPLACE INTO mt_game_theory_scores
                (center_id, center_name, shapley_value, avg_marginal, solo_score,
                 top_coalition, n_coalitions, core_member, nash_mix, calculated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (cid, cname,
                 round(shapley_map[cid], 4),
                 round(avg_mc_map[cid], 4),
                 round(solo_map[cid], 4),
                 json.dumps(tc, ensure_ascii=False),
                 len(history),
                 1 if cid in core_info["core_member_ids"] else 0,
                 json.dumps({cid: round(nash_mix[cid], 3)}, ensure_ascii=False),
                 now_ts))
        c.commit()
    finally:
        c.close()

    # 落库 coalition 粒度数据
    c = _db()
    try:
        for combo, (ncnt, avg) in history.items():
            chash = ",".join(map(str, sorted(combo)))
            vS = v(combo, history)
            marginal = {cid: round(v(tuple(sorted(set(combo) - {cid})), history) - v(combo, history), 3) for cid in combo}
            c.execute("""INSERT OR REPLACE INTO mt_game_theory_coalitions
                (coalition_hash, members, member_names, n_delivered, total_score,
                 v_value, marginal_list, calculated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (chash, chash,
                 json.dumps([id_name[c] for c in sorted(combo)], ensure_ascii=False),
                 ncnt, round(avg * ncnt, 2),
                 round(vS, 3), json.dumps(marginal, ensure_ascii=False), now_ts))
        c.commit()
    finally:
        c.close()

    elapsed = time.time() - t0
    # 排序输出 Top 5
    ranked = sorted(shapley_map.items(), key=lambda x: -x[1])
    return {
        "ok": True,
        "elapsed_ms": round(elapsed * 1000),
        "n_centers": n,
        "n_coalitions": len(history),
        "top5_shapley": [{"center_id": cid, "center_name": id_name[cid],
                          "shapley": round(sv, 4), "avg_marginal": round(avg_mc_map[cid], 4),
                          "core_member": cid in core_info["core_member_ids"]}
                         for cid, sv in ranked[:5]],
        "core_non_empty": core_info["core_non_empty"],
        "core_members": [id_name[cid] for cid in core_info["core_member_ids"]],
        "top_blocking": core_info["top_blocking"],
        "nash_mix": {id_name[cid]: round(nash_mix[cid], 3) for cid in center_ids},
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="🎲 大厅协作博弈论评估引擎")
    ap.add_argument("action", nargs="?", default="compute",
                    choices=["install", "compute", "once", "preview"])
    args = ap.parse_args()
    if args.action == "install":
        ensure_tables(); print("✅ mt_game_theory_scores + mt_game_theory_coalitions")
    elif args.action == "compute":
        print(json.dumps(compute_all(), ensure_ascii=False, indent=2))
    elif args.action == "preview":
        c = sqlite3.connect(DB_PATH, timeout=5); c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM mt_game_theory_scores ORDER BY shapley_value DESC LIMIT 10").fetchall()
        for r in rows: print(dict(r))
        c.close()
