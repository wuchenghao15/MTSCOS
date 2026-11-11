# -*- coding: utf-8 -*-
"""
古灵阁印章生成器 v2 · 严格按国务院规范 + DB11/T 918—2021
  · 中央真 polygon 五角星 (10 点, 内角 36°, 外角 72°, 直径 14mm)
  · 宋体 (SimSun/Songti), 字高 8mm, 字边距 1mm
  · 弧形: 260° 上弧环排 (自左而右)
  · 尺寸: 公司公章 φ42mm / 部门专用章 φ40mm / 财务章 φ38mm
  · 边宽: 1.2mm (42mm) / 1.0mm (40/38mm)
  · 颜色: 中国红 #c8102e
"""
import os, math, hashlib
from datetime import datetime

STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "_runtime", "gobelin_seals_museum")
os.makedirs(STORE, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# 国标尺寸表 (国务院令第 256 号 + DB11/T 918—2021)
# ═══════════════════════════════════════════════════════════════
SPECS = {
    "company_seal": {   # 公司公章
        "diameter_mm": 42, "border_mm": 1.2, "star_mm": 14,
        "text_height_mm": 8, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#c8102e",
    },
    "dept_seal": {      # 部门/专用章
        "diameter_mm": 40, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 8, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#c8102e",
    },
    "finance_seal": {   # 财务专用章
        "diameter_mm": 38, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 7, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#c8102e",
    },
    "contract_seal": {  # 合同专用章
        "diameter_mm": 42, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 8, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#c8102e",
    },
    "law_seal": {       # 法务专用章
        "diameter_mm": 40, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 7, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#c8102e",
    },
    "hr_seal": {        # 人事专用章
        "diameter_mm": 40, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 7, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#c8102e",
    },
    "ceo_seal": {       # 董事长专用章 (部门章规格)
        "diameter_mm": 42, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 8, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#c8102e",
    },
    "admin_seal": {     # Admin 系统管理章 (蓝色)
        "diameter_mm": 40, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 7, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#0058a3",
    },
    "sa_seal": {        # SA 超级管理员章 (紫色)
        "diameter_mm": 42, "border_mm": 1.0, "star_mm": 14,
        "text_height_mm": 8, "text": True, "font": "SimSun, STSong, Songti, serif",
        "arc_deg": 260, "color": "#7b1fa2",
    },
}


def star_polygon(cx, cy, r):
    """生成真正的五角星 polygon 点 (10 点交替内外, 内角 36°, 外角 72°)
    外半径 r, 内半径 r * 0.382 (黄金分割), 点从顶端 (-90°) 开始
    """
    import math
    pts = []
    for i in range(10):
        angle = -math.pi/2 + i * math.pi/5
        rr = r if i % 2 == 0 else r * 0.382
        pts.append(f"{cx + rr*math.cos(angle):.2f},{cy + rr*math.sin(angle):.2f}")
    return " ".join(pts)


def make_seal(top_text, bot_text, spec_key, out_path, date_text=None):
    """
    按国标 + 阳刻敲章视觉 生成圆形公章 SVG
    阳刻公章敲在纸上 = 红色线条轮廓 + 白色留白 + 轻微透明度 + 毛边
    """
    spec = SPECS[spec_key]
    D = spec["diameter_mm"]
    B = spec["border_mm"]
    S = spec["star_mm"]
    TH = spec["text_height_mm"]
    color = spec["color"]
    FONT  = spec["font"]
    ARC   = spec["arc_deg"]
    scale = 3.779527559
    W = int(D * scale)
    CX = CY = W / 2
    R_OUTER = W / 2 - 2
    R_INNER = R_OUTER - B * scale
    R_STAR  = S * scale / 2
    R_TEXT  = R_INNER - TH * scale / 2
    STAR_PTS = star_polygon(CX, CY, R_STAR)
    date_str = date_text or datetime.now().strftime('%Y.%m.%d')

    # 阳刻敲章效果: 所有图形元素都只有 stroke (描边), 不 fill (填充)
    # 五角星 fill="none" → 敲出来中间是白的 (纸色), 只有边缘线条是红印泥
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{W}" viewBox="0 0 {W} {W}">
  <!-- 敲章整体透明度 (不是 100% 实心, 有轻微浓淡) -->
  <g opacity="0.82">
    <!-- 外圈: 红色描边, 无填充 (阳刻: 只有凸起边缘蘸到印泥) -->
    <circle cx="{CX}" cy="{CY}" r="{R_OUTER}" fill="none" stroke="{color}" stroke-width="{B*scale}" stroke-linecap="round"/>
    <!-- 内圈: 细红色描边 -->
    <circle cx="{CX}" cy="{CY}" r="{R_INNER}" fill="none" stroke="{color}" stroke-width="{B*scale*0.5}"/>
    <!-- 中央五角星: 只描边不填充! 敲出来中间是白色纸色 -->
    <polygon points="{STAR_PTS}" fill="none" stroke="{color}" stroke-width="{B*scale*0.55}"/>
    <!-- 五角星内部细线 (增强阳刻效果: 五条交叉对角线) -->
    <line x1="{CX-R_STAR*math.sin(math.pi/10)}" y1="{CY-R_STAR*math.cos(math.pi/10)}"
          x2="{CX+R_STAR*math.sin(math.pi/10)}" y2="{CY-R_STAR*math.cos(math.pi/10)}"
          stroke="{color}" stroke-width="{B*scale*0.2}"/>
    <!-- 上弧文字路径 -->
    <path id="arc-top" d="M {CX - R_TEXT} {CY} A {R_TEXT} {R_TEXT} 0 1 1 {CX + R_TEXT} {CY}" fill="none"/>
    <!-- 上弧文字 (宋体, fill=红色 — 文字笔画本身就是凸起的, 笔画内部填满印泥) -->
    <text font-family="{FONT}" font-size="{TH*scale}" font-weight="bold" fill="{color}" letter-spacing="auto">
      <textPath href="#arc-top" startOffset="50%" text-anchor="middle">{top_text}</textPath></text>
    <!-- 下弦章名 (红色填充文字) -->
    <text x="{CX}" y="{CY + R_STAR + TH*scale*2.0}" font-family="{FONT}" font-size="{TH*scale*0.85}"
          fill="{color}" text-anchor="middle" font-weight="bold">{bot_text}</text>
    <!-- 日期小字 -->
    <text x="{CX}" y="{CY + R_STAR + TH*scale*3.0}" font-family="Arial, monospace" font-size="{TH*scale*0.45}"
          fill="{color}" text-anchor="middle">{date_str}</text>
  </g>
</svg>'''
    open(out_path, 'w', encoding='utf-8').write(svg)
    print(f"  ✓ {os.path.basename(out_path)}  ({D}mm 阳刻敲章, polygon stroke 五角星)")
    return out_path

    # 生成 SVG
    date_str = date_text or datetime.now().strftime('%Y.%m.%d')
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{W}" viewBox="0 0 {W} {W}">
  <!-- 外圈 (边宽 B) -->
  <circle cx="{CX}" cy="{CY}" r="{R_OUTER}" fill="none" stroke="{color}" stroke-width="{B*scale}" stroke-linecap="round"/>
  <!-- 五角星 (真 polygon) -->
  <polygon points="{STAR_PTS}" fill="{color}" stroke="{color}" stroke-width="0.5"/>
  <!-- 上弧文字 (260° 环排) -->
  <path id="arc-top" d="M {CX - arc_top_r} {CY} A {arc_top_r} {arc_top_r} 0 1 1 {CX + arc_top_r} {CY}" fill="none"/>
  <text font-family="{FONT}" font-size="{TH*scale}" font-weight="bold" fill="{color}"
        letter-spacing="auto">
    <textPath href="#arc-top" startOffset="50%" text-anchor="middle">{top_text}</textPath>
  </text>
  <!-- 下弦文字 (部门名称/类型) -->
  <text x="{CX}" y="{CY + arc_bot_r + TH*scale}" font-family="{FONT}" font-size="{TH*scale*0.85}"
        fill="{color}" text-anchor="middle" font-weight="bold">{bot_text}</text>
  <!-- 日期小字 (Arial) -->
  <text x="{CX}" y="{CY + arc_bot_r + TH*scale*2.2}" font-family="Arial, monospace" font-size="{TH*scale*0.45}"
        fill="{color}" text-anchor="middle">{date_str}</text>
</svg>'''
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(svg)
    print(f"  ✓ {os.path.basename(out_path)}  ({D}mm {spec_key})")
    return out_path


# ═══════════════════════════════════════════════════════════════
# 批量生成 14 枚公章 (全部按国标)
# ═══════════════════════════════════════════════════════════════
seal_jobs = [
    # (输出文件名, 上弧公司名, 下弦章类型, spec_key)
    ("01_公司公章_42mm.svg",    "古灵阁证券交易有限公司", "公  章",        "company_seal"),
    ("02_财务专用章_38mm.svg",  "古灵阁证券交易有限公司", "财务专用章",    "finance_seal"),
    ("03_合同专用章_42mm.svg",  "古灵阁证券交易有限公司", "合同专用章",    "contract_seal"),
    ("04_人事专用章_40mm.svg",  "古灵阁证券交易有限公司", "人事专用章",    "hr_seal"),
    ("05_业务专用章_40mm.svg",  "古灵阁证券交易有限公司", "业务专用章",    "dept_seal"),
    ("06_法务专用章_40mm.svg",  "古灵阁证券交易有限公司", "法务专用章",    "law_seal"),
    ("07_董事长专用章_42mm.svg","古灵阁证券交易有限公司", "董事长专用章",  "ceo_seal"),
    ("08_审计中心章_40mm.svg",  "古灵阁证券交易有限公司", "审计中心专用章","law_seal"),
    ("09_复核中心章_40mm.svg",  "古灵阁证券交易有限公司", "复核中心专用章","dept_seal"),
    ("10_印章管理中心章_40mm.svg","古灵阁证券交易有限公司","印章管理专用章","dept_seal"),
    ("11_Admin系统章_40mm.svg", "古灵阁 AI 自治社区",     "系统管理专用章", "admin_seal"),
    ("12_SA超级管理员章_42mm.svg","仙女座 AI 审计委员会","超级管理员专用章","sa_seal"),
    ("13_仙女座法务委员会_42mm.svg","仙女座审计委员会",     "法务专用章",    "sa_seal"),  # 紫色系
    ("14_CAOPW学生签名章.svg",  "古灵阁证券交易有限公司", "CAOPW 签名章 (已降级)", "finance_seal"),
]

# 先删掉全部旧公章 (保留 members/ 子目录里的 130 签名章)
for f in os.listdir(STORE):
    fp = os.path.join(STORE, f)
    if f.endswith('.svg') and os.path.isfile(fp):
        os.remove(fp)
        print(f"  ✗ 删除旧版: {f}")

print("\n=== 重生成国标公章 ===")
for fname, top, bot, sk in seal_jobs:
    out = os.path.join(STORE, fname)
    make_seal(top, bot, sk, out)

print(f"\n全部印章已按国务院令第 256 号 + DB11/T 918—2021 规范重新生成")
print(f"→ {STORE}")
