---
name: "industry-split"
description: "行业人员多维细分 — group_tag 划拨 + ALTER TABLE 加列 + 硬/软规则 + hash 补满 + 交叉验证。Invoke when 用户要求给某行业（教育/污染治理/金融等）AI 人员按赛道/年级/职称/荣誉等维度细分。"
---

# 行业人员多维细分 (Industry Split)

给 ai_employees 表中某行业（由 group_tag 标识）的 AI 人员做多维度标签分配。

## 触发条件

用户说：
- "划一部分人到 XX 行业" / "给 XX 行业按 YY 区分"
- "XX 领域 AI 人员细分按 YY/ZZ/WW 区分"
- 任何要求给现有 AI 员工打 group_tag 或新增维度列的请求

## 执行流程 (7 步)

```
┌─ 1. 审计 ─────────────────────────────────┐
│ 查 ai_employees schema + group_tag 现状     │
│ 查现有 domain 分布 (employee_code 前缀)    │
│ 查 mini Flask 状态 (health 接口)            │
└─────────────────────────────────────────────┘
         │
         ▼
┌─ 2. 停 Flask ────────────────────────────┐
│ pkill -9 -f 'modular_start.*5001'          │
│ sleep 3 → pgrep 确认 down                  │
│ 原因: ALTER TABLE + 大批量 UPDATE 需独占   │
└─────────────────────────────────────────────┘
         │
         ▼
┌─ 3. ALTER TABLE ADD COLUMN ─────────────┐
│ 逐个检查列是否已存在 (PRAGMA table_info)   │
│ 不存在才 ADD, 已存在则清空重分配            │
│ 示例新列: grade / gender / track / title   │
│          career_status / honor_title /     │
│          admin_role                        │
└─────────────────────────────────────────────┘
         │
         ▼
┌─ 4. 硬规则分配 ──────────────────────────┐
│ 按已有列精确匹配 (grade IN / skill_level=) │
│ 例: grade IN ('大学','研究生') → 高等教学  │
│ 例: skill_level=4 → 退休 hash 15%          │
└─────────────────────────────────────────────┘
         │
         ▼
┌─ 5. 软规则分配 ──────────────────────────┐
│ 按 employee_code LIKE 前缀匹配 domain       │
│ 例: FIN_* → 商务教学                        │
│ 例: MED_TCM / MED_INTERNAL → 老年教学       │
└─────────────────────────────────────────────┘
         │
         ▼
┌─ 6. 剩余 hash 均匀分配 ──────────────────┐
│ WHERE track='' OR track IS NULL             │
│ md5(employee_code).hexdigest() → int        │
│ 取模分桶: h % N → 桶索引                    │
│ 可加权: grade 在小学/初中 → K12 权重高      │
└─────────────────────────────────────────────┘
         │
         ▼
┌─ 7. 交叉验证 + 重启 ─────────────────────┐
│ GROUP BY 全维度交叉统计                     │
│ 合规规则检查 (如 院士必须来自教授)          │
│ SQLite 0 空值检查                           │
│ 重启 Flask → health 200 确认                │
└─────────────────────────────────────────────┘
```

## 关键约束

### 1. DB 连接配置 (每次执行)
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")
```

### 2. 停 Flask 不可跳过
- ALTER TABLE 在 Flask daemon 运行时会 `database is locked`
- 批量 UPDATE (3000+ 行) WAL 下也可能 lock
- 必须 `pkill -9` + 等待 3s

### 3. 确定性 hash (而非随机)
```python
h = int(hashlib.md5(code.encode()).hexdigest(), 16)
bucket = h % N          # 均匀分桶
bucket = (h >> bits) % N  # 位移避免同 hash 多列关联
```
- 可复现：同一人每次分到同一桶
- 均匀性：MD5 分布 ≈ 均匀

### 4. group_tag 空守卫 (避免覆盖)
```sql
WHERE group_tag='教育' AND (grade='' OR grade IS NULL)
```

### 5. 合规规则必须写死检查
每次细分后必须验证：
- 荣誉头衔来源 (院士 ← 教授)
- 行政角色赛道 (班导 ← K12/幼教)
- 退休级别 (退休 ← skill_level=4)
- 进阶级别 (进阶 ← skill_level≤2)

## 可加维度模板

| 维度名 | 列名 | 值域 | 分配策略 |
|---|---|---|---|
| 赛道 | track | 幼教/K12/高等/商务/老年/再教育/成人 | 硬规则(grade)+软规则(domain)+hash |
| 年级 | grade | 小学1-6/初中7-9/高中10-12/大学/研究生 | grade 已有 → 或 hash 分 14 桶 |
| 性别 | gender | 男/女 | hash 2 桶 (≈50/50) |
| 级别 | skill_level | 1-4 (初级/中级/高级/特级) | 原地 UPDATE 1-4 (hash 4 桶) |
| 职称 | title | 二级/一级/高级/特级教师 + 助教/讲师/副教授/教授 | K12 vs 高等 分段映射 |
| 荣誉 | honor_title | 院士/博导/硕导/none | 从高职称 hash 精选 |
| 行政 | admin_role | 班主任/班导/none | 从 K12/幼教 hash 30% |
| 状态 | career_status | 在职/进阶中/退休 | 高级别→退休 15%, 低级别→进阶 20% |

## 脚本模板

```python
#!/usr/bin/env python3
"""行业细分脚本 — 由 industry-split skill 生成"""
import sqlite3, hashlib, os

DB_PATH = os.path.expanduser("~/MTSCOS_AI_Project/flask-app/database/app.db")
INDUSTRY_TAG = "教育"  # ← 改这里
NEW_COLS = [
    # (col, dtype, default)
    ("grade", "TEXT", "''"),
]  # ← 改这里

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")

# Step 1: ALTER TABLE
cols_exist = [r[1] for r in conn.execute("PRAGMA table_info(ai_employees)").fetchall()]
for col, dtype, default in NEW_COLS:
    if col in cols_exist:
        conn.execute(f"UPDATE ai_employees SET {col}={default} WHERE group_tag=?", (INDUSTRY_TAG,))
    else:
        conn.execute(f"ALTER TABLE ai_employees ADD COLUMN {col} {dtype} DEFAULT {default}")
conn.commit()

# Step 2: 硬规则 / 软规则 / hash (按需求写)
# ...

# Step 3: 交叉验证
rows = conn.execute("SELECT X, COUNT(*) FROM ai_employees WHERE group_tag=? GROUP BY X", (INDUSTRY_TAG,)).fetchall()
total = sum(r[1] for r in rows)
for r in rows:
    print(f"  {r[0]:<12s} {r[1]:>4}  {r[1]*100//total:>3}%")

conn.close()
```

## mini 部署命令

```bash
# 停 Flask
ssh MINI "pkill -9 -f 'modular_start.*5001'; sleep 3"
# 执行
ssh MINI "python3 /tmp/xxx.py"
# 重启
ssh MINI "export NODE_ROLE=SERVER OLLAMA_HOST=http://127.0.0.1:11434 OLLAMA_MODEL=qwen2.5:14b && cd ~/MTSCOS_AI_Project/flask-app && nohup python3 -u modular_start.py --port=5001 >/tmp/flask.log 2>&1 & disown"
# 验证
curl -s -o /dev/null -w '%{http_code}' http://MINI:5001/health
```

## 历史应用记录 (本会话)

| # | 行业 | 维度 | 人数 | 核心规则 |
|---|---|---|---|---|
| 1 | 教育 | group_tag 划拨 | 3,853 | SCI_*/MED_*/LAW_* 等 domain 前缀 |
| 2 | 污染治理 | group_tag 划拨 | 1,960 | SEC_*/QA_*/POLICE/CLEANER 等 |
| 3 | 教育 | grade/gender/title/skill_level | 3,853 | hash 14+2+4+4 桶, 职称分段映射 |
| 4 | 教育 | track (7赛道) | 3,853 | grade 硬规则 + domain 软规则 + hash 5桶 |
| 5 | 教育 | career_status/honor_title/admin_role | 3,853 | 院士←教授, 博导←教授+副教授, 班导←K12 |
