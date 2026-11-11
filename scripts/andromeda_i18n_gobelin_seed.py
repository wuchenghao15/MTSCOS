#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
古灵阁双终端 i18n 批量录入 (mt_i18n_keys)
==========================================
- 键域: gobelin.term.* (双终端共用) / gobelin.sandbox.* / gobelin.live.*
- 语种: zh_cn(源) / zh_tw / ja_jp / en_us
- 幂等: INSERT OR IGNORE, 可重复执行
- 目标库: core.db_path.get_db_path('app.db') 权威解析 (本地 129MB app.db)

Run: python3 flask-app/scripts/andromeda_i18n_gobelin_seed.py
"""
from __future__ import annotations
import os, sys, sqlite3, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.db_path import get_db_path  # noqa: E402

DB = get_db_path('app.db')
NOW = lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# (key, zh_cn, zh_tw, ja_jp, en_us)
GOBELIN_I18N = [
    # ── 页面框架 ─────────────────────────────────────────────
    ("gobelin.term.title", "古灵阁 · 证券交易沙盘 · v3.0", "古靈閣 · 證券交易沙盤 · v3.0", "グリンゴッツ · 証券取引サンドボックス · v3.0", "Gringotts · Securities Trading Sandbox · v3.0"),
    ("gobelin.term.brand", "青瓷操盘台", "青瓷操盤台", "青磁オペレーション台", "Celadon Trading Desk"),
    ("gobelin.live.title", "古灵阁证券交易系统（实盘） · Celadon Terminal", "古靈閣證券交易系統（實盤） · Celadon Terminal", "グリンゴッツ証券取引システム（実弾） · Celadon Terminal", "Gringotts Securities Trading System (Live) · Celadon Terminal"),
    ("gobelin.live.badge", "LIVE MODE · 真金白银实盘", "LIVE MODE · 真金白銀實盤", "LIVE MODE · 実弾トレード", "LIVE MODE · Real Money Trading"),
    ("gobelin.live.current_mode", "当前模式:", "目前模式:", "現在のモード:", "Current Mode:"),
    ("gobelin.live.risk_cushion", "风险垫:", "風險墊:", "リスククッション:", "Risk Cushion:"),
    ("gobelin.live.mode.dry_run", "DRY_RUN 干跑", "DRY_RUN 乾跑", "DRY_RUN ドライラン", "DRY_RUN"),
    ("gobelin.live.mode.paper", "PAPER 纸面", "PAPER 紙面", "PAPER ペーパー", "PAPER Trading"),
    ("gobelin.live.mode.live", "LIVE 实盘", "LIVE 實盤", "LIVE 実弾", "LIVE"),
    ("gobelin.live.confirm.switch", "切到 LIVE 后, 每一次下单都是真金白银!\n确认继续?", "切到 LIVE 後, 每一次下單都是真金白銀!\n確認繼續?", "LIVE に切り替えると、全ての注文が実弾になります!\n続行しますか?", "After switching to LIVE, every order is real money!\nConfirm to continue?"),
    ("gobelin.live.confirm.double", "二次确认: 真的要让 AI 军团直接对接中信证券 API 吗?", "二次確認: 真的要讓 AI 軍團直接對接中信證券 API 嗎?", "二次確認: AI 軍団を中信証券 API に直接接続しますか?", "Double confirm: really let the AI Legion connect directly to CITIC Securities API?"),
    ("gobelin.term.err.conn", "沙盘服务连接失败，正在重试…", "沙盤服務連接失敗，正在重試…", "サンドボックス接続失敗、再試行中…", "Sandbox service connection failed, retrying…"),
    ("gobelin.term.err.perm", "权限不足：沙盘仅 SA / CAOPW 可访问，请从 www.mtos.site 登录后重试。", "權限不足：沙盤僅 SA / CAOPW 可訪問，請從 www.mtos.site 登入後重試。", "権限不足：サンドボックスは SA / CAOPW のみアクセス可能。www.mtos.site からログインしてください。", "Permission denied: sandbox is SA / CAOPW only. Please login via www.mtos.site and retry."),

    # ── 市场阶段 / 交易时段 ──────────────────────────────────
    ("gobelin.term.phase.call_auction", "集合竞价", "集合競價", "集合競價", "Call Auction"),
    ("gobelin.term.phase.continuous", "连续竞价", "連續競價", "連続競價", "Continuous Auction"),
    ("gobelin.term.phase.closed", "收盘", "收盤", "引け", "Closed"),
    ("gobelin.term.phase.suspended", "停牌", "停牌", "売買停止", "Suspended"),
    ("gobelin.term.phase.lunch", "午休", "午休", "昼休み", "Lunch Break"),
    ("gobelin.term.hours.closed", "非交易时段", "非交易時段", "取引時間外", "Non-trading Hours"),
    ("gobelin.term.hours.am", "上午 9:30-11:30", "上午 9:30-11:30", "午前 9:30-11:30", "AM 9:30-11:30"),
    ("gobelin.term.hours.pm", "下午 13:00-15:00", "下午 13:00-15:00", "午後 13:00-15:00", "PM 13:00-15:00"),
    ("gobelin.term.hours.close", "收市 15:00", "收市 15:00", "大引け 15:00", "Market Close 15:00"),

    # ── 事件 / 信号 ─────────────────────────────────────────
    ("gobelin.term.event.market_anomaly", "市场异动", "市場異動", "市場異動", "Market Anomaly"),
    ("gobelin.term.event.big_wave", "大幅波动", "大幅波動", "大幅変動", "Major Fluctuation"),
    ("gobelin.term.event.ma_cross", "均线交叉", "均線交叉", "移動平均クロス", "MA Cross"),
    ("gobelin.term.event.volume_surge", "放量异动", "放量異動", "出来高急増異動", "Volume Surge"),
    ("gobelin.term.signal.buy", "买入信号", "買入信號", "買いシグナル", "Buy Signal"),
    ("gobelin.term.signal.sell", "卖出信号", "賣出信號", "売りシグナル", "Sell Signal"),

    # ── 页签 / 面板 ─────────────────────────────────────────
    ("gobelin.term.tab.position", "持仓", "持倉", "ポジション", "Positions"),
    ("gobelin.term.tab.deal", "成交", "成交", "約定", "Deals"),
    ("gobelin.term.tab.board", "董事会", "董事會", "取締役会", "Board"),
    ("gobelin.term.tab.intercept", "订单拦截", "訂單攔截", "注文拦截", "Order Intercept"),
    ("gobelin.term.tab.engine", "引擎", "引擎", "エンジン", "Engines"),
    ("gobelin.term.tab.rule", "规则", "規則", "ルール", "Rules"),
    ("gobelin.term.tab.risk", "风控", "風控", "リスク管理", "Risk Control"),
    ("gobelin.term.tab.rebalance", "调仓", "調倉", "リバランス", "Rebalance"),
    ("gobelin.term.board.detail", "董事会详情", "董事會詳情", "取締役会詳細", "Board Details"),
    ("gobelin.sandbox.tab.replay", "沙盘复盘", "沙盤復盤", "サンドボックス復盤", "Sandbox Replay"),
    ("gobelin.sandbox.tab.guard_alert", "守护告警", "守護告警", "ガードアラート", "Guardian Alerts"),
    ("gobelin.sandbox.tab.iron_veto", "铁律否决", "鐵律否決", "鉄律拒否", "Iron-Rule Veto"),
    ("gobelin.sandbox.tab.hall", "任务入厅", "任務入廳", "タスクホール投入", "Task Hall Submit"),
    ("gobelin.sandbox.tab.brain_feed", "脑库投喂", "腦庫投餵", "ブレインバンク投入", "Brain-Bank Feed"),
    ("gobelin.sandbox.tab.bus", "协作总线", "協作總線", "協調バス", "Collaboration Bus"),

    # ── 指标 ────────────────────────────────────────────────
    ("gobelin.term.metric.total_asset", "总资金", "總資金", "総資産", "Total Assets"),
    ("gobelin.term.metric.position_value", "持仓市值", "持倉市值", "保有時価", "Position Value"),
    ("gobelin.term.metric.cash", "可用资金", "可用資金", "利用可能資金", "Available Cash"),
    ("gobelin.term.metric.position_count", "持仓数", "持倉數", "保有銘柄数", "Positions"),
    ("gobelin.term.metric.total_pnl", "累计盈亏", "累計盈虧", "累計損益", "Total P&L"),
    ("gobelin.term.metric.return_rate", "收益率", "收益率", "収益率", "Return Rate"),

    # ── 交易 / 行情 ─────────────────────────────────────────
    ("gobelin.term.trade.buy", "买入", "買入", "買い", "Buy"),
    ("gobelin.term.trade.sell", "卖出", "賣出", "売り", "Sell"),
    ("gobelin.term.trade.profit", "盈利", "盈利", "利益", "Profit"),
    ("gobelin.term.trade.loss", "亏损", "虧損", "損失", "Loss"),
    ("gobelin.term.sentiment.long", "多", "多", "ロング", "Long"),
    ("gobelin.term.sentiment.short", "空", "空", "ショート", "Short"),
    ("gobelin.term.sentiment.shock", "震荡", "震盪", "レンジ", "Choppy"),
    ("gobelin.term.kline", "K线", "K線", "ローソク足", "Candlestick"),
    ("gobelin.term.ma5", "5日", "5日", "5日", "MA5"),
    ("gobelin.term.ma10", "10日", "10日", "10日", "MA10"),
    ("gobelin.term.ma20", "20日", "20日", "20日", "MA20"),
    ("gobelin.term.up", "涨", "漲", "上昇", "Up"),
    ("gobelin.term.down", "跌", "跌", "下落", "Down"),
    ("gobelin.term.no_trades", "暂无交易记录", "暫無交易記錄", "取引記録なし", "No trade records"),
    ("gobelin.term.buy_avg", "买入均价", "買入均價", "平均買値", "Avg Buy Price"),
    ("gobelin.term.sell_avg", "卖出均价", "賣出均價", "平均売値", "Avg Sell Price"),

    # ── 风控提示 / 保险箱 ────────────────────────────────────
    ("gobelin.term.risk.hhi_high", "HHI 偏高,持仓过度集中", "HHI 偏高,持倉過度集中", "HHI 偏高、ポジション過集中", "High HHI: over-concentrated positions"),
    ("gobelin.term.risk.overweight", "占比 >50%,建议减仓", "佔比 >50%,建議減倉", "比率 >50%、削減推奨", "Weight >50%, consider reducing"),
    ("gobelin.term.risk.too_few", "持仓数量偏少,建议分散", "持倉數量偏少,建議分散", "保有数が少ない、分散推奨", "Too few positions, diversify recommended"),
    ("gobelin.term.risk.cash_low", "现金垫不足 10%", "現金墊不足 10%", "現金クッション 10% 未満", "Cash cushion below 10%"),
    ("gobelin.term.risk.healthy", "持仓健康 · 无重大风险", "持倉健康 · 無重大風險", "ポジション健全 · 重大リスクなし", "Positions healthy · No major risk"),
    ("gobelin.term.vault.locked", "古灵阁保险箱 · 累计锁利", "古靈閣保險箱 · 累計鎖利", "グリンゴッツ金庫 · 累計利確", "Gringotts Vault · Profit Locked"),
    ("gobelin.term.vault.empty", "古灵阁保险箱 · 尚未锁利", "古靈閣保險箱 · 尚未鎖利", "グリンゴッツ金庫 · 利確未実施", "Gringotts Vault · No profit locked yet"),

    # ── 沙盘策略 ─────────────────────────────────────────────
    ("gobelin.sandbox.strategy.momentum", "动量追涨", "動量追漲", "モメンタム追跡", "Momentum Chase"),
    ("gobelin.sandbox.strategy.tp1", "第一档止盈", "第一檔止盈", "第一段利確", "Take-Profit Tier 1"),
    ("gobelin.sandbox.strategy.tp2", "第二档止盈", "第二檔止盈", "第二段利確", "Take-Profit Tier 2"),
    ("gobelin.sandbox.strategy.force_clear", "强制全清", "強制全清", "強制全清算", "Force Clear All"),
    ("gobelin.sandbox.strategy.force_lock", "强制锁利", "強制鎖利", "強制利確", "Force Profit Lock"),
    ("gobelin.sandbox.strategy.bottom_fish", "抄底", "抄底", "底値拾い", "Bottom Fishing"),
    ("gobelin.sandbox.strategy.sector_rotate", "板块轮动", "板塊輪動", "セクターローテーション", "Sector Rotation"),
    ("gobelin.sandbox.strategy.open_break", "开盘突破", "開盤突破", "寄り付きブレイク", "Opening Breakout"),
    ("gobelin.sandbox.strategy.volume_chase", "放量追击", "放量追擊", "出来高追撃", "Volume Chase"),
    ("gobelin.sandbox.strategy.peace_intercept", "和平卫士拦截", "和平衛士攔截", "平和ガード拦截", "Peace-Guard Intercept"),
    ("gobelin.sandbox.strategy.ai_auto", "AI自动", "AI自動", "AI 自動", "AI Auto"),
    ("gobelin.sandbox.strategy.synergetic", "协同联动", "協同聯動", "協同連動", "Synergetic Link"),
    ("gobelin.sandbox.strategy.engine", "沙盘引擎", "沙盤引擎", "サンドボックスエンジン", "Sandbox Engine"),
    ("gobelin.sandbox.strategy.brain_auto", "脑库自动", "腦庫自動", "ブレインバンク自動", "Brain-Bank Auto"),
    ("gobelin.sandbox.strategy.gap", "跳空缺口", "跳空缺口", "ギャップ", "Price Gap"),
    ("gobelin.sandbox.strategy.limit_up", "涨停冲击", "漲停衝擊", "ストップ高衝撃", "Limit-Up Rush"),
    ("gobelin.sandbox.strategy.limit_down", "跌停冲击", "跌停衝擊", "ストップ安衝撃", "Limit-Down Rush"),

    # ── 董事会 12 成员 (name/title/tagline/bio) ──────────────
    ("gobelin.term.crew.bing.name", "冰山玄尊·终身荣誉教授·冰", "冰山玄尊·終身榮譽教授·冰", "氷山玄尊·終身名誉教授·氷", "Iceberg Sage · Lifetime Honorary Professor · Bing"),
    ("gobelin.term.crew.bing.title", "总控指挥官·教授级", "總控指揮官·教授級", "総控指揮官·教授級", "Commander-in-Chief · Professor Grade"),
    ("gobelin.term.crew.bing.tagline", "2847场 · 胜率68% · 首席宗师", "2847場 · 勝率68% · 首席宗師", "2847戦 · 勝率68% · 首席宗師", "2847 Battles · 68% Win Rate · Grand Master"),
    ("gobelin.term.crew.bing.bio", "AI军团总指挥,独创军团调度算法,85%仓位红线制度发明人", "AI軍團總指揮,獨創軍團調度算法,85%倉位紅線制度發明人", "AI軍団総指揮、軍団スケジューリングアルゴリズム創始者、85%ポジションレッドライン制度発明者", "AI Legion Commander, inventor of the legion scheduling algorithm and the 85% position red-line rule"),
    ("gobelin.term.crew.council.name", "天团研判委员会·专家团", "天團研判委員會·專家團", "天団研判委員会·専門家団", "Legion Council · Expert Panel"),
    ("gobelin.term.crew.council.title", "研判委员会·教授级", "研判委員會·教授級", "研判委員会·教授級", "Judgment Council · Professor Grade"),
    ("gobelin.term.crew.council.tagline", "独创鹰犬投票制 · 三维战法", "獨創鷹犬投票制 · 三維戰法", "鷹犬投票制創始 · 三次元戦法", "Hawk-Hound Voting System · 3D Tactics"),
    ("gobelin.term.crew.council.bio", "技术+资金+情绪三维研判,每笔决策鹰/犬双票制", "技術+資金+情緒三維研判,每筆決策鷹/犬雙票制", "技術+資金+センチメントの三次元研判、全決定に鷹/犬ダブル投票制", "Tech + capital + sentiment 3D analysis; hawk/hound dual-vote per decision"),
    ("gobelin.term.crew.mage.name", "老法师·终身学术带头人", "老法師·終身學術帶頭人", "老魔導師·終身学術リーダー", "Old Mage · Lifetime Academic Leader"),
    ("gobelin.term.crew.mage.title", "风控顾问·教授级", "風控顧問·教授級", "リスク顧問·教授級", "Risk Advisor · Professor Grade"),
    ("gobelin.term.crew.mage.tagline", "救场127次 · HHI发明人", "救場127次 · HHI發明人", "救場127回 · HHI 発明者", "127 Rescues · HHI Inventor"),
    ("gobelin.term.crew.mage.bio", "集中度HHI风险模型创立者,三维风控体系奠基人", "集中度HHI風險模型創立者,三維風控體系奠基人", "集中度 HHI リスクモデル創設者、三次元リスク管理体系の創始者", "Founder of the HHI concentration risk model; pioneer of the 3D risk-control system"),
    ("gobelin.term.crew.slip.name", "滑点女王·首席订单学", "滑點女王·首席訂單學", "スリッページ女王·首席注文学", "Slippage Queen · Chief Order Scientist"),
    ("gobelin.term.crew.slip.title", "订单执行·教授级", "訂單執行·教授級", "注文執行·教授級", "Order Execution · Professor Grade"),
    ("gobelin.term.crew.slip.tagline", "BPS优化大师 · 零误单", "BPS優化大師 · 零誤單", "BPS 最適化マスター · 誤注文ゼロ", "BPS Optimization Master · Zero Mis-orders"),
    ("gobelin.term.crew.slip.bio", "限价单智能路由算法发明人,T+1锁仓管理首席架构", "限價單智能路由算法發明人,T+1鎖倉管理首席架構", "指値注文スマートルーティング発明者、T+1 ロック管理チーフアーキテクト", "Inventor of smart routing for limit orders; chief architect of T+1 lock-up management"),
    ("gobelin.term.crew.tide.name", "潮汐操盘手·实战派教授", "潮汐操盤手·實戰派教授", "潮汐オペレーター·実戦派教授", "Tide Trader · Field Professor"),
    ("gobelin.term.crew.tide.title", "操盘手·教授级", "操盤手·教授級", "オペレーター·教授級", "Trader · Professor Grade"),
    ("gobelin.term.crew.tide.tagline", "分档战法发明人 · SCALE_OUT架构", "分檔戰法發明人 · SCALE_OUT架構", "段階戦法発明者 · SCALE_OUT アーキテクチャ", "Tiered-Trading Inventor · SCALE_OUT Architecture"),
    ("gobelin.term.crew.tide.bio", "分档买卖战法创立者,单票30%上限制度设计者", "分檔買賣戰法創立者,單票30%上限制度設計者", "段階売買戦法創設者、単一銘柄 30% 上限制度設計者", "Creator of tiered buy/sell tactics; designer of the 30% single-stock cap"),
    ("gobelin.term.crew.radar.name", "千里眼·雷达学教授", "千里眼·雷達學教授", "千里眼·レーダー学教授", "Clairvoyant · Radar Professor"),
    ("gobelin.term.crew.radar.title", "异动雷达·教授级", "異動雷達·教授級", "異動レーダー·教授級", "Anomaly Radar · Professor Grade"),
    ("gobelin.term.crew.radar.tagline", "|chg|>2%秒级响应 · 雷达学奠基人", "|chg|>2%秒級響應 · 雷達學奠基人", "|chg|>2% 秒級応答 · レーダー学の祖", "|chg|>2% Second-Level Response · Radar Founder"),
    ("gobelin.term.crew.radar.bio", "全A异动雷达系统架构师,实时信号处理专家", "全A異動雷達系統架構師,實時信號處理專家", "全 A 株異動レーダーアーキテクト、リアルタイム信号処理専門家", "Architect of the all-A-share anomaly radar; real-time signal processing expert"),
    ("gobelin.term.crew.ma.name", "均线狙击手·形态学教授", "均線狙擊手·形態學教授", "移動平均スナイパー·形態学教授", "MA Sniper · Pattern Professor"),
    ("gobelin.term.crew.ma.title", "MA侦察·教授级", "MA偵察·教授級", "MA 偵察·教授級", "MA Recon · Professor Grade"),
    ("gobelin.term.crew.ma.tagline", "金叉死叉零误判 · 形态识别专家", "金叉死叉零誤判 · 形態識別專家", "GC/DC 誤判定ゼロ · 形態認識専門家", "Zero-misread Crosses · Pattern Recognition Expert"),
    ("gobelin.term.crew.ma.bio", "MA排列侦察算法创立者,多空形态识别体系奠基人", "MA排列偵察算法創立者,多空形態識別體系奠基人", "MA 配列偵察アルゴリズム創設者、強弱形態認識体系の祖", "Creator of MA-array recon algorithms; founder of bull/bear pattern recognition"),
    ("gobelin.term.crew.vol.name", "放量猎手·量能学教授", "放量獵手·量能學教授", "出来高ハンター·量能学教授", "Volume Hunter · Volume Professor"),
    ("gobelin.term.crew.vol.title", "量能监测·教授级", "量能監測·教授級", "量能監視·教授級", "Volume Monitor · Professor Grade"),
    ("gobelin.term.crew.vol.tagline", "量价背离专家 · VOLUME_SURGE架构", "量價背離專家 · VOLUME_SURGE架構", "量価乖離専門家 · VOLUME_SURGE アーキテクチャ", "Price-Volume Divergence Expert · VOLUME_SURGE Architecture"),
    ("gobelin.term.crew.vol.bio", "放量缩量异动识别算法发明人,量价关系权威", "放量縮量異動識別算法發明人,量價關係權威", "出来高増減異動認識アルゴリズム発明者、量価関係の権威", "Inventor of volume-surge/shrink anomaly detection; authority on price-volume dynamics"),
    ("gobelin.term.crew.news.name", "资讯快刀·舆情学教授", "資訊快刀·輿情學教授", "情報快刀·世論学教授", "News Blade · Sentiment Professor"),
    ("gobelin.term.crew.news.title", "舆情监控·教授级", "輿情監控·教授級", "世論監視·教授級", "Sentiment Watch · Professor Grade"),
    ("gobelin.term.crew.news.tagline", "三通道并行 · 舆情快反体系", "三通道並行 · 輿情快反體系", "三チャネル並列 · 世論即応体制", "Tri-channel Parallel · Rapid Sentiment Response"),
    ("gobelin.term.crew.news.bio", "三通道舆情聚合系统架构师,利好利空秒推协议设计者", "三通道輿情聚合系統架構師,利好利空秒推協議設計者", "三チャネル世論集約アーキテクト、好悪材料秒速プッシュ設計者", "Architect of tri-channel sentiment aggregation; designer of instant bullish/bearish push protocol"),
    ("gobelin.term.crew.fin.name", "精算师·财务学教授", "精算師·財務學教授", "アクチュアリー·財務学教授", "Actuary · Finance Professor"),
    ("gobelin.term.crew.fin.title", "财务管家·教授级", "財務管家·教授級", "財務管家·教授級", "Finance Steward · Professor Grade"),
    ("gobelin.term.crew.fin.tagline", "分毫不差 · 自动对账体系", "分毫不差 · 自動對賬體系", "寸分違わず · 自動照合体系", "Penny-Perfect · Auto-Reconciliation"),
    ("gobelin.term.crew.fin.bio", "佣金+印花税+过户费实时精算系统创立者,月度对账权威", "佣金+印花稅+過戶費實時精算系統創立者,月度對賬權威", "手数料+印紙税+名義書換料のリアルタイム精算創設者、月次照合の権威", "Founder of real-time commission/stamp-tax/transfer-fee accounting; monthly reconciliation authority"),
    ("gobelin.term.crew.judge.name", "铁律判官·规则学教授", "鐵律判官·規則學教授", "鉄律判官·規則学教授", "Iron-Rule Judge · Rules Professor"),
    ("gobelin.term.crew.judge.title", "规则执法·教授级", "規則執法·教授級", "規則執行·教授級", "Rule Enforcement · Professor Grade"),
    ("gobelin.term.crew.judge.tagline", "红线守护者 · 8大铁律制度", "紅線守護者 · 8大鐵律制度", "レッドライン守護者 · 8 大鉄律", "Red-Line Guardian · 8 Iron Rules"),
    ("gobelin.term.crew.judge.bio", "铁律规则委员会首席裁决人,追涨7%/T+0禁令制度创立者", "鐵律規則委員會首席裁決人,追漲7%/T+0禁令制度創立者", "鉄律委員会首席裁定者、追高 7%/T+0 禁止制度の創設者", "Chief arbiter of the Iron-Rule Committee; creator of the 7% chase-ban and T+0 prohibition"),
    ("gobelin.term.crew.memo.name", "复盘学者·认知科学教授", "復盤學者·認知科學教授", "復盤学者·認知科学教授", "Replay Scholar · Cognitive Science Professor"),
    ("gobelin.term.crew.memo.title", "脑库管理员·教授级", "腦庫管理員·教授級", "ブレインバンク管理·教授級", "Brain-Bank Curator · Professor Grade"),
    ("gobelin.term.crew.memo.tagline", "每日AI脑库学习 · 经验传承体系", "每日AI腦庫學習 · 經驗傳承體系", "毎日 AI ブレインバンク学習 · 経験継承体系", "Daily AI Brain-Bank Learning · Experience Legacy"),
    ("gobelin.term.crew.memo.bio", "复盘脑库系统架构师,AI认知进化权威", "復盤腦庫系統架構師,AI認知進化權威", "復盤ブレインバンクアーキテクト、AI 認知進化の権威", "Architect of the replay brain-bank; authority on AI cognitive evolution"),

    # ── 引擎 / 外部专家 7 席 ──────────────────────────────────
    ("gobelin.term.engine.shardquant.name", "ShardQuant 超算引擎", "ShardQuant 超算引擎", "ShardQuant スーパーコンピュータ", "ShardQuant Supercomputing Engine"),
    ("gobelin.term.engine.shardquant.title", "高频量化引擎", "高頻量化引擎", "HFT クオンツエンジン", "HFT Quant Engine"),
    ("gobelin.term.engine.shardquant.tagline", "128核并发", "128核並發", "128 コア並列", "128-Core Parallel"),
    ("gobelin.term.engine.shardquant.bio", "tick级统计套利/配对交易/因子挖掘,毫秒级多因子组合", "tick級統計套利/配對交易/因子挖掘,毫秒級多因子組合", "tick 級統計アービトラージ/ペア取引/ファクター発掘、ミリ秒マルチファクター", "Tick-level stat-arb / pairs / factor mining; millisecond multi-factor portfolios"),
    ("gobelin.term.engine.backtest.name", "冰山回测云", "冰山回測雲", "アイスバーグ・バックテストクラウド", "Iceberg Backtest Cloud"),
    ("gobelin.term.engine.backtest.title", "超级回测引擎", "超級回測引擎", "スーパーバックテストエンジン", "Super Backtest Engine"),
    ("gobelin.term.engine.backtest.tagline", "10年秒级回放", "10年秒級回放", "10 年秒級リプレイ", "10-Year Second-Level Replay"),
    ("gobelin.term.engine.backtest.bio", "10年A股历史K线秒级回放,策略验证/参数扫描/蒙特卡洛模拟", "10年A股歷史K線秒級回放,策略驗證/參數掃描/蒙特卡洛模擬", "10 年 A 株 K 線秒級再生、戦略検証/パラメータ走査/モンテカルロ", "10-year A-share candlestick replay; strategy validation / parameter sweep / Monte Carlo"),
    ("gobelin.term.engine.bs.name", "Black-Scholes 定价专家", "Black-Scholes 定價專家", "Black-Scholes プライシング専門家", "Black-Scholes Pricing Expert"),
    ("gobelin.term.engine.bs.title", "期权定价/希腊字母", "期權定價/希臘字母", "オプションプライシング/グリークス", "Options Pricing / Greeks"),
    ("gobelin.term.engine.bs.tagline", "波动率曲面大师", "波動率曲面大師", "ボラティリティ曲面マスター", "Volatility Surface Master"),
    ("gobelin.term.engine.bs.bio", "B-S模型/二叉树/蒙特卡洛,隐含波动率曲面构建", "B-S模型/二叉樹/蒙特卡洛,隱含波動率曲面構建", "B-S/二項木/モンテカルロ、IV 曲面構築", "B-S / binomial / Monte Carlo; implied-volatility surface construction"),
    ("gobelin.term.expert.joe.name", "华尔街老乔", "華爾街老喬", "ウォール街のジョー", "Wall Street Joe"),
    ("gobelin.term.expert.joe.title", "交易心理学·实战派专家", "交易心理學·實戰派專家", "取引心理学·実戦派専門家", "Trading Psychology · Veteran"),
    ("gobelin.term.expert.joe.tagline", "30年交易员 · 认知偏差校正", "30年交易員 · 認知偏差校正", "30 年トレーダー · 認知バイアス矯正", "30-Year Trader · Cognitive-Bias Correction"),
    ("gobelin.term.expert.joe.bio", "反追涨杀跌特训体系创立者,认知偏差校正权威", "反追漲殺跌特訓體系創立者,認知偏差校正權威", "逆張り訓練体系創設者、認知バイアス矯正の権威", "Founder of anti-chase training; authority on cognitive-bias correction"),
    ("gobelin.term.expert.peace.name", "维和部队·市场维稳专员", "維和部隊·市場維穩專員", "平和維持部隊·市場安定専門官", "Peacekeeper · Market Stabilizer"),
    ("gobelin.term.expert.peace.title", "市场维稳·实战派专家", "市場維穩·實戰派專家", "市場安定·実戦派専門家", "Market Stabilization · Veteran"),
    ("gobelin.term.expert.peace.tagline", "2015/2018/2022行情维稳经验", "2015/2018/2022行情維穩經驗", "2015/2018/2022 相場安定経験", "2015/2018/2022 Stabilization Veteran"),
    ("gobelin.term.expert.peace.bio", "极端行情自动减仓+保护,大盘急跌熔断预案,黑天鹅处置", "極端行情自動減倉+保護,大盤急跌熔斷預案,黑天鵝處置", "極端相場の自動削減+保護、急落時サーキットブレーカー、ブラックスワン対処", "Auto de-risking in extreme markets; crash circuit-breaker plans; black-swan handling"),
    ("gobelin.term.expert.law.name", "法委·合规审查专员", "法委·合規審查專員", "法務委員·コンプライアンス審査官", "Legal Counsel · Compliance Reviewer"),
    ("gobelin.term.expert.law.title", "合规审查·法学专家", "合規審查·法學專家", "コンプライアンス審査·法学専門家", "Compliance Review · Legal Expert"),
    ("gobelin.term.expert.law.tagline", "证券法+基金法+期货法精通", "證券法+基金法+期貨法精通", "証券法+基金法+先物法精通", "Securities / Fund / Futures Law"),
    ("gobelin.term.expert.law.bio", "T+0禁令执法,追涨7%红线审查,内幕交易防范", "T+0禁令執法,追漲7%紅線審查,內幕交易防範", "T+0 禁止執行、追高 7% 審査、インサイダー防止", "T+0 ban enforcement; 7% chase red-line review; insider-trading prevention"),
    ("gobelin.term.expert.standby", "待命入驻", "待命入駐", "待機中", "Standing By"),

    # ── 引擎徽标 ─────────────────────────────────────────────
    ("gobelin.term.badge.super", "超算", "超算", "スーパーコンピュータ", "Supercomputer"),
    ("gobelin.term.badge.expert", "专家", "專家", "専門家", "Expert"),
    ("gobelin.term.badge.gold", "金牌", "金牌", "ゴールド", "Gold"),

    # ── 导航分组 (andromeda_nav) ─────────────────────────────
    ("gobelin.nav.group", "古灵阁", "古靈閣", "グリンゴッツ", "Gringotts"),
    ("gobelin.nav.stock", "证券沙盘", "證券沙盤", "証券サンドボックス", "Securities Sandbox"),
    ("gobelin.nav.live", "实盘终端", "實盤終端", "実弾ターミナル", "Live Terminal"),
    ("gobelin.nav.writing", "网文创作", "網文創作", "Web 小説創作", "Web-Novel Studio"),
    ("gobelin.nav.shield", "金盾安全", "金盾安全", "金盾セキュリティ", "Golden Shield"),
]


def main() -> int:
    if not os.path.isfile(DB):
        print(f"[ERROR] DB not found: {DB}")
        return 1
    print(f"[i18n-seed] DB = {DB}")
    conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
    cur = conn.cursor()
    cur.execute("PRAGMA busy_timeout=60000")
    cur.execute("""CREATE TABLE IF NOT EXISTS mt_i18n_keys (
        key_id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL, source TEXT DEFAULT 'manual',
        domain TEXT DEFAULT 'global',
        zh_cn TEXT NOT NULL, ja_jp TEXT, en_us TEXT, remark TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        zh_tw TEXT
    )""")

    inserted = skipped = 0
    for key, zh_cn, zh_tw, ja_jp, en_us in GOBELIN_I18N:
        cur.execute("""INSERT OR IGNORE INTO mt_i18n_keys
            (key, source, domain, zh_cn, zh_tw, ja_jp, en_us, remark, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (key, "andromeda_batch", "gobelin", zh_cn, zh_tw, ja_jp, en_us,
             "古灵阁双终端文案批量录入", NOW(), NOW()))
        if cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1

    total = cur.execute("SELECT COUNT(*) FROM mt_i18n_keys WHERE domain='gobelin'").fetchone()[0]
    all_cnt = cur.execute("SELECT COUNT(*) FROM mt_i18n_keys").fetchone()[0]
    print(f"[i18n-seed] 新增 {inserted} / 跳过 {skipped} / gobelin 域 {total} / 全表 {all_cnt}")
    conn.close()
    print("[i18n-seed] DONE")
    return 0


if __name__ == '__main__':
    sys.exit(main())
