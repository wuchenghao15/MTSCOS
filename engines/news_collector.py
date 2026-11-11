"""
📰 仙女座休市新闻/情绪采集器 — NewsCollector
══════════════════════════════════════════════════════════
休市期间收集外部消息面作为 replay 学习因子:

  数据源 (全部走 akshare, 已实测通):
  ┌─ stock_news_em              东方财富个股新闻 (每只股票 10 条)
  ├─ stock_sector_fund_flow_rank 板块资金流排行 (今日热点板块)
  ├─ stock_hsgt_fund_flow_summary_em 北向资金 (外资动向)
  ├─ news_cctv                  CCTV 财经要闻 (政策面)
  └─ macro_china_market_margin_sh 上交所融资融券 (杠杆情绪)

  作用:
  - 为 replay 提供"为什么这几天涨/跌"的消息面解释
  - 发现"隐性因子" (如某板块集体异动 + 新闻催化)
  - 结果 → AI 脑库投喂 (和 replay 一起学)
══════════════════════════════════════════════════════════
"""
from __future__ import annotations
import time, json, datetime
from typing import Optional


class NewsCollector:
    """休市新闻/情绪/板块采集器"""

    def __init__(self, symbols: list = None):
        self.symbols = symbols or ['000001', '601012', '601398', '600519',
                                   '000858', '300750', '600036', '002594']
        self._cache = {}

    # ═══════════════════════════════════════════════════════════
    # ① 个股新闻 (东方财富)
    # ═══════════════════════════════════════════════════════════
    def fetch_stock_news(self, limit_per_symbol: int = 5) -> dict:
        """每只股票的最新新闻 → {symbol: [{'title','content','time'}]}"""
        result = {}
        try:
            import akshare as ak
        except ImportError:
            return result

        for s in self.symbols:
            try:
                df = ak.stock_news_em(symbol=s)
                if df is None or len(df) == 0:
                    continue
                rows = []
                for _, r in df.head(limit_per_symbol).iterrows():
                    title = (r.get('新闻标题') or r.get('title') or '').strip()
                    content = (r.get('新闻内容') or r.get('content') or '').strip()[:200]
                    pub_time = str(r.get('发布时间') or r.get('time') or '')[:16]
                    if title:
                        rows.append({'title': title, 'content': content, 'time': pub_time})
                result[s] = rows
                time.sleep(0.4)
            except Exception as e:
                result[s] = []
        return result

    # ═══════════════════════════════════════════════════════════
    # ② 板块资金流 (今日热点)
    # ═══════════════════════════════════════════════════════════
    def fetch_sector_flow(self, top_n: int = 10) -> dict:
        """今日板块资金流排行 → {'hot_in': [...], 'hot_out': [...]}"""
        result = {'hot_in': [], 'hot_out': [], 'top_in': [], 'top_out': []}
        try:
            import akshare as ak
            df = ak.stock_sector_fund_flow_rank(indicator="今日")
            if df is None or len(df) == 0:
                return result

            # 尝试找主力净流入列
            net_col = None
            for c in df.columns:
                if '主力净流入' in c and '净' in c and '额' in c:
                    net_col = c; break
            if net_col is None:
                for c in df.columns:
                    if '净流入' in c:
                        net_col = c; break

            name_col = next((c for c in df.columns if '名称' in c or '板块' in c), None)
            if name_col is None:
                return result

            # 清洗 + 排序
            df[net_col] = df[net_col].astype(float)
            df_sorted = df.sort_values(net_col, ascending=False)

            result['hot_in'] = [
                {'name': str(r[name_col]), 'net': float(r[net_col])}
                for _, r in df_sorted.head(top_n).iterrows()
            ]
            result['hot_out'] = [
                {'name': str(r[name_col]), 'net': float(r[net_col])}
                for _, r in df_sorted.tail(top_n).iloc[::-1].iterrows()
            ]
        except Exception as e:
            result['error'] = str(e)[:100]
        return result

    # ═══════════════════════════════════════════════════════════
    # ③ 北向资金 (外资风向)
    # ═══════════════════════════════════════════════════════════
    def fetch_north_flow(self) -> dict:
        """北向资金 (沪深港通) 最新动向"""
        result = {}
        try:
            import akshare as ak
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is None or len(df) == 0:
                return result

            # 取上一个交易日 (最新一条是今天未收盘的)
            row = df.iloc[-1] if len(df) > 0 else None
            if row is not None:
                for col in df.columns:
                    val = row[col]
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        val = str(val)[:40]
                    result[str(col)] = val
        except Exception as e:
            result['error'] = str(e)[:100]
        return result

    # ═══════════════════════════════════════════════════════════
    # ④ 政策要闻 (CCTV)
    # ═══════════════════════════════════════════════════════════
    def fetch_cctv_news(self, date: str = None, limit: int = 10) -> list:
        """CCTV 财经/政策要闻 — 政策面学习因子"""
        result = []
        try:
            import akshare as ak
            date = date or datetime.datetime.now().strftime('%Y%m%d')
            df = ak.news_cctv(date=date)
            if df is None or len(df) == 0:
                # 可能当天没新闻, 试试往前一天
                prev = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y%m%d')
                df = ak.news_cctv(date=prev)
            if df is None or len(df) == 0:
                return result

            for _, r in df.head(limit).iterrows():
                title = (r.get('title') or '').strip()
                content = (r.get('content') or '').strip()[:200]
                if title and len(title) > 5:
                    result.append({'title': title, 'content': content})
        except Exception as e:
            result = [{'error': str(e)[:100]}]
        return result

    # ═══════════════════════════════════════════════════════════
    # ⑤ 融资融券 (杠杆情绪温度计)
    # ═══════════════════════════════════════════════════════════
    def fetch_margin_sentiment(self) -> dict:
        """上交所融资融券余额 — 杠杆多空比"""
        result = {}
        try:
            import akshare as ak
            df = ak.macro_china_market_margin_sh()
            if df is None or len(df) < 2:
                return result

            # 取最新两天
            latest = df.iloc[-1]
            prev = df.iloc[-2]

            rz_balance_now = float(latest.get('融资余额', 0))
            rq_balance_now = float(latest.get('融券余额', 0))
            rz_balance_prev = float(prev.get('融资余额', 0))

            # 融资余额环比变化
            rz_change_pct = ((rz_balance_now - rz_balance_prev) / rz_balance_prev * 100
                            if rz_balance_prev else 0)

            # 杠杆情绪指标: 融资/融券比
            leverage_ratio = (rz_balance_now / rq_balance_now if rq_balance_now > 0 else 0)

            # 情绪判定
            if rz_change_pct > 2:
                sentiment = '🔥 高杠杆看多 (融资余额激增)'
            elif rz_change_pct < -2:
                sentiment = '❄️ 杠杆撤退 (融资余额下降)'
            elif leverage_ratio > 50:
                sentiment = '📈 杠杆偏多 (融资/融券>50)'
            elif leverage_ratio < 30:
                sentiment = '📉 杠杆偏空'
            else:
                sentiment = '⚖️ 杠杆中性'

            result = {
                'date': str(latest.get('日期', ''))[:10],
                'rz_balance': rz_balance_now,
                'rq_balance': rq_balance_now,
                'rz_change_pct': round(rz_change_pct, 2),
                'leverage_ratio': round(leverage_ratio, 1),
                'sentiment': sentiment,
            }
        except Exception as e:
            result['error'] = str(e)[:100]
        return result

    # ═══════════════════════════════════════════════════════════
    # ⑥ 公司画像 (巨潮官网级档案)
    # ═══════════════════════════════════════════════════════════
    def fetch_company_profiles(self, limit: int = 8) -> dict:
        """每只自选股的巨潮公司档案 — 官方级资料"""
        result = {}
        try:
            import akshare as ak
        except ImportError:
            return result

        for s in self.symbols[:limit]:
            try:
                df = ak.stock_profile_cninfo(symbol=s)
                if df is None or len(df) == 0:
                    continue
                r = df.iloc[0]
                result[s] = {
                    'name': str(r.get('公司名称', '')),
                    'industry': str(r.get('所属行业', '')),
                    'website': str(r.get('官方网站', '')),
                    'list_date': str(r.get('上市日期', ''))[:10],
                    'establish_date': str(r.get('成立日期', ''))[:10],
                    'legal_rep': str(r.get('法人代表', '')),
                    'business_scope': str(r.get('经营范围', ''))[:200],
                    'main_business': str(r.get('主营业务', ''))[:200],
                    'indices': str(r.get('入选指数', '')),
                    'intro': str(r.get('机构简介', ''))[:300],
                }
                time.sleep(0.3)
            except Exception as e:
                result[s] = {'error': str(e)[:80]}
        return result

    # ═══════════════════════════════════════════════════════════
    # ⑦ 同业竞品对标 (同行业成分股 + 涨跌幅对比)
    # ═══════════════════════════════════════════════════════════
    def fetch_peers_comparison(self, company_profiles: dict, top_n: int = 5) -> dict:
        """根据行业拉同行业所有股票 — 和自选股做涨跌对比"""
        result = {}
        try:
            import akshare as ak
        except ImportError:
            return result

        seen_industries = {}  # 行业名 → 已拉过的行业板块名 (行业名可能有 银行 / 银行Ⅱ, 映射用)

        for symbol, profile in company_profiles.items():
            if 'error' in profile:
                continue
            industry = profile.get('industry', '')
            if not industry:
                continue

            # 尝试不同行业名变体
            variants = [
                industry,
                industry.replace('Ⅱ', '').replace('Ⅰ', ''),  # 去掉罗马数字
                industry[:6],  # 前 6 字
                industry[:4],  # 前 4 字
                industry[:2],  # 前 2 字 (兜底)
            ]
            # 常见行业名 → 东方财富行业板块名 映射
            industry_map = {
                '货币金融服务': '银行', '银行': '银行',
                '电气机械和器材制造业': '电机', '电机': '电机',
                '酒、饮料和精制茶制造业': '白酒Ⅲ',
                '软件和信息技术服务业': '软件开发',
                '互联网和相关服务': '互联网电商',
                '计算机、通信和其他电子设备制造业': '半导体',
                '汽车制造业': '汽车',
                '化学原料和化学制品制造业': '化学原料',
                '医药制造业': '医药生物',
                '电力、热力生产和供应业': '电力',
                '批发和零售业': '商贸零售',
                '房地产业': '房产租赁经纪',
                '建筑业': '建筑装饰',
                '食品制造业': '食品加工',
                '铁路、船舶、航空航天和其它运输设备制造业': '国防军工',
                '资本市场服务': '证券Ⅱ',
                '保险业': '保险',
            }
            mapped = industry_map.get(industry)
            if mapped and mapped not in variants:
                variants.insert(1, mapped)  # 映射插到第二位 (优先试)
            peers_df = None
            tried = []
            for v in variants:
                try:
                    if v in seen_industries:
                        peers_df = seen_industries[v]; break
                    df = ak.stock_board_industry_cons_em(symbol=v)
                    if df is not None and len(df) > 0:
                        peers_df = df
                        seen_industries[v] = df
                        break
                except Exception:
                    tried.append(v)
                    time.sleep(0.2)

            if peers_df is None:
                result[symbol] = {'error': f'行业 {industry} 未找到'}
                continue

            # 找出这只在同行业里的排名
            target_code = symbol
            cols_map = {c: c for c in peers_df.columns}
            code_col = next((c for c in peers_df.columns if '代码' in c), None)
            name_col = next((c for c in peers_df.columns if '名称' in c), None)
            pct_col = next((c for c in peers_df.columns if '涨跌幅' in c), None)
            price_col = next((c for c in peers_df.columns if '最新价' in c or '收盘价' in c), None)
            mkt_col = next((c for c in peers_df.columns if '市值' in c), None)

            if code_col is None:
                result[symbol] = {'industry': industry, 'peers_count': len(peers_df)}
                continue

            total = len(peers_df)
            # 计算排名
            peers_sorted = peers_df.copy()
            if pct_col:
                peers_sorted = peers_sorted.sort_values(pct_col, ascending=False)
            rank = None
            for i, (_, r) in enumerate(peers_sorted.iterrows()):
                code = str(r.get(code_col, ''))
                if code.endswith(target_code) or code == target_code:
                    rank = i + 1
                    break

            # 拉 TOP 竞品 (不含自己)
            top_peers = []
            for _, r in peers_df.head(top_n + 2).iterrows():
                code = str(r.get(code_col, ''))
                if code.endswith(target_code):
                    continue
                peer = {'code': code}
                if name_col: peer['name'] = str(r.get(name_col, ''))
                if pct_col: peer['pct'] = float(r.get(pct_col, 0))
                if price_col: peer['price'] = float(r.get(price_col, 0))
                if mkt_col:
                    try: peer['market_cap'] = float(r.get(mkt_col, 0))
                    except: pass
                top_peers.append(peer)
                if len(top_peers) >= top_n:
                    break

            result[symbol] = {
                'industry': industry,
                'peers_count': total,
                'rank_by_pct': rank,
                'top_peers': top_peers,
            }
            time.sleep(0.3)

        return result

    # ═══════════════════════════════════════════════════════════
    # 一键采集全部 (扩展 7 类)
    # ═══════════════════════════════════════════════════════════
    def collect_all(self, log_func=print) -> dict:
        """一键采集 7 类数据"""
        t0 = time.time()
        log_func("📰 [NEWS] 开始采集 7 类外部因子...")
        data = {}

        # ① 个股新闻
        log_func("  ① 个股新闻...")
        data['stock_news'] = self.fetch_stock_news()

        # ② 板块资金流
        log_func("  ② 板块资金流...")
        data['sector_flow'] = self.fetch_sector_flow()

        # ③ 北向资金
        log_func("  ③ 北向资金...")
        data['north_flow'] = self.fetch_north_flow()

        # ④ CCTV 政策要闻
        log_func("  ④ CCTV 政策要闻...")
        data['cctv_news'] = self.fetch_cctv_news()

        # ⑤ 融资融券
        log_func("  ⑤ 融资融券...")
        data['margin'] = self.fetch_margin_sentiment()

        # 🆕 ⑥ 公司画像 (巨潮档案)
        log_func("  ⑥ 公司画像 (巨潮官网档案)...")
        data['profiles'] = self.fetch_company_profiles()
        prof_count = len([v for v in data['profiles'].values() if 'error' not in v])
        log_func(f"     ✅ {prof_count}/{len(self.symbols)} 只有效")

        # 🆕 ⑦ 同业竞品对标
        log_func("  ⑦ 同业竞品对标...")
        data['peers'] = self.fetch_peers_comparison(data['profiles'])
        peer_ok = len([v for v in data['peers'].values() if 'error' not in v])
        log_func(f"     ✅ {peer_ok}/{len(self.symbols)} 对标完成")

        dt = time.time() - t0
        log_func(f"  ✅ 采集完成 — {dt:.1f}s")
        return data

    # ═══════════════════════════════════════════════════════════
    # 生成学习因子摘要 (给 AI 脑库投喂用)
    # ═══════════════════════════════════════════════════════════
    def generate_learning_factors(self, news_data: dict, replay_result: dict = None) -> str:
        """把采集到的新闻/情绪浓缩成学习因子摘要"""
        parts = []
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

        # 板块热点
        hot = news_data.get('sector_flow', {}).get('hot_in', [])[:3]
        cold = news_data.get('sector_flow', {}).get('hot_out', [])[:2]
        if hot or cold:
            parts.append(f"🔥今日净流入板块: {[s['name'] for s in hot]}")
            if cold:
                parts.append(f"❄️净流出板块: {[s['name'] for s in cold]}")

        # 北向资金
        north = news_data.get('north_flow', {})
        if north:
            direction = north.get('资金方向', '')
            net = north.get('资金净流入', 0)
            parts.append(f"🌐北向资金 {direction} ¥{net}亿 (沪深港通)")

        # 杠杆情绪
        margin = news_data.get('margin', {})
        if margin and 'sentiment' in margin:
            parts.append(f"📊融资融券 {margin['sentiment']} (融资/融券={margin.get('leverage_ratio','?')})")

        # CCTV 政策
        cctv = news_data.get('cctv_news', [])[:3]
        if cctv:
            parts.append(f"📺政策面: {'; '.join(n['title'][:40] for n in cctv)}")

        # 个股重要新闻 (挑和我们监控池相关的)
        stock_news = news_data.get('stock_news', {})
        important = []
        for sym, news_list in stock_news.items():
            for n in news_list[:2]:
                title = n.get('title', '')
                if any(k in title for k in ['外资', '机构', '增持', '减持', '业绩', '利好', '利空',
                                             '涨停', '跌停', '回购', '分红', '北向']):
                    important.append(f"{sym}:{title[:50]}")
                    break
        if important:
            parts.append(f"📌监控池重要消息: {'; '.join(important[:4])}")

        # 🆕 公司画像 + 竞品对标
        profiles = news_data.get('profiles', {})
        peers = news_data.get('peers', {})
        if profiles:
            # 每只的一行画像
            profile_lines = []
            for sym, p in list(profiles.items())[:4]:
                if 'error' in p:
                    continue
                industry = p.get('industry', '?')
                name = p.get('name', '')[:6]
                website = p.get('website', '')
                line = f"{sym} {name}[{industry}]"
                peer_info = peers.get(sym, {})
                if 'error' not in peer_info:
                    rank = peer_info.get('rank_by_pct', '?')
                    total = peer_info.get('peers_count', '?')
                    top = peer_info.get('top_peers', [])
                    top_names = '/'.join(pp.get('name', '')[:4] for pp in top[:3])
                    line += f" | 行业涨跌排名 {rank}/{total} | TOP竞品: {top_names}"
                if website:
                    line += f" | 官网 {website}"
                profile_lines.append(line)
            if profile_lines:
                parts.append(f"🏢公司画像: {' || '.join(profile_lines)}")

        # Replay 关联分析
        if replay_result:
            r = replay_result
            loss_syms = [t['symbol'] for t in r.get('losing_trades', [])[:3]]
            win_syms = [t['symbol'] for t in r.get('winning_trades', [])[:3]]
            if loss_syms or win_syms:
                parts.append(f"🔄Replay复盘: 胜率{r.get('win_rate','?')}% | "
                            f"赢:{'/'.join(win_syms[:3])} | 亏:{'/'.join(loss_syms[:3])}")

        if not parts:
            return f"[NEWS-FACTOR {ts}] 今日消息面平静, 无显著外部学习因子"

        return f"[NEWS-FACTOR {ts}] " + " | ".join(parts)


# CLI 测试
if __name__ == '__main__':
    nc = NewsCollector()
    data = nc.collect_all(log_func=print)
    print("\n" + "=" * 50)
    print("📰 学习因子摘要:")
    print("=" * 50)
    summary = nc.generate_learning_factors(data)
    print(summary)
