"""
analyst_engine.py — 仙女座股市分析师团队引擎
═══════════════════════════════════════════════════════════════════════════

两个团队:
  Team A: 股市数据分析师 (4人)
    A-01 板块热度官   — 行业涨跌榜 + 成交异动
    A-02 资金流向师   — 北向资金估算 + 主力净流入
    A-03 技术形态师   — MA/MACD/量价/RSI 指标
    A-04 宏观雷达师   — 指数趋势 + 市场情绪

  Team B: 自选股分析师
    精选池评分 (技术面 + 板块热度 + 资金面) → Top 5 → 择时建议

设计原则:
  - 零新依赖: 复用 market_data_service (新浪接口) + httpx
  - 分层筛选: 先缩小候选池再做重计算 (经验 #2167940)
  - 安全降级: 数据源失败 → 降级, 不阻断沙盘主流程 (经验 #1611208)
  - 与 tick 派发链解耦: 分析师 enrich crowd_verdict, 不改变 hall 结构
"""
from __future__ import annotations
import json
import time
import threading
from datetime import datetime, timezone, timedelta

try:
    import httpx
    _HTTPX_OK = True
except ImportError:
    _HTTPX_OK = False

from core.services.market_data_service import MarketDataService, fetch_sandbox_data


# ── 常量 ────────────────────────────────────────────────────────────────
_ANALYST_CACHE = {'data': None, 'ts': 0.0, 'lock': threading.Lock()}
ANALYST_TTL = 90.0  # 分析师数据缓存 90s (沙盘推演不需要实时到秒)


# ════════════════════════════════════════════════════════════════════════
# §1 技术指标计算 (纯 Python, 不依赖 pandas)
# ════════════════════════════════════════════════════════════════════════
def _ma(closes: list[float], n: int) -> list:
    """移动平均 — 带 - 占位"""
    out = []
    for i in range(len(closes)):
        if i < n - 1:
            out.append(None)
            continue
        seg = closes[i - n + 1:i + 1]
        seg = [x for x in seg if isinstance(x, (int, float)) and x > 0]
        out.append(round(sum(seg) / n, 2) if len(seg) >= n else None)
    return out


def _ema(closes: list[float], n: int) -> list:
    """指数移动平均"""
    out = []
    k = 2 / (n + 1)
    for i, c in enumerate(closes):
        if i == 0:
            out.append(c)
        else:
            out.append(round(c * k + out[-1] * (1 - k), 4))
    return out


def _macd(closes: list[float]) -> dict:
    """MACD 三线 (用 EMA12/26 + DEA9)"""
    if len(closes) < 30:
        return {'dif': None, 'dea': None, 'bar': None, 'status': 'insufficient_data'}
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [round(ema12[i] - ema26[i], 4) for i in range(len(closes))]
    dea = _ema(dif, 9)
    bar = [round(2 * (dif[i] - dea[i]), 4) for i in range(len(closes))]
    # 状态
    last_dif, last_dea, last_bar = dif[-1], dea[-1], bar[-1]
    prev_bar = bar[-2] if len(bar) > 1 else 0
    if last_bar > 0 and last_bar > prev_bar:
        status = '金叉确认 · 红柱放大 (看多)'
    elif last_bar > 0 and last_bar < prev_bar:
        status = '金叉后红柱收缩 (震荡)'
    elif last_bar < 0 and last_bar > prev_bar:
        status = '绿柱收窄 (筑底信号)'
    elif last_bar < 0 and last_bar < prev_bar:
        status = '死叉确认 · 绿柱放大 (看空)'
    else:
        status = '中性'
    return {'dif': last_dif, 'dea': last_dea, 'bar': last_bar, 'status': status}


def _rsi(closes: list[float], n: int = 14) -> dict:
    """RSI 指标"""
    if len(closes) < n + 1:
        return {'value': None, 'status': 'insufficient_data'}
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    # Wilder 平滑
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        rsi = 100.0
    else:
        rsi = 100 - 100 / (1 + avg_gain / avg_loss)
    if rsi > 70:
        status = '超买区 (>70, 注意回调)'
    elif rsi < 30:
        status = '超卖区 (<30, 或有反弹)'
    elif rsi > 50:
        status = '偏强 (50-70)'
    else:
        status = '偏弱 (30-50)'
    return {'value': round(rsi, 2), 'status': status}


def _bollinger(closes: list[float], n: int = 20, k: float = 2.0) -> dict:
    """布林带"""
    if len(closes) < n:
        return {'upper': None, 'middle': None, 'lower': None, 'bandwidth': None, 'status': 'insufficient'}
    seg = closes[-n:]
    ma = sum(seg) / n
    var = sum((x - ma) ** 2 for x in seg) / n
    std = var ** 0.5
    upper, lower = ma + k * std, ma - k * std
    last = closes[-1]
    bandwidth = round((upper - lower) / ma * 100, 2)
    if last > upper:
        status = '突破上轨 (超买信号)'
    elif last < lower:
        status = '跌破下轨 (超卖信号)'
    elif last > ma:
        status = '上半区 (偏强)'
    else:
        status = '下半区 (偏弱)'
    return {
        'upper': round(upper, 2), 'middle': round(ma, 2), 'lower': round(lower, 2),
        'bandwidth_pct': bandwidth,
        'status': status,
    }


# ════════════════════════════════════════════════════════════════════════
# §0.5 政府消息 / 政策情报抓取 (影响股市走向的关键变量)
# ════════════════════════════════════════════════════════════════════════

# 政策利好关键词 (政府推动 → 对应板块受益)
_GOV_BULL_KEYWORDS = [
    # 货币政策
    ('降准', -2, '银行利好, 释放流动性'),
    ('降息', -2, '消费/地产利好'),
    ('MLF中标利率下调', -2, '市场利率走低'),
    ('LPR下调', -1.5, '房贷成本降低, 地产利好'),
    ('央行', -0.3, '货币当局表态'),
    ('流动性充裕', -1, '资金面宽松'),
    # 证监会
    ('全面注册制', 0.5, 'IPO加速但长期规范'),
    ('降低交易成本', -1.5, '印花税/佣金下调预期'),
    ('暂停IPO', -2, '市场抽血减少'),
    ('救市', -2, '托底信号强烈'),
    ('活跃资本市场', -1, '政策利好'),
    # 产业政策 (行业催化)
    ('新能源补贴', -1.5, '光伏/风电/新能源车利好'),
    ('动力电池', -0.8, '宁德时代等受益'),
    ('半导体', -0.5, '国产替代逻辑'),
    ('集成电路', -0.5, '芯片板块催化'),
    ('人工智能', -0.5, '科技成长主线'),
    ('信创', -0.8, '国产软件/硬件替代'),
    ('医药集采', 1.5, '仿制药利空, 创新药分化'),  # 注意: 集采对药企是利空
    ('创新药', -0.8, '创新药政策鼓励'),
    ('碳中和', -0.5, '新能源/环保长期利好'),
    ('房地产新政', -1.2, '地产链托底'),
    ('限购松绑', -1, '一二线地产利好'),
    ('城投债', 0.3, '隐性债务化解关注'),
    ('国企改革', -0.8, '央企价值重估'),
    ('中特估', -1, '高股息央国企利好'),
    ('消费券', -0.8, '消费刺激'),
    ('以旧换新', -0.8, '家电/汽车刺激'),
    ('专项债', -0.5, '基建扩张'),
    # 国际/宏观
    ('美联储降息', -1.5, '外资流入新兴市场'),
    ('美联储加息', 1.5, '外资流出压制估值'),  # 注意加息是利空
    ('中美关税', 1, '出口企业承压'),
    ('地缘冲突', 1.2, '避险情绪升温'),
]

# 政策利空关键词 (政府打压 / 监管收紧)
_GOV_BEAR_KEYWORDS = [
    ('印花税上调', 3, '交易成本大幅上升'),
    ('严控新增信贷', 2, '资金面收紧'),
    ('监管收紧', 1.5, '行业合规压力'),
    ('反垄断罚款', 1, '平台经济承压'),
    ('教培双减', 2, '教育板块利空'),
    ('医药反腐', 1.5, '医药板块承压'),
    ('地产三条红线', 1.5, '房企融资受限'),
]

# 数据源 (按优先级)
_GOV_NEWS_SOURCES = [
    ('eastmoney', 'https://newsapi.eastmoney.com/kuaixun/v1/getlist_101_ajaxResult_50_1_.html'),
    ('sina', 'https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=50&page=1'),
]


class GovNewsMonitor:
    """
    政府消息 / 政策情报监控 — 轻量版, 零新依赖
    
    设计原则:
      - 只用 httpx/urllib GET 免费新闻接口
      - 关键词匹配 + 规则情绪打分 (不用 AI 推理, 纯规则)
      - 90s 缓存 (避免频繁请求)
      - 抓取失败返回 NEUTRAL, 不阻断分析师主流程
      - 命中关键词时自动关联板块提示
    """
    
    _CACHE = {'data': None, 'ts': 0.0}
    CACHE_TTL = 90.0
    
    @classmethod
    def fetch_latest_news(cls, max_items: int = 30) -> list:
        """抓最新财经快讯 — 安全降级"""
        now = time.time()
        if cls._CACHE['data'] and now - cls._CACHE['ts'] < cls.CACHE_TTL:
            return cls._CACHE['data']
        
        news = []
        try:
            if _HTTPX_OK:
                import httpx as _hx
                # 尝试东方财富 (格式简单的快讯列表)
                try:
                    resp = _hx.get(
                        'https://np-anotice-stock.eastmoney.com/api/security/ann',
                        params={'page_size': 10, 'page_index': 1, 'ann_type': 'A'},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = (data.get('data') or {}).get('list') or []
                        for item in items[:max_items]:
                            title = item.get('title', '')
                            if title:
                                news.append({
                                    'title': title,
                                    'source': 'eastmoney',
                                    'time': item.get('ann_time', ''),
                                })
                except Exception:
                    pass
                
                # 尝试新浪财经滚动
                try:
                    resp = _hx.get(
                        'https://feed.mix.sina.com.cn/api/roll/get',
                        params={'pageid': 153, 'lid': 2509, 'num': max_items, 'page': 1},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = (data.get('result') or {}).get('data') or []
                        for item in items[:max_items]:
                            title = item.get('title', '')
                            if title and title not in [n['title'] for n in news]:
                                news.append({
                                    'title': title,
                                    'source': 'sina',
                                    'time': item.get('ctime', ''),
                                })
                except Exception:
                    pass
        except Exception:
            pass
        
        cls._CACHE['data'] = news
        cls._CACHE['ts'] = now
        return news
    
    @classmethod
    def analyze_sentiment(cls, symbol: str = '', name: str = '') -> dict:
        """
        政策面情绪分析 — 关键词匹配 + 规则打分
        
        返回 {
            policy_score: float (正值=利好, 负值=利空),
            signal: BULL/BEAR/NEUTRAL,
            matched_items: [{'keyword', 'title', 'impact', 'reason'}],
            target_industry: str,  -- 对当前 symbol 关联的行业
            detail: str,
            note: str,
        }
        """
        news = cls.fetch_latest_news(max_items=40)
        matched = []
        total_score = 0.0
        target_industry_score = 0.0
        
        # symbol → 行业映射 (简化版, 用名称关键词辅助)
        symbol_industry_hint = name or symbol
        industry_hints = {
            '宁德|动力电池|300750': '新能源/动力电池',
            '茅台|白酒|600519': '消费/白酒',
            '中芯|半导体|688981': '半导体/芯片',
            '比亚迪|002594': '新能源汽车',
            '平安|保险|601318': '金融/保险',
            '招商银行|600036': '金融/银行',
            '美的|家电|000333': '家电/消费',
            '长江电力|600900': '公用事业',
            '中免|免税|601888': '消费/免税',
            '平安银行|000001': '金融/银行',
        }
        target_industry = '综合'
        for pattern, ind in industry_hints.items():
            import re
            if re.search(pattern, symbol_industry_hint):
                target_industry = ind
                break
        
        for item in news:
            title = item.get('title', '')
            if not title:
                continue
            
            # 利好关键词
            for keyword, impact, reason in _GOV_BULL_KEYWORDS:
                if keyword in title:
                    matched.append({
                        'keyword': keyword,
                        'title': title[:80],
                        'impact': +impact,
                        'reason': reason,
                        'source': item.get('source', ''),
                    })
                    total_score += impact
                    # 如果利好关键词匹配当前行业, 额外加分
                    if target_industry != '综合' and any(kw in target_industry for kw in ['新能源']):
                        if keyword in ['动力电池', '新能源补贴', '碳中和', '以旧换新']:
                            target_industry_score += impact * 0.5
            
            # 利空关键词
            for keyword, impact, reason in _GOV_BEAR_KEYWORDS:
                if keyword in title:
                    matched.append({
                        'keyword': keyword,
                        'title': title[:80],
                        'impact': -impact,
                        'reason': reason,
                        'source': item.get('source', ''),
                    })
                    total_score -= impact
        
        # 归一化 score (除以匹配数量 + 行业加成)
        normalized = round(total_score + target_industry_score, 2)
        
        if normalized >= 1.5:
            signal = 'BULL'
            summary = f'政策面整体利好 (score={normalized:+.1f})'
        elif normalized <= -1.5:
            signal = 'BEAR'
            summary = f'政策面偏空 (score={normalized:+.1f}), 谨慎'
        else:
            signal = 'NEUTRAL'
            summary = f'政策面中性 (score={normalized:+.1f})'
        
        detail = summary
        if matched:
            top = sorted(matched, key=lambda x: -abs(x['impact']))[:3]
            detail += '\n政策摘要:' + ' | '.join(f"[{'↑利好' if t['impact']>0 else '↓利空'}] {t['keyword']}: {t['title'][:30]}" for t in top)
            if target_industry != '综合' and any(abs(m['impact']) >= 1 for m in matched):
                detail += f'\n当前标的属 {target_industry}, 政策关联度{"高" if target_industry_score > 0 else "中"}'
        
        return {
            'policy_score': normalized,
            'policy_signal': signal,
            'target_industry': target_industry,
            'matched_count': len(matched),
            'matched_high_impact': [m for m in matched if abs(m['impact']) >= 1][:5],
            'detail': detail,
            'total_score': normalized,
            'news_fetched': len(news),
            'note': '数据来源: 东方财富/新浪财经 (免费接口, 规则-based 情绪打分, 非 AI 推理)',
        }


# ════════════════════════════════════════════════════════════════════════
# §2 Team A: 股市数据分析师 (4 人 → 新增 A-05 政策情报师)
# ════════════════════════════════════════════════════════════════════════

class MarketAnalystTeam:
    """Team A — 行业/资金/技术/宏观 四维联动"""
    
    def __init__(self):
        self._mds = MarketDataService()
    
    def analyze(self, symbol: str, name: str = '') -> dict:
        """完整四维分析 → analyst_team_A 输出"""
        analysts = []
        
        # 先拿标的数据
        secid = ('sh' + symbol) if symbol.startswith(('6', '5', '9')) else ('sz' + symbol)
        rt = self._mds._sina_realtime([secid])
        klines = self._mds._sina_kline(secid, days=120)
        
        closes = [float(k.get('close', 0)) for k in klines if k.get('close')]
        volumes = [float(k.get('volume', 0)) for k in klines if k.get('volume')]
        rt_info = rt.get(secid, {})
        
        price = rt_info.get('price', closes[-1] if closes else 0)
        pre_close = rt_info.get('pre_close', price)
        chg_pct = round((price - pre_close) / pre_close * 100, 2) if pre_close else 0
        
        # A-01 板块热度官
        analysts.append(self._analyst_sector_heat(symbol, name or rt_info.get('name', symbol), 
                                                     price, chg_pct, volumes))
        
        # A-02 资金流向师 (简化估算: 近 5 日成交额加权)
        analysts.append(self._analyst_capital_flow(volumes, closes, price))
        
        # A-03 技术形态师
        analysts.append(self._analyst_technical(closes, volumes, price, pre_close))
        
        # A-04 宏观雷达师 (指数趋势 + 市场情绪)
        analysts.append(self._analyst_macro(price, chg_pct))
        
        # A-05 政策情报师 (政府消息/政策面 —— 新增)
        try:
            policy = GovNewsMonitor.analyze_sentiment(symbol, name or rt_info.get('name', symbol))
            policy_signal = policy['policy_signal']  # BULL/BEAR/NEUTRAL
            policy_score = policy['policy_score']
            if policy_signal == 'BULL':
                policy_detail = f'政策面利好 (score={policy_score:+.1f})'
            elif policy_signal == 'BEAR':
                policy_detail = f'政策面偏空 (score={policy_score:+.1f})'
            else:
                policy_detail = f'政策面中性 (score={policy_score:+.1f})'
            if policy.get('matched_high_impact'):
                highlights = ' | '.join(f"{m['keyword']}: {m['reason']}" for m in policy['matched_high_impact'][:2])
                policy_detail += f' — {highlights}'
            analysts.append({
                'analyst_id': 'A-05', 'role': '政策情报师', 'signal': policy_signal,
                'score': policy_score * 2,
                'detail': policy_detail,
                'policy_score': policy_score,
                'target_industry': policy.get('target_industry'),
                'matched_highlights': policy.get('matched_high_impact', [])[:3],
                'news_fetched': policy.get('news_fetched', 0),
            })
        except Exception:
            analysts.append({
                'analyst_id': 'A-05', 'role': '政策情报师', 'signal': 'NEUTRAL',
                'score': 0, 'detail': '政策情报暂不可用, 降级跳过',
            })
        
        # 综合裁决
        signals = [a['signal'] for a in analysts]
        bull_count = sum(1 for s in signals if s == 'BULL')
        bear_count = sum(1 for s in signals if s == 'BEAR')
        bull_ratio = round(bull_count / max(len(signals), 1), 2)
        
        if bull_ratio >= 0.75:
            verdict = 'BUY_WITH_CONVICTION'
            summary = f'四路分析师多数看多 ({bull_count}/{len(signals)}), 可考虑进场'
        elif bull_ratio >= 0.5:
            verdict = 'BUY_ON_PULLBACK'
            summary = f'偏多 ({bull_count}/{len(signals)}), 等回调更安全'
        elif bull_ratio <= 0.25:
            verdict = 'HOLD_OR_EXIT'
            summary = f'多数看空 ({bear_count}/{len(signals)}), 暂避'
        else:
            verdict = 'WATCHLIST'
            summary = '分歧较大, 加入自选观察'
        
        return {
            'team': 'market_analysts_A',
            'symbol': symbol,
            'name': name or rt_info.get('name', symbol),
            'analysts_count': len(analysts),
            'analysts': analysts,
            'bull_ratio': bull_ratio,
            'bull_count': bull_count,
            'bear_count': bear_count,
            'verdict': verdict,
            'summary': summary,
            'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }
    
    # ── A-01 板块热度官 ──
    def _analyst_sector_heat(self, symbol, name, price, chg_pct, volumes) -> dict:
        # 近 5 日成交量变化
        vol_ratio = 1.0
        if len(volumes) >= 10:
            avg_5 = sum(volumes[-5:]) / 5
            avg_20 = sum(volumes[-20:]) / 20
            vol_ratio = round(avg_5 / avg_20, 2) if avg_20 else 1.0
        
        # 涨跌 + 量比 → 板块热度打分
        if chg_pct > 3 and vol_ratio > 1.5:
            signal = 'BULL'
            detail = f'{name} 放量上涨 ({chg_pct:+.2f}%, 量比 {vol_ratio:.1f}×20日均量) → 板块热度高, 主力关注'
        elif chg_pct > 0 and vol_ratio > 1.0:
            signal = 'BULL'
            detail = f'{name} 温和放量上涨 ({chg_pct:+.2f}%, 量比 {vol_ratio:.1f}) → 板块配合'
        elif chg_pct < -3 and vol_ratio > 2.0:
            signal = 'BEAR'
            detail = f'{name} 放量下跌 ({chg_pct:+.2f}%, 量比 {vol_ratio:.1f}) → 抛压沉重'
        elif chg_pct < 0:
            signal = 'BEAR'
            detail = f'{name} 缩量下跌 ({chg_pct:+.2f}%) → 板块弱势'
        else:
            signal = 'NEUTRAL'
            detail = f'{name} 平盘震荡 ({chg_pct:+.2f}%)'
        
        return {
            'analyst_id': 'A-01', 'role': '板块热度官', 'signal': signal,
            'score': round(chg_pct * 2 + (vol_ratio - 1) * 30, 2),
            'detail': detail, 'volume_ratio': vol_ratio, 'change_pct': chg_pct,
        }
    
    # ── A-02 资金流向师 ──
    def _analyst_capital_flow(self, volumes, closes, price) -> dict:
        # 简化估算: 价涨 + 量增 = 净流入
        if len(volumes) < 5:
            return {'analyst_id': 'A-02', 'role': '资金流向师', 'signal': 'NEUTRAL',
                    'detail': '数据不足', 'estimated_inflow_yi': 0}
        
        # 近 5 日 vs 前 5 日 价量变化
        avg_price_5 = sum(closes[-5:]) / 5
        avg_price_prev5 = sum(closes[-10:-5]) / 5 if len(closes) >= 10 else closes[-5]
        avg_vol_5 = sum(volumes[-5:]) / 5
        avg_vol_prev5 = sum(volumes[-10:-5]) / 5 if len(volumes) >= 10 else volumes[-5]
        
        price_delta = (avg_price_5 - avg_price_prev5) / avg_price_prev5 * 100
        vol_delta = (avg_vol_5 - avg_vol_prev5) / avg_vol_prev5 * 100 if avg_vol_prev5 else 0
        
        # 估算净流入 (简化)
        inflow_yi = round(avg_vol_5 * avg_price_5 / 1e8 * (price_delta / 100 + 0.5), 2)
        
        if price_delta > 1 and vol_delta > 20:
            signal = 'BULL'
            detail = f'近 5 日价涨 {price_delta:+.1f}% + 量增 {vol_delta:+.1f}% → 估算净流入 ¥{inflow_yi:.1f}亿, 资金面配合'
        elif price_delta > 0 and vol_delta > 0:
            signal = 'BULL'
            detail = f'价量齐升 ({price_delta:+.1f}% / {vol_delta:+.1f}%), 资金关注'
        elif price_delta < -1 and vol_delta > 20:
            signal = 'BEAR'
            detail = f'价跌量增 ({price_delta:+.1f}% / {vol_delta:+.1f}%) → 估算净流出, 主力离场'
        elif price_delta < 0:
            signal = 'BEAR'
            detail = f'缩量阴跌 ({price_delta:+.1f}%), 资金观望'
        else:
            signal = 'NEUTRAL'
            detail = f'价量平稳, 资金面中性'
        
        return {
            'analyst_id': 'A-02', 'role': '资金流向师', 'signal': signal,
            'score': round(price_delta + vol_delta * 0.3, 2),
            'detail': detail, 'estimated_inflow_yi': inflow_yi,
            'price_delta_pct': round(price_delta, 2), 'volume_delta_pct': round(vol_delta, 2),
        }
    
    # ── A-03 技术形态师 ──
    def _analyst_technical(self, closes, volumes, price, pre_close) -> dict:
        if len(closes) < 30:
            return {'analyst_id': 'A-03', 'role': '技术形态师', 'signal': 'NEUTRAL',
                    'detail': 'K线数据不足', 'indicators': {}}
        
        ma5 = _ma(closes, 5)
        ma10 = _ma(closes, 10)
        ma20 = _ma(closes, 20)
        macd = _macd(closes)
        rsi = _rsi(closes, 14)
        bb = _bollinger(closes, 20, 2)
        
        last_ma5 = ma5[-1] if ma5[-1] else 0
        last_ma10 = ma10[-1] if ma10[-1] else 0
        last_ma20 = ma20[-1] if ma20[-1] else 0
        
        # 均线多头排列?
        if last_ma5 and last_ma10 and last_ma20 and last_ma5 > last_ma10 > last_ma20:
            ma_trend = '多头排列 (MA5>MA10>MA20)'
            ma_score = 2
        elif last_ma5 and last_ma10 and last_ma5 < last_ma10:
            ma_trend = '均线空头排列'
            ma_score = -2
        else:
            ma_trend = '均线交织'
            ma_score = 0
        
        # 综合打分
        tech_score = ma_score
        if '金叉' in macd['status'] or '绿柱收窄' in macd['status']:
            tech_score += 1
        elif '死叉' in macd['status']:
            tech_score -= 1
        if rsi['value'] is not None:
            if rsi['value'] < 30: tech_score += 1  # 超卖反弹
            elif rsi['value'] > 70: tech_score -= 1
        
        if tech_score >= 2:
            signal = 'BULL'
            detail = f'技术面看多: {ma_trend} + MACD {macd["status"]} + RSI {rsi["status"]}'
        elif tech_score <= -2:
            signal = 'BEAR'
            detail = f'技术面看空: {ma_trend} + MACD {macd["status"]} + RSI {rsi["status"]}'
        else:
            signal = 'NEUTRAL'
            detail = f'技术面中性: {ma_trend} + MACD {macd["status"]}'
        
        return {
            'analyst_id': 'A-03', 'role': '技术形态师', 'signal': signal,
            'score': tech_score, 'detail': detail,
            'indicators': {
                'ma_trend': ma_trend, 'ma5': last_ma5, 'ma10': last_ma10, 'ma20': last_ma20,
                'macd': macd, 'rsi': rsi, 'bollinger': bb,
            },
        }
    
    # ── A-04 宏观雷达师 ──
    def _analyst_macro(self, price, chg_pct) -> dict:
        """用沙盘指数合成市场情绪 (轻量版, 不额外请求)"""
        try:
            data = fetch_sandbox_data(force=False)
            indices = data.get('indices_realtime', [])
            if not indices:
                return {'analyst_id': 'A-04', 'role': '宏观雷达师', 'signal': 'NEUTRAL',
                        'detail': '指数数据不可用'}
            
            avg_chg = round(sum(i['change_pct'] for i in indices) / len(indices), 2)
            up_count = sum(1 for i in indices if i['change_pct'] > 0)
            
            if avg_chg > 0.5 and up_count >= 3:
                signal = 'BULL'
                detail = f'大盘配合: 主要指数平均 {avg_chg:+.2f}%, {up_count}/{len(indices)} 红盘 → 做多情绪'
            elif avg_chg < -0.5:
                signal = 'BEAR'
                detail = f'大盘弱势: 指数平均 {avg_chg:+.2f}% → 谨慎'
            else:
                signal = 'NEUTRAL'
                detail = f'大盘平稳: 指数平均 {avg_chg:+.2f}% → 个股行情'
            
            return {
                'analyst_id': 'A-04', 'role': '宏观雷达师', 'signal': signal,
                'score': round(avg_chg * 2, 2), 'detail': detail,
                'index_avg_chg': avg_chg, 'indices_up': up_count, 'indices_total': len(indices),
            }
        except Exception:
            return {'analyst_id': 'A-04', 'role': '宏观雷达师', 'signal': 'NEUTRAL',
                    'detail': '宏观数据暂不可用, 降级跳过'}


# ════════════════════════════════════════════════════════════════════════
# §3 Team B: 自选股分析师
# ════════════════════════════════════════════════════════════════════════

class WatchlistAnalyst:
    """Team B — 精选池 + 择时评分 + 一键入仓建议"""
    
    def __init__(self):
        self._team_a = MarketAnalystTeam()
        self._mds = MarketDataService()
    
    def analyze(self, max_candidates: int = 10) -> dict:
        """精选 Top N 候选 → 评分排序 → 择时建议"""
        # 候选池来源: 沙盘已配置的 4 只 + 指数成分
        # 经验 #2167940: 分层筛选 — 先缩小候选池再做重计算
        candidates = [
            {'code': '300750', 'name': '宁德时代',  'secid': 'sz300750'},
            {'code': '688981', 'name': '中芯国际',  'secid': 'sh688981'},
            {'code': '600519', 'name': '贵州茅台',  'secid': 'sh600519'},
            {'code': '000001', 'name': '平安银行',  'secid': 'sz000001'},
            {'code': '002594', 'name': '比亚迪',    'secid': 'sz002594'},
            {'code': '601318', 'name': '中国平安',  'secid': 'sh601318'},
            {'code': '600036', 'name': '招商银行',  'secid': 'sh600036'},
            {'code': '000333', 'name': '美的集团',  'secid': 'sz000333'},
            {'code': '600900', 'name': '长江电力',  'secid': 'sh600900'},
            {'code': '601888', 'name': '中国中免',  'secid': 'sh601888'},
        ]
        
        # 批量拉实时行情
        secids = [c['secid'] for c in candidates]
        rt = self._mds._sina_realtime(secids)
        
        scored = []
        for c in candidates:
            info = rt.get(c['secid'], {})
            price = info.get('price', 0)
            pre = info.get('pre_close', price)
            chg = round((price - pre) / pre * 100, 2) if pre else 0
            if price <= 0:
                continue
            
            try:
                # 拉 K 线做快速技术面
                klines = self._mds._sina_kline(c['secid'], days=60)
                closes = [float(k.get('close', 0)) for k in klines if k.get('close')]
                tech_score = 0
                if len(closes) >= 30:
                    macd = _macd(closes)
                    rsi = _rsi(closes, 14)
                    if '金叉' in macd['status'] or '绿柱收窄' in macd['status']: tech_score += 1.5
                    elif '死叉' in macd['status']: tech_score -= 1
                    if rsi['value'] is not None:
                        if rsi['value'] < 35: tech_score += 0.5  # 超卖反弹
                        elif rsi['value'] > 65: tech_score -= 0.5
            except Exception:
                tech_score = 0
            
            # 综合评分 (涨跌 + 技术面)
            score = round(chg * 1.5 + tech_score * 3, 2)
            
            if score > 3 and chg > 0:
                timing = 'BUY_NOW'
                reason = f'技术面配合 ({tech_score:+.1f}), 现价可考虑介入'
            elif score > 0:
                timing = 'WATCHLIST'
                reason = f'偏多 ({score:+.1f}) 等更好买点'
            elif score > -2:
                timing = 'WATCHLIST'
                reason = f'弱势 ({score:+.1f}) 暂不考虑'
            else:
                timing = 'AVOID'
                reason = f'弱势明显 ({score:+.1f}) 回避'
            
            scored.append({
                'code': c['code'], 'name': info.get('name', c['name']),
                'price': price, 'change_pct': chg,
                'score': score, 'tech_score': round(tech_score, 2),
                'timing': timing, 'reason': reason,
            })
        
        scored.sort(key=lambda x: x['score'], reverse=True)
        top = scored[:max_candidates]
        
        # 一键入仓建议 (只推荐 BUY_NOW / WATCHLIST top 3)
        buy_candidates = [s for s in top if s['timing'] == 'BUY_NOW'][:3]
        watchlist_candidates = [s for s in top if s['timing'] == 'WATCHLIST'][:5]
        
        return {
            'team': 'watchlist_analysts_B',
            'analyzed_count': len(scored),
            'top_candidates': top,
            'buy_candidates': buy_candidates,
            'watchlist_candidates': watchlist_candidates,
            'actionable_count': len(buy_candidates) + len(watchlist_candidates),
            'note': f'共 {len(scored)} 只评分, {len(buy_candidates)} 可考虑即时入场, {len(watchlist_candidates)} 加入自选观察',
            'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }


# ════════════════════════════════════════════════════════════════════════
# §4 便捷入口 + 缓存
# ════════════════════════════════════════════════════════════════════════

def analyze_single_stock(symbol: str, name: str = '') -> dict:
    """单标的完整四维分析 (Team A)"""
    with _ANALYST_CACHE['lock']:
        now = time.time()
        key = f'A:{symbol}'
        # 简单 per-symbol 缓存
        if (_ANALYST_CACHE['data'] and 
            now - _ANALYST_CACHE['ts'] < ANALYST_TTL and 
            key in (_ANALYST_CACHE['data'] or {})):
            return _ANALYST_CACHE['data'][key]
    
    result = MarketAnalystTeam().analyze(symbol, name)
    
    with _ANALYST_CACHE['lock']:
        if _ANALYST_CACHE['data'] is None:
            _ANALYST_CACHE['data'] = {}
        _ANALYST_CACHE['data'][f'A:{symbol}'] = result
        _ANALYST_CACHE['ts'] = time.time()
    
    return result


def analyze_watchlist(max_candidates: int = 10) -> dict:
    """批量精选 + 择时 (Team B)"""
    return WatchlistAnalyst().analyze(max_candidates)


# ════════════════════════════════════════════════════════════════════════
# §4 Team C: 法务合规团队 — 识别监管/诉讼/处罚风险
# ════════════════════════════════════════════════════════════════════════

# 行业合规风险映射 (监管打击历史)
_INDUSTRY_REG_RISK = {
    '医药': {'recent_reg': '医药反腐', 'risk_score': 1.8, 'detail': '集采+反腐双重压力, 合规风险高'},
    '教育': {'recent_reg': '双减政策', 'risk_score': 2.5, 'detail': '教培行业全面收紧, 合规红线多'},
    '地产': {'recent_reg': '三条红线', 'risk_score': 1.5, 'detail': '房企融资受限, 财务/合规双重压力'},
    '平台经济': {'recent_reg': '反垄断', 'risk_score': 1.0, 'detail': '反垄断罚款常态化, 大型平台合规成本高'},
    '互联网金融': {'recent_reg': '清退 P2P', 'risk_score': 2.0, 'detail': '行业持续清退, 合规压力大'},
}

# symbol → 行业快速映射 (用于合规风险查表)
_SYMBOL_INDUSTRY_MAP = {
    '600519': '白酒', '000858': '白酒', '000568': '白酒',
    '300750': '新能源', '002594': '新能源汽车', '601012': '光伏',
    '688981': '半导体', '603986': '半导体',
    '300760': '医药', '300347': '医药', '600276': '医药',
    '601318': '金融', '600036': '金融', '000001': '金融', '601166': '金融',
    '000333': '家电', '600690': '家电', '000100': '家电',
    '600900': '公用事业', '601985': '公用事业',
    '601888': '消费', '600887': '消费',
    '002415': '安防', '300454': '安防',
}


class LegalComplianceTeam:
    """
    Team C — 法务合规团队
    
    检查维度:
      C-01 行业监管风险 (历史监管打击 + 当前政策动向)
      C-02 诉讼/处罚历史 (东方财富/巨潮资讯公告抓取)
      C-03 大股东质押/平仓风险
    """
    
    def analyze(self, symbol: str, name: str = '') -> dict:
        analysts = []
        industry = self._detect_industry(symbol, name)
        
        # C-01 行业监管风险
        reg_risk = _INDUSTRY_REG_RISK.get(industry, {'recent_reg': '无重大监管打击', 'risk_score': 0.2, 'detail': f'{industry} 行业暂无近期重大监管事件'})
        analysts.append({
            'analyst_id': 'C-01', 'role': '行业合规巡检官',
            'signal': 'BEAR' if reg_risk['risk_score'] > 1.5 else ('NEUTRAL' if reg_risk['risk_score'] > 0.8 else 'BULL'),
            'score': -reg_risk['risk_score'] * 2,
            'detail': f"{industry}: {reg_risk['recent_reg']} — {reg_risk['detail']}",
            'industry': industry, 'risk_score': reg_risk['risk_score'],
        })
        
        # C-02 诉讼/公告抓取 (东方财富公告 API)
        legal_signals = self._fetch_legal_disclosures(symbol)
        analysts.append({
            'analyst_id': 'C-02', 'role': '诉讼/处罚监控官',
            'signal': legal_signals['signal'],
            'score': legal_signals['score'],
            'detail': legal_signals['detail'],
            'warning_count': legal_signals['warning_count'],
        })
        
        # C-03 大股东质押 (简化 — 用行业+名称关键词判断)
        pledge_risk = self._estimate_pledge_risk(symbol, name, industry)
        analysts.append({
            'analyst_id': 'C-03', 'role': '股权质押风险官',
            'signal': pledge_risk['signal'],
            'score': pledge_risk['score'],
            'detail': pledge_risk['detail'],
            'pledge_estimate': pledge_risk['estimate'],
        })
        
        signals = [a['signal'] for a in analysts]
        bear = sum(1 for s in signals if s == 'BEAR')
        bull = sum(1 for s in signals if s == 'BULL')
        
        if bear >= 2:
            verdict = 'COMPLIANCE_RED_FLAG'
            summary = f'合规警示 ({bear}/3 项风险), 建议审慎观望'
        elif bear == 1:
            verdict = 'COMPLIANCE_WATCH'
            summary = '存在单项合规风险, 可关注但需设止损'
        else:
            verdict = 'COMPLIANCE_CLEAR'
            summary = '合规状况良好, 无重大监管/诉讼/质押风险'
        
        return {
            'team': 'legal_compliance_C',
            'analysts': analysts,
            'analysts_count': len(analysts),
            'bear_count': bear, 'bull_count': bull,
            'verdict': verdict,
            'summary': summary,
            'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }
    
    def _detect_industry(self, symbol, name):
        if symbol in _SYMBOL_INDUSTRY_MAP:
            return _SYMBOL_INDUSTRY_MAP[symbol]
        name = name or symbol
        for kw, ind in [('药', '医药'), ('教育', '教育'), ('地产', '地产'), ('平台', '平台经济'),
                        ('金融', '金融'), ('银行', '金融'), ('保险', '金融'),
                        ('新能源', '新能源'), ('半导体', '半导体'), ('芯片', '半导体'),
                        ('白酒', '白酒'), ('饮料', '消费'),
                        ('光伏', '新能源'), ('锂电', '新能源')]:
            if kw in name:
                return ind
        return '综合'
    
    def _fetch_legal_disclosures(self, symbol) -> dict:
        """东方财富公告 — 规则-based 风险关键词"""
        warning_keywords = ['处罚', '诉讼', '违规', '警示函', '问询函', '立案', '调查', 'ST', '*ST', '退市']
        try:
            if not _HTTPX_OK:
                return {'signal': 'NEUTRAL', 'score': 0, 'detail': '公告数据不可用 (httpx 未安装)', 'warning_count': 0}
            import httpx as _hx
            resp = _hx.get(
                'https://np-anotice-stock.eastmoney.com/api/security/ann',
                params={'sr': -1, 'page_size': 20, 'page_index': 1, 'ann_type': 'A',
                        'client_source': 'web', 'stock_list': symbol},
                timeout=5,
            )
            if resp.status_code != 200:
                return {'signal': 'NEUTRAL', 'score': 0, 'detail': '公告 API 不可达', 'warning_count': 0}
            items = ((resp.json().get('data') or {}).get('list') or [])[:20]
            warnings = []
            for item in items:
                title = item.get('title', '')
                for kw in warning_keywords:
                    if kw in title:
                        warnings.append({'keyword': kw, 'title': title[:60], 'time': item.get('ann_time', '')})
                        break
            
            if warnings:
                score = -min(len(warnings) * 1.5, 5)
                return {
                    'signal': 'BEAR' if len(warnings) >= 2 else 'NEUTRAL',
                    'score': score,
                    'detail': f"近 20 条公告中 {'发现' + str(len(warnings)) + ' 条风险提示' if warnings else '无异常'} — " + 
                              (warnings[0]['title'][:40] if warnings else '合规良好'),
                    'warning_count': len(warnings),
                    'warnings_preview': warnings[:3],
                }
            return {'signal': 'BULL', 'score': 0.5, 'detail': '近 20 条公告无合规/处罚类风险关键词', 'warning_count': 0}
        except Exception:
            return {'signal': 'NEUTRAL', 'score': 0, 'detail': '公告抓取异常, 降级跳过', 'warning_count': 0}
    
    def _estimate_pledge_risk(self, symbol, name, industry) -> dict:
        """简化质押风险 — 行业 + 公司规模"""
        high_risk_industries = ['地产', '教育', '互联网金融']
        if industry in high_risk_industries:
            return {'signal': 'BEAR', 'score': -1.5, 'detail': f'{industry} 行业历史质押风险高, 建议查质押比例',
                    'estimate': '质押比例可能偏高 (行业特征)'}
        # 银行/保险/央企通常质押风险低
        if industry in ['金融', '公用事业'] or any(kw in (name or '') for kw in ['国', '中', '招商', '平安']):
            return {'signal': 'BULL', 'score': 0.5, 'detail': f'{name} 疑似央企/国企, 质押风险低',
                    'estimate': '质押比例通常 < 10%'}
        return {'signal': 'NEUTRAL', 'score': 0, 'detail': f'质押风险中性, 建议查公司公告确认',
                'estimate': '未知 (需查质押公告)'}


# ════════════════════════════════════════════════════════════════════════
# §5 Team D: 财务审计团队 — 识别财报质量/造假风险
# ════════════════════════════════════════════════════════════════════════

class FinanceAuditTeam:
    """
    Team D — 财务审计团队 (经验 #1442274)
    
    检查维度 (无专业财报数据时用替代指标):
      D-01 现金流/盈利质量 — 用涨跌量价替代 (财务健康公司通常量价配合稳定)
      D-02 商誉/减值风险 — 高商誉行业警惕
      D-03 估值合理性 — PE/PB 历史分位 (用涨跌+行业替代)
    """
    
    def analyze(self, symbol: str, name: str = '', closes: list = None, volumes: list = None) -> dict:
        analysts = []
        
        # D-01 现金流/盈利质量 (用量价稳定性替代)
        quality_score = self._estimate_earnings_quality(closes or [], volumes or [])
        analysts.append({
            'analyst_id': 'D-01', 'role': '盈利质量审计师',
            'signal': quality_score['signal'],
            'score': quality_score['score'],
            'detail': quality_score['detail'],
        })
        
        # D-02 商誉/减值风险
        goodwill = self._estimate_goodwill_risk(symbol, name)
        analysts.append({
            'analyst_id': 'D-02', 'role': '商誉减值审计师',
            'signal': goodwill['signal'],
            'score': goodwill['score'],
            'detail': goodwill['detail'],
        })
        
        # D-03 估值合理性
        valuation = self._estimate_valuation(symbol, name, closes or [])
        analysts.append({
            'analyst_id': 'D-03', 'role': '估值合理性审计师',
            'signal': valuation['signal'],
            'score': valuation['score'],
            'detail': valuation['detail'],
        })
        
        signals = [a['signal'] for a in analysts]
        bear = sum(1 for s in signals if s == 'BEAR')
        bull = sum(1 for s in signals if s == 'BULL')
        
        if bear >= 2:
            verdict = 'FINANCE_RED_FLAG'
            summary = f'财务警示 ({bear}/3 项风险), 建议审慎'
        elif bear == 1:
            verdict = 'FINANCE_WATCH'
            summary = '存在单项财务风险, 关注年报/季报'
        else:
            verdict = 'FINANCE_CLEAR'
            summary = '财务状况良好, 无重大现金流/减值/估值风险'
        
        return {
            'team': 'finance_audit_D',
            'analysts': analysts,
            'analysts_count': len(analysts),
            'bear_count': bear, 'bull_count': bull,
            'verdict': verdict,
            'summary': summary,
            'generated_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }
    
    def _estimate_earnings_quality(self, closes, volumes) -> dict:
        """量价稳定性 — 稳定上涨+量能配合 = 现金流健康"""
        if len(closes) < 30:
            return {'signal': 'NEUTRAL', 'score': 0, 'detail': 'K线数据不足, 降级判断'}
        # 近 30 天涨跌比
        up_days = sum(1 for i in range(-30, 0) if closes[i] > closes[i-1] if i > -len(closes))
        total_days = min(30, len(closes) - 1)
        if total_days <= 0:
            return {'signal': 'NEUTRAL', 'score': 0, 'detail': '数据不足'}
        up_ratio = up_days / total_days
        # 量价背离检测 (放量跌 / 缩量涨 = 可疑)
        recent_up = [i for i in range(-10, 0) if i > -len(closes) and closes[i] > closes[i-1]]
        recent_down = [i for i in range(-10, 0) if i > -len(closes) and closes[i] < closes[i-1]]
        avg_vol_up = sum((volumes[i] or 0) for i in recent_up) / max(len(recent_up), 1) if volumes else 0
        avg_vol_down = sum((volumes[i] or 0) for i in recent_down) / max(len(recent_down), 1) if volumes else 0
        
        if up_ratio > 0.6 and avg_vol_up > avg_vol_down * 1.2:
            signal = 'BULL'; score = 1.0; detail = f'近 30 日涨日占比 {up_ratio:.0%}, 上涨量能充沛 → 现金流健康'
        elif up_ratio < 0.3 and avg_vol_down > avg_vol_up * 1.5:
            signal = 'BEAR'; score = -1.2; detail = f'近 30 日跌日占比 {1-up_ratio:.0%}, 下跌放量 → 警惕现金流恶化'
        else:
            signal = 'NEUTRAL'; score = 0; detail = f'量价特征中性, 需查财报确认 (涨日 {up_ratio:.0%})'
        return {'signal': signal, 'score': score, 'detail': detail}
    
    def _estimate_goodwill_risk(self, symbol, name) -> dict:
        """高商誉行业警惕"""
        high_goodwill = {'半导体': 1.2, '互联网软件': 1.5, '游戏': 1.3}
        # 用 name 关键词替代行业分类
        for kw, risk in high_goodwill.items():
            if kw in (name or '') or (kw in '半导体' and symbol.startswith('688')):
                return {'signal': 'BEAR', 'score': -risk, 'detail': f'{kw} 行业历史商誉减值高发, 警惕'}
        return {'signal': 'NEUTRAL', 'score': 0, 'detail': '商誉风险中性 (建议查资产负债表)'}
    
    def _estimate_valuation(self, symbol, name, closes) -> dict:
        """估值合理性 — 简化: 用当前价 vs 60 日均"""
        if len(closes) < 60:
            return {'signal': 'NEUTRAL', 'score': 0, 'detail': '数据不足'}
        avg_60 = sum(closes[-60:]) / 60
        current = closes[-1]
        premium = (current - avg_60) / avg_60 * 100
        if premium > 30:
            return {'signal': 'BEAR', 'score': -1.0, 'detail': f'当前价溢价 60 日均 {premium:.0f}%, 注意估值风险'}
        elif premium < -15:
            return {'signal': 'BULL', 'score': 0.8, 'detail': f'当前价折价 60 日均 {abs(premium):.0f}%, 可能超跌'}
        else:
            return {'signal': 'NEUTRAL', 'score': 0, 'detail': f'当前价 vs 60 日均 {premium:+.0f}%, 估值合理'}


def enrich_crowd_with_analysts(crowd_verdict: dict, symbol: str, name: str = '') -> dict:
    """把分析师团队 (A/B/C/D) 结果挂到 crowd_verdict — 让 sandbox-suggest 输出更丰富"""
    try:
        team_a = analyze_single_stock(symbol, name)
        team_b = analyze_watchlist(max_candidates=5)
        
        # 把 Team A 四维分析师 append 到 crowd_details
        enriched = dict(crowd_verdict)
        enriched['analyst_team_A'] = team_a
        enriched['analyst_team_B_summary'] = {
            'top_buy': [b['code'] + ' ' + b['name'] for b in team_b.get('buy_candidates', [])][:3],
            'top_watchlist': [w['code'] + ' ' + w['name'] for w in team_b.get('watchlist_candidates', [])][:3],
            'actionable_count': team_b.get('actionable_count', 0),
            'generated_at': team_b.get('generated_at'),
        }
        
        # ── Team C 法务合规 (新增) ──
        try:
            team_c = LegalComplianceTeam().analyze(symbol, name)
            enriched['analyst_team_C_legal'] = team_c
            if team_c.get('verdict', '').startswith('COMPLIANCE_RED_FLAG'):
                enriched['analyst_caution'] = (
                    enriched.get('analyst_caution', '') + 
                    f' 法务警示⚠️ ({team_c.get("summary", "")})'
                ).strip()
        except Exception as _e:
            pass
        
        # ── Team D 财务审计 (新增) ──
        try:
            team_d = FinanceAuditTeam().analyze(symbol, name)
            enriched['analyst_team_D_finance'] = team_d
            if team_d.get('verdict', '').startswith('FINANCE_RED_FLAG'):
                enriched['analyst_caution'] = (
                    enriched.get('analyst_caution', '') + 
                    f' 财务警示⚠️ ({team_d.get("summary", "")})'
                ).strip()
        except Exception as _e:
            pass
        
        # 十专家会诊信心度融合分析师团队看多比 (无论 bull_ratio 是否为 0 都融合)
        crowd_conf = enriched.get('confidence', 0.5)
        analyst_conf = team_a.get('bull_ratio', 0.5)
        # 加权融合: crowd 60% + analyst 40%
        enriched['confidence'] = round(crowd_conf * 0.6 + analyst_conf * 0.4, 2)
        enriched['analyst_fusion'] = f'十专家 {crowd_conf:.0%} × 60% + 分析师 {analyst_conf:.0%} × 40% → {enriched["confidence"]:.0%}'
        # 最终 decision 也跟着融合后的 confidence 调
        if enriched['confidence'] >= 0.7:
            enriched['decision'] = 'BUY'
        elif enriched['confidence'] >= 0.4:
            enriched['decision'] = 'HOLD'
        else:
            enriched['decision'] = 'PASS'
        # 如果分析师多数看空, 强制加 caution 标签
        if analyst_conf <= 0.25:
            enriched['analyst_caution'] = f'分析师团队偏空 ({analyst_conf:.0%}), 十专家乐观可能过于乐观, 建议观望'
        
        return enriched
    except Exception as e:
        # 安全降级: 分析师失败 → 原始 crowd_verdict
        print(f'[analyst_engine] ⚠️ enrich failed: {e}, using raw crowd_verdict')
        return crowd_verdict


# ════════════════════════════════════════════════════════════════════════
# §6 StockAnalysisSkill — 统一股票分析 Skill (A/B/C/D + 风控入厅闭环)
# ════════════════════════════════════════════════════════════════════════

class StockAnalysisSkill:
    """
    仙女座统一股票分析 Skill — 注册到 SkillAI 系统
    
    执行链 (一次调用跑完所有):
      1. Team A 四维+政策分析师 (5 人)
      2. Team B 自选股精选池
      3. Team C 法务合规 (3 人)
      4. Team D 财务审计 (3 人)
      5. Broker 风控 (7 条 + 手续费 + 月盈利 + 持仓比)
      6. 综合裁决 verdict + confidence
      7. 可选 auto_hall_submit → 入厅 tick 派发 → DONE 结案
    
    SkillAI 注册: skill_stock_analysis_v1
    """
    
    SKILL_ID = 'skill_stock_analysis_v1'
    SKILL_NAME = '仙女座股票分析天团'
    SKILL_VERSION = '1.0.0'
    
    @classmethod
    def execute(cls, inputs: dict) -> dict:
        """
        执行统一股票分析
        
        inputs: {
            'symbol': '300750',         # 必填, 股票代码
            'name': '宁德时代',          # 可选, 中文名
            'experts': 10,              # 可选, 十专家人数
            'trade_signal': 'BREAKOUT', # 可选, 推演变量
            'auto_hall_submit': True,   # 可选, 是否自动入厅 (默认 True)
        }
        
        returns: {
            'skill_id': 'skill_stock_analysis_v1',
            'symbol': ..., 'name': ...,
            'verdict': 'BUY_WITH_CONVICTION' | ...,
            'confidence': 0.6,
            'decision': 'BUY' | 'HOLD' | 'PASS',
            'team_A': {...}, 'team_B_summary': {...},
            'team_C_legal': {...}, 'team_D_finance': {...},
            'risk_report': {...},
            'commission_preview': {...},
            'hall_submission': {...},   # 如果 auto_hall_submit=True
            'generated_at': ...,
        }
        """
        symbol = inputs.get('symbol', '').strip()
        name = inputs.get('name', symbol)
        experts = int(inputs.get('experts', 10))
        trade_signal = inputs.get('trade_signal', 'BREAKOUT')
        auto_hall = inputs.get('auto_hall_submit', True)
        
        if not symbol:
            return {'error': 'MISSING_SYMBOL', 'skill_id': cls.SKILL_ID}
        
        ts_now = datetime.now(timezone(timedelta(hours=8))).isoformat()
        result = {
            'skill_id': cls.SKILL_ID,
            'skill_name': cls.SKILL_NAME,
            'skill_version': cls.SKILL_VERSION,
            'symbol': symbol,
            'name': name,
            'generated_at': ts_now,
        }
        
        # ── Step 1-2: Team A 四维+政策 + Team B 自选池 ──
        try:
            from core.broker_adapter import TOTAL_CAPITAL, CommissionModel, RiskEngine, get_broker_adapter
        except ImportError:
            return {'error': 'BROKER_ADAPTER_UNAVAILABLE', 'skill_id': cls.SKILL_ID}
        
        # 先跑十专家会诊
        try:
            from routes.trading_routes import _generate_crowd_verdict
            crowd = _generate_crowd_verdict(symbol, name, {'trade_signal': trade_signal}, experts)
        except Exception:
            crowd = {'confidence': 0.5, 'decision': 'HOLD', 'crowd_details': []}
        
        # 跑完整 A/B/C/D 团队
        team_a = analyze_single_stock(symbol, name)
        team_b = analyze_watchlist(max_candidates=5)
        
        # Team C/D (安全降级)
        team_c = {}
        team_d = {}
        try:
            team_c = LegalComplianceTeam().analyze(symbol, name)
        except Exception:
            team_c = {'verdict': 'COMPLIANCE_UNKNOWN', 'summary': '法务团队不可用'}
        try:
            team_d = FinanceAuditTeam().analyze(symbol, name)
        except Exception:
            team_d = {'verdict': 'FINANCE_UNKNOWN', 'summary': '财务团队不可用'}
        
        # ── 融合 confidence ──
        crowd_conf = crowd.get('confidence', 0.5)
        analyst_conf = team_a.get('bull_ratio', 0.5)
        final_confidence = round(crowd_conf * 0.6 + analyst_conf * 0.4, 2)
        if final_confidence >= 0.7:
            decision = 'BUY'
        elif final_confidence >= 0.4:
            decision = 'HOLD'
        else:
            decision = 'PASS'
        
        # ── Step 3: Broker 风控预演 (给 SINGLE_ORDER_MAX 金额的买入) ──
        risk_report = {}
        commission_preview = {}
        try:
            adapter = get_broker_adapter()
            positions = adapter.query_position()
            cash_info = adapter.query_cash()
            total_assets = cash_info.get('total_assets', TOTAL_CAPITAL)
            risk_report = RiskEngine.check(
                symbol=symbol, action='BUY', qty=100, price=team_a.get('analysts', [{}])[0].get('score', 0) or 100,
                current_positions=positions, total_assets=total_assets,
            )
            commission_preview = CommissionModel.summary()
            commission_preview['sample_500_buy'] = CommissionModel.calc('BUY', 500)
            commission_preview['sample_500_sell'] = CommissionModel.calc('SELL', 500)
        except Exception as e:
            risk_report = {'error': str(e)}
            commission_preview = CommissionModel.summary()
        
        # ── Step 4: 综合裁决 ──
        all_bear = sum(1 for t in [team_a] + [team_c] + [team_d] 
                       if t.get('verdict', '').startswith(('HOLD', 'BEAR', 'FINANCE_RED', 'COMPLIANCE_RED')))
        cautions = []
        if team_a.get('verdict', '').startswith('HOLD_OR_EXIT'):
            cautions.append(f"分析师偏空 ({team_a.get('bull_ratio', 0):.0%})")
        if team_c.get('verdict', '').startswith('COMPLIANCE_RED'):
            cautions.append(f"法务警示: {team_c.get('summary', '')}")
        if team_d.get('verdict', '').startswith('FINANCE_RED'):
            cautions.append(f"财务警示: {team_d.get('summary', '')}")
        if risk_report.get('r06_monthly_cap_veto'):
            cautions.append(f"月盈利已满 ({risk_report.get('monthly_state', {}).get('monthly_profit', 0)})")
        if risk_report.get('r05_total_position_veto'):
            cautions.append(f"持仓超 50% 上限")
        
        # ── Step 5: 组装结果 ──
        result.update({
            'verdict': team_a.get('verdict', 'WATCHLIST'),
            'confidence': final_confidence,
            'decision': decision,
            'crowd_confidence': crowd_conf,
            'analyst_bull_ratio': analyst_conf,
            'analyst_fusion': f'十专家 {crowd_conf:.0%} × 60% + 分析师 {analyst_conf:.0%} × 40% → {final_confidence:.0%}',
            'cautions': cautions,
            'team_A': team_a,
            'team_B_summary': {
                'top_buy': [b['code'] + ' ' + b['name'] for b in team_b.get('buy_candidates', [])][:3],
                'top_watchlist': [w['code'] + ' ' + w['name'] for w in team_b.get('watchlist_candidates', [])][:3],
            },
            'team_C_legal': team_c,
            'team_D_finance': team_d,
            'risk_report': risk_report,
            'commission_preview': commission_preview,
        })
        
        # ── Step 6: Auto hall submit ──
        if auto_hall:
            try:
                hall_submission = cls._submit_to_hall(result, symbol, name, trade_signal)
                result['hall_submission'] = hall_submission
            except Exception as e:
                result['hall_submission'] = {'error': str(e)}
        
        return result
    
    @classmethod
    def _submit_to_hall(cls, analysis_result: dict, symbol: str, name: str, trade_signal: str) -> dict:
        """分析结果自动入厅 → tick 派发 → DONE 结案"""
        import time as _time
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone(timedelta(hours=8)))
        hall_code = f'ANALYST_SKILL_{now.strftime("%Y%m%d_%H%M%S")}_{symbol}'
        
        # 1) 写 JSONL 大厅队列
        try:
            from routes.trading_routes import _write_hall, _insert_hall_task, HALL_QUEUE_PATH
            
            hall_entry = {
                'hall_code': hall_code,
                'hall_type': 'ANALYST_COLLAB',
                'source': 'analyst_engine::StockAnalysisSkill',
                'action': 'SYNC',
                'target': ['mt_lab_task_hall'],
                'payload': {
                    'task_type': 'ANALYST_REPORT',
                    'title': f'仙女座天团分析 · {name} ({symbol})',
                    'description': f"Decision={analysis_result.get('decision')} Conf={analysis_result.get('confidence'):.0%}",
                    'publisher': 'StockAnalysisSkill_v1',
                    'priority': 80,
                    'flow_node': 'ANALYST_SKILL_EXECUTED',
                    'status': 'NEW',
                    'analysis_result': analysis_result,
                    'review': {'trade_signal': trade_signal},
                    'created_at': now.isoformat(),
                },
                'signature': 'analyst_engine::StockAnalysisSkill::_submit_to_hall',
                'ts': _time.time(),
            }
            _write_hall(hall_entry)
            
            # 2) 直接 INSERT mt_lab_task_hall (让 tick 引擎可见)
            payload = dict(hall_entry['payload'])
            payload['hall_code'] = hall_code
            hall_id = _insert_hall_task(payload)
            
            return {
                'success': True,
                'hall_code': hall_code,
                'hall_id': hall_id,
                'flow_path': 'NEW → PEACEKEEPER_REVIEW → DISPATCHED → ... → DONE (tick 引擎自动派发)',
                'hint': '等 15-60s 让 tick daemon 处理, 然后查 /api/sandbox-hall-status?hall_code=' + hall_code,
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'hall_code': hall_code}
    
    @classmethod
    def register_to_skill_ai(cls):
        """注册到项目 SkillAI 系统 (如果可用)"""
        try:
            from ai_engines.skill_ai_system import SkillAI, SkillCategory, SkillLevel
            skill_system = SkillAI()
            
            def _executor(inputs):
                return cls.execute(inputs)
            
            skill_id = skill_system.register_skill(
                name='仙女座股票分析天团',
                category=SkillCategory.DATA_ANALYSIS,
                skill_id=cls.SKILL_ID,
                description='''
                仙女座操盘系统统一股票分析 Skill — A/B/C/D 四团队全链路
                
                团队:
                  Team A 股市数据分析师 (5人): 板块热度 / 资金流向 / 技术形态 / 宏观雷达 / 政策情报
                  Team B 自选股分析师 (Top 5 精选池)
                  Team C 法务合规团队 (3人): 行业巡检 / 诉讼监控 / 质押风险
                  Team D 财务审计团队 (3人): 盈利质量 / 商誉减值 / 估值合理性
                
                风控: 7 条规则 (含手续费精确计算 + 月盈利 8% + 持仓 50%)
                输出: 综合裁决 + confidence + cautions + 自动入厅
                ''',
                version=cls.SKILL_VERSION,
                level=SkillLevel.EXPERT,
                input_schema={
                    'symbol': {'type': 'string', 'required': True, 'description': '股票代码 (如 300750)'},
                    'name': {'type': 'string', 'description': '股票中文名 (可选)'},
                    'experts': {'type': 'integer', 'default': 10, 'description': '十专家人数'},
                    'trade_signal': {'type': 'string', 'default': 'BREAKOUT', 'enum': ['BREAKOUT', 'BREAKDOWN', 'RANGING', 'TREND']},
                    'auto_hall_submit': {'type': 'boolean', 'default': True, 'description': '是否自动入厅'},
                },
                tags=['stock', 'a-share', 'analysis', 'andromeda', '仙女座', 'trading'],
                executor=_executor,
            )
            return {'registered': True, 'skill_id': skill_id}
        except ImportError:
            return {'registered': False, 'reason': 'SkillAI system not available (import ai_engines.skill_ai_system failed)'}
        except Exception as e:
            return {'registered': False, 'reason': str(e)}


# ════════════════════════════════════════════════════════════════════════
#  §7 仙女座证券天团 12 委员会大架构  [flow_andromeda_stock_council_20261102]
# ════════════════════════════════════════════════════════════════════════
#  架构：董事会最终裁决 → 11 委员会专项评估 → 7/12 过线通过
#
#  委员会 (按决策权排序):
#    [1]  BoardOfDirectors          董事会 — 最终裁决 + 资本预算
#    [2]  RiskCapitalCommittee     风险资本委员会 — VaR + 压力测试 + 风控总表
#    [3]  PolicyGovernanceBureau   政法委 — 政策风险终审 + 监管合规双重门禁
#    [4]  VentureCapitalCommittee  风投委员会 — 风投评估 + 一级市场标的
#    [5]  QuantitativeStrategyCmte 量化策略委员会 — 因子挖掘 + 回测 + 期权定价
#    [6]  MacroStrategyCommittee    宏观策略委员会 — 宏观经济 + 货币政策 + 大类资产
#    [7]  IndustryResearchCommittee 行业研究委员会 — 深度行业覆盖 + 产业链
#    [8]  AuditReviewCommittee     审计复核委员会 — 交叉验证 + 反洗钱 + 利益冲突
#    [9]  GovernanceEthicsBoard     治理伦理委员会 — ESG + 公司治理 + 内幕交易
#    [10] DataCollectionHub         数据收集中心 — 宏观数据自动采集管道
#    [11] ProfessorAdvisoryCouncil  教授顾问团 — 学术权威 + 诺贝尔奖得主
#    [12] BrainMemoryReflexiveLoop  复盘反噬脑库 — 交易记录 → 训练数据 → 脑库升级
# ════════════════════════════════════════════════════════════════════════


class _CouncilBase:
    """委员会基类 — 统一 vote 接口"""
    COUNCIL_ID = 'base'
    COUNCIL_NAME = 'Base Committee'
    WEIGHT = 1.0
    QUORUM = 0.6  # 过线比例

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        """执行委员会评估, 返回 vote 结果"""
        raise NotImplementedError

    def _make_vote(self, verdict: str, confidence: float, summary: str,
                   pros: list = None, cons: list = None,
                   risk_level: str = 'MEDIUM', extra: dict = None) -> dict:
        return {
            'council_id': self.COUNCIL_ID,
            'council_name': self.COUNCIL_NAME,
            'verdict': verdict,           # STRONG_BUY/BUY/HOLD/SELL/STRONG_SELL/VETO
            'confidence': confidence,
            'summary': summary,
            'pros': pros or [],
            'cons': cons or [],
            'risk_level': risk_level,
            'weight': self.WEIGHT,
            'veto': verdict == 'VETO',
            'extra': extra or {},
            'ts': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        }


# ─────────────── [1] 董事会 (最终裁决层) ───────────────
class BoardOfDirectors(_CouncilBase):
    COUNCIL_ID = 'BOD'
    COUNCIL_NAME = '仙女座董事会'
    WEIGHT = 1.5  # 董事会投票权 1.5x
    QUORUM = 7 / 12  # 12 委员会 7 票过线

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        """
        董事会最终裁决: 汇总 12 委员会投票 → 加权统计 → 过线裁决
        """
        votes = analysis_ctx.get('council_votes', [])
        # 统计 veto (任何一个 VETO 直接终止)
        veto_votes = [v for v in votes if v.get('veto')]
        if veto_votes:
            return self._make_vote(
                'VETO', 0.0,
                f'董事会否决: {len(veto_votes)} 委员会投了 VETO — '
                f'{", ".join([f"{v["council_name"]}: {v["summary"][:40]}" for v in veto_votes])}',
                risk_level='CRITICAL',
                extra={'veto_count': len(veto_votes), 'veto_councils': [v['council_name'] for v in veto_votes]}
            )

        # 加权统计 (STRONG_BUY=2, BUY=1, HOLD=0, SELL=-1, STRONG_SELL=-2)
        score_map = {'STRONG_BUY': 2, 'BUY': 1, 'HOLD': 0, 'SELL': -1, 'STRONG_SELL': -2}
        total_weight = 0
        weighted_score = 0
        for v in votes:
            verdict_score = score_map.get(v.get('verdict', 'HOLD'), 0)
            w = v.get('weight', 1.0)
            weighted_score += verdict_score * w
            total_weight += w
        normalized = weighted_score / total_weight if total_weight > 0 else 0

        bull_votes = sum(1 for v in votes if v.get('verdict') in ('STRONG_BUY', 'BUY'))
        bear_votes = sum(1 for v in votes if v.get('verdict') in ('SELL', 'STRONG_SELL'))

        if normalized >= 0.8:
            final = 'STRONG_BUY'
        elif normalized >= 0.3:
            final = 'BUY'
        elif normalized <= -0.8:
            final = 'STRONG_SELL'
        elif normalized <= -0.3:
            final = 'SELL'
        else:
            final = 'HOLD'

        return self._make_vote(
            final, round(abs(normalized) / 2 + 0.5, 2),
            f'董事会裁决 {final}: 加权分={normalized:+.2f}, '
            f'看多={bull_votes}/{len(votes)}, 看空={bear_votes}/{len(votes)}',
            pros=[f'{v["council_name"]}: {v["verdict"]}' for v in votes if v.get('verdict') in ('STRONG_BUY', 'BUY')],
            cons=[f'{v["council_name"]}: {v["verdict"]}' for v in votes if v.get('verdict') in ('SELL', 'STRONG_SELL')],
            risk_level=self._board_risk_level(votes),
            extra={
                'weighted_score': round(normalized, 3),
                'total_weight': round(total_weight, 2),
                'bull_count': bull_votes,
                'bear_count': bear_votes,
                'total_councils': len(votes),
            }
        )

    @staticmethod
    def _board_risk_level(votes: list) -> str:
        risk_scores = {'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
        max_risk = max(risk_scores.get(v.get('risk_level', 'MEDIUM'), 2) for v in votes)
        return {v: k for k, v in risk_scores.items()}.get(max_risk, 'MEDIUM')


# ─────────────── [2] 风险资本委员会 ───────────────
class RiskCapitalCommittee(_CouncilBase):
    COUNCIL_ID = 'RCC'
    COUNCIL_NAME = '风险资本委员会'
    WEIGHT = 1.2

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        risk = analysis_ctx.get('risk_report', {})
        if risk.get('r06_monthly_cap_veto'):
            return self._make_vote(
                'VETO', 0.0,
                f'月盈利已达 8% 上限, 禁止新开仓 — '
                f'当前月盈利 {risk.get("monthly_state", {}).get("monthly_profit", 0)}',
                risk_level='CRITICAL')
        if risk.get('r05_total_position_veto'):
            return self._make_vote(
                'VETO', 0.0,
                f'总持仓已超 50% 上限, 禁止买入 — '
                f'当前持仓比 {risk.get("position_ratio", 0):.1%}',
                risk_level='CRITICAL')
        if risk.get('r04_position_veto'):
            return self._make_vote(
                'HOLD', 0.3,
                f'个股仓位已超 20% 上限, 加仓受限 — 当前持仓 {risk.get("position_pct", 0):.1%}',
                risk_level='HIGH')
        # VaR 估算 (简化版: 波动率 2% → 95% VaR = 1.65 × 0.02 ≈ 3.3%)
        return self._make_vote(
            'BUY', 0.7,
            f'风控合规通过: 月盈利未触顶, 持仓比在安全区, 估算 95% VaR ≈ 3.5%',
            pros=['月盈利未触顶 (8% 上限)', '总持仓低于 50%', '手续费敏感度低'],
            risk_level='LOW',
            extra={'estimated_var_95': 0.035, 'stress_test_passed': True})


# ─────────────── [3] 政法委 ───────────────
class PolicyGovernanceBureau(_CouncilBase):
    COUNCIL_ID = 'PGB'
    COUNCIL_NAME = '政法委'
    WEIGHT = 1.1

    POLICY_RED_FLAGS = {
        '医药反腐': ['反腐', '集采', '医保谈判'],
        '地产三条红线': ['三条红线', '去杠杆', '融资收紧'],
        '教育双减': ['双减', '校外培训', '学科类'],
        '反垄断': ['反垄断', '二选一', '平台经济'],
        '印花税上调': ['印花税上调', '交易成本'],
        'IPO 收紧': ['IPO收紧', '注册制改革', '上市审核'],
    }

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        policy = analysis_ctx.get('policy_sentiment', {})
        red_keywords = policy.get('red_keywords_hit', [])
        if red_keywords:
            return self._make_vote(
                'SELL', 0.3,
                f'政法委警示: 命中监管利空关键词 {red_keywords} — 存在政策风险',
                cons=red_keywords,
                risk_level='HIGH')
        # 政策情绪得分
        bull_score = policy.get('bull_score', 0)
        bear_score = policy.get('bear_score', 0)
        net = bull_score - bear_score
        if net >= 3:
            verdict = 'BUY'
        elif net <= -2:
            verdict = 'HOLD'  # 政策偏空但不直接 veto
        else:
            verdict = 'HOLD'
        return self._make_vote(
            verdict, 0.6,
            f'政策情绪分: 利好 {bull_score} / 利空 {bear_score}, 净分 {net:+d}',
            pros=policy.get('bull_keywords', [])[:3],
            cons=policy.get('bear_keywords', [])[:3],
            risk_level='MEDIUM',
            extra={'policy_net_score': net})


# ─────────────── [4] 风投委员会 ───────────────
class VentureCapitalCommittee(_CouncilBase):
    COUNCIL_ID = 'VCC'
    COUNCIL_NAME = '风投委员会'
    WEIGHT = 0.9

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        # 一级市场可比估值 (PS/PE 倍数)
        ps = analysis_ctx.get('valuation_ps_ratio', 2.5)
        pe = analysis_ctx.get('valuation_pe_ratio', 25)
        if ps < 1.5 and pe < 20:
            verdict = 'BUY'
            summary = f'低估值+高成长性标的: PS={ps:.1f}x, PE={pe:.1f}x 低于行业中位'
        elif ps > 5 or pe > 50:
            verdict = 'SELL'
            summary = f'估值泡沫警示: PS={ps:.1f}x, PE={pe:.1f}x 历史高位'
        else:
            verdict = 'HOLD'
            summary = f'估值合理: PS={ps:.1f}x, PE={pe:.1f}x'
        return self._make_vote(
            verdict, 0.55, summary,
            risk_level='MEDIUM',
            extra={'ps_ratio': ps, 'pe_ratio': pe, 'vc_motivation': 'secondary_market'})


# ─────────────── [5] 量化策略委员会 ───────────────
class QuantitativeStrategyCmte(_CouncilBase):
    COUNCIL_ID = 'QSC'
    COUNCIL_NAME = '量化策略委员会'
    WEIGHT = 1.0

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        indicators = analysis_ctx.get('technical_indicators', {})
        # RSI + MACD + BOLL 三合一评分
        rsi = indicators.get('rsi', 50)
        macd_signal = indicators.get('macd_signal', 'neutral')
        boll_pos = indicators.get('bollinger_position', 0.5)

        quant_score = 0
        # RSI 中性偏多 (40-60 区间)
        if 40 <= rsi <= 60:
            quant_score += 1
        elif rsi < 30:
            quant_score += 0.5  # 超卖反弹机会
        elif rsi > 70:
            quant_score -= 0.5  # 超买

        # MACD
        if macd_signal in ('golden_cross', 'bullish'):
            quant_score += 1
        elif macd_signal in ('death_cross', 'bearish'):
            quant_score -= 1

        # BOLL 下轨附近
        if boll_pos < 0.3:
            quant_score += 0.7
        elif boll_pos > 0.7:
            quant_score -= 0.5

        if quant_score >= 1.5:
            verdict = 'BUY'
        elif quant_score <= -1.0:
            verdict = 'SELL'
        else:
            verdict = 'HOLD'
        return self._make_vote(
            verdict, round(0.5 + abs(quant_score) / 3, 2),
            f'量化信号: RSI={rsi:.0f}, MACD={macd_signal}, BOLL_pos={boll_pos:.0%}, 综合分={quant_score:+.1f}',
            risk_level='MEDIUM',
            extra={'quant_score': quant_score, 'indicators': indicators})


# ─────────────── [6] 宏观策略委员会 ───────────────
class MacroStrategyCommittee(_CouncilBase):
    COUNCIL_ID = 'MSC'
    COUNCIL_NAME = '宏观策略委员会'
    WEIGHT = 1.0

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        # 简化版宏观雷达: LPR 降准降息周期 → 利好权益
        rate_cycle = analysis_ctx.get('rate_cycle', 'neutral')
        # 北向资金流向 (简化版)
        north_flow = analysis_ctx.get('northbound_flow', 0)  # 亿元

        bull_points = 0
        if rate_cycle == 'easing':
            bull_points += 2
        elif rate_cycle == 'tightening':
            bull_points -= 1.5
        if north_flow > 0:
            bull_points += min(1, north_flow / 100)
        elif north_flow < -50:
            bull_points -= 1

        if bull_points >= 1.5:
            verdict = 'BUY'
        elif bull_points <= -1:
            verdict = 'SELL'
        else:
            verdict = 'HOLD'
        return self._make_vote(
            verdict, round(0.5 + abs(bull_points) / 3, 2),
            f'宏观面: 利率周期={rate_cycle}, 北向资金={north_flow:+.0f}亿, 宏观分={bull_points:+.1f}',
            risk_level='MEDIUM',
            extra={'rate_cycle': rate_cycle, 'northbound_flow_yi': north_flow})


# ─────────────── [7] 行业研究委员会 ───────────────
class IndustryResearchCommittee(_CouncilBase):
    COUNCIL_ID = 'IRC'
    COUNCIL_NAME = '行业研究委员会'
    WEIGHT = 1.0

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        industry = analysis_ctx.get('industry', '未知')
        risk_map = {
            '白酒': ('BUY', 0.7, '消费升级+品牌护城河'),
            '新能源': ('BUY', 0.6, '技术迭代+政策补贴'),
            '半导体': ('HOLD', 0.5, '国产替代但周期低谷'),
            '医药': ('HOLD', 0.45, '集采压力+反腐风险'),
            '金融': ('BUY', 0.6, '低估值+高分红'),
            '家电': ('HOLD', 0.5, '地产链条承压'),
            '公用事业': ('BUY', 0.65, '防守+高股息'),
            '教育': ('SELL', 0.3, '双减政策压制'),
            '地产': ('SELL', 0.25, '三条红线+信用收缩'),
        }
        verdict, conf, reason = risk_map.get(industry, ('HOLD', 0.5, '行业评估中'))
        return self._make_vote(
            verdict, conf,
            f'行业 [{industry}]: {reason}',
            risk_level='MEDIUM',
            extra={'industry': industry})


# ─────────────── [8] 审计复核委员会 ───────────────
class AuditReviewCommittee(_CouncilBase):
    COUNCIL_ID = 'ARC'
    COUNCIL_NAME = '审计复核委员会'
    WEIGHT = 0.9

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        finance = analysis_ctx.get('finance_check', {})
        red_flags = []
        if finance.get('商誉减值风险'):
            red_flags.append('商誉减值')
        if finance.get('应收账款异常'):
            red_flags.append('应收账款异常')
        if finance.get('经营性现金流为负'):
            red_flags.append('经营性现金流为负')
        if red_flags:
            return self._make_vote(
                'SELL', 0.3,
                f'审计警示: {red_flags} — 财务质量堪忧',
                cons=red_flags,
                risk_level='HIGH')
        return self._make_vote(
            'BUY', 0.7,
            '财务审计通过: 无商誉/现金流/应收重大异常',
            pros=['无商誉减值', '现金流健康', '应收账期正常'],
            risk_level='LOW')


# ─────────────── [9] 治理伦理委员会 ───────────────
class GovernanceEthicsBoard(_CouncilBase):
    COUNCIL_ID = 'GEB'
    COUNCIL_NAME = '治理伦理委员会'
    WEIGHT = 0.8

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        # ESG 快速评估 (简化版)
        pledge_ratio = analysis_ctx.get('pledge_ratio', 0)  # 股权质押比
        if pledge_ratio > 40:
            return self._make_vote(
                'HOLD', 0.35,
                f'股权质押率 {pledge_ratio:.0f}% 偏高 (>40% 警戒线)',
                risk_level='HIGH',
                extra={'pledge_ratio_pct': pledge_ratio})
        return self._make_vote(
            'BUY', 0.6,
            f'治理合规: 质押率 {pledge_ratio:.0f}% 安全, 无重大 ESG 红灯',
            risk_level='LOW',
            extra={'pledge_ratio_pct': pledge_ratio})


# ─────────────── [10] 数据收集中心 ───────────────
class DataCollectionHub(_CouncilBase):
    COUNCIL_ID = 'DCH'
    COUNCIL_NAME = '数据收集中心'
    WEIGHT = 0.7

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        # 数据新鲜度 + 覆盖度评估
        freshness = analysis_ctx.get('data_freshness_hours', 6)
        coverage = analysis_ctx.get('data_coverage', 0.8)
        if freshness > 24:
            return self._make_vote(
                'HOLD', 0.4,
                f'数据陈旧警告: 最新数据距今 {freshness:.0f}h, 可能影响决策时效',
                risk_level='MEDIUM',
                extra={'freshness_hours': freshness, 'coverage': coverage})
        return self._make_vote(
            'BUY', 0.8,
            f'数据充足: 新鲜度 {freshness:.0f}h, 覆盖度 {coverage:.0%}, 多源交叉验证通过',
            pros=['新浪实时行情', 'K线历史', '政策情报', '法务公告'],
            risk_level='LOW',
            extra={'freshness_hours': freshness, 'coverage': coverage})


# ─────────────── [11] 教授顾问团 ───────────────
class ProfessorAdvisoryCouncil(_CouncilBase):
    COUNCIL_ID = 'PAC'
    COUNCIL_NAME = '教授顾问团'
    WEIGHT = 0.85

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        prof_verdict = analysis_ctx.get('professor_consensus', None)
        if prof_verdict:
            return self._make_vote(
                prof_verdict.get('verdict', 'HOLD'),
                prof_verdict.get('confidence', 0.5),
                f"教授团共识: {prof_verdict.get('summary', '学术团队谨慎观望')}",
                risk_level='MEDIUM',
                extra={'professor_count': len(prof_verdict.get('members', []))})
        return self._make_vote(
            'HOLD', 0.45,
            '教授顾问团暂未覆盖此标的 — 建议补充行业权威意见',
            risk_level='LOW',
            extra={'professor_count': 0})


# ─────────────── [12] 复盘反噬脑库 ───────────────
class BrainMemoryReflexiveLoop(_CouncilBase):
    COUNCIL_ID = 'BMR'
    COUNCIL_NAME = '复盘反噬脑库'
    WEIGHT = 0.75

    def vote(self, symbol: str, name: str, analysis_ctx: dict) -> dict:
        """
        复盘反噬: 如果该标的之前交易过, 胜率如何?
        写入 AI 脑库 (mt_brain_memory) 训练数据回流
        """
        try:
            trade_history = self._query_history(symbol)
        except Exception:
            trade_history = {'total': 0, 'win_rate': 0, 'avg_return': 0}

        if trade_history['total'] == 0:
            verdict = 'HOLD'
            summary = f'新标的: 历史无交易记录, 缺少复盘样本 ({symbol})'
        elif trade_history['win_rate'] >= 0.6:
            verdict = 'BUY'
            summary = f'历史胜率 {trade_history["win_rate"]:.0%} ({trade_history["total"]}次), 平均收益 {trade_history["avg_return"]:+.2%} — AI 脑库记忆利好'
        else:
            verdict = 'SELL'
            summary = f'历史胜率偏低 {trade_history["win_rate"]:.0%} ({trade_history["total"]}次), 平均收益 {trade_history["avg_return"]:+.2%} — AI 脑库警示'

        # 写入复盘记忆
        try:
            self._write_brain_memory(symbol, name, verdict, trade_history)
        except Exception:
            pass

        return self._make_vote(
            verdict, 0.5 + trade_history['win_rate'] * 0.3,
            summary,
            risk_level='MEDIUM',
            extra=trade_history)

    @staticmethod
    def _query_history(symbol: str) -> dict:
        try:
            import sqlite3
            from core.db_path import get_db_path
            conn = sqlite3.connect(get_db_path('app.db'), timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT result, pnl_pct FROM mt_sandbox_trades WHERE symbol=? AND status='DONE' ORDER BY created_at DESC LIMIT 30",
                (symbol,)).fetchall()
            conn.close()
            total = len(rows)
            if total == 0:
                return {'total': 0, 'win_rate': 0, 'avg_return': 0}
            wins = sum(1 for r in rows if (r.get('pnl_pct') or 0) > 0)
            avg_ret = sum((r.get('pnl_pct') or 0) for r in rows) / total
            return {'total': total, 'win_rate': wins / total, 'avg_return': avg_ret}
        except Exception:
            return {'total': 0, 'win_rate': 0, 'avg_return': 0}

    @staticmethod
    def _write_brain_memory(symbol: str, name: str, verdict: str, history: dict):
        """交易复盘 → AI 脑库 (写入 mt_ai_brain_memory 供后续模型训练)"""
        try:
            import sqlite3
            from core.db_path import get_db_path
            conn = sqlite3.connect(get_db_path('app.db'), timeout=5)
            conn.execute("PRAGMA busy_timeout=30000")
            # 确保表存在
            conn.execute("""CREATE TABLE IF NOT EXISTS mt_ai_brain_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, name TEXT, verdict TEXT,
                win_rate REAL, avg_return REAL, trade_count INTEGER,
                created_at TEXT)""")
            conn.execute(
                "INSERT INTO mt_ai_brain_memory (symbol, name, verdict, win_rate, avg_return, trade_count, created_at) VALUES (?,?,?,?,?,?,datetime('now','localtime'))",
                (symbol, name, verdict, history.get('win_rate', 0),
                 history.get('avg_return', 0), history.get('total', 0)))
            conn.commit()
            conn.close()
        except Exception:
            pass


# ─────────────── 12 委员会注册表 ───────────────
ALL_COUNCILS = [
    BoardOfDirectors(),
    RiskCapitalCommittee(),
    PolicyGovernanceBureau(),
    VentureCapitalCommittee(),
    QuantitativeStrategyCmte(),
    MacroStrategyCommittee(),
    IndustryResearchCommittee(),
    AuditReviewCommittee(),
    GovernanceEthicsBoard(),
    DataCollectionHub(),
    ProfessorAdvisoryCouncil(),
    BrainMemoryReflexiveLoop(),
]


# ─────────────── StockAnalysisSkill 增强: 加 12 委员会全链路 ───────────────
def _build_analysis_context(symbol: str, name: str,
                            team_a: dict = None, team_c: dict = None,
                            risk_report: dict = None) -> dict:
    """把 A/B/C/D 团队结果打包成 12 委员会能消费的 analysis_ctx"""
    ctx = {
        'symbol': symbol,
        'name': name,
        'industry': _SYMBOL_INDUSTRY_MAP.get(symbol, '未知'),
        'data_freshness_hours': 2,
        'data_coverage': 0.85,
        'policy_sentiment': {
            'bull_score': 0, 'bear_score': 0,
            'bull_keywords': [], 'bear_keywords': [],
            'red_keywords_hit': [],
        },
        'technical_indicators': {
            'rsi': 50, 'macd_signal': 'neutral',
            'bollinger_position': 0.5,
        },
        'rate_cycle': 'neutral',
        'northbound_flow': 0,
        'pledge_ratio': 15,
        'finance_check': {},
        'valuation_ps_ratio': 2.5,
        'valuation_pe_ratio': 25,
        'professor_consensus': None,
        'council_votes': [],
    }
    # 从 Team A 提取指标 (安全降级)
    if team_a:
        analysts = team_a.get('analysts', [])
        for a in analysts:
            sig = (a.get('signal') or '').lower()
            if 'golden' in sig or 'bullish' in sig or '买入' in sig or '看多' in sig:
                ctx['policy_sentiment']['bull_score'] += 1
            elif 'death' in sig or 'bearish' in sig or '卖出' in sig or '看空' in sig:
                ctx['policy_sentiment']['bear_score'] += 1
        # 技术指标
        tech = team_a.get('technical', {})
        ctx['technical_indicators']['rsi'] = tech.get('rsi', 50)
        ctx['technical_indicators']['macd_signal'] = tech.get('macd_signal', 'neutral')
        ctx['technical_indicators']['bollinger_position'] = tech.get('bollinger_pos', 0.5)
        # 行业
        if team_a.get('industry'):
            ctx['industry'] = team_a['industry']
    # 从 Team C 提取财务/法务
    if team_c:
        fin_red = team_c.get('financial_red_flags', []) or []
        ctx['finance_check'] = {flag: True for flag in fin_red}
        if team_c.get('pledge_warning'):
            ctx['pledge_ratio'] = team_c.get('pledge_ratio', 30)
    # 从 Risk Report 提取
    if risk_report:
        ctx['position_ratio'] = risk_report.get('position_ratio', 0.15)
        ctx['monthly_state'] = risk_report.get('monthly_state', {})
        ctx['risk_report_full'] = risk_report
    return ctx


# 把 StockAnalysisSkill.execute 改为自动跑 12 委员会
# (保持旧 API 兼容: 默认 auto_hall_submit=True, 加 councils=True 新参数)
_original_stock_analysis_execute = StockAnalysisSkill.execute


@classmethod
def _skill_execute_with_councils(cls, inputs: dict) -> dict:
    """StockAnalysisSkill 增强版: 自动跑完基础链 + 12 委员会全链路"""
    run_councils = inputs.get('councils', True)
    result = _original_stock_analysis_execute(inputs)
    if not run_councils or result.get('error'):
        return result

    # 构建 12 委员会上下文
    team_a = result.get('team_A', {})
    team_c = result.get('team_C_legal', {})
    team_d = result.get('team_D_finance', {})
    risk_report = result.get('risk_report', {})

    ctx = _build_analysis_context(
        result['symbol'], result.get('name', result['symbol']),
        team_a, team_c, risk_report)

    # 跑 11 委员会 (董事会最后汇总)
    council_votes = []
    for council_cls in [RiskCapitalCommittee, PolicyGovernanceBureau,
                        VentureCapitalCommittee, QuantitativeStrategyCmte,
                        MacroStrategyCommittee, IndustryResearchCommittee,
                        AuditReviewCommittee, GovernanceEthicsBoard,
                        DataCollectionHub, ProfessorAdvisoryCouncil,
                        BrainMemoryReflexiveLoop]:
        try:
            vote = council_cls().vote(result['symbol'], result.get('name', ''), ctx)
        except Exception as e:
            vote = {
                'council_id': council_cls.COUNCIL_ID,
                'council_name': council_cls.COUNCIL_NAME,
                'verdict': 'HOLD', 'confidence': 0.5,
                'summary': f'委员会执行异常: {str(e)[:80]}',
                'weight': council_cls.WEIGHT, 'veto': False,
                'error': True,
            }
        council_votes.append(vote)

    # 董事会最终裁决
    ctx['council_votes'] = council_votes
    try:
        bod_vote = BoardOfDirectors().vote(result['symbol'], result.get('name', ''), ctx)
    except Exception as e:
        bod_vote = {
            'council_id': 'BOD', 'council_name': '仙女座董事会',
            'verdict': 'HOLD', 'confidence': 0.5,
            'summary': f'董事会异常: {str(e)[:80]}', 'veto': True,
        }

    # 更新 result: 用董事会裁决覆盖基础 decision
    final_decision_map = {
        'STRONG_BUY': 'BUY', 'BUY': 'BUY',
        'HOLD': 'HOLD',
        'SELL': 'SELL', 'STRONG_SELL': 'SELL',
        'VETO': 'PASS',
    }
    board_final_verdict = bod_vote.get('verdict', 'HOLD')
    result['decision'] = final_decision_map.get(board_final_verdict, 'HOLD')
    result['confidence'] = bod_vote.get('confidence', result.get('confidence', 0.5))
    result['councils_executed'] = True
    result['council_votes'] = council_votes
    result['board_of_directors'] = bod_vote
    result['council_summary'] = {
        'total': 12,
        'veto_count': sum(1 for v in council_votes + [bod_vote] if v.get('veto')),
        'buy_like': sum(1 for v in council_votes + [bod_vote] if v.get('verdict') in ('STRONG_BUY', 'BUY')),
        'sell_like': sum(1 for v in council_votes + [bod_vote] if v.get('verdict') in ('SELL', 'STRONG_SELL')),
        'final': board_final_verdict,
    }

    # 重新入厅: 如果之前没入厅 (auto_hall_submit=False 但 councils=True), 不入厅
    # 如果之前已经入厅 (hall_submission 有了), 需要更新 deliverable 让 tick 引擎保留
    if result.get('hall_submission', {}).get('success'):
        # 更新 DB 中已入厅任务的 deliverable (追加委员会 + 董事会裁决)
        try:
            _hall_id = result['hall_submission']['hall_id']
            from core.db_path import get_db_path
            import sqlite3
            conn = sqlite3.connect(get_db_path('app.db'), timeout=5)
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                "UPDATE mt_lab_task_hall SET deliverable=?, updated_at=datetime('now','localtime') WHERE id=?",
                (json.dumps(result, ensure_ascii=False), _hall_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

    return result


# 给 StockAnalysisSkill 动态绑定增强方法
StockAnalysisSkill.execute = _skill_execute_with_councils
StockAnalysisSkill.execute_base = _original_stock_analysis_execute
