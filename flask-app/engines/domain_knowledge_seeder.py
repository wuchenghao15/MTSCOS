#!/usr/bin/env python3
"""
仙女座专业知识库种子注入器 — domain_knowledge_seeder.py
=======================================================
驱动: 一次性种子脚本 + 后续由 auto_evolution 自动扩写
目的: 给 7 大专业领域 (中医药/现代医学/乐理/日语/英语/大数据/论文) 注入核心术语 + 教材摘要 + 关键论文
      → nomic-embed-text 向量化 → mt_vector_knowledge 表
      → qwen2.5 7b/14b 通过 RAG 自动检索解释

设计:
  - 结构化种子数据 → JSON 内嵌 (不依赖外部文件, 开箱即用)
  - 每个种子条目: {domain, term, definition, source, context}
  - embed → SQLite FTS + pgvector-like 语义搜索 (自实现 cosine)
  - 后续 auto_evolution 扩写时自动追加新术语

FLOW_ID: flow_andromeda_awakening_20261025
"""
from __future__ import annotations
import json, sqlite3, hashlib, time, urllib.request, urllib.error, uuid
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "database" / "app.db"

# ── nomic-embed-text 向量化端点 ──
EMBED_HOST = "127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text:latest"
EMBED_DIM = 768


def embed(text: str) -> list[float] | None:
    """调 mini 本地 Ollama nomic-embed-text"""
    url = f"http://{EMBED_HOST}/api/embeddings"
    try:
        data = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
        with urllib.request.urlopen(urllib.request.Request(url, data=data,
                headers={"Content-Type": "application/json"}), timeout=30) as resp:
            r = json.loads(resp.read().decode())
            return r.get("embedding")
    except Exception as e:
        print(f"  embed fail: {e}")
        return None


# ── 专业领域种子数据 ──
SEEDS = {
    "中医药": [
        {"term": "阴阳学说", "definition": "中医核心理论: 宇宙万物由阴阳对立统一构成, 人体生理病理皆可用阴阳解释. 阳化气, 阴成形; 阳在外阴之使也, 阴在内阳之守也.", "source": "黄帝内经·素问", "context": "中医八纲辨证总纲, 贯穿病因病机诊断治疗"},
        {"term": "五行学说", "definition": "木火土金水相生相克: 肝木→心火→脾土→肺金→肾水; 木克土, 土克水, 水克火, 火克金, 金克木. 对应人体五脏六腑五志五味.", "source": "黄帝内经·素问", "context": "藏象学说基础, 用于脏腑关系病理传变分析"},
        {"term": "藏象学说", "definition": "肝心脾肺肾五脏 (藏精气而不泻) + 胆胃小肠大肠膀胱三焦六腑 (传化物而不藏). 肝主疏泄藏血, 心主血脉藏神, 脾主运化统血, 肺主气司呼吸, 肾主藏精主水.", "source": "黄帝内经·素问·灵兰秘典论", "context": "中医生理病理核心框架, 所有疾病分析起点"},
        {"term": "经络系统", "definition": "十二正经 + 八奇脉 (任督带冲跷阴阳维) + 络脉. 十二正经: 手三阴三阳 + 足三阴三阳, 循环流注昼夜五十周.", "source": "黄帝内经·灵枢·经脉", "context": "针灸取穴, 药物归经, 循经辨证"},
        {"term": "四气五味", "definition": "药物属性: 寒凉温热 (四气) + 酸苦甘辛咸 (五味). 酸入肝, 苦入心, 甘入脾, 辛入肺, 咸入肾. 升浮降沉: 花叶升浮, 种子根茎降沉.", "source": "神农本草经", "context": "中药药性理论, 方剂配伍依据"},
        {"term": "八纲辨证", "definition": "阴阳表里寒热虚实八类基本证候. 阴阳总纲, 表里病位, 寒热病性, 虚实盛衰.", "source": "景岳全书·传忠录", "context": "所有辨证方法的总纲, 先辨八纲再辨脏腑经络"},
        {"term": "六经辨证", "definition": "太阳阳明少阳太阴少阴厥阴. 太阳主表, 阳明主里热, 少阳半表半里, 太阴脾寒, 少阴心肾两虚, 厥阴寒热错杂.", "source": "伤寒论", "context": "张仲景外感辨证体系, 伤寒六经传变规律"},
        {"term": "卫气营血辨证", "definition": "卫分→气分→营分→血分. 叶天士温病辨证: 卫之后方言气, 营之后方言血. 卫分宜辛凉解肌, 气分宜清热生津, 营分宜清营透热, 血分宜凉血散血.", "source": "叶天士·温热论", "context": "温病学派核心辨证, 用于外感热病层次分析"},
        {"term": "脏腑辨证", "definition": "心气虚/心血虚/心阴虚/心阳虚/心火亢盛; 肝郁气滞/肝火上炎/肝血虚/肝阴虚/肝阳上亢/肝风内动; 脾气虚/脾阳虚/脾不统血/湿困脾阳; 肺气虚/肺阴虚/风寒束肺/风热犯肺/痰热壅肺; 肾阴虚/肾阳虚/肾精不足/肾气不固.", "source": "中医基础理论", "context": "临床最常用辨证方法, 内伤杂病首选"},
        {"term": "中药归经", "definition": "药物选择性作用于某脏腑经络. 柴胡入肝胆经疏肝解郁, 麻黄入肺经宣肺平喘, 石膏入肺胃经清热泻火. 依据: 五味入五脏 + 临床验证.", "source": "本草纲目·序例", "context": "方剂配伍核心原则, 引经报使药如桔梗载药上行至肺, 牛膝引药下行至肾"},
        {"term": "君臣佐使", "definition": "方剂配伍原则: 君药 (针对主证主病, 量最大) + 臣药 (助君药或治兼证) + 佐药 (监制毒烈或反佐) + 使药 (引经报使或调和). 例: 麻黄汤 麻黄君 桂枝臣 杏仁佐 炙甘草使.", "source": "黄帝内经·素问·至真要大论", "context": "方剂学基本理论, 所有经方时方皆循此"},
        {"term": "伤寒", "definition": "广义: 一切外感热病总称. 狭义: 伤寒论所论伤寒, 特指外感寒邪引起的六经传变. 伤寒论 113 方为群方之祖.", "source": "伤寒论·张仲景", "context": "中医四大经典之一, 方剂鼻祖, 辨证论治源头"},
        {"term": "温病", "definition": "温病学派: 风温春温暑温湿温秋燥冬温. 卫气营血辨证 + 三焦辨证. 代表: 叶天士温热论 + 吴鞠通温病条辨 + 王孟英温热经纬.", "source": "温病条辨·吴鞠通", "context": "明清温病学派, 弥补伤寒论在外感热病上的不足"},
        {"term": "针灸得气", "definition": "针刺后患者产生酸麻胀重等感觉 + 医者感到针下沉紧如鱼吞钩饵. 得气则有效, 不得气则调整手法或腧穴. 气至而有效, 效之信若风之吹云.", "source": "黄帝内经·灵枢·九针十二原", "context": "针灸疗效关键指标"},
    ],
    "现代医学": [
        {"term": "循证医学 (EBM)", "definition": "Evidence-Based Medicine: 临床决策需基于当前最佳证据 + 临床经验 + 患者意愿. 证据等级: 1a 系统综述/Meta分析 > 1b 随机对照试验 (RCT) > 2a 队列研究 > 3a 病例对照 > 4 病例报告 > 5 专家意见.", "source": "Oxford Centre for Evidence-Based Medicine", "context": "现代医学决策黄金标准, 指南制定依据"},
        {"term": "ICD-11", "definition": "国际疾病分类第11版, WHO 2018年发布. 编码结构: 字母+数字+数字+扩展码. 包含传统医学章节 (TCM VM1-9) 和功能评估 (ICF). 替代 ICD-10.", "source": "WHO", "context": "全球疾病统计 + 医保编码 + 临床记录标准"},
        {"term": "组学 (Omics)", "definition": "基因组学 (genomics) + 转录组学 (transcriptomics) + 蛋白质组学 (proteomics) + 代谢组学 (metabolomics) + 表观基因组学 (epigenomics) + 宏基因组学 (microbiomics). 多组学联合分析 = 系统生物学.", "source": "Nature Reviews Genetics 2022", "context": "精准医疗 + 个体化治疗 + 生物标志物发现"},
        {"term": "精准医疗", "definition": "Precision Medicine: 基于个体基因组 + 临床表型 + 生活方式 + 环境因素定制预防治疗方案. 例: 肺癌 EGFR 突变 → 奥希替尼靶向; BRCA1/2 突变 → PARP 抑制剂.", "source": "President's Council of Advisors on Science and Technology 2011", "context": "癌症治疗 + 罕见病 + 药物基因组学"},
        {"term": "药物基因组学 (PGx)", "definition": "Pharmacogenomics: 基因变异如何影响药物代谢和疗效. 关键酶: CYP2D6 (他莫昔芬) + CYP2C19 (氯吡格雷) + CYP2C9 (华法林). FDA 已批准 300+ PGx 标签.", "source": "FDA Pharmacogenomics", "context": "避免药物不良反应 + 个体化给药剂量"},
        {"term": "生物标志物 (Biomarker)", "definition": "可客观测量的生理/病理指标. 类型: 诊断性 (PSA前列腺癌) + 预后性 (HER2乳腺癌) + 预测性 (EGFR突变 vs 奥希替尼疗效) + 药效性. FDA 批准伴随诊断 (CDx) 需同步开发.", "source": "FDA Biomarker Qualification", "context": "药物开发 + 疾病早筛 + 疗效监测"},
        {"term": "临床研究四期", "definition": "Ⅰ期 (20-100人, 安全性, 剂量) → Ⅱ期 (100-500人, 有效性+安全性, 对照) → Ⅲ期 (1000-5000人, 大规模验证, 多中心, RCT) → Ⅳ期 (上市后, 真实世界数据, 长期安全性).", "source": "ICH GCP E6(R2)", "context": "新药审批 FDA/NMPA 核心路径"},
        {"term": "真实世界证据 (RWE)", "definition": "Real-World Evidence: 临床常规实践中产生的数据 (电子病历 + 医保 + 疾病登记库). FDA 2016 年正式接受 RWE 用于上市后研究 + 某些加速审批.", "source": "FDA Real-World Evidence Framework", "context": "补充 RCT 局限性 + 罕见病药物开发"},
    ],
    "大数据分析": [
        {"term": "向量数据库", "definition": "Vector Database: 将文本/图像/音频编码为高维向量 (embedding), 用近似最近邻 (ANN) 索引实现语义搜索. 主流: Pinecone, Weaviate, Milvus, Qdrant, Chroma, pgvector (PostgreSQL 扩展). 核心算法: HNSW, IVF-PQ, FAISS.", "source": "Pinecone Engineering Blog 2024", "context": "RAG 检索增强生成 + 语义搜索引擎"},
        {"term": "RAG 检索增强生成", "definition": "Retrieval-Augmented Generation: 先检索相关文档 (向量相似度) → 注入 LLM prompt context → 生成回答. 解决 LLM 幻觉 + 知识过时. 关键组件: embedding model + vector store + chunking strategy + reranker.", "source": "Lewis et al., arXiv:2005.11401 (2020)", "context": "企业知识库 + 问答系统 + 文献综述"},
        {"term": "Transformer 注意力机制", "definition": "Scaled Dot-Product Attention: Attention(Q,K,V) = softmax(QK^T/√d_k)V. Multi-Head Attention: 多个注意力头并行. 位置编码解决顺序丢失. BERT (encoder) + GPT (decoder) 架构差异.", "source": "Vaswani et al., NeurIPS 2017 'Attention Is All You Need'", "context": "所有现代 LLM 基础架构"},
        {"term": "LoRA 微调", "definition": "Low-Rank Adaptation: 冻结预训练权重 W, 训练低秩增量 ΔW = BA (B∈R^{d×r}, A∈R^{r×k}, r<<min(d,k)). 参数高效 (仅训练 1-10%), 显存需求低, 可插拔切换多任务. QLoRA 加 bitsandbytes 4-bit 量化.", "source": "Hu et al., ICML 2022 'LoRA: Low-Rank Adaptation'", "context": "领域自适应 + 多任务学习 + 低成本微调"},
        {"term": "强化学习人类反馈 (RLHF)", "definition": "RLHF: ① 收集人类偏好数据 (比较 A vs B) → ② 训练奖励模型 (Reward Model, RM) 拟合偏好 → ③ 用 PPO 算法基于 RM 微调 LLM. InstructGPT/Claude/ChatGPT 核心训练方法. DPO 是更简单替代 (直接对比学习, 无需 RM).", "source": "Ouyang et al., NeurIPS 2022 'Training language models to follow instructions with human feedback'", "context": "对齐 LLM 与人类价值观 + 指令遵循"},
        {"term": "Pandas DataFrame", "definition": "pandas.core.frame.DataFrame: 二维异构表格, 带行索引和列标签. 核心方法: groupby (SQL GROUP BY), merge (JOIN), pivot_table, apply (行/列函数), loc/iloc (索引). 与 SQL 对比: pandas = Python 内存 SQL, SQL = 磁盘 SQL.", "source": "pandas documentation v2.0+", "context": "数据清洗 + ETL + 探索性分析 (EDA)"},
    ],
    "乐理": [
        {"term": "和声学", "definition": "研究和弦构造 + 连接规则 + 调性. 三和弦 (三度叠加) 七和弦 (四度叠加). 功能体系: T (主) S (下属) D (属). 数字低音: 罗马数字 I ii iii IV V vi vii°. 终止式: 正格终止 V→I, 变格终止 IV→I, 伪终止 V→vi.", "source": "斯波索宾和声学教程", "context": "巴洛克到浪漫主义作曲基础, 钢琴即兴伴奏"},
        {"term": "十二平均律", "definition": "12-Tone Equal Temperament: 八度等分成 12 个半音, 每个半音频率比 2^(1/12) ≈ 1.05946. C4=261.63Hz, A4=440Hz (标准音高). 巴赫平均律钢琴曲集 48 首证明所有调性可用.", "source": "Zhu Zaiyu 1584 + Andreas Werckmeister 1691", "context": "现代钢琴/吉他所有调性自由转调基础"},
        {"term": "调式体系", "definition": "七种教会调式 + 大小调. Ionian (自然大调) / Dorian / Phrygian / Lydian / Mixolydian / Aeolian (自然小调) / Locrian. 每种调式的半音结构 + 主音三和弦性质不同.", "source": "Gregorian Chant 传统", "context": "爵士乐 + 摇滚 + 电影配乐色彩选择"},
        {"term": "对位法", "definition": "Counterpoint: 两条或多条独立旋律线同时进行, 不构成和声冲突. 五种: 一对一 (note against note), 一对二, 一对四, 切分音, 花腔. 巴赫赋格是对位法巅峰.", "source": "Fux Gradus ad Parnassum (1725)", "context": "复调音乐 + 赋格 + 卡农"},
        {"term": "曲式学", "definition": "Musical Form: 乐段 (Period, 8-16 小节, 半终止+正格终止) → 二段式 (Binary, A+B) → 三段式 (Ternary, A+B+A) → 回旋曲式 (Rondo, A+BA+CA+...) → 奏鸣曲式 (Sonata, 呈示部+展开部+再现部).", "source": "Clemens Kühn Formenlehre", "context": "音乐分析 + 作曲结构框架"},
    ],
    "日语": [
        {"term": "日本语能力测试 (JLPT)", "definition": "JLPT N5 (入门) → N4 (基础) → N3 (中级) → N2 (上级) → N1 (最高). 测试: 文字词汇 + 文法 + 读解 + 听力. N2 ≈ 母语水平日常交流, N1 ≈ 学术/商务. 合格率: N1 ≈ 40%, N5 ≈ 80%.", "source": "JLPT 官方", "context": "日语学习进度评估 + 留学/就业标准"},
        {"term": "五十音图", "definition": "5 元音 (あいうえお) × 10 辅音 (かさたなはまやらわ) = 50 基本音节. 清音 → 浊音 (がざだば) → 半浊音 (ぱぴぷぺぽ) → 拗音 (きゃしゃちゃ...) → 长音 (ー) → 促音 (っ). 片假名 (外来语) vs 平假名 (日语固有词).", "source": "日本语文法书", "context": "日语入门第一关, 所有单词发音基础"},
        {"term": "敬语体系", "definition": "尊敬语 (そんけいご, 抬高对方: いらっしゃる なさる 召し上がる) + 谦让语 (けんじょうご, 谦虚自己: 参る 申す いただく) + 丁宁语 (ていねいご, 礼貌: です ます). 规则: 对上司/客户/陌生人必须用敬语; 对朋友/家人不用.", "source": "日本语教育文法", "context": "商务日语 + 敬语是日语社交核心"},
        {"term": "助词", "definition": "日语助词: 格助词 (をにでへとからまでより) + 提示助词 (はも) + 副助词 (だけしかばかり) + 终助词 (かよねわ). は vs が: は话题标记, が主语焦点标记. を宾语, に对象/地点/时间, で手段/场所.", "source": "金田一春彦『日本语文法』", "context": "日语语法核心, 句子意思主要靠助词区分"},
    ],
    "英语": [
        {"term": "托福 (TOEFL)", "definition": "TOEFL iBT: Reading (35min 20题) + Listening (36min 28题) + Speaking (16min 4题) + Writing (29min 2题). 满分 120, 美国大学本科最低 80+, 藤校 105+. 有效期 2 年.", "source": "ETS", "context": "美本/美研留学申请 + 奖学金评估"},
        {"term": "雅思 (IELTS)", "definition": "IELTS Academic (学术) / General Training (移民). Listening (40题) + Reading (40题) + Writing (2篇) + Speaking (11-14min 面试). 0-9 分制, 单项不低于某分. 英国/澳洲/加拿大主流.", "source": "British Council", "context": "英联邦留学 + 技术移民 + 工作签证"},
        {"term": "GRE", "definition": "GRE General Test: Verbal Reasoning (130-170) + Quantitative Reasoning (130-170) + Analytical Writing (0-6). 计算机自适应, 3 小时 45 分. 美国研究生 (除法学/商科) 标准.", "source": "ETS", "context": "美研申请, 尤其是 CS/工程/社科"},
        {"term": "核心英语词根 (Latin/Greek)", "definition": "英语 60% 词汇源自拉丁语 + 希腊语. 核心词根: spect (看 inspect respect), port (运 transport export), dict (说 predict dictionary), struct (建 construct structure), duct (引 conduct introduce). 掌握 100 词根 ≈ 认识 10000+ 单词.", "source": "Oxford Dictionary of Word Origins", "context": "词汇量快速扩展 + 单词记忆法"},
        {"term": "学术写作 IMRaD", "definition": "Introduction (背景+gap+目的) + Methods (设计+样本+分析) + Results (描述+表格) + Discussion (解释+意义+局限). 所有 SCI/SSCI 论文标准结构. 每个部分有特定时态: Introduction 现在时, Methods 过去时, Results 现在时 + 过去时.", "source": "Publication Manual of APA 7th", "context": "论文写作 + SCI 投稿"},
    ],
    "论文科研": [
        {"term": "SCI 论文结构", "definition": "SCI (Science Citation Index) 收录期刊论文. 标准结构: Title → Author/Affiliation → Abstract (背景+目的+方法+结果+结论) → Keywords → Introduction → Methods → Results → Discussion → Conclusion → References → Supplementary Materials. 影响因子 (IF) 每两年更新.", "source": "Web of Science", "context": "学术发表 + 引用指标 + 职称评审"},
        {"term": "Meta 分析", "definition": "Meta-analysis: 系统综述的统计方法, 合并多个独立研究的效应量. 步骤: PRISMA 系统检索 → 纳入/排除 → 质量评估 (Cochrane risk of bias) → 效应量合并 (固定效应模型 vs 随机效应模型) → 异质性检验 (I² statistic). 权威来源: Cochrane Library.", "source": "Cochrane Handbook v6.5", "context": "循证医学 + 公共卫生政策 + 系统综述最高证据级别"},
        {"term": "同行评议 (Peer Review)", "definition": "审稿模式: Single-blind (匿名审稿人) / Double-blind (匿名双方) / Open (双方公开). 审稿人需检查: 原创性 + 方法严谨性 + 数据可信度 + 伦理合规. PubMed Central + arXiv 预印本先发布后评议.", "source": "COPE Guidelines", "context": "学术质量把关 + 论文发表核心机制"},
        {"term": "DOI (Digital Object Identifier)", "definition": "永久标识符, 格式: 10.TARGET/PREFIX.SUFFIX. 例: 10.1038/s41586-023-05678-9. 分配: Crossref (主要) + DataCite + mEDRA. 自动解析 → 文献全文 URL. 比 URL 稳定.", "source": "International DOI Foundation", "context": "学术引用 + 数据可追溯 + 永久访问"},
    ],
}


def init_tables(db: sqlite3.Connection):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS mt_domain_knowledge (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        domain      TEXT NOT NULL,
        term        TEXT NOT NULL,
        definition  TEXT NOT NULL,
        source      TEXT,
        context     TEXT,
        embed       BLOB,                      -- 768-dim float32 向量
        embed_dim   INTEGER DEFAULT 768,
        embed_model TEXT DEFAULT 'nomic-embed-text',
        term_hash   TEXT UNIQUE,
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_dk_domain ON mt_domain_knowledge(domain);
    CREATE INDEX IF NOT EXISTS idx_dk_term   ON mt_domain_knowledge(term);
    """)
    db.commit()


def seed_all(db_path: Path = DB) -> dict:
    """向量化 + 入库 + 返回统计"""
    # 等本地 Ollama 起
    import time as _t
    for _ in range(6):
        try:
            embed("test")
            break
        except:
            print(f"  等 Ollama...", end=" ")
            _t.sleep(2)

    db = sqlite3.connect(str(db_path), timeout=15)
    init_tables(db)
    c = db.cursor()

    total = 0
    seeded = 0
    failed = 0

    for domain, terms in SEEDS.items():
        print(f"\n=== {domain}: {len(terms)} 术语 ===", flush=True)
        for item in terms:
            total += 1
            h = hashlib.md5(f"{item['domain']}::{item['term']}".encode()).hexdigest()
            c.execute("SELECT id FROM mt_domain_knowledge WHERE term_hash=?", (h,))
            if c.fetchone():
                continue  # 已存在

            # embed(term + definition → 更好语义)
            text = f"{item['domain']}: {item['term']} — {item['definition']}"
            vec = embed(text)
            if not vec:
                failed += 1
                continue

            # float32 → BLOB
            import struct
            blob = struct.pack(f"<{len(vec)}f", *vec)

            c.execute("""
                INSERT INTO mt_domain_knowledge
                (domain, term, definition, source, context, embed, embed_dim, term_hash)
                VALUES (?,?,?,?,?,?,?,?)""",
                (item["domain"], item["term"], item["definition"],
                 item.get("source", ""), item.get("context", ""),
                 blob, len(vec), h))
            seeded += 1
            print(f"  ✅ {item['term'][:20]}", flush=True)
            _t.sleep(0.3)  # Ollama ratelimit

        db.commit()

    print(f"\n=== 种子完成: {seeded}/{total} 入库, {failed} 失败 ===", flush=True)

    # 报告
    c.execute("SELECT domain, COUNT(*) FROM mt_domain_knowledge GROUP BY domain")
    for row in c.fetchall():
        print(f"  {row[0]}: {row[1]} terms")

    db.close()
    return {"total": total, "seeded": seeded, "failed": failed}


def search(query: str, top_k: int = 5) -> list[dict]:
    """语义搜索: query embed → cosine sim → 返回 top_k"""
    import struct, math
    vec = embed(query)
    if not vec:
        return []

    db = sqlite3.connect(str(DB), timeout=10)
    c = db.cursor()
    c.execute("SELECT domain, term, definition, source, context, embed FROM mt_domain_knowledge WHERE embed IS NOT NULL")

    results = []
    q_norm = math.sqrt(sum(v * v for v in vec))
    for row in c.fetchall():
        blob = row[5]
        d = struct.unpack(f"<{len(blob)//4}f", blob)
        dot = sum(a * b for a, b in zip(vec, d))
        d_norm = math.sqrt(sum(v * v for v in d))
        if q_norm > 0 and d_norm > 0:
            sim = dot / (q_norm * d_norm)
            results.append({
                "domain": row[0], "term": row[1],
                "definition": row[2], "source": row[3],
                "context": row[4], "similarity": round(sim, 4)
            })

    db.close()
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    print("\n" + "="*60)
    print("仙女座专业知识库种子注入器")
    print("7 领域: 中医药 / 现代医学 / 乐理 / 日语 / 英语 / 大数据 / 论文科研")
    print("="*60 + "\n")
    result = seed_all()
    print(f"\n最终: {result['seeded']} seeds, {result['failed']} failed")
    print("使用: from domain_knowledge_seeder import search; search('什么是阴阳学说')")
