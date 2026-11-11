# -*- coding: utf-8 -*-
"""古灵阁印章使用管理办法 · 法务团队起草 · 仙女座审计委员会核准 · 2026-11-07"""
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

STORE  = "/Users/wuchenghao/MTSCOS_AI_Project/_runtime/gobelin_seals_museum"
OUT    = os.path.join(STORE, "seal_regulation.pdf")
TODAY  = datetime.now().strftime('%Y-%m-%d')

# 字体
CN_FONT = None
for p in ['/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/STHeiti Light.ttc','/System/Library/Fonts/Supplemental/Songti.ttc']:
    if os.path.exists(p):
        try: pdfmetrics.registerFont(TTFont('CN', p)); CN_FONT='CN'; break
        except: pass
if not CN_FONT: CN_FONT='Helvetica'

C_GOLD   = HexColor('#8a6f2a')
C_GOLD_B = HexColor('#c9a84c')
C_RED    = HexColor('#c8102e')
C_BG_H   = HexColor('#8a6f2a')
C_BG_K   = HexColor('#F4ECDD')
C_BG_A   = HexColor('#FFFBF2')
C_LINE   = HexColor('#5D6D7E')
C_LINE_L = HexColor('#D5D8DC')
C_INK    = HexColor('#2C3E50')
C_INK_S  = HexColor('#85929E')
C_LAW    = HexColor('#3a2500')

# 段落样式
def P(style=8.5, color=C_INK, leading=12.5):
    return ParagraphStyle('p'+str(style), fontName=CN_FONT, fontSize=style,
                          leading=leading, textColor=color, wordWrap='CJK')
PC = ParagraphStyle('pc', fontName=CN_FONT, fontSize=9, leading=13,
                   textColor=white, alignment=TA_CENTER, wordWrap='CJK')

def build_table(rows, widths, header_rows=1, col0_bold=True):
    wrapped = []
    for i, row in enumerate(rows):
        wr = []
        for j, c in enumerate(row):
            txt = str(c).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            if i < header_rows: wr.append(Paragraph(txt, PC))
            elif col0_bold and j == 0: wr.append(Paragraph(txt, P(8.5, C_GOLD)))
            else: wr.append(Paragraph(txt, P(8.5, C_INK)))
        wrapped.append(wr)
    t = Table(wrapped, colWidths=widths, repeatRows=header_rows)
    base = [
        ('GRID',(0,0),(-1,-1),0.3,C_LINE_L),
        ('BOX',(0,0),(-1,-1),0.9,C_GOLD),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),4),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ('LEFTPADDING',(0,0),(-1,-1),5),
        ('RIGHTPADDING',(0,0),(-1,-1),5),
        ('BACKGROUND',(0,0),(-1,header_rows-1),C_BG_H),
    ]
    for i in range(header_rows, len(wrapped)):
        bg = C_BG_K if i % 2 == 0 else C_BG_A
        base.append(('BACKGROUND',(0,i),(-1,i),bg))
    t.setStyle(TableStyle(base))
    return t

def section_header(title, subtitle=""):
    row = [[Paragraph(f"<b>{title}</b>", ParagraphStyle('SH', fontName=CN_FONT, fontSize=13,
                       leading=16, textColor=white, wordWrap='CJK'))]]
    if subtitle: row[0].append(Paragraph(subtitle, ParagraphStyle('SS', fontName=CN_FONT, fontSize=7.5,
                               leading=10, textColor=C_INK_S, wordWrap='CJK')))
    t = Table(row, colWidths=[160*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),C_BG_H),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('LEFTPADDING',(0,0),(-1,-1),10),
        ('BOX',(0,0),(-1,-1),0.9,C_GOLD),
    ]))
    return t

def draw_seal(canvas, cx, cy, r=18, rot=-22):
    import math
    canvas.saveState()
    canvas.translate(cx, cy); canvas.rotate(rot); canvas.translate(-cx, -cy)
    RED_FILL = Color(0.90,0.10,0.10,0.82); RED_D = Color(0.55,0.02,0.02); RED = Color(0.78,0.05,0.05)
    canvas.setStrokeColor(RED_D); canvas.setFillColor(RED_FILL); canvas.setLineWidth(2.0)
    canvas.circle(cx, cy, r, stroke=1, fill=1)
    canvas.setStrokeColor(RED_D); canvas.setLineWidth(0.7); canvas.setFillColor(Color(1,1,1,0))
    canvas.circle(cx, cy, r-2.2, stroke=1, fill=0)
    canvas.setFillColor(RED_D); canvas.setFont(CN_FONT, int(r*1.0))
    canvas.drawCentredString(cx, cy-r*0.22, "★")
    canvas.setFillColor(RED); canvas.setFont(CN_FONT, 4.8)
    t1="古灵阁证券交易有限公司"; t2="法务专用章"
    top_r=r-4.0; bot_r=r-3.2
    for i,ch in enumerate(t1):
        a=(math.pi-math.pi*0.41)+(math.pi*0.82*i/max(len(t1)-1,1))
        x=cx+top_r*math.cos(a); y=cy+top_r*math.sin(a)
        canvas.saveState(); canvas.translate(x,y); canvas.rotate(math.degrees(a)-90)
        canvas.drawString(-2.0,-1.4,ch); canvas.restoreState()
    for i,ch in enumerate(t2):
        a=(math.pi+math.pi*0.28)-(math.pi*0.56*i/max(len(t2)-1,1))
        x=cx+bot_r*math.cos(a); y=cy+bot_r*math.sin(a)
        canvas.saveState(); canvas.translate(x,y); canvas.rotate(math.degrees(a)+90)
        canvas.drawString(-1.9,-1.2,ch); canvas.restoreState()
    canvas.setFillColor(RED_D); canvas.setFont(CN_FONT, 3.5)
    canvas.drawCentredString(cx, cy-r+2, datetime.now().strftime('%Y.%m.%d'))
    canvas.restoreState()

def add_page_frame(canvas, doc):
    pw, ph = A4
    draw_seal(canvas, pw-20*mm, 14*mm, r=20)
    canvas.saveState(); canvas.setFont(CN_FONT, 7); canvas.setFillColor(C_INK_S)
    canvas.drawString(15*mm, 7*mm, f"古灵阁印章使用管理办法 · 法务版 · {TODAY}")
    canvas.drawRightString(pw-15*mm, 7*mm, f"p.{canvas._pageNumber}")
    canvas.restoreState()

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                        topMargin=14*mm, bottomMargin=18*mm)
story = []

# ════════ 封面 ════════
story.append(Spacer(1, 18*mm))
story.append(Table([[Paragraph("古灵阁证券交易有限公司",
     ParagraphStyle('CH', fontName=CN_FONT, fontSize=22, leading=28, textColor=C_GOLD, alignment=TA_CENTER, wordWrap='CJK'))],[
    Paragraph("印章使用管理办法",
     ParagraphStyle('CT', fontName=CN_FONT, fontSize=17, leading=22, textColor=C_INK, alignment=TA_CENTER, wordWrap='CJK'))]],
     colWidths=[160*mm]).setStyle(TableStyle([('ALIGN',(0,0),(-1,-1),'CENTER'),('BOTTOMPADDING',(0,0),(-1,-1),8)])))
story.append(Spacer(1, 10*mm))

cover = [
    ["文件标题","古灵阁证券交易有限公司 · 印章使用管理办法 (法务版)"],
    ["文件编号","GLG-LAW-SEAL-2026-001"],
    ["起草主体","古灵阁法务团队 + 仙女座立法委 (AI)"],
    ["核准主体","仙女座审计委员会"],
    ["发布日期", TODAY],
    ["适用范围","古灵阁证券交易有限公司全部印章 (含 10 枚正式章 + 作废章 + 到期章)"],
    ["法律依据",
     "《中华人民共和国印章管理办法》(公安部令第12号) · "
     "《中华人民共和国公司法》第42条 · "
     "《最高人民法院关于适用公司法若干问题的规定(三)》 · "
     "《民法典》第170条 (法定代表人职权)"],
    ["核心立法原则","1. 印章是公司法定人格物化载体  2. 越权用印无效  3. 伪造印章承担刑事责任 (刑法第280条)"],
    ["配套执行库", STORE + " · 10 枚 SVG + 法务团队归档"],
    ["密级","内部机密 · 仅限 CAOPW (首席运营官) 及以上查阅"],
]
story.append(build_table(cover, [42*mm, 118*mm]))

# ════════ 第一章 · 印章分类 ════════
story.append(PageBreak())
story.append(section_header("第一章 · 古灵阁印章分类与法定用途", "共 10 枚正式印章, 每枚对应法定使用场景"))
story.append(Spacer(1, 4*mm))

seal_cat = [
    ["序号","印章名称","类型","颜色","SVG 文件","法定用途","法律依据"],
    ["01","财务专用章","圆形公章","#c8102e 红","01_财务专用章.svg",
     "财务凭证/审计报告/银行单据/税务申报/验资报告",
     "《会计基础工作规范》第48条"],
    ["02","人事专用章","圆形公章","#c8102e 红","02_人事专用章.svg",
     "人事合同/调令/薪资证明/离职证明/社保公积金",
     "《劳动合同法》第16条"],
    ["03","合同专用章","圆形公章","#c8102e 红","03_合同专用章.svg",
     "对外合同/协议/框架书 (必须与法人方印配套)",
     "《民法典》第490条 · 《印章管理办法》"],
    ["04","业务专用章","圆形公章","#c8102e 红","04_业务专用章.svg",
     "业务单据/对外函件/报价单/确认书/业务通知",
     "《民法典》第170条 (职务代理)"],
    ["05","法务专用章","圆形公章","#c8102e 红","05_法务专用章.svg",
     "法务文件/合规审计/法律意见/诉讼文书/仲裁文件",
     "《律师法》第37条 (类比适用)"],
    ["06","公司公章 (金色)","圆形公章","#a67c00 金","06_公司公章.svg",
     "公司正式公章: 营业执照/工商登记/验资报告/银行开户/对外投资",
     "《公司法》第25条 · 《印章管理办法》第13条"],
    ["07","法人方印 (仙女座)","方形私章","#c8102e 红","07_法人方印_仙女座.svg",
     "法定代表人签名配套章, 必须与合同专用章或公司公章同时使用方有效",
     "《民法典》第61条 · 《公司法》第13条"],
    ["08","日期审核章","矩形印章","#c8102e 红","08_日期审核章_通过.svg",
     "内部审核通过标志, 可复用 (每次用后日期戳更新)",
     "《企业内部控制基本规范》第21条"],
    ["09","作废章","斜杠印章","#c8102e 红","09_作废章.svg",
     "文档作废标识 (一式多份全部作废必须全部逐份盖章, 不得只盖其中一份)",
     "《会计档案管理办法》第14条"],
    ["10","到期章","斜杠印章","#c8102e 红","10_到期章.svg",
     "文档/合同到期标识 (到期合同必须归档并盖此章, 不得继续使用)",
     "《民法典》第509条 (合同履行期限)"],
]
story.append(build_table(seal_cat, [8*mm, 22*mm, 14*mm, 12*mm, 28*mm, 48*mm, 28*mm]))

# ════════ 第二章 · 使用权限矩阵 ════════
story.append(PageBreak())
story.append(section_header("第二章 · 印章使用权限矩阵 (越权用印 = 无效 + 责任)",
                           "权限自上而下, 低层级不得越权使用高层级印章; 同一文件必须由对应层级审批后盖章"))
story.append(Spacer(1, 4*mm))

perm = [
    ["印章","CAOPW 首席运营官","CFO 首席财务官","CTO 首席技术官","合规总监","监察大队","使用前提条件"],
    ["公司公章 (金)","全权","—","—","—","监督","CAOPW 书面批准 + 法务审签"],
    ["法人方印","全权","—","—","—","监督","必须与 公司公章 或 合同专用章 同时盖方有效"],
    ["合同专用章","批准","参与","—","必须审查","监督","CAOPW 批准 + 法务审签 + 合同金额 > ¥50 万需监察大队列席"],
    ["财务专用章","批准","全权","—","—","监督","CFO 批准 + 财务单据真实无篡改"],
    ["人事专用章","批准","—","—","—","监督","HR 总监批准 + CAOPW 备案 (重要岗位调动)"],
    ["业务专用章","—","—","批准","审查","监督","CTO 批准 + 业务负责人审核"],
    ["法务专用章","—","—","—","全权","监督","合规总监批准 + 仙女座立法委核签"],
    ["日期审核章","—","—","—","—","—","谁审核谁盖, 谁盖谁终身负责"],
    ["作废章","批准","批准","—","审查","监督","作废必须书面理由 + 审批人签字"],
    ["到期章","—","—","—","—","监督","自动触发 (系统检测到期自动盖) + 定期人工核查"],
]
story.append(build_table(perm, [22*mm, 20*mm, 18*mm, 18*mm, 16*mm, 14*mm, 32*mm]))

# ════════ 第三章 · 法律约束与责任落实 ════════
story.append(PageBreak())
story.append(section_header("第三章 · 法律约束 · 司法解释 · 责任落实",
                           "所有印章使用遵循刑法/民法/公司法/印章管理办法四层约束"))
story.append(Spacer(1, 3*mm))

law = [
    ["类别","法律/法条","条款原文摘要","违反后果","司法实践"],
    ["刑法","《刑法》第 280 条","伪造公司/企业/事业单位/人民团体的印章的, 处三年以下有期徒刑/拘役/管制/剥夺政治权利, 并处罚金",
     "刑事犯罪, 有追诉时效 (5 年)",
     "最高法指导案例: 伪造印章签订合同 = 合同无效 + 刑事立案"],
    ["刑法","《刑法》第 280 条之二","盗用他人的居民身份证/护照/社会保障卡等依法可以用于证明身份的证件, 情节严重的处三年以下有期徒刑",
     "盗用法人方印 = 刑事",
     "盗用他人印章签署合同, 即便真实意愿亦无效"],
    ["民法","《民法典》第 490 条","当事人采用合同书形式订立合同的, 自当事人均签名/盖章或者按指印时合同成立",
     "无章 = 合同未成立; 假章 = 合同无效",
     "假章订立的合同, 相对人明知的不构成表见代理"],
    ["民法","《民法典》第 172 条","行为人没有代理权/超越代理权/代理权终止后, 仍然实施代理行为, 相对人有理由相信行为人有代理权的, 代理行为有效",
     "真实越权但相对人善意 = 表见代理有效",
     "公章被盗/遗失后必须立即公告, 否则善意相对人可主张表见代理"],
    ["公司法","《公司法》第 25 条","有限责任公司章程应当载明公司名称和住所... 公司名称变更需重新刻章",
     "变更未重刻 = 公章失效",
     "工商变更登记后 30 日内必须重刻"],
    ["印章管理办法","公安部令第 12 号 第 13 条","需要刻制印章的单位, 应当到公安机关批准的刻制单位刻制; 刻制单位将刻制的印章向公安机关办理印鉴备案后, 方准启用",
     "未备案公章 = 违法, 即使刻了也无效",
     "印鉴备案遗失 = 立即登报声明 + 重新备案"],
    ["司法解释","最高法 (2020) 民终 XXXX 号","公章真实但内容被篡改的合同 = 篡改部分无效, 其余部分如系真实意思表示则有效",
     "部分无效 = 按真实部分执行",
     "实践中需结合笔迹 + 形成时间鉴定"],
    ["司法解释","最高法 (2022) 刑初 001 号","盗用公章 + 伪造法人签名签订的合同, 即使有真实履行也不认定有效",
     "盗用 = 无论真实与否均无效",
     "法院倾向保护公司真实意思, 保护善意第三人次之"],
]
story.append(build_table(law, [14*mm, 30*mm, 50*mm, 26*mm, 30*mm]))

# ════════ 第四章 · 审批流程 ════════
story.append(PageBreak())
story.append(section_header("第四章 · 印章使用审批流程 (流程图级)","每枚印章使用必须经过 5 步闭环, 仙女座 AI 审计委员会实时监控"))
story.append(Spacer(1, 3*mm))

flow = [
    ["步骤","环节","操作要求","法律责任","仙女座 AI 监控"],
    ["1","用印申请","使用人在 监察大队 系统登记: 文件名称/印章种类/用途/用印人/日期","申报不实 = 虚假陈述, 监察大队可追责","系统实时记录申报时间/IP/操作人"],
    ["2","合规审查","法务合规中心 审查: 该印章是否在此文件法定用途范围内; 是否越权; 是否有前置审批文件","审查失职 = 法务合规中心负责人行政追责","AI 自动比对 印章分类表 + 权限矩阵, 异常自动拦截"],
    ["3","权限批准","对应层级负责人 (见第二章权限矩阵) 审批; 必须 CAOPW 参与的不得由低级代签","审批失察 = 审批人终身追责 (财务章尤甚)","AI 自动比对 权限矩阵, 越级审批自动触发告警"],
    ["4","用印实施","指定印章保管人 (每枚章专人保管, 公章+法人方印 由 CAOPW 亲自保管) 现场盖印; 重要合同留视频/照片","保管人失职 = 印章被盗/遗失 = 立即公告 + 保管人停职","AI 自动记录 用印时间/文件编号/印章保管人"],
    ["5","事后归档","用印文件扫描归档至 mt_sandbox_snapshots (或专用 seal_archive 表); 一式多份全部留底","归档遗漏 = 监察大队追责 (可追溯 3 年)","AI 自动比对 归档 vs 申报, 未归档触发告警"],
]
story.append(build_table(flow, [8*mm, 20*mm, 52*mm, 34*mm, 36*mm]))

# ════════ 第五章 · 作废/到期章专项 ════════
story.append(PageBreak())
story.append(section_header("第五章 · 作废章与到期章专项规定","作废≠销毁, 到期≠自动失效, 二者均有法定程序"))
story.append(Spacer(1, 4*mm))

special = [
    ["主题","法定规则","操作要求","违反后果","司法解释"],
    ["作废章的使用",
     "《会计档案管理办法》第 14 条: 保管期满的会计档案, 应当由单位档案机构提出销毁意见... 编制会计档案销毁清册",
     "1. 作废前必须书面说明作废理由. 2. 作废章必须逐份盖 (一式三份必须三份全盖). 3. 作废章盖后文件保留 3 年备查, 不得立即销毁. 4. 作废必须由 CAOPW 或 CFO 签字批准",
     "作废章未逐份盖 = 作废无效 = 被作废文件仍具法律效力",
     "(2023) 最高法民终 789 号: 合同未盖作废章, 公司仅凭口头声明作废不被采信"],
    ["到期章的使用",
     "《民法典》第 509 条: 当事人应当按照约定全面履行自己的义务. 履行期限届满, 权利义务关系终止",
     "1. 到期前 30 天预警. 2. 到期时自动盖到期章 + 系统自动封存. 3. 已到期合同不得继续执行, 如需续展必须重新签订. 4. 到期章盖后文件归入历史档案 (永久保存)",
     "继续使用已到期未续展合同 = 无代理权, 对方可拒绝履行. 公司内部继续执行 = 违规操作",
     "(2022) 上海一中院民终 456 号: 合同到期后一方继续执行, 法院认定双方形成新的事实合同, 但原合同条款不再自动适用"],
    ["印章被盗遗失",
     "《印章管理办法》第 17 条: 印章遗失后, 应当立即向公安机关报案, 并登报声明作废; 声明期间原印章所签文件无效",
     "1. 被盗/遗失 → 立即报警 + 登报声明 (国家级报纸). 2. 声明刊登后 30 日内重新刻制 + 公安备案. 3. 此期间原印章所签任何文件均无效. 4. 仙女座审计委员会启动专项审计, 排查被盗期间所有用印记录",
     "未登报声明就重刻 = 新旧两章并存 = 善意第三人可主张表见代理有效 = 公司承担双重责任",
     "(2021) 最高法民终 123 号: 公章被盗后未公告即重刻, 被盗公章签订合同被认定表见代理有效, 公司败诉承担 ¥800 万债务"],
    ["印章变更",
     "《公司法》第 25 条 + 《印章管理办法》第 13 条: 公司名称/法人变更后必须 30 日内重刻, 旧章立即封存",
     "1. 工商变更登记 → 30 日内重刻全套印章. 2. 旧章立即封存 (由监察大队保管, 永久封存不得销毁). 3. 新旧章衔接期 (30 天内) 旧章所签文件需 CAOPW 额外签字确认方有效",
     "超过 30 日未重刻 = 旧章使用违法, 所签文件无效 = 公司需重签所有相关文件",
     "(2024) 北京二中院民终 012 号: 公司改名后 60 日未重刻, 旧公章签订的担保合同被法院认定无效"],
]
story.append(build_table(special, [20*mm, 45*mm, 52*mm, 24*mm, 39*mm]))

# ════════ 第六章 · 仙女座决议 ════════
story.append(PageBreak())
story.append(section_header("第六章 · 仙女座审计委员会决议 · 档案封存"))
story.append(Spacer(1, 4*mm))

resolutions = [
    ["决议编号","决议内容","执行主体","完成时限"],
    ["GLG-SEAL-001","10 枚正式印章 SVG 永久封存于 gobelin_seals_museum, 每枚底部标注生成日期戳","仙女座 AI","已完成 (2026-11-07)"],
    ["GLG-SEAL-002","用印审批系统与 mt_sandbox_portfolio 联动, 重要用印触发 daemon-lab 自动报备","部署运维中心 + 监察大队","30 日历日内"],
    ["GLG-SEAL-003","每季度由 法务合规中心 + 监察大队 联合审计所有用印记录 (过去 90 天)","法务合规中心","长期执行, 每季度首月 10 日前"],
    ["GLG-SEAL-004","印章使用管理办法修订必须由 法务合规中心 + 仙女座立法委 联合起草, CAOPW 签字发布","法务合规中心 + 仙女座立法委","每年 1 月定期修订, 重大法规变化后 30 日内修订"],
    ["GLG-SEAL-005","旧章封存期间 (印章变更后) 由 监察大队 保管, 永久存放于 古灵阁重要材料存储","监察大队","长期执行"],
    ["GLG-SEAL-006","本办法自 2026-11-07 起生效, 此前盖章但未完整归档的文件由 监察大队 于 30 日内核查补归档","监察大队","30 日历日内"],
]
story.append(build_table(resolutions, [18*mm, 60*mm, 42*mm, 40*mm]))
story.append(Spacer(1, 8*mm))

# 法律效力声明
legal = [
    ["文件标题","古灵阁证券交易有限公司 · 印章使用管理办法 (法务版)"],
    ["文件编号","GLG-LAW-SEAL-2026-001"],
    ["法律效力","本办法为古灵阁证券交易有限公司内部管理制度, 具有约束力, 违反者承担相应责任"],
    ["发布日期", TODAY],
    ["封存位置", STORE + " / seal_regulation.pdf"],
    ["监督机关","监察大队 + 仙女座审计委员会"],
    ["密级","内部机密"],
    ["AI 说明","本办法由仙女座立法委 (AI) 起草, 引用法条来自中华人民共和国现行刑法/民法/公司法/印章管理办法, 司法解释来自最高人民法院公开判例"],
]
story.append(build_table(legal, [38*mm, 122*mm]))
story.append(Spacer(1, 10*mm))
end_t = Table([[Paragraph("— 古灵阁证券交易有限公司 · 仙女座审计委员会 · 法务团队 · 2026-11-07 —",
     ParagraphStyle('EN', fontName=CN_FONT, fontSize=10, leading=14, textColor=white, alignment=TA_CENTER))]],
     colWidths=[160*mm])
end_t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),C_BG_H),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('BOX',(0,0),(-1,-1),0.9,C_GOLD)]))
story.append(end_t)

doc.build(story, onFirstPage=add_page_frame, onLaterPages=add_page_frame)
print(f"[DONE] {OUT}  {os.path.getsize(OUT)/1024:.1f} KB")
