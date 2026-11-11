#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI员工全量盘点 - 逼近2000人规模"""
import sqlite3, json, os

DB = "/Users/wuchenghao/Library/CloudStorage/OneDrive-个人/文档/MTSCOS_AI_Project/flask-app/app.db"
conn = sqlite3.connect(DB, timeout=30)
c = conn.cursor()

print("=" * 80)
print("AI员工全量盘点（逼近2000人规模统筹规划）")
print("=" * 80)

# 1. 所有AI员工相关表
tables = [
    "mtscos_ai_employees", "ai_employees", "mt_terminal_ai_employees",
    "ai_employee_config", "ai_employee_empowerment", "ai_employee_learning",
    "ai_employee_roles", "ai_employee_capabilities", "ai_employee_certifications",
    "ai_employee_achievements", "ai_employee_growth_tree", "ai_employee_skill_nodes",
    "ai_employee_emotion_log",
]
print("\n【1】全量AI员工表数据统计:")
for t in tables:
    try:
        c.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = c.fetchone()[0]
        print(f"  {t:35s} = {cnt:>6d} rows")
    except Exception as e:
        print(f"  {t:35s} = ERROR: {str(e)[:50]}")

# 2. 去重统计
print("\n【2】去重统计真实员工数:")
c.execute("SELECT COUNT(DISTINCT id) FROM mtscos_ai_employees")
mtscos = c.fetchone()[0]
print(f"  mtscos_ai_employees 去重: {mtscos}")

try:
    c.execute("SELECT COUNT(DISTINCT id) FROM ai_employees")
    ai_emp = c.fetchone()[0]
    print(f"  ai_employees 去重: {ai_emp}")
except:
    ai_emp = 0

try:
    c.execute("SELECT COUNT(DISTINCT id) FROM mt_terminal_ai_employees")
    term = c.fetchone()[0]
    print(f"  mt_terminal_ai_employees 去重: {term}")
except:
    term = 0

grand = mtscos + ai_emp + term
print(f"  >>> 三表合计去重: {grand} (逼近2000人规模)")

# 3. 等级分布
print("\n【3】mtscos_ai_employees 等级分布:")
c.execute("""SELECT
    CASE
        WHEN role LIKE '%L1%' OR role LIKE '%初级%' OR role LIKE '%实习%' OR role LIKE '%助理%' THEN 'L1_初级'
        WHEN role LIKE '%L2%' OR role LIKE '%中级%' THEN 'L2_中级'
        WHEN role LIKE '%L3%' OR role LIKE '%高级%' THEN 'L3_高级'
        WHEN role LIKE '%L4%' OR role LIKE '%资深%' OR role LIKE '%专家%' OR role LIKE '%主管%' THEN 'L4_资深'
        WHEN role LIKE '%L5%' OR role LIKE '%首席%' OR role LIKE '%总监%' OR role LIKE '%负责人%' THEN 'L5_首席'
        ELSE 'L1_初级'
    END as lv, COUNT(*) as cnt
    FROM mtscos_ai_employees GROUP BY lv ORDER BY lv""")
for lv, cnt in c.fetchall():
    print(f"  {lv:12s}: {cnt:>4d}人 ({cnt*100//max(mtscos,1):>3d}%)")

# 4. 按role分布
print("\n【4】按角色分布(TOP20):")
c.execute("SELECT role, COUNT(*) as cnt FROM mtscos_ai_employees GROUP BY role ORDER BY cnt DESC LIMIT 20")
for role, cnt in c.fetchall():
    print(f"  {(role or 'NULL')[:32]:34s}: {cnt:>4d}人")

# 5. 赋能覆盖率
print("\n【5】赋能覆盖率（规则§2.2.3合规）:")
c.execute("""SELECT COUNT(DISTINCT m.id) FROM mtscos_ai_employees m
    INNER JOIN ai_employee_empowerment e ON CAST(m.id AS TEXT)=CAST(e.employee_id AS TEXT)""")
emp = c.fetchone()[0]
c.execute("""SELECT COUNT(DISTINCT m.id) FROM mtscos_ai_employees m
    INNER JOIN ai_employee_config cf ON CAST(m.id AS TEXT)=CAST(cf.employee_id AS TEXT)
    WHERE cf.status='active'""")
cfg = c.fetchone()[0]
c.execute("""SELECT COUNT(DISTINCT m.id) FROM mtscos_ai_employees m
    INNER JOIN ai_employee_learning l ON CAST(m.id AS TEXT)=CAST(l.employee_id AS TEXT)""")
lea = c.fetchone()[0]
print(f"  Personality人格赋能: {emp}/{mtscos} = {emp*100//max(mtscos,1)}%")
print(f"  Config=Active激活  : {cfg}/{mtscos} = {cfg*100//max(mtscos,1)}%")
print(f"  Learning学习引擎   : {lea}/{mtscos} = {lea*100//max(mtscos,1)}%")

# 6. ai_employees表分布
if ai_emp > 0:
    print("\n【6】ai_employees表（历史员工）:")
    c.execute("PRAGMA table_info(ai_employees)")
    cols = [x[1] for x in c.fetchall()]
    print(f"  列: {cols}")
    c.execute("SELECT COUNT(*) FROM ai_employees GROUP BY name HAVING COUNT(*) > 1 LIMIT 5")
    dups = c.fetchall()
    if dups:
        print(f"  发现重复name: {len(dups)}个")

# 7. mt_terminal_ai_employees
if term > 0:
    print(f"\n【7】mt_terminal_ai_employees (终端员工={term}):")
    c.execute("PRAGMA table_info(mt_terminal_ai_employees)")
    cols = [x[1] for x in c.fetchall()]
    print(f"  列: {cols}")

# 8. EigenFlux专家
print("\n【8】EigenFlux专家协作网络:")
c.execute("SELECT COUNT(*) FROM eigenflux_experts")
print(f"  专家总数: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM eigenflux_registrations WHERE registration_status='ACTIVE'")
print(f"  ACTIVE注册: {c.fetchone()[0]}")

# 9. 未覆盖员工（gap分析）
print("\n【9】GAP分析 - 未覆盖赋能的员工:")
c.execute("""SELECT COUNT(*) FROM mtscos_ai_employees m
    WHERE NOT EXISTS (SELECT 1 FROM ai_employee_empowerment e WHERE CAST(m.id AS TEXT)=CAST(e.employee_id AS TEXT))""")
gap_emp = c.fetchone()[0]
c.execute("""SELECT COUNT(*) FROM mtscos_ai_employees m
    WHERE NOT EXISTS (SELECT 1 FROM ai_employee_learning l WHERE CAST(m.id AS TEXT)=CAST(l.employee_id AS TEXT))""")
gap_lea = c.fetchone()[0]
c.execute("""SELECT COUNT(*) FROM mtscos_ai_employees m
    WHERE NOT EXISTS (SELECT 1 FROM ai_employee_config cf WHERE CAST(m.id AS TEXT)=CAST(cf.employee_id AS TEXT) AND cf.status='active')""")
gap_cfg = c.fetchone()[0]
print(f"  缺Personality人格: {gap_emp}人")
print(f"  缺Config=Active  : {gap_cfg}人")
print(f"  缺Learning学习   : {gap_lea}人")

# 10. ai_employees是否有对应的config/empowerment/learning
if ai_emp > 0:
    print("\n【10】ai_employees表(103人历史)与赋能表的关联:")
    c.execute("PRAGMA table_info(ai_employees)")
    cols = [x[1] for x in c.fetchall()]
    # 查找可能的ID列
    id_col = "id"
    for candidate in ["employee_id", "uid", "eid"]:
        if candidate in cols:
            id_col = candidate
            break
    print(f"  ID列: {id_col}")
    c.execute(f"""SELECT COUNT(DISTINCT a.{id_col}) FROM ai_employees a
        INNER JOIN ai_employee_config cf ON CAST(a.{id_col} AS TEXT)=CAST(cf.employee_id AS TEXT)""")
    linked_cfg = c.fetchone()[0]
    print(f"  ai_employees→config关联: {linked_cfg}/{ai_emp}")

# 11. mt_terminal_ai_employees关联
if term > 0:
    print(f"\n【11】mt_terminal_ai_employees({term}人)与赋能表关联:")
    c.execute("PRAGMA table_info(mt_terminal_ai_employees)")
    cols = [x[1] for x in c.fetchall()]
    id_col = "id"
    for candidate in ["employee_id", "uid", "eid"]:
        if candidate in cols:
            id_col = candidate
            break
    print(f"  ID列: {id_col}, 列: {cols}")
    c.execute(f"""SELECT COUNT(DISTINCT t.{id_col}) FROM mt_terminal_ai_employees t
        INNER JOIN ai_employee_config cf ON CAST(t.{id_col} AS TEXT)=CAST(cf.employee_id AS TEXT)""")
    linked = c.fetchone()[0]
    print(f"  terminal→config关联: {linked}/{term}")

conn.close()
print(f"\n>>> 总计需要统筹的AI员工规模: {grand}人 (mtscos={mtscos} + ai_employees={ai_emp} + terminal={term})")
print(">>> 需要：1)合并去重 2)全员赋能覆盖 3)等级体系完善 4)EigenFlux协作 5)2000人规模管理架构")
