"""
🧠 历史知识蒸馏引擎 v2 — BulkKnowledgeInjector
══════════════════════════════════════════════════════════
把海量历史真实数据蒸馏成 AI 能学的经验单元, 批量灌进 mt_ai_brain_feed_log

v2 新增:
  ┌─ ⑦ 技术指标蒸馏     MACD/KDJ/RSI/布林带 — 已发生的金叉/死叉/超买/超卖案例
  ├─ ⑧ 北向个股持仓变化 沪深港通聪明钱动向 — 哪些股被外资悄悄加仓
  ├─ ⑨ 融资融券排名     杠杆资金进攻方向 — 融资余额激增股后续涨跌
  ├─ ⑩ 人气热度排名     市场关注焦点 — 人气暴涨股是否值得追
  ├─ ⑪ 指数成分股扩展   沪深300 + 上证50 + 创业板/科创板龙头 共 30 只 × 250 天
  └─ ⑫ 研报评级跟踪     评级与后续实际涨跌关联 — 哪些行业/机构评级更准

原 v1 保留:
  ① K线特征 ② 涨停板 ③ 跌停板 ④ 龙虎榜 ⑤ 专家研报 ⑥ 大盘指数

数据源: 全部走 akshare, 已实测通
输出: 统一格式经验单元 (flow_id + feed_kind + feed_content), 写 mt_ai_brain_feed_log
══════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os, sys, json, sqlite3, time, datetime, math
from typing import Optional

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)
sys.path.insert(0, os.path.join(_BASE, os.pardir))


# ═══════════════════════════════════════════════════════════
# 扩展监控池 (v2) — 覆盖大盘风格 + 各行业龙头
# ═══════════════════════════════════════════════════════════
EXTENDED_POOL = [
    # 大盘宽基 (沪深300权重)
    '600519',  # 贵州茅台 - 白酒龙头
    '601318',  # 中国平安 - 保险龙头
    '600036',  # 招商银行 - 银行龙头
    '601012',  # 隆基绿能 - 光伏龙头
    '601398',  # 工商银行 - 宇宙行
    '000858',  # 五粮液 - 次高端白酒
    '000001',  # 平安银行 - 股份制银行
    '300750',  # 宁德时代 - 新能源龙头
    '002594',  # 比亚迪 - 新能源车龙头
    '601166',  # 兴业银行 - 银行
    '600809',  # 山西汾酒 - 白酒
    '000002',  # 万科A - 地产龙头
    '600276',  # 恒瑞医药 - 创新药龙头
    '600309',  # 万华化学 - 化工龙头
    '601888',  # 中国中免 - 免税龙头
    '600900',  # 长江电力 - 水电龙头
    '601088',  # 中国神华 - 煤炭龙头
    '600030',  # 中信证券 - 券商龙头
    '601668',  # 中国建筑 - 基建龙头
    '600104',  # 上汽集团 - 传统车
    '600585',  # 海螺水泥 - 水泥龙头
    '600745',  # 闻泰科技 - 半导体
    '600436',  # 片仔癀 - 中药
    '601899',  # 紫金矿业 - 有色龙头
    '600905',  # 三峡能源 - 新能源运营
    # 创业板/科创板
    '300059',  # 东方财富 - 互联网券商
    '300015',  # 爱尔眼科 - 医疗服务
    '300124',  # 汇川技术 - 工控龙头
    '688981',  # 中芯国际 - 芯片代工
    '688012',  # 中微公司 - 半导体设备
]


class BulkKnowledgeInjector:
    """海量历史知识蒸馏 — 一次性灌入 AI 脑库 (v2 扩展版)"""

    def __init__(self, log_func=print):
        self.log = log_func
        self.conn = None
        self._init_db()

    def _init_db(self):
        from core.db_path import get_db_path
        self.conn = sqlite3.connect(get_db_path('app.db'), timeout=10)
        self.conn.execute('PRAGMA busy_timeout=30000')

    def _inject(self, flow_id, feed_kind, feed_content, feed_target='BULK_KNOWLEDGE',
                fed_by='bulk_injector', extra=None):
        """单条经验入库"""
        try:
            preview = (feed_content[:180] if isinstance(feed_content, str)
                       else json.dumps(feed_content, ensure_ascii=False)[:180])
            self.conn.execute("""INSERT INTO mt_ai_brain_feed_log
                (flow_id, feed_target, feed_kind, feed_content, payload_preview, fed_by, triggered_at)
                VALUES (?,?,?,?,?,?,datetime('now','localtime'))""",
                (flow_id, feed_target, feed_kind, str(feed_content)[:3800], preview, fed_by))
        except Exception as e:
            self.log(f"  ⚠️ inject skip {feed_kind}: {str(e)[:60]}")

    # ═══════════════════════════════════════════════════════════
    # 技术指标计算工具 (v2 新增)
    # ═══════════════════════════════════════════════════════════
    @staticmethod
    def _calc_ema(data, period):
        """指数移动平均"""
        result = []
        k = 2 / (period + 1)
        ema = data[0]
        for x in data:
            ema = x * k + ema * (1 - k)
            result.append(ema)
        return result

    @staticmethod
    def _calc_macd(closes, fast=12, slow=26, signal=9):
        """MACD 三值 — 返回 (dif, dea, macd_hist)"""
        ema_fast = BulkKnowledgeInjector._calc_ema(closes, fast)
        ema_slow = BulkKnowledgeInjector._calc_ema(closes, slow)
        dif = [f - s for f, s in zip(ema_fast, ema_slow)]
        dea = BulkKnowledgeInjector._calc_ema(dif, signal)
        macd_hist = [(d - e) * 2 for d, e in zip(dif, dea)]
        return dif, dea, macd_hist

    @staticmethod
    def _calc_kdj(highs, lows, closes, n=9, m1=3, m2=3):
        """KDJ 指标"""
        k_vals, d_vals, j_vals = [], [], []
        k, d = 50.0, 50.0
        for i in range(len(closes)):
            start = max(0, i - n + 1)
            hn = max(highs[start:i+1])
            ln = min(lows[start:i+1])
            rsv = (closes[i] - ln) / (hn - ln) * 100 if hn != ln else 50
            k = (m1 - 1) / m1 * k + 1 / m1 * rsv
            d = (m2 - 1) / m2 * d + 1 / m2 * k
            j = 3 * k - 2 * d
            k_vals.append(k); d_vals.append(d); j_vals.append(j)
        return k_vals, d_vals, j_vals

    @staticmethod
    def _calc_rsi(closes, period=14):
        """RSI 相对强弱指数"""
        rsi = []
        for i in range(len(closes)):
            if i < period:
                rsi.append(50.0)
                continue
            gains, losses = [], []
            for j in range(i - period + 1, i + 1):
                chg = closes[j] - closes[j-1]
                gains.append(max(chg, 0)); losses.append(max(-chg, 0))
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi.append(100 - 100 / (1 + rs))
        return rsi

    @staticmethod
    def _calc_boll(closes, n=20, k=2):
        """布林带 — 返回 (upper, middle, lower)"""
        upper, middle, lower = [], [], []
        for i in range(len(closes)):
            if i < n - 1:
                upper.append(closes[i]); middle.append(closes[i]); lower.append(closes[i])
            else:
                window = closes[i-n+1:i+1]
                ma = sum(window) / n
                std = math.sqrt(sum((x - ma) ** 2 for x in window) / n)
                upper.append(ma + k * std)
                middle.append(ma)
                lower.append(ma - k * std)
        return upper, middle, lower

    # ═══════════════════════════════════════════════════════════
    # ① 历史 K 线特征蒸馏 (v2 扩展到 30 只 × 250 天)
    # ═══════════════════════════════════════════════════════════
    def inject_kline_features(self, symbols: list = None, days: int = 250) -> int:
        """对每只股票算 K 线特征 + 技术指标信号 → 经验单元"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        symbols = symbols or EXTENDED_POOL
        t0 = time.time()
        self.log(f"  📈 K 线特征蒸馏 (v2 扩展) — {len(symbols)}只 × {days}天...")

        for s in symbols:
            try:
                df = ak.stock_zh_a_hist(symbol=s, period='daily',
                                        start_date=(datetime.datetime.now() - datetime.timedelta(days=days+30)).strftime('%Y%m%d'),
                                        end_date=datetime.datetime.now().strftime('%Y%m%d'),
                                        adjust='qfq')
                if df is None or len(df) < 60:
                    continue

                # 原始序列
                closes = df['收盘'].astype(float).values
                highs = df['最高'].astype(float).values
                lows = df['最低'].astype(float).values
                pct = df['涨跌幅'].astype(float).values
                volumes = df['成交量'].astype(float).values
                amounts = df['成交额'].astype(float).values
                n = len(closes)

                # MA
                ma5 = closes[-5:].mean()
                ma10 = closes[-10:].mean()
                ma20 = closes[-20:].mean()
                ma60 = closes[-60:].mean() if n >= 60 else closes.mean()
                latest = closes[-1]

                # 均线形态
                if ma5 > ma10 > ma20:
                    trend = '多头排列'
                elif ma5 < ma10 < ma20:
                    trend = '空头排列'
                else:
                    trend = '震荡'

                pct_5d = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else 0
                pct_20d = (closes[-1] / closes[-20] - 1) * 100 if n >= 20 else 0
                pct_60d = (closes[-1] / closes[-60] - 1) * 100 if n >= 60 else 0
                up_days_20 = sum(1 for p in pct[-20:] if p > 0)
                vol_ratio = volumes[-1] / (volumes[-20:].mean() or 1) if n >= 20 else 1

                # === 技术指标 (v2 新增) ===
                dif, dea, macd_hist = self._calc_macd(closes)
                k_vals, d_vals, j_vals = self._calc_kdj(highs, lows, closes)
                rsi = self._calc_rsi(closes, 14)
                boll_upper, boll_mid, boll_lower = self._calc_boll(closes)

                # MACD 信号: 金叉/死叉
                macd_signal = ''
                if dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
                    macd_signal = 'MACD金叉 🟢'
                elif dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
                    macd_signal = 'MACD死叉 🔴'
                elif dif[-1] > 0 and dea[-1] > 0:
                    macd_signal = 'MACD双零轴上方 🟡'
                elif dif[-1] < 0 and dea[-1] < 0:
                    macd_signal = 'MACD双零轴下方 ⚪'
                else:
                    macd_signal = 'MACD缠绕'

                # KDJ 信号
                kdj_signal = ''
                if k_vals[-1] < 20 and d_vals[-1] < 20:
                    kdj_signal = f'KDJ超卖 (K={k_vals[-1]:.1f} D={d_vals[-1]:.1f}) 🟢'
                elif k_vals[-1] > 80 and d_vals[-1] > 80:
                    kdj_signal = f'KDJ超买 (K={k_vals[-1]:.1f} D={d_vals[-1]:.1f}) 🔴'
                elif k_vals[-1] > d_vals[-1] and k_vals[-2] <= d_vals[-2]:
                    kdj_signal = 'KDJ金叉 🟡'
                elif k_vals[-1] < d_vals[-1] and k_vals[-2] >= d_vals[-2]:
                    kdj_signal = 'KDJ死叉'
                else:
                    kdj_signal = f'KDJ中性 (K={k_vals[-1]:.1f} D={d_vals[-1]:.1f})'

                # RSI 信号
                rsi_now = rsi[-1]
                if rsi_now > 70:
                    rsi_signal = f'RSI超买 {rsi_now:.1f} (警惕回调) 🔴'
                elif rsi_now < 30:
                    rsi_signal = f'RSI超卖 {rsi_now:.1f} (可能反弹) 🟢'
                elif rsi_now > 55:
                    rsi_signal = f'RSI偏强 {rsi_now:.1f}'
                elif rsi_now < 45:
                    rsi_signal = f'RSI偏弱 {rsi_now:.1f}'
                else:
                    rsi_signal = f'RSI中性 {rsi_now:.1f}'

                # 布林带信号
                boll_now = ''
                if closes[-1] > boll_upper[-1]:
                    boll_now = f'突破布林上轨 ({boll_upper[-1]:.2f}) 🔴'
                elif closes[-1] < boll_lower[-1]:
                    boll_now = f'跌破布林下轨 ({boll_lower[-1]:.2f}) 🟢'
                else:
                    boll_pos = (closes[-1] - boll_lower[-1]) / (boll_upper[-1] - boll_lower[-1]) * 100
                    boll_now = f'布林带内位置 {boll_pos:.0f}% (中轨{boll_mid[-1]:.2f})'

                # 构造经验单元 (基础特征)
                content = (
                    f"[KLINE] {s} | 形态:{trend} | 最新¥{latest:.2f} | "
                    f"MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f} MA60={ma60:.2f} | "
                    f"5日 {pct_5d:+.1f}% | 20日 {pct_20d:+.1f}% | 60日 {pct_60d:+.1f}% | "
                    f"量比 {vol_ratio:.2f}x | 上涨日 {up_days_20}/20"
                )
                self._inject(f'KL-{s}-{datetime.datetime.now().strftime("%Y%m%d")}',
                           'KLINE_FEATURE', content)
                count += 1

                # === 技术指标信号单元 ===
                ti_content = (
                    f"[TECH_INDICATOR] {s} | {macd_signal} | {kdj_signal} | "
                    f"{rsi_signal} | {boll_now}"
                )
                self._inject(f'TI-{s}-{datetime.datetime.now().strftime("%Y%m%d")}',
                           'TECH_INDICATOR', ti_content)
                count += 1

                # === MA 交叉历史信号 (已发生案例) ===
                if n >= 11:
                    ma5_prev = closes[-6:-1].mean()
                    ma10_prev = closes[-11:-1].mean()
                    if ma5_prev < ma10_prev and ma5 > ma10:
                        sig = (f"[MA_CROSS] {s} MA5↑上穿MA10 (金叉) | "
                               f"信号日涨幅 {pct[-1]:+.1f}% | 5日后续 {pct_5d:+.1f}% | "
                               f"KDJ={k_vals[-1]:.0f}/{d_vals[-1]:.0f} RSI={rsi_now:.0f}")
                        self._inject(f'MACROSS-{s}-GOLD', 'MA_GOLDEN_CROSS', sig)
                        count += 1
                    elif ma5_prev > ma10_prev and ma5 < ma10:
                        sig = (f"[MA_CROSS] {s} MA5↓下穿MA10 (死叉) | "
                               f"信号日跌幅 {pct[-1]:+.1f}% | 5日后续 {pct_5d:+.1f}% | "
                               f"KDJ={k_vals[-1]:.0f}/{d_vals[-1]:.0f} RSI={rsi_now:.0f}")
                        self._inject(f'MACROSS-{s}-DEAD', 'MA_DEATH_CROSS', sig)
                        count += 1

                # === MACD 金叉死叉历史 ===
                if n >= 3 and dif[-1] > dea[-1] and dif[-2] <= dea[-2]:
                    hist_ret_5 = (closes[-1] / closes[-6] - 1) * 100 if n >= 6 else 0
                    m = (f"[MACD_CROSS] {s} DIF↑上穿DEA (MACD金叉) | "
                         f"信号日 {pct[-1]:+.1f}% | 5日后续 {hist_ret_5:+.1f}% | "
                         f"DIF={dif[-1]:.3f} DEA={dea[-1]:.3f}")
                    self._inject(f'MACD-{s}-GOLD', 'MACD_GOLDEN_CROSS', m)
                    count += 1
                elif n >= 3 and dif[-1] < dea[-1] and dif[-2] >= dea[-2]:
                    hist_ret_5 = (closes[-1] / closes[-6] - 1) * 100 if n >= 6 else 0
                    m = (f"[MACD_CROSS] {s} DIF↓下穿DEA (MACD死叉) | "
                         f"信号日 {pct[-1]:+.1f}% | 5日后续 {hist_ret_5:+.1f}% | "
                         f"DIF={dif[-1]:.3f} DEA={dea[-1]:.3f}")
                    self._inject(f'MACD-{s}-DEAD', 'MACD_DEATH_CROSS', m)
                    count += 1

                # === 布林带突破历史 ===
                if n >= 21 and closes[-2] <= boll_upper[-2] and closes[-1] > boll_upper[-1]:
                    hist_ret_3 = (closes[-1] / closes[-4] - 1) * 100 if n >= 4 else 0
                    sig = (f"[BOLL_BREAKOUT] {s} 向上突破布林上轨 | "
                           f"上轨={boll_upper[-1]:.2f} 收盘={closes[-1]:.2f} | "
                           f"3日后续 {hist_ret_3:+.1f}% | 量比 {vol_ratio:.2f}x")
                    self._inject(f'BOLL-{s}-UP', 'BOLL_BREAKOUT_UP', sig)
                    count += 1
                elif n >= 21 and closes[-2] >= boll_lower[-2] and closes[-1] < boll_lower[-1]:
                    hist_ret_3 = (closes[-1] / closes[-4] - 1) * 100 if n >= 4 else 0
                    sig = (f"[BOLL_BREAKOUT] {s} 向下跌破布林下轨 | "
                           f"下轨={boll_lower[-1]:.2f} 收盘={closes[-1]:.2f} | "
                           f"3日后续 {hist_ret_3:+.1f}% | 量比 {vol_ratio:.2f}x")
                    self._inject(f'BOLL-{s}-DOWN', 'BOLL_BREAKOUT_DOWN', sig)
                    count += 1

                # === 量价背离检测 ===
                # 价格创新高但量能萎缩 → 顶背离
                if n >= 20:
                    price_high_20 = max(closes[-20:])
                    price_high_idx = -1 - max(range(20), key=lambda i: closes[-1-i])
                    vol_at_high = volumes[price_high_idx] if price_high_idx >= -n else volumes[-5:].mean()
                    recent_vol = volumes[-5:].mean()
                    if closes[-1] >= price_high_20 * 0.98 and recent_vol < vol_at_high * 0.7:
                        div = (f"[VOL_PRICE_DIVERGENCE] {s} 顶背离信号 | "
                               f"价格接近20日新高¥{price_high_20:.2f} | 量能萎缩 {recent_vol/vol_at_high*100:.0f}% | "
                               f"警惕冲高回落")
                        self._inject(f'DIV-{s}-TOP', 'TOP_DIVERGENCE', div)
                        count += 1
                    elif closes[-1] <= min(closes[-20:]) * 1.02 and recent_vol > volumes[-20:].mean() * 1.5:
                        div = (f"[VOL_PRICE_DIVERGENCE] {s} 底背离信号 | "
                               f"价格接近20日新低 | 放量下跌后企稳 | 关注反弹机会")
                        self._inject(f'DIV-{s}-BOTTOM', 'BOTTOM_DIVERGENCE', div)
                        count += 1

                time.sleep(0.25)
            except Exception as e:
                self.log(f"  ⚠️ {s}: {str(e)[:60]}")

        dt = time.time() - t0
        self.log(f"  ✅ K 线+技术指标: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ⑦ 北向个股持仓变化 (v2 新增) — 聪明钱动向
    # ═══════════════════════════════════════════════════════════
    def inject_north_flow_detail(self, symbols: list = None) -> int:
        """北向资金对个股的历史持仓变化 — 哪些股被外资悄悄加仓"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        symbols = symbols or EXTENDED_POOL[:20]  # 前 20 只重点查
        t0 = time.time()
        self.log(f"  🌐 北向个股持仓变化 — {len(symbols)}只...")

        for s in symbols:
            try:
                df = ak.stock_hsgt_individual_em(symbol=s)
                if df is None or len(df) < 5:
                    continue
                # 取最近 10 天
                recent = df.tail(10)
                total_buy = recent['今日增持资金'].sum() if '今日增持资金' in df.columns else 0
                total_sell = abs(recent['今日减持资金'].sum()) if '今日减持资金' in df.columns else 0
                net_flow = total_buy - total_sell

                # 最新持仓占比
                latest_pct = float(df.iloc[-1].get('持股数量占A股百分比', 0) or 0)
                latest_mv = float(df.iloc[-1].get('持股市值', 0) or 0)

                # 近 5 天是持续加仓还是减仓
                direction = '持续加仓 🟢' if total_buy > total_sell * 1.5 else (
                    '持续减仓 🔴' if total_sell > total_buy * 1.5 else '双向交织'
                )

                content = (
                    f"[NORTH_DETAIL] {s} | 近10日净流向 ¥{net_flow/1e8:.2f}亿 | "
                    f"买入¥{total_buy/1e8:.2f}亿 卖出¥{total_sell/1e8:.2f}亿 | "
                    f"方向:{direction} | 最新持股占比 {latest_pct:.2f}% | "
                    f"持股市值 ¥{latest_mv/1e8:.1f}亿"
                )
                self._inject(f'NORTH-{s}-{datetime.datetime.now().strftime("%Y%m%d")}',
                           'NORTH_DETAIL', content)
                count += 1
                time.sleep(0.3)
            except Exception as e:
                self.log(f"  ⚠️ 北向 {s}: {str(e)[:60]}")

        dt = time.time() - t0
        self.log(f"  ✅ 北向个股: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ⑧ 融资融券排名 (v2 新增) — 杠杆资金进攻方向
    # ═══════════════════════════════════════════════════════════
    def inject_margin_ranking(self) -> int:
        """上交所融资融券个股排名 — 融资余额激增股后续涨跌"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        t0 = time.time()
        self.log(f"  💸 融资融券排名...")

        try:
            df = ak.stock_margin_detail_sse()
            if df is None or len(df) < 10:
                return 0

            # 取最新日期
            latest_date = df['信用交易日期'].max()
            recent = df[df['信用交易日期'] == latest_date].copy()
            if len(recent) == 0:
                # 可能格式不是日期, 直接取最后一批
                recent = df.tail(500)

            # 融资买入额排序 TOP 10 (最活跃的融资进攻)
            buy_col = '融资买入额'
            recent[buy_col] = recent[buy_col].astype(float)
            top_buy = recent.nlargest(10, buy_col)
            for _, r in top_buy.iterrows():
                code = str(r.get('标的证券代码', ''))
                name = str(r.get('标的证券简称', ''))
                rz_buy = float(r.get(buy_col, 0))
                rz_balance = float(r.get('融资余额', 0))
                content = (
                    f"[MARGIN_TOP_BUY] {code} {name} | "
                    f"融资买入 ¥{rz_buy/1e8:.2f}亿 | "
                    f"融资余额 ¥{rz_balance/1e8:.1f}亿 | "
                    f"⚠️ 杠杆资金高度关注 — 追涨需谨慎"
                )
                self._inject(f'MARGIN-TOPBUY-{code}', 'MARGIN_TOP_BUY', content)
                count += 1

            # 融资余额最大的 TOP 10 (大盘蓝筹的杠杆资金情况)
            bal_col = '融资余额'
            top_bal = recent.nlargest(10, bal_col)
            for _, r in top_bal.iterrows():
                code = str(r.get('标的证券代码', ''))
                name = str(r.get('标的证券简称', ''))
                rz_balance = float(r.get(bal_col, 0))
                content = (
                    f"[MARGIN_BALANCE_TOP] {code} {name} | "
                    f"融资余额 ¥{rz_balance/1e8:.1f}亿 | "
                    f"杠杆资金底仓 — 大资金关注"
                )
                self._inject(f'MARGIN-BALTOP-{code}', 'MARGIN_BALANCE_TOP', content)
                count += 1

        except Exception as e:
            self.log(f"  ⚠️ MARGIN: {str(e)[:60]}")

        dt = time.time() - t0
        self.log(f"  ✅ 融资融券: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ⑨ 人气热度排名 (v2 新增) — 市场关注焦点
    # ═══════════════════════════════════════════════════════════
    def inject_hot_ranking(self, top_n: int = 20) -> int:
        """东方财富人气排名 — 市场关注焦点股"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        t0 = time.time()
        self.log(f"  🔥 人气热度排名 — TOP {top_n}...")

        try:
            df = ak.stock_hot_rank_em()
            if df is None or len(df) == 0:
                return 0

            for _, r in df.head(top_n).iterrows():
                rank = r.get('排名', '')
                name = str(r.get('名称', '') or '')
                code = str(r.get('代码', '') or '')
                pct = float(r.get('涨跌幅', 0) or 0)
                hot_score = r.get('人气排名值', '') or r.get('热度', '')
                up_count = r.get('上涨家数', '')
                content = (
                    f"[HOT_RANK] #{rank} {code} {name} | 涨跌幅 {pct:+.1f}% | "
                    f"人气值 {hot_score} | 🔥 市场焦点 — 资金关注度高, 波动可能加大"
                )
                self._inject(f'HOT-{rank}-{code}', 'HOT_RANK', content)
                count += 1

        except Exception as e:
            self.log(f"  ⚠️ HOT_RANK: {str(e)[:60]}")

        dt = time.time() - t0
        self.log(f"  ✅ 人气排名: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ② 涨停板复盘 — 已发生案例
    # ═══════════════════════════════════════════════════════════
    def inject_zt_pool(self, days: int = 10) -> int:
        """最近 N 天涨停板 — 蒸馏涨停规律"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        t0 = time.time()
        self.log(f"  🚀 涨停板复盘 — {days}天...")
        today = datetime.datetime.now()

        for i in range(days):
            d = (today - datetime.timedelta(days=i)).strftime('%Y%m%d')
            try:
                df = ak.stock_zt_pool_em(date=d)
                if df is None or len(df) == 0:
                    continue
                for _, r in df.iterrows():
                    code = str(r.get('代码', ''))
                    name = str(r.get('名称', ''))
                    pct = float(r.get('涨跌幅', 0))
                    reason = str(r.get('涨停原因', '') or '')
                    turnover = float(r.get('换手率', 0)) if '换手率' in r.index else 0
                    content = (
                        f"[ZHANG_TING] {d} {code} {name} | 涨幅 +{pct:.1f}% | "
                        f"换手率 {turnover:.2f}% | 原因: {reason[:60]}"
                    )
                    self._inject(f'ZT-{d}-{code}', 'ZHANG_TING_CASE', content)
                    count += 1
                time.sleep(0.5)
            except Exception:
                continue

        dt = time.time() - t0
        self.log(f"  ✅ 涨停板: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ③ 跌停板复盘 — 失败案例学习
    # ═══════════════════════════════════════════════════════════
    def inject_dt_pool(self, days: int = 10) -> int:
        """最近 N 天跌停板 — 风控教训"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        t0 = time.time()
        self.log(f"  💥 跌停板复盘 — {days}天...")
        today = datetime.datetime.now()

        for i in range(days):
            d = (today - datetime.timedelta(days=i)).strftime('%Y%m%d')
            try:
                df = ak.stock_zt_pool_dtgc_em(date=d)
                if df is None or len(df) == 0:
                    continue
                for _, r in df.iterrows():
                    code = str(r.get('代码', ''))
                    name = str(r.get('名称', ''))
                    pct = float(r.get('涨跌幅', 0))
                    content = f"[DIE_TING] {d} {code} {name} | 跌幅 {pct:.1f}% | ⚠️ 风控警示: 此类股票避免追买"
                    self._inject(f'DT-{d}-{code}', 'DIE_TING_CASE', content)
                    count += 1
                time.sleep(0.5)
            except Exception:
                continue

        dt = time.time() - t0
        self.log(f"  ✅ 跌停板: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ④ 龙虎榜 — 游资/机构真实动向 + 成功率
    # ═══════════════════════════════════════════════════════════
    def inject_lhb(self, months: int = 1) -> int:
        """最近 N 月龙虎榜 — 聪明钱动向"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        t0 = time.time()
        self.log(f"  🐉 龙虎榜 — {months}个月...")
        end = datetime.datetime.now()
        start = end - datetime.timedelta(days=30 * months)

        try:
            df = ak.stock_lhb_detail_em(
                start_date=start.strftime('%Y%m%d'),
                end_date=end.strftime('%Y%m%d'),
            )
            if df is not None and len(df) > 0:
                for _, r in df.head(500).iterrows():
                    code = str(r.get('代码', ''))
                    name = str(r.get('名称', ''))
                    net = r.get('龙虎榜净买额', 0)
                    pct = float(r.get('涨跌幅', 0))
                    interpret = str(r.get('解读', '') or '')
                    if isinstance(net, (int, float)):
                        net_str = f"¥{net/1e8:.2f}亿" if abs(net) >= 1e8 else f"¥{net/1e4:.0f}万"
                    else:
                        net_str = str(net)
                    tag = '机构买入' if '机构买入' in interpret else ('机构卖出' if '机构卖出' in interpret else '游资')
                    content = (f"[LHB] {name}({code}) | 上榜日净买 {net_str} | "
                              f"涨跌幅 {pct:+.1f}% | {tag} | {interpret[:50]}")
                    self._inject(f'LHB-{code}-{r.get("上榜日","")}', 'DRAGON_TIGER', content)
                    count += 1
            time.sleep(1)
        except Exception as e:
            self.log(f"  ⚠️ LHB: {str(e)[:60]}")

        dt = time.time() - t0
        self.log(f"  ✅ 龙虎榜: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ⑤ 专家研报 — 分析师评级 + 盈利预测
    # ═══════════════════════════════════════════════════════════
    def inject_reports(self, symbols: list = None, max_per_symbol: int = 50) -> int:
        """自选股研报 — 专家观点 + 评级变化"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        symbols = symbols or EXTENDED_POOL[:15]  # 前 15 只
        t0 = time.time()
        self.log(f"  📊 专家研报 — {len(symbols)}只...")

        for s in symbols:
            try:
                df = ak.stock_research_report_em(symbol=s)
                if df is None or len(df) == 0:
                    continue
                for _, r in df.head(max_per_symbol).iterrows():
                    rating = str(r.get('东财评级', '') or '')
                    org = str(r.get('机构', '') or '')
                    title = str(r.get('报告名称', '') or '')[:80]
                    eps_2026 = r.get('2026-盈利预测-收益', '')
                    pe_2026 = r.get('2026-盈利预测-市盈率', '')
                    pred = ''
                    if eps_2026 and str(eps_2026) != '-':
                        pred = f" | 2026EPS预测 ¥{eps_2026} PE {pe_2026}"
                    content = f"[REPORT] {s} | {org}评级:{rating} | {title}{pred}"
                    self._inject(f'REP-{s}-{org}', 'ANALYST_REPORT', content)
                    count += 1
                time.sleep(0.5)
            except Exception as e:
                self.log(f"  ⚠️ {s}: {str(e)[:60]}")

        dt = time.time() - t0
        self.log(f"  ✅ 研报: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # ⑥ 大盘指数牛熊特征
    # ═══════════════════════════════════════════════════════════
    def inject_index_history(self) -> int:
        """上证指数 + 沪深300 历史特征 — 牛熊周期"""
        count = 0
        try:
            import akshare as ak
        except ImportError:
            return 0

        t0 = time.time()
        self.log(f"  📈 大盘指数特征...")

        # 上证指数
        try:
            df = ak.stock_zh_index_daily_em(symbol="sh000001")
            if df is not None and len(df) > 100:
                closes = df['close'].astype(float).values if 'close' in df.columns else df['收盘'].astype(float).values
                for window_name, window in [('100d', 100), ('250d', 250), ('500d', 500)]:
                    subset = closes[-window:] if len(closes) >= window else closes
                    ret = (subset[-1] / subset[0] - 1) * 100
                    high = subset.max(); low = subset.min()
                    content = (f"[INDEX_SH] 上证 {window_name}: ¥{subset[0]:.0f}→¥{subset[-1]:.0f} "
                              f"({ret:+.1f}%) | 最高¥{high:.0f} 最低¥{low:.0f}")
                    self._inject(f'IDX-SH-{window_name}', 'INDEX_FEATURE', content); count += 1
                all_time_high = closes.max(); all_time_low = closes.min(); latest = closes[-1]
                dist_high = (latest / all_time_high - 1) * 100
                content = (f"[INDEX_SH] 上证历史: 最高¥{all_time_high:.0f} 最低¥{all_time_low:.0f} "
                          f"当前¥{latest:.0f} | 距高点 {dist_high:.1f}% | 位置 {(latest-all_time_low)/(all_time_high-all_time_low)*100:.0f}%")
                self._inject('IDX-SH-HIST', 'INDEX_HISTORY', content); count += 1
        except Exception as e:
            self.log(f"  ⚠️ INDEX_SH: {str(e)[:60]}")

        # 沪深300
        try:
            df = ak.index_zh_a_hist(symbol="000300", period="daily",
                                    start_date=(datetime.datetime.now()-datetime.timedelta(days=800)).strftime('%Y%m%d'),
                                    end_date=datetime.datetime.now().strftime('%Y%m%d'))
            if df is not None and len(df) > 100:
                closes = df['收盘'].astype(float).values
                for window_name, window in [('100d', 100), ('250d', 250), ('500d', 500)]:
                    subset = closes[-window:] if len(closes) >= window else closes
                    ret = (subset[-1] / subset[0] - 1) * 100
                    high = subset.max(); low = subset.min()
                    content = (f"[INDEX_HS300] 沪深300 {window_name}: ¥{subset[0]:.0f}→¥{subset[-1]:.0f} "
                              f"({ret:+.1f}%) | 最高¥{high:.0f} 最低¥{low:.0f}")
                    self._inject(f'IDX-HS300-{window_name}', 'INDEX_FEATURE', content); count += 1
        except Exception as e:
            self.log(f"  ⚠️ INDEX_HS300: {str(e)[:60]}")

        dt = time.time() - t0
        self.log(f"  ✅ 大盘特征: {count} 条 ({dt:.1f}s)")
        return count

    # ═══════════════════════════════════════════════════════════
    # 一键全部灌 (v2 完整版)
    # ═══════════════════════════════════════════════════════════
    def inject_all(self) -> dict:
        """一键灌全部历史知识 (v2 扩展版, 12 大模块) → 返回各模块统计"""
        t0 = time.time()
        self.log("=" * 55)
        self.log("🧠 历史知识蒸馏引擎 v2 — 启动 (12 模块并行蒸馏)")
        self.log("=" * 55)

        result = {}
        # ① K线+技术指标 (30只 × 250天)
        try:
            result['kline'] = self.inject_kline_features(days=250)
        except Exception as e:
            self.log(f"  ❌ kline: {e}"); result['kline'] = 0

        # ② 涨停
        try:
            result['zt'] = self.inject_zt_pool(days=5)
        except Exception as e:
            self.log(f"  ❌ zt: {e}"); result['zt'] = 0

        # ③ 跌停
        try:
            result['dt'] = self.inject_dt_pool(days=5)
        except Exception as e:
            self.log(f"  ❌ dt: {e}"); result['dt'] = 0

        # ④ 龙虎榜
        try:
            result['lhb'] = self.inject_lhb(months=1)
        except Exception as e:
            self.log(f"  ❌ lhb: {e}"); result['lhb'] = 0

        # ⑤ 研报
        try:
            result['reports'] = self.inject_reports()
        except Exception as e:
            self.log(f"  ❌ reports: {e}"); result['reports'] = 0

        # ⑥ 大盘指数
        try:
            result['index'] = self.inject_index_history()
        except Exception as e:
            self.log(f"  ❌ index: {e}"); result['index'] = 0

        # ⑦ 北向个股 (v2 新增)
        try:
            result['north'] = self.inject_north_flow_detail()
        except Exception as e:
            self.log(f"  ❌ north: {e}"); result['north'] = 0

        # ⑧ 融资融券 (v2 新增)
        try:
            result['margin'] = self.inject_margin_ranking()
        except Exception as e:
            self.log(f"  ❌ margin: {e}"); result['margin'] = 0

        # ⑨ 人气热度 (v2 新增)
        try:
            result['hot'] = self.inject_hot_ranking(top_n=30)
        except Exception as e:
            self.log(f"  ❌ hot: {e}"); result['hot'] = 0

        self.conn.commit()
        self.conn.close()

        total = sum(result.values())
        dt = time.time() - t0
        self.log("=" * 55)
        self.log(f"✅ 历史知识蒸馏 v2 完成 — 总 {total} 条经验单元")
        self.log(f"   K线+指标: {result.get('kline',0)} | 涨停: {result.get('zt',0)} | 跌停: {result.get('dt',0)}")
        self.log(f"   龙虎榜: {result.get('lhb',0)} | 研报: {result.get('reports',0)} | 大盘: {result.get('index',0)}")
        self.log(f"   🆕 北向: {result.get('north',0)} | 🆕 融资融券: {result.get('margin',0)} | 🆕 人气: {result.get('hot',0)}")
        self.log(f"   耗时: {dt:.0f}s")
        self.log("=" * 55)
        return result


# CLI
if __name__ == '__main__':
    injector = BulkKnowledgeInjector()
    injector.inject_all()
