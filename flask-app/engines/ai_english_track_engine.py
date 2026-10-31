#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
英语考试赛道引擎 (flow_english_track_20261031)
================================================
目的: 完善「英语类」考试赛道 — 雅思 / 托福 / 新概念英语 / 四级 / 六级 / 考研英语
      补齐考试院 (exam_auto_daemon) 赛道题库缺口:
        - 旧题库: lang_NCE 缺第三册; 托福题 grade 无前缀无法按赛道抽题; 雅思仅 10 处提及
        - 本引擎: 15 条赛道 (grade=track 精确落库), 零 token 本地造题, 双写教学平台

赛道矩阵 (4 大族 · 15 条):
  雅思族: 雅思听力 / 雅思阅读 / 雅思写作 / 雅思口语
  托福族: 托福阅读 / 托福听力 / 托福口语 / 托福写作
  新概念族: 新概念第一册 / 第二册 / 第三册 / 第四册
  国内应试族: 英语四级 / 英语六级 / 考研英语

数据流:
  ① 造题   真实知识题库(考点题+词汇题) → 变体扩充 → 幂等去重(uniq_qb_content)
           双写: question_bank(subject='英语', grade=赛道名, tags含赛道关键词)
                + mt_lang_qbank(language='en', topic=赛道名) → 教学平台联动
  ② 课程   mt_lang_courses 挂赛道课程 (cefr=赛道码) + mt_lang_lessons 挂课时
  ③ 学情   聚合 exam_results → 每赛道正确率/健康度 (题量<50 自动标记补题)
  ④ Daemon daemon_cycle(): 每轮补题量最少 3 赛道 × 6 题, 30min 周期, 零 token

CLI:
  python3 ai_english_track_engine.py init      # 建表 + 全赛道首轮播种
  python3 ai_english_track_engine.py expand    # 补题一轮 (daemon 单步)
  python3 ai_english_track_engine.py status    # 赛道总览
"""
import json
import os
import random
import sqlite3
import sys
import uuid
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.db_path import get_db_path  # noqa: E402

DB_PATH = get_db_path('app.db')
_FLOW = "flow_english_track_20261031"
SOURCE = "eng_track_engine"


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
#  赛道注册表 (4 族 15 赛道)
# ============================================================

TRACKS = [
    # (track, family, family_en, difficulty默认带, 说明)
    ("雅思听力", "雅思", "IELTS", (2, 4), "Section 1-4 场景词汇 / 题型策略 / 同义替换"),
    ("雅思阅读", "雅思", "IELTS", (2, 4), "TFNG / Heading / Matching / 学术长难句"),
    ("雅思写作", "雅思", "IELTS", (3, 5), "Task1 图表表达 / Task2 论证 / 评分标准"),
    ("雅思口语", "雅思", "IELTS", (2, 4), "Part1-3 策略 / 话题词 / 连接语"),
    ("托福阅读", "托福", "TOEFL", (2, 5), "学术词汇 / 插入题 / 小结题"),
    ("托福听力", "托福", "TOEFL", (2, 5), "Lecture 结构 / 信号词 / 态度题"),
    ("托福口语", "托福", "TOEFL", (2, 5), "独立/综合任务模板"),
    ("托福写作", "托福", "TOEFL", (3, 5), "综合写作 / 学术讨论"),
    ("新概念第一册", "新概念", "NCE1", (1, 2), "基础句型 / 初级词汇 / 日常对话"),
    ("新概念第二册", "新概念", "NCE2", (1, 3), "时态体系 / 被动 / 不定式"),
    ("新概念第三册", "新概念", "NCE3", (2, 4), "分词 / 虚拟 / 倒装 / 复杂从句"),
    ("新概念第四册", "新概念", "NCE4", (3, 5), "学术长句 / 修辞 / 议论文"),
    ("英语四级", "国内应试", "CET4", (1, 3), "高频词 / 新闻听力 / 翻译 / 写作"),
    ("英语六级", "国内应试", "CET6", (2, 4), "高阶词 / 长阅读 / 翻译"),
    ("考研英语", "国内应试", "KAOYAN", (3, 5), "长难句 / 完形逻辑 / 图画作文"),
]

# ============================================================
#  真实考点题库 (每赛道核心 knowledge items)
#  格式: (stem, [optA,optB,optC,optD], answer_idx, explanation, knowledge_point, diff)
# ============================================================

_KB = {
    "雅思听力": [
        ("雅思听力填空题答案字数限制「NO MORE THAN TWO WORDS」表示最多写几个词?", ["一个词", "两个词", "三个词", "不限"], 1, "NO MORE THAN TWO WORDS = 最多两个词, 写三个词即使内容对也判错。", "填空字数规则", 1),
        ("听力中听到「Let me just check that for you」通常预示接下来会出现?", ["无关话题", "关键信息确认", "录音结束", "换话题"], 1, "确认类话语后常重复或更正关键信息(电话/地址/数字), 是高频出题点。", "信号词", 2),
        ("Section 1 租房场景中「deposit」指?", ["月租", "押金", "中介费", "水电费"], 1, "deposit 押金; rent 租金; agency fee 中介费; utilities 水电。租房场景高频词。", "租房场景词", 1),
        ("听力地图题中「opposite the entrance」表示?", ["入口旁边", "入口对面", "入口里面", "入口上方"], 1, "opposite = 对面。地图题方位词: opposite对/adjacent to邻/beside旁/at the corner of角落。", "地图题方位", 2),
        ("听到「the deadline has been put forward」 deadlines 变化是?", ["延后", "提前", "取消", "不变"], 1, "put forward = 提前; put off / postpone = 推迟。此为经典易错同义替换。", "同义替换", 3),
        ("雅思听力四个 Section 中, 学术讨论(monograph/tutor)通常出现在?", ["Section 1", "Section 2", "Section 3", "Section 4"], 3, "S1 生活对话, S2 独白介绍, S3 学术讨论(2-4人), S4 学术讲座。", "结构", 1),
        ("「booked up」在预约场景中的含义是?", ["已订满", "刚开门", "打折中", "已关闭"], 0, "be booked up = 预订一空。同义: fully booked / no vacancies。", "预约场景词", 2),
        ("数字「double 2」正确记录方式?", ["22", "222", "2222", "2"], 0, "double X = 两个连续 X, double 2 = 22; triple 3 = 333。电话号码高频规则。", "数字规则", 1),
        ("听力中「I'd prefer... but ... is fine」表达了?", ["唯一选择", "偏好与妥协", "强烈拒绝", "完全同意"], 1, "prefer 提出偏好, but 后是最终接受项。说话人态度题经典结构。", "态度题", 3),
        ("Section 4 讲座笔记填空题的特点是?", ["有人物对话", "连续独白+学术笔记", "电话对话", "导游介绍"], 1, "S4 为学术独白, 考查笔记式填空, 注意信号词 (however/another point is)。", "结构", 2),
    ],
    "雅思阅读": [
        ("TFNG 题中, 原文说「most students」, 题目说「all students」, 应判断?", ["True", "False", "Not Given", "无法判断"], 1, "most→all 属于范围扩大化, 与原文矛盾, 判 False。范围词: all>most>some。", "TFNG规则", 2),
        ("TFNG 中「Not Given」的判定标准是?", ["与原文矛盾", "原文完全未提及或无法推断", "原文说反了", "原文部分提及"], 1, "NG = 原文没说且推不出来; False = 原文明确说了相反内容。", "TFNG规则", 2),
        ("List of Headings 题应先关注段落?", ["首句和尾句", "只看中间", "只看例子", "全部精读"], 0, "主题句常在段首(英文行文)或段尾(归纳), 先读首尾句抓大意。", "Heading技巧", 1),
        ("「agriculture = farming」这类关系在雅思阅读判断题中属于?", ["矛盾", "同义替换", "Not Given", "数字陷阱"], 1, "阅读本质是同义替换定位: agriculture↔farming, crucial↔vital。", "同义替换", 1),
        ("Matching 题中「NB You may use any letter more than once」意味着?", ["每个字母只用一次", "可能有选项重复使用", "有选项用不上", "答案唯一"], 1, "NB 提示 = 选项可复用, 定位时不能排除已选字母。", "Matching规则", 2),
        ("雅思阅读 A 类三篇文章的题材通常是?", ["小说", "学术科普(杂志/期刊改编)", "新闻评论", "广告"], 1, "A 类阅读取材于期刊/杂志/书籍, 学术性科普说明文为主, 不考文学。", "题材", 1),
        ("「the findings cast doubt on...」表示研究结果?", ["证实了", "质疑了", "忽略了", "补充了"], 1, "cast doubt on = 质疑。作者态度词: doubt质疑/endorse支持/dismiss否定。", "作者态度", 3),
        ("完成句子填空中, 空格前是「a」且语法需要名词, 应优先填?", ["动词", "名词(单数)", "形容词", "副词"], 1, "利用语法预判词性: a/an + 单数可数名词。填空先判词性再定位。", "填空词性预判", 2),
        ("「respectively」出现时表示?", ["各自对应", "综上所述", "然而", "例如"], 0, "respectively = 分别地, 前后列表一一对应, 常伴随数据配对题。", "学术词汇", 2),
        ("段落信息定位题(answer: paragraph D)最有效的顺序是?", ["先做此题型", "放到最后做", "先精读全文", "跳过"], 1, "段落细节定位题无顺序性, 放最后做, 先做有顺序性的填空/判断题。", "做题顺序", 2),
    ],
    "雅思写作": [
        ("Task 1 图表作文最少字数?", ["120", "150", "180", "250"], 1, "Task1 ≥150 词, Task2 ≥250 词。字数不足扣 TR 分。", "字数要求", 1),
        ("Task 2 议论文最少字数?", ["150", "200", "250", "300"], 2, "Task2 ≥250 词且占 2/3 分值, 建议先写 Task2。", "字数要求", 1),
        ("写作评分四项标准是?", ["听说读写", "TR/CC/LR/GRA", "词/句/段/篇", "语法/拼写/结构/速度"], 1, "TR任务回应/CC连贯衔接/LR词汇丰富/GRA语法多样性及准确。", "评分标准", 2),
        ("线图描述上升趋势的词是?", ["decline", "surge", "fluctuate", "remain"], 1, "上升: surge/soar/climb; 下降: decline/drop; 波动: fluctuate。", "Task1词汇", 1),
        ("「the number of」与「the amount of」的区别依据是?", ["可数与不可数", "单复数", "时间", "语态"], 0, "number + 可数名词, amount + 不可数名词。图表数据描述基础语法。", "Task1语法", 2),
        ("agree/disagree 题型的开头段应包含?", ["背景+改写题目+立场", "只有立场", "例子先行", "结论先行详述"], 0, "开头三要素: 背景句 + 题目改写(paraphrase) + 亮明立场。", "Task2结构", 2),
        ("「On the one hand ... On the other hand」用于?", ["列举", "对比两面", "因果", "让步"], 1, "双面讨论结构标志词, 用于 discuss both views 类题型。", "衔接词", 1),
        ("Task 1 结尾段通常写?", ["预测未来", "总结主要特征", "个人观点", "新数据"], 1, "Task1 结尾 = overview 总结最大/最显著特征, 不写个人观点。", "Task1结构", 2),
        ("「This essay will elaborate on...」属于?", ["结论句", "主题句", "让步句", "例子句"], 1, "elaborate on = 阐述, 主题句标志; 结论常用 in conclusion/to conclude。", "学术表达", 2),
        ("以下哪个是 Task2 高分论证方法?", ["只给例子", "观点+解释+例子+小结(PEEL)", "堆砌高级词", "重复题目"], 1, "PEEL: Point观点-Explain解释-Example例证-Link回扣, 论证完整闭环。", "论证方法", 3),
    ],
    "雅思口语": [
        ("Part 2 独白准备时间?", ["30秒", "1分钟", "2分钟", "3分钟"], 1, "Part2 准备1分钟+纸上笔记, 独白讲 1-2 分钟。", "流程", 1),
        ("口语评分四项标准是?", ["听说读写", "FC/LR/GRA/P", "词句段篇", "音形义用"], 1, "FC流利连贯/LR词汇/GRA语法/P发音。", "评分标准", 2),
        ("Part 3 讨论性质是?", ["个人经历", "抽象社会话题延伸", "看图描述", "读文章"], 1, "Part3 是考官基于 Part2 话题的抽象双向讨论, 考查论证能力。", "流程", 2),
        ("「I'm really into...」表达?", ["讨厌", "热衷于", "刚开始学", "不得不"], 1, "be into = 热衷, 地道表达, 优于 like。口语词汇多样性得分点。", "口语表达", 1),
        ("听不懂考官问题时, 最佳做法?", ["沉默", "请考官重复: Could you rephrase that?", "背模板", "换话题"], 1, "口语允许合理请求澄清, 不扣分; 沉默影响 FC 分。", "应试策略", 1),
        ("描述人物话题的高分维度是?", ["只有外貌", "外貌+性格+影响", "只有成就", "只有关系"], 1, "人物题三维: 外貌特征 + 性格品质 + 对我的影响。", "话题展开", 2),
        ("以下哪个连接语适合口语举例?", ["Furthermore", "For instance", "In contrast", "Therefore"], 1, "For instance 口语书面通用; furthermore 偏书面, 口语用 besides/plus。", "口语表达", 1),
        ("「It's a double-edged sword」用于描述?", ["纯优点", "有利有弊", "纯缺点", "中性事实"], 1, "double-edged sword 双刃剑 = 有利有弊, Part3 讨论利弊高分表达。", "口语表达", 2),
        ("发音项(P)关注的核心不包括?", ["连读", "语调", "重音", "词汇量"], 3, "P 项考发音特征(连读/弱读/语调/重音), 词汇量属 LR 项。", "评分标准", 2),
        ("Part1 回答理想长度?", ["一个词", "一句话", "2-4句扩展", "越长越好"], 2, "Part1 答 2-4 句: 直接回答+理由/例子, 过短显得不流利, 过长越界。", "应试策略", 1),
    ],
    "托福阅读": [
        ("托福阅读词汇题「vocabulary question」的做题要领是?", ["查上下文矛盾", "代入四个选项看原义保持", "选最生僻的", "凭词根猜"], 1, "词汇题将原词代入选项, 保持句意不变即为答案, 不需背景知识。", "题型", 1),
        ("插入题(sentence insertion)利用的关键线索是?", ["黑体词", "指代词(this/they/such)与逻辑连接词", "数字", "标题"], 1, "指代回指前文, 转折/因果衔接决定位置。", "题型", 2),
        ("Prose Summary 小结题要求选出?", ["6选3 概括主旨项", "细节项", "未提及项", "矛盾项"], 0, "小结题 6 选 3, 选能概括全文结构的主旨句, 细节/错误项排除。", "题型", 2),
        ("「ubiquitous」的意思是?", ["稀有的", "无处不在的", "古老的", "昂贵的"], 1, "ubiquitous = 普遍存在的, 托福学术高频词 (ubiquitous technology)。", "学术词汇", 2),
        ("阅读文章来源主要是?", ["小说", "大学 level 学术教科书", "新闻", "广告"], 1, "托福阅读取材北美大学教材级学术文章, 4-5 段, 700 词左右。", "题材", 1),
        ("否定事实信息题(negative factual)应?", ["找原文直接提到的", "找四个选项中原文未提到/矛盾的", "全选", "选主题"], 1, "EXCEPT/NOT 题选原文不支持的那个选项。", "题型", 2),
        ("「hypothesis」在学术文章中指?", ["结论", "假说(待验证)", "数据", "引言"], 1, "hypothesis 假说, 与 theory(已验证理论)、evidence(证据)区分。", "学术词汇", 2),
        ("推断题(inference)的正确答案特征是?", ["原文原句照抄", "由原文逻辑强暗示但未明说", "个人常识", "最极端表述"], 1, "推断 = 原文暗示的合理结论; 原句照抄通常是陷阱。", "题型", 3),
        ("「The word 'which' refers to」类题考查?", ["词汇量", "指代关系", "语法时态", "修辞"], 1, "指代题找前文最近的逻辑一致的名词单复数匹配。", "题型", 2),
        ("托福阅读一篇文章的题量约为?", ["5题", "10题", "14题", "20题"], 1, "每篇约 10 题, 2 篇共 20 题, 36 分钟(新版)。", "考试结构", 1),
    ],
    "托福听力": [
        ("听力 Conversation 通常发生在?", ["新闻现场", "校园场景(办公室/图书馆/注册处)", "机场", "法庭"], 1, "Conversation 为校园对话: 办公时间/服务场景, 5 题左右。", "考试结构", 1),
        ("Lecture 中教授说「Let's focus on...」后面通常?", ["结束", "进入考查重点", "闲聊", "重复开场"], 1, "focus on / today we'll cover 是主题信号词, 决定考点方向。", "信号词", 2),
        ("教授说「however, that's not the whole story」暗示?", ["补充新观点", "结束话题", "无关内容", "读题"], 0, "however/actually/yet 转折后是高频考点, 常修正前述观点。", "信号词", 2),
        ("「reverberate」在讲座中的含义是?", ["消失", "回响", "固化", "蒸发"], 1, "reverberate 回响/回荡, 声学/地质类讲座高频。", "学科词汇", 3),
        ("学生说「So, just to clarify...」的功能是?", ["质疑教授", "确认理解", "转换话题", "请求延期"], 1, "clarify = 澄清, 学生确认信息的复述常对应细节考点。", "对话功能", 2),
        ("Lecture 重放题(replay)考查的是?", ["拼写", "语句功能/态度", "数字", "日期"], 1, "重放某句问 why does the professor say this → 功能/态度题。", "题型", 2),
        ("「photosynthesis」属于哪个学科高频词?", ["艺术史", "生物学", "经济学", "法学"], 1, "photosynthesis 光合作用, 生物讲座核心词。", "学科词汇", 1),
        ("教授列举「first, second, third」时考官最爱考?", ["开头", "列举的对应细节配对", "结尾", "语气"], 1, "列举结构对应多选题/配对题, 记笔记按序号对齐。", "笔记策略", 2),
        ("「sediment」常出现在哪类讲座?", ["地质/地理", "市场营销", "诗歌", "会计"], 0, "sediment 沉积物, 地质学高频 (sedimentary rock 沉积岩)。", "学科词汇", 2),
        ("听力笔记的最佳原则是?", ["逐字记录", "关键词+结构缩写", "只记数字", "不记"], 1, "记缩写/符号/层次结构, 防止逐字掉信息。", "笔记策略", 1),
    ],
    "托福口语": [
        ("独立口语 Task 1 准备时间?", ["5秒", "15秒", "30秒", "1分钟"], 1, "独立题 15 秒准备, 45 秒作答(新版 10 秒准备)。", "流程", 1),
        ("综合口语答「阅读+听力」关系时应?", ["只复述阅读", "重点讲听力如何支持/反驳阅读", "只讲阅读", "自由发挥"], 1, "综合任务核心 = 听力内容 + 与阅读的关系(支持或反驳)。", "综合任务", 2),
        ("口语高分模板的第一句最好是?", ["长难句", "直接回应题干表明观点", "背景铺垫", "引经据典"], 1, "直给观点+2理由, 首句切题保证评分项 Task fulfillment。", "答题策略", 1),
        ("「from my perspective」用于?", ["举例", "表达个人观点", "总结", "对比"], 1, "from my perspective = 依我之见, 独立题开头表达观点。", "表达", 1),
        ("口语中「elaborate」的意思是?", ["简化", "详细阐述", "否认", "重复"], 1, "elaborate 阐述, 综合口语要求 elaborate on the reading。", "词汇", 2),
        ("综合任务校园通知题先出现的是?", ["学生对话", "阅读通知", "教授讲座", "图片"], 1, "先读通知/政策(45s), 再听对话中学生讨论其优劣。", "流程", 2),
        ("托福口语整体共几题(新版)?", ["2", "4", "6", "8"], 1, "新版 4 题: 1 独立 + 3 综合。", "考试结构", 1),
        ("表达「发展技能」的地道搭配是?", ["grow a skill", "develop a skill", "rise a skill", "open a skill"], 1, "develop/acquire a skill 地道搭配, 动词搭配是评分点。", "表达", 2),
        ("听力部分学生举反例的功能是?", ["装饰", "反驳/质疑通知中的优点", "重复原文", "无关"], 1, "对话中学生常吐槽通知缺陷 → 综合口语答案主体。", "对话功能", 2),
        ("45 秒独立题的理想结构?", ["1观点1理由重复", "观点+2理由+简要展开", "三观点并列", "故事叙述"], 1, "观点 + 2 个理由 + 各一句展开, 时间刚好不超时。", "答题策略", 2),
    ],
    "托福写作": [
        ("综合写作要求?", ["纯个人观点", "总结听力如何反驳/支持阅读", "自由发挥", "复述阅读"], 1, "综合写作 = 客观转述听力对阅读三点论据的回应, 不写个人观点。", "题型", 1),
        ("学术讨论写作(Academic Discussion)字数建议?", ["50词", "至少100词", "300词", "500词"], 1, "新版学术讨论题 10 分钟, 建议 100+ 词, 有观点+论证+回应他人。", "题型", 2),
        ("综合写作听力反驳阅读的信号表达是?", ["as we all know", "This directly contradicts the reading", "in conclusion", "for example"], 1, "contradicts/casts doubt on/challenges 是反驳关系标志。", "表达", 2),
        ("「The lecture refutes the passage by pointing out...」中 refute 意为?", ["支持", "反驳", "补充", "忽略"], 1, "refute = 驳斥, 综合写作核心动词 (refute/challenge/disprove)。", "词汇", 2),
        ("综合写作结构建议?", ["一段到底", "四段: 引言+三个对应点", "八段", "两段"], 1, "引言概括关系 + 三段逐一对应阅读三点, 结构清晰得分稳。", "结构", 2),
        ("独立写作(旧版)五段式的核心是?", ["开头+3论证+结尾", "开头+结论", "纯例子", "纯反驳"], 0, "经典五段: 引言 + 3 论证段(每段观点+解释+例子) + 结论。", "结构", 1),
        ("「concede that...however...」体现的论证技巧是?", ["让步反驳", "并列", "举例", "因果"], 0, "先让步承认对方合理处, 再 however 转折反驳, 论证更立体。", "论证", 3),
        ("学术讨论题中回应其他同学观点的正确姿势?", ["无视", "引用并补充新论据", "人身反驳", "只贴模板"], 1, "高分要素: 直接回应他人贡献 + 加入新材料/新视角。", "题型", 2),
        ("「plausible」的意思是?", ["错误的", "貌似合理的", "荒谬的", "确定的"], 1, "plausible 貌似可信的, 学术写作评价观点常用。", "词汇", 3),
        ("以下哪个是综合写作第一段要点?", ["详细抄阅读", "一句话概括阅读+听力关系", "抛出个人观点", "写例子"], 1, "首段: The reading proposes..., while the lecture argues... 点明对立关系。", "结构", 1),
    ],
    "新概念第一册": [
        ("「This is a pen.」中 a 的用法是?", ["特指", "泛指单数可数名词", "复数", "不可数"], 1, "a/an + 单数可数名词表泛指; a 用于辅音音素前, an 用于元音音素前。", "冠词", 1),
        ("「an apple」用 an 是因为?", ["元音字母开头", "元音音素开头", "复数", "强调"], 1, "看音素不看字母: an hour(h 不发音) 正确, a university(juː 辅音音素) 正确。", "冠词", 2),
        ("「There is a book on the desk.」句型表示?", ["拥有", "存在", "命令", "疑问"], 1, "there be 句型表存在; have/has 表拥有。", "there be", 1),
        ("「Are you a teacher?」的回答?", ["Yes, I am.", "Yes, I do.", "Yes, I have.", "Yes, I is."], 0, "be 动词问句用 be 动词回答: Yes, I am. / No, I'm not.", "be动词", 1),
        ("「What are you doing? I ___ reading.」", ["am", "is", "are", "be"], 0, "I + am; 现在进行时 be doing 表示正在进行的动作。", "现在进行时", 1),
        ("「I don't have ___ money.」", ["some", "any", "many", "a"], 1, "否定/疑问用 any, 肯定用 some。", "some any", 1),
        ("「Whose pen is this? It's ___ .」", ["me", "my", "mine", "I"], 2, "mine = my pen 名词性物主代词, 单独使用; my 后必须接名词。", "物主代词", 2),
        ("「Can you ___ English?」", ["say", "speak", "talk", "tell"], 1, "speak + 语言; say + 内容; talk 交谈; tell 讲述(故事)。", "动词辨析", 2),
        ("「The cat is ___ the table.」(在...下面)", ["on", "under", "in", "at"], 1, "under 在下方; on 在上面; in 在里面。方位介词。", "方位介词", 1),
        ("「How do you do?」的正确回应?", ["I'm fine.", "How do you do?", "Yes, I do.", "Goodbye."], 1, "How do you do 是初次见面正式问候, 回答同样 How do you do。", "交际用语", 1),
    ],
    "新概念第二册": [
        ("「He ___ to school every day.」(go)", ["go", "goes", "going", "gone"], 1, "主语三单 + 动词加 s/es, 一般现在时。", "一般现在时", 1),
        ("「I ___ my keys yesterday.」(lose)", ["lose", "lost", "will lose", "losing"], 1, "yesterday 标志一般过去时, lose→lost 不规则变化。", "一般过去时", 1),
        ("「The letter ___ tomorrow.」(send)", ["will send", "will be sent", "sends", "sent"], 1, "信是被寄出 → 一般将来时被动语态 will be done。", "被动语态", 2),
        ("「He said he ___ been to Paris.」", ["has", "had", "have", "was"], 1, "间接引语中现在完成时后退一步为过去完成时 had done。", "间接引语", 3),
        ("「I have ___ finished my homework.」(已经)", ["yet", "already", "still", "ever"], 1, "already 用于肯定句「已经」, yet 用于否定/疑问句句尾。", "现在完成时", 2),
        ("「If it ___ tomorrow, we'll stay home.」(rain)", ["rains", "will rain", "rained", "rain"], 0, "if 条件状语从句用一般现在时表将来, 主句用 will。", "条件句", 2),
        ("「She is the girl ___ won the prize.」", ["which", "who", "whom", "whose"], 1, "先行词 the girl 指人且作主语 → who。", "定语从句", 2),
        ("「He told me ___ worry about it.」", ["don't", "not to", "to not", "no"], 1, "tell sb not to do 否定不定式结构。", "不定式", 2),
        ("「Neither of the answers ___ correct.」", ["are", "is", "were", "be"], 1, "neither of + 复数名词, 谓语用单数(正式语法)。", "主谓一致", 3),
        ("「While I ___ dinner, the phone rang.」(cook)", ["cooked", "was cooking", "cook", "am cooking"], 1, "while + 进行时作背景, 过去时表短暂动作插入。", "过去进行时", 2),
    ],
    "新概念第三册": [
        ("「The house, ___ windows were broken, looked deserted.」", ["which", "that", "whose", "its"], 2, "whose + 名词表所属, 非限定性定语从句不能用 that。", "定语从句", 3),
        ("「___ from space, the earth looks blue.」(see)", ["Seeing", "Seen", "To see", "See"], 1, "地球被看 → 过去分词作状语表被动, 分词逻辑主语与主句一致。", "分词", 3),
        ("「Had I known earlier, I ___ you.」(tell)", ["will tell", "would have told", "told", "would tell"], 1, "省略 if 的虚拟条件句(过去), 主句 would have done。", "虚拟语气", 4),
        ("「Not until yesterday ___ the truth.」", ["I knew", "did I know", "I did know", "do I know"], 1, "not until 置于句首, 主句部分倒装 did I know。", "倒装", 4),
        ("「It was in 1990 ___ he was born.」", ["when", "that", "which", "on which"], 1, "强调句型 It is/was + 被强调部分 + that + 其余。", "强调句", 3),
        ("「The problem is ___ we lack funds.」", ["that", "what", "which", "how"], 0, "表语从句句意完整用 that; what 在从句中作成分。", "名词性从句", 3),
        ("「He is said ___ in London for ten years.」", ["to live", "to have lived", "living", "lived"], 1, "不定式完成式 to have done 表示动作先于主句发生。", "不定式", 4),
        ("「No sooner ___ home than it rained.」", ["I had got", "had I got", "I got", "did I got"], 1, "no sooner...than... 句型, no sooner 置句首用过去完成时倒装。", "倒装", 4),
        ("「Only by working hard ___ success.」", ["you can achieve", "can you achieve", "you achieve", "achieve you"], 1, "only + 状语置于句首, 主句部分倒装。", "倒装", 4),
        ("「The evidence suggests that he ___ aware of the risk.」(be)", ["is", "was", "be", "were"], 1, "suggest 表「表明」时从句用陈述语气; 表「建议」才用 should+动词原形。", "虚拟语气辨析", 4),
    ],
    "新概念第四册": [
        ("「The theory he put forward was soon borne out by facts.」borne out 意为?", ["否定的", "证实的", "忽略的", "修改的"], 1, "bear out = 证实, 学术议论文常用搭配。", "短语动词", 4),
        ("「___ the evidence, the committee reached a unanimous verdict.」", ["In the light of", "In case of", "In spite of", "In favor of"], 0, "in the light of = 根据/鉴于, 正式书面衔接。", "书面衔接", 4),
        ("「It is imperative that every member ___ present.」(be)", ["is", "be", "was", "were"], 1, "it is imperative/essential that + (should) 动词原形虚拟。", "虚拟语气", 5),
        ("「The decline was ___ attributable to mismanagement.」", ["largely", "large", "enlarge", "largeness"], 0, "largely = 在很大程度上, 副词修饰形容词 attributable。", "副词", 3),
        ("「Far from ___ , his remark clarified the issue.」", ["obscure it", "obscuring it", "obscured it", "to obscure"], 1, "far from + doing 表「非但没有」, 介词短语后接动名词。", "非谓语", 4),
        ("「Such ___ his conduct that everyone was scandalized.」", ["was", "were", "is", "being"], 0, "such be + 名词倒装句型, 主语为 his conduct 单数过去时 was。", "倒装", 5),
        ("「The argument rests on the ___ that all men are equal.」", ["premise", "premium", "premise's", "promise"], 0, "premise 前提, rest on the premise 建立在前提上, 议论文核心词。", "学术词汇", 4),
        ("「Not that I dislike the task, ___ that I have no time.」", ["but", "and", "or", "so"], 0, "not that...but that... = 不是因为...而是因为..., 平行结构。", "平行结构", 4),
        ("「The author's tone in the passage can best be described as ___ .」", ["indifferent", "analytical", "sarcastic", "sentimental"], 1, "NCE4 课文以分析性说理为主, tone 题积累: analytical/neutral/critical。", "文体分析", 3),
        ("「Were it not for the sun, nothing ___ .」", ["will exist", "would exist", "exists", "would have existed"], 1, "were it not for 虚拟(与现在相反), 主句 would + 动词原形。", "虚拟语气", 5),
    ],
    "英语四级": [
        ("「abandon」的意思是?", ["坚持", "放弃/抛弃", "提高", "获得"], 1, "abandon 放弃, 四级高频动词 (abandon oneself to 沉溺于)。", "高频词汇", 1),
        ("「The meeting was put off」中 put off 意为?", ["穿上", "推迟", "脱下", "扑灭"], 1, "put off = 推迟 = postpone, 听力长对话高频。", "短语动词", 1),
        ("四级听力新闻题第一句通常包含?", ["评论", "新闻要点(who/what/where)", "广告", "音乐"], 1, "新闻导语(首句)承载核心信息, 题目多出自首句。", "新闻听力", 2),
        ("「contribute to」的意思是?", ["归咎于", "有助于/导致", "来自于", "依赖于"], 1, "contribute to 促成/有助于; 注意与 attribute to(归因于)区分。", "高频短语", 2),
        ("四级翻译常考「中国经济快速发展」中「经济」是?", ["economy/economic", "economics", "economist", "economical"], 0, "economy 名词, economic 形容词「经济的」, economical 节俭的。", "翻译词汇", 2),
        ("「available」的意思是?", ["无效的", "可获得的/可用的", "可避免的", "有价值的"], 1, "available 可用的, 听力阅读双高频 (tickets available)。", "高频词汇", 1),
        ("「adopt」与「adapt」的区别是?", ["同义", "adopt采纳/收养, adapt适应/改编", "反义都指放弃", "无区别"], 1, "adopt 采纳收养; adapt 适应改编。形近词辨析经典考点。", "形近词", 2),
        ("「make a difference」意为?", ["制造分歧", "产生影响", "做决定", "有区别地对待"], 1, "make a difference 产生影响/起作用, 写作口语通用。", "高频短语", 1),
        ("四级写作万能衔接「Moreover」表示?", ["转折", "递进", "因果", "总结"], 1, "递进: moreover/furthermore/in addition; 转折: however/nevertheless。", "写作衔接", 1),
        ("「be concerned about」意为?", ["涉及", "关心/担忧", "包含", "由...组成"], 1, "be concerned about 关心担忧; be concerned with 与...有关。", "高频短语", 2),
    ],
    "英语六级": [
        ("「compulsory」的意思是?", ["可选的", "强制的/必修的", "自由的", "义务帮忙的"], 1, "compulsory 强制的 (compulsory courses 必修课), 反义 optional。", "高频词汇", 2),
        ("「deteriorate」的意思是?", ["改善", "恶化", "决定", "探测"], 1, "deteriorate 恶化 (health deteriorating), 阅读态度/趋势题高频。", "高频词汇", 3),
        ("「The findings are ___ with previous studies.」(一致)", ["consistent", "constant", "contingent", "contemporary"], 0, "be consistent with 与...一致, 六级阅读实证类文章高频。", "学术短语", 3),
        ("「长难句: The hypothesis that birds navigate by magnetism remains unproven.」主干是?", ["birds navigate", "The hypothesis remains unproven", "by magnetism", "unproven birds"], 1, "同位语从句 that... 修饰 hypothesis, 主干 = The hypothesis remains unproven。", "长难句", 3),
        ("「ambiguous」的意思是?", ["明确的", "模棱两可的", "雄心勃勃的", "相似"], 1, "ambiguous 模棱两可, 与 ambitious(有雄心的)形近辨析。", "形近词", 2),
        ("「subsidize」的意思是?", ["征税", "补贴/资助", "订阅", "下属"], 1, "subsidize 补贴 (government-subsidized housing), 经济类文章高频。", "高频词汇", 3),
        ("「under no circumstances ___ share the password.」", ["you should", "should you", "you must", "must you not"], 1, "under no circumstances 否定状语前置 → 部分倒装 should you。", "倒装", 4),
        ("「plausible」与「feasible」都表示?", ["可能性", "plausible 貌似合理, feasible 切实可行", "困难", "昂贵"], 1, "plausible 貌似有理(未证实); feasible 可行的(可执行)。", "近义词辨析", 3),
        ("六级听力讲座题常考教授的?", ["衣着", "观点转折与强调处", "姓名", "口音"], 1, "however/actually/in fact 转折强调处为出题核心。", "听力策略", 2),
        ("「take...with a grain of salt」意为?", ["加盐", "对...持保留态度", "认真消化", "一口吞下"], 1, "习语: 对...半信半疑, 六级听力习语题。", "习语", 3),
    ],
    "考研英语": [
        ("「长难句: What the recent study reveals is that optimism, far from being innate, can be cultivated.」主语是?", ["optimism", "What the recent study reveals", "far from", "can be cultivated"], 1, "what 引导主语从句作主语, far from being innate 插入语。", "长难句", 4),
        ("「address」在考研阅读「address the issue」中意为?", ["地址", "解决/处理", "演讲only", "称呼"], 1, "address = 应对解决 (address the problem), 熟词僻义高频。", "熟词僻义", 2),
        ("「school」在「the Chicago school of economics」中意为?", ["学校", "学派", "学院楼", "上课"], 1, "school 学派, 考研熟词僻义 (a school of thought 思想流派)。", "熟词僻义", 3),
        ("「aptitude」的意思是?", ["态度", "天赋/才能", "海拔", "感激"], 1, "aptitude 天资 (aptitude test 能力测试), 与 attitude 形近辨析。", "形近词", 3),
        ("完形填空中「However」出现时预示?", ["递进", "前后语义转折", "因果", "举例"], 1, "完形逻辑题: however 转折/therefore 因果/meanwhile 并列, 看前后句关系。", "完形逻辑", 2),
        ("「长难句: Only when the root cause is addressed can the symptom be alleviated.」倒装规律是?", ["无倒装", "Only+状语从句位于句首, 主句部分倒装", "全倒装", "表语倒装"], 1, "only when... 主句 can the symptom be 部分倒装。", "倒装", 4),
        ("阅读态度词「skeptical」表示?", ["支持", "怀疑", "中立", "热情"], 1, "skeptical 怀疑的, 考研态度题高频词 (be skeptical of)。", "态度词", 2),
        ("「图片作文」第一段应?", ["给解决方案", "描述图画+点明寓意", "只抄题目", "列数据"], 1, "图画作文: 描图 → 寓意阐释 → 评论/建议三段式。", "写作", 2),
        ("「propensity」的意思是?", ["财产", "倾向/习性", "提议", "原理"], 1, "propensity 倾向 (a propensity for saving), 替代 tendency 的高级词。", "高频词汇", 4),
        ("「The author would most likely agree with...」这类题应?", ["凭常识答", "依据文中作者明确倾向推断", "选最强表述", "选未提及项"], 1, "作者态度/推论题依据文中语气词与论证方向, 忌常识代入。", "阅读方法", 3),
    ],
}

# ============================================================
#  词汇库 (每赛道单词 → 自动生成词义选择题)
#  格式: (word, 选项[4], answer_idx, 释义)
# ============================================================

_VOCAB = {
    "雅思听力": [("accommodation", 2, "住宿"), ("enrolment", 2, "注册入学"), ("itinerary", 1, "行程单"), ("recreation", 2, "娱乐"), ("suburb", 1, "郊区"), ("auditorium", 2, "礼堂"), ("renewal", 2, "续期"), ("luggage", 1, "行李"), ("guidance", 2, "指导"), ("cafeteria", 2, "自助餐厅"), ("landlord", 2, "房东"), ("appointment", 2, "预约")],
    "雅思阅读": [("hypothesis", 1, "假说"), ("metabolism", 2, "新陈代谢"), ("ecosystem", 1, "生态系统"), ("consecutive", 2, "连续的"), ("prevailing", 1, "盛行的"), ("vulnerable", 2, "脆弱的"), ("abundant", 1, "丰富的"), ("component", 1, "组成部分"), ("resemble", 2, "类似"), ("distort", 2, "扭曲"), ("mitigate", 2, "缓解"), ("empirical", 2, "实证的")],
    "雅思写作": [("deteriorate", 2, "恶化"), ("prohibit", 1, "禁止"), ("advocate", 2, "提倡"), ("inevitable", 2, "不可避免的"), ("controversial", 2, "有争议的"), ("phenomenon", 2, "现象"), ("priority", 1, "优先事项"), ("substantial", 2, "大量的"), ("undermine", 2, "削弱"), ("facilitate", 2, "促进")],
    "雅思口语": [("leisure", 1, "休闲"), ("cuisine", 2, "烹饪/菜系"), ("hustle", 2, "忙碌喧闹"), ("vibrant", 1, "充满活力的"), ("nostalgic", 2, "怀念的"), ("ambience", 1, "氛围"), ("therapeutic", 2, "治愈的"), ("rural", 1, "乡村的"), ("commute", 1, "通勤"), ("spectator", 2, "观众")],
    "托福阅读": [("sediment", 1, "沉积物"), ("erosion", 2, "侵蚀"), ("fossil", 1, "化石"), ("hypothesis", 1, "假说"), ("vertebrate", 2, "脊椎动物"), ("chlorophyll", 2, "叶绿素"), ("nutrient", 2, "养分"), ("predator", 1, "捕食者"), ("camouflage", 2, "伪装"), ("artisan", 2, "工匠"), ("commodity", 1, "商品"), ("monopoly", 2, "垄断"), ("revenue", 1, "收入"), ("prominent", 2, "杰出的"), ("incentive", 2, "激励")],
    "托福听力": [("syllabus", 2, "教学大纲"), ("assignment", 2, "作业"), ("extension", 2, "延期"), ("lab experiment", 2, "实验"), ("photosynthesis", 1, "光合作用"), ("glacier", 1, "冰川"), ("sediment", 1, "沉积物"), ("meteor", 1, "流星"), ("canvas", 1, "帆布/画布"), ("symphony", 2, "交响乐"), ("acoustics", 2, "声学"), ("manuscript", 2, "手稿")],
    "托福口语": [("campus dining", 2, "校园餐饮"), ("commute", 1, "通勤"), ("tuition", 1, "学费"), ("major in", 2, "主修"), ("scholarship", 1, "奖学金"), ("club fair", 2, "社团招新"), ("volunteer", 2, "志愿"), ("semester", 1, "学期"), ("orientation", 2, "迎新"), ("internship", 2, "实习")],
    "托福写作": [("refute", 2, "反驳"), ("contend", 2, "主张"), ("concede", 2, "承认(让步)"), ("substantiate", 2, "证实"), ("inherent", 2, "固有的"), ("alternative", 1, "替代方案"), ("consequence", 2, "后果"), ("justification", 2, "正当理由"), ("paradox", 2, "悖论"), ("renewable", 2, "可再生的")],
    "新概念第一册": [("apple", 2, "苹果"), ("window", 2, "窗户"), ("letter", 1, "信"), ("kitchen", 2, "厨房"), ("umbrella", 2, "雨伞"), ("passport", 2, "护照"), ("engineer", 2, "工程师"), ("milkman", 1, "送奶工"), ("neighbour", 2, "邻居"), ("holiday", 1, "假期")],
    "新概念第二册": [("entertain", 2, "招待"), ("temper", 2, "脾气"), ("persuade", 1, "说服"), ("refuse", 1, "拒绝"), ("request", 2, "请求"), ("tramp", 2, "流浪汉"), ("pawnbroker", 2, "典当商"), ("notices", 1, "通告"), ("curtain", 2, "窗帘"), ("anxious", 2, "焦虑的")],
    "新概念第三册": [("adventurer", 2, "冒险家"), ("reckon", 2, "估计"), ("confide", 2, "吐露"), ("grieve", 2, "悲伤"), ("conscientious", 2, "尽责的"), ("dignity", 2, "尊严"), ("boisterous", 2, "喧闹的"), ("precaution", 2, "预防措施"), ("punctual", 1, "准时的"), ("intuition", 2, "直觉"), ("suspicious", 2, "可疑的"), ("acquaintance", 2, "熟人")],
    "新概念第四册": [("premise", 2, "前提"), ("propound", 2, "提出(理论)"), ("conformity", 2, "符合"), ("galaxy", 1, "星系"), ("speculation", 2, "推测"), ("axiomatic", 2, "公理的"), ("elucidate", 2, "阐明"), ("paradoxical", 2, "矛盾的"), ("allegation", 2, "指控/断言"), ("intrinsic", 2, "内在的"), ("reciprocal", 2, "互惠的"), ("aesthetics", 2, "美学")],
    "英语四级": [("abandon", 1, "放弃"), ("abundant", 2, "丰富的"), ("accomplish", 2, "完成"), ("acquire", 2, "获得"), ("appropriate", 2, "恰当的"), ("betray", 1, "背叛"), ("capacity", 2, "容量/能力"), ("deliver", 1, "投递/发表"), ("eliminate", 2, "消除"), ("enthusiasm", 2, "热情"), ("flexible", 2, "灵活的"), ("genuine", 2, "真正的"), ("harmony", 1, "和谐"), ("identity", 2, "身份"), ("initiative", 2, "主动性"), ("justify", 2, "证明合理"), ("moderate", 2, "适度的"), ("negotiate", 2, "谈判")],
    "英语六级": [("alleviate", 2, "缓解"), ("ambiguous", 2, "模糊的"), ("compulsory", 2, "强制的"), ("deteriorate", 2, "恶化"), ("dilemma", 2, "困境"), ("elaborate", 2, "详尽的/阐述"), ("entail", 2, "需要"), ("feasible", 2, "可行的"), ("hypothesis", 2, "假说"), ("incentive", 2, "激励"), ("legitimate", 2, "合法的"), ("manipulate", 2, "操纵"), ("notorious", 2, "臭名昭著的"), ("prevail", 2, "盛行/获胜"), ("restrain", 2, "抑制"), ("scrutiny", 2, "审查"), ("subsidize", 2, "补贴"), ("undermine", 2, "削弱")],
    "考研英语": [("address", 1, "解决(僻义)"), ("advocate", 2, "提倡者/提倡"), ("coincide", 2, "一致"), ("comprehensive", 2, "全面的"), ("condemn", 2, "谴责"), ("contempt", 2, "轻蔑"), ("discrepancy", 2, "差异"), ("empirical", 2, "实证的"), ("entitle", 2, "使有权/命名"), ("exempt", 2, "免除"), ("implausible", 2, "难以置信的"), ("incline", 2, "倾向"), ("intuition", 2, "直觉"), ("legislation", 2, "立法"), ("manipulate", 2, "操纵"), ("paradox", 2, "悖论"), ("plausible", 2, "貌似合理的"), ("propensity", 2, "倾向")],
}

_DISTRactors = {
    "accommodation": ["娱乐", "交通", "签证"], "enrolment": ["毕业", "放假", "考试"], "itinerary": ["登机牌", "护照", "签证"],
    "recreation": ["教育", "医疗", "交通"], "suburb": ["市中心", "海外", "乡村"], "auditorium": ["图书馆", "实验室", "宿舍"],
    "renewal": ["注销", "挂失", "办理"], "luggage": ["机票", "座位", "护照"], "guidance": ["投诉", "退款", "罚款"],
    "cafeteria": ["图书馆", "宿舍", "体育馆"], "landlord": ["租客", "中介", "管家"], "appointment": ["工资", "考勤", "报销"],
}


def _distract(word, correct_mean, domain_mean):
    """为词义题生成 3 个干扰项: 优先词库干扰, 否则同赛道其他词义"""
    pool = list(_DISTRactors.get(word, []))
    all_words = []
    for tr, ws in _VOCAB.items():
        for w, _, m in ws:
            if w != word and m != correct_mean:
                all_words.append(m)
    random.shuffle(all_words)
    while len(pool) < 3 and all_words:
        m = all_words.pop()
        if m not in pool:
            pool.append(m)
    return pool[:3]


def _vocab_questions(track):
    """由词汇库生成词义选择题"""
    qs = []
    for word, ai, mean in _VOCAB.get(track, []):
        opts = _distract(word, mean, None)
        opts.insert(random.randint(0, 3), mean)
        qs.append((
            f"词汇题:「{word}」最接近的意思是?",
            opts[:4],
            opts.index(mean),
            f"{word} = {mean} ({track} 高频词)。",
            "词汇", random.randint(1, 3),
        ))
    return qs


def _all_items(track):
    """赛道全部基础题 = 考点题 + 词汇题"""
    return list(_KB.get(track, [])) + _vocab_questions(track)


# ============================================================
#  建表
# ============================================================

_DDL = [
    """CREATE TABLE IF NOT EXISTS mt_eng_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track TEXT UNIQUE NOT NULL,
    family TEXT NOT NULL,
    family_en TEXT,
    min_diff INTEGER DEFAULT 1,
    max_diff INTEGER DEFAULT 3,
    description TEXT,
    target_count INTEGER DEFAULT 100,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    """CREATE TABLE IF NOT EXISTS mt_eng_track_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_no INTEGER,
    action TEXT NOT NULL,
    track TEXT,
    input_count INTEGER DEFAULT 0,
    output_count INTEGER DEFAULT 0,
    detail TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
)""",
    # 教学平台联动表 (pedagogy 引擎未 init 时兜底建表)
    """CREATE TABLE IF NOT EXISTS mt_lang_qbank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qcode TEXT UNIQUE NOT NULL,
    language TEXT NOT NULL,
    question TEXT NOT NULL,
    q_type TEXT DEFAULT '语法选择',
    topic TEXT,
    knowledge_points TEXT,
    difficulty INTEGER DEFAULT 3,
    answer TEXT,
    solution TEXT,
    analysis TEXT,
    hints TEXT,
    source TEXT DEFAULT 'engine',
    expert_id TEXT,
    model_ref TEXT,
    quality_score REAL DEFAULT 0.8,
    usage_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
)""",
]


def ensure_tables():
    conn = get_conn()
    c = conn.cursor()
    for sql in _DDL:
        c.execute(sql)
    # 题库内容幂等索引 (与生产 uniq_qb_content 对齐; 旧库已存在则跳过)
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_qb_content ON question_bank(content)")
    except Exception:
        pass
    for tr, fam, fam_en, (d1, d2), desc in TRACKS:
        c.execute("""INSERT INTO mt_eng_tracks (track, family, family_en, min_diff, max_diff, description)
                     VALUES (?,?,?,?,?,?)
                     ON CONFLICT(track) DO UPDATE SET family=excluded.family,
                       family_en=excluded.family_en, min_diff=excluded.min_diff,
                       max_diff=excluded.max_diff, description=excluded.description""",
                  (tr, fam, fam_en, d1, d2, desc))
    conn.commit()
    conn.close()


# ============================================================
#  造题 (幂等, 双写 question_bank + mt_lang_qbank)
# ============================================================

def _diff_map(d):
    return {1: "easy", 2: "easy", 3: "medium", 4: "hard", 5: "hard"}.get(d, "medium")


def generate_questions(track, count=6, cycle_no=1, with_variants=True):
    """为指定赛道造 count 道 + 可选变体题, 幂等入库 (uniq_qb_content 去重)"""
    items = _all_items(track)
    if not items:
        return 0, 0
    conn = get_conn()
    c = conn.cursor()
    added = 0
    dup = 0
    letters = ["A", "B", "C", "D"]
    tries = 0
    while added < count and tries < count * 6:
        tries += 1
        stem, opts, ai, expl, kp, diff = random.choice(items)
        family = next((f for t, f, _, _, _ in TRACKS if t == track), "英语")
        variant = random.randint(0, 8)
        content = stem if variant == 0 else f"{stem} (变体{variant + 1})"
        # 变体时轻微改变正确项位置
        order = list(range(4))
        if variant:
            random.shuffle(order)
        new_opts = [opts[i] for i in order]
        answer = letters[order.index(ai)]
        qb_id = f"eng_{track}_{uuid.uuid4().hex[:8]}"
        try:
            c.execute("""INSERT INTO question_bank
                (question_id, subject, grade, question_type, difficulty, content,
                 options, answer, explanation, knowledge_points, source, source_type,
                 tags, difficulty_text, score)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (qb_id, "英语", track, "single_choice", _diff_map(diff), content,
                 json.dumps(new_opts, ensure_ascii=False), answer, expl,
                 json.dumps([track, family, kp], ensure_ascii=False),
                 SOURCE, "auto",
                 json.dumps([track, family, kp, "英语赛道"], ensure_ascii=False),
                 _diff_map(diff), round(3.0 + diff * 0.4, 1)))
            c.execute("""INSERT INTO mt_lang_qbank
                (qcode, language, question, q_type, topic, knowledge_points,
                 difficulty, answer, solution, analysis, source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (f"ENG-{uuid.uuid4().hex[:10]}", "en", content, "选择题", track,
                 json.dumps([track, kp], ensure_ascii=False), diff, answer,
                 expl, f"赛道: {track} / 考点: {kp} / {_FLOW}", SOURCE))
            added += 1
        except sqlite3.IntegrityError:
            dup += 1  # uniq_qb_content 命中重复 → 跳过
        except Exception as e:
            # 真异常: 回滚本轮并留痕, 禁止静默吞错 (IRON_RULE)
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            _log("GEN_ERROR", track, tries, added, str(e)[:200])
            return added, dup
    conn.commit()
    conn.close()
    return added, dup


def seed_all_tracks(per_track=30):
    """首轮全赛道播种"""
    ensure_tables()
    total = 0
    log = {}
    for tr, _, _, _, _ in TRACKS:
        added, dup = generate_questions(tr, per_track, 0, with_variants=True)
        log[tr] = added
        total += added
    _log("SEED_ALL", None, sum(log.values()), total, json.dumps(log, ensure_ascii=False))
    return {"total": total, "per_track": log}


# ============================================================
#  课程挂接 (联动 ai_language_pedagogy_engine 的 mt_lang_* 表)
# ============================================================

def seed_track_courses():
    """为 15 条赛道在 mt_lang_courses 建课程 + 挂 4 课时 (幂等)"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS mt_lang_courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_code TEXT UNIQUE NOT NULL,
        language TEXT NOT NULL, cefr TEXT NOT NULL, native_level TEXT,
        title TEXT NOT NULL, description TEXT,
        difficulty INTEGER DEFAULT 1, lesson_count INTEGER DEFAULT 0,
        order_no INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime')))""")
    c.execute("""CREATE TABLE IF NOT EXISTS mt_lang_lessons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lesson_code TEXT UNIQUE NOT NULL,
        course_code TEXT NOT NULL, title TEXT NOT NULL,
        lesson_type TEXT NOT NULL, content TEXT,
        difficulty INTEGER DEFAULT 1, order_no INTEGER DEFAULT 0)""")
    n = 0
    for i, (tr, fam, fam_en, (d1, d2), desc) in enumerate(TRACKS):
        code = f"EN-{fam_en}"
        c.execute("""INSERT INTO mt_lang_courses (course_code, language, cefr, native_level,
                     title, description, difficulty, lesson_count, order_no)
                     VALUES (?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(course_code) DO UPDATE SET description=excluded.description""",
                  (code, "en", fam_en[:3], tr, f"{fam} · {tr}", desc,
                   (d1 + d2) // 2, 4, 100 + i))
        for li, lt in enumerate(["vocab", "grammar", "listening", "speaking"]):
            c.execute("""INSERT INTO mt_lang_lessons (lesson_code, course_code, title,
                         lesson_type, content, difficulty, order_no)
                         VALUES (?,?,?,?,?,?,?)
                         ON CONFLICT(lesson_code) DO NOTHING""",
                      (f"{code}-L{li + 1}", code, f"{tr} · {lt}", lt,
                       json.dumps({"track": tr, "type": lt}, ensure_ascii=False),
                       (d1 + d2) // 2, li))
            n += 1
    conn.commit()
    conn.close()
    return n


# ============================================================
#  学情总览 + 健康
# ============================================================

def track_overview():
    """15 赛道: 题量 / 平均难度 / 模考正确率 / 健康度"""
    conn = get_conn()
    c = conn.cursor()
    out = []
    for tr, fam, fam_en, _, desc in TRACKS:
        row = c.execute("""SELECT COUNT(*) cnt, AVG(CASE difficulty
                        WHEN 'easy' THEN 1 WHEN 'medium' THEN 3 ELSE 4 END) avg_d
                        FROM question_bank WHERE subject='英语' AND grade=? AND status='published'""",
                    (tr,)).fetchone()
        cnt = row["cnt"] or 0
        acc = 0.0
        try:
            acc = c.execute("""SELECT AVG(er.is_correct) acc FROM exam_results er
                            JOIN question_bank qb ON qb.question_id = er.question_id
                            WHERE qb.grade=?""", (tr,)).fetchone()["acc"] or 0.0
        except Exception:
            acc = 0.0  # exam_results 尚未建表 (考试院 daemon 首跑前)
        out.append({
            "track": tr, "family": fam, "family_en": fam_en,
            "questions": cnt, "avg_difficulty": round(row["avg_d"] or 0, 1),
            "accuracy": round(acc * 100, 1),
            "healthy": cnt >= 50,
            "description": desc,
        })
    conn.close()
    return out


# ============================================================
#  Daemon: 自动补题闭环
# ============================================================

def _log(action, track, inp, outp, detail=""):
    conn = get_conn()
    conn.execute("""INSERT INTO mt_eng_track_log (cycle_no, action, track, input_count, output_count, detail)
                    VALUES ((SELECT COALESCE(MAX(cycle_no),0)+1 FROM mt_eng_track_log),?,?,?,?,?)""",
                (action, track, inp, outp, detail))
    conn.commit()
    conn.close()


def daemon_cycle(cycle_no=0):
    """每轮: 题量<50 的赛道优先补 12 题, 其余随机 3 赛道各补 6 题 (零 token)"""
    ensure_tables()
    ov = track_overview()
    weak = [o for o in ov if not o["healthy"]]
    others = [o for o in ov if o["healthy"]]
    random.shuffle(others)
    targets = [(o["track"], 12) for o in weak] + [(o["track"], 6) for o in others[:3]]
    added_total = 0
    for tr, n in targets:
        added, dup = generate_questions(tr, n, cycle_no)
        added_total += added
    _log("DAEMON_CYCLE", None, len(targets), added_total,
         json.dumps({"targets": [t for t, _ in targets]}, ensure_ascii=False))
    return {"tracks": len(targets), "added": added_total}


def run_daemon_loop(interval=1800):
    import time
    while True:
        try:
            daemon_cycle()
        except Exception as e:
            try:
                _log("DAEMON_ERROR", None, 0, 0, str(e)[:200])
            except Exception:
                pass
        time.sleep(interval)


# ============================================================
#  CLI
# ============================================================

def _cli_init():
    ensure_tables()
    r = seed_all_tracks(per_track=30)
    seed_track_courses()
    ov = track_overview()
    print(f"[{_FLOW}] init 完成: 播种 {r['total']} 题")
    for o in ov:
        print(f"  {o['track']:<8} {o['family']:<5} 题量={o['questions']:<4} 健康={'√' if o['healthy'] else '×'}")
    print("使用: expand=补题一轮 / status=总览")


def _cli_expand():
    r = daemon_cycle()
    print(f"[{_FLOW}] expand: 补 {r['tracks']} 赛道, 新增 {r['added']} 题")


def _cli_status():
    ov = track_overview()
    total = sum(o["questions"] for o in ov)
    print(f"[{_FLOW}] 15 赛道总题量: {total}")
    for o in ov:
        flag = "√" if o["healthy"] else "× NEED"
        print(f"  {o['track']:<8} {o['family']:<5} 题量={o['questions']:<5} 正确率={o['accuracy']}% {flag}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "init":
        _cli_init()
    elif cmd == "expand":
        _cli_expand()
    elif cmd == "status":
        _cli_status()
    else:
        print("用法: python3 ai_english_track_engine.py [init|expand|status]")
