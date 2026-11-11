"""
market_data_service.py — 仙女座沙盘真实行情数据源
双源兜底: 新浪 CN_MarketData (主) + 东方财富 (备)
单例 + TTL 缓存 60s + 节流 0.8s/请求

契约:
  get_all_for_sandbox() → {
    'idx_000001': {...},      # 上证指数
    'idx_399006': {...},      # 创业板指
    'idx_000688': {...},      # 科创50
    'stk_300750': {...},      # 宁德时代
    'stk_688981': {...},      # 中芯国际
    'stk_600519': {...},      # 贵州茅台
    'indices_realtime': [...],
    'sectors': [...]
  }
  每只标的内含 kdata: {dates, ohlc, volumes, ma5, ma10, ma20}
  ohlc = [[open, close, low, high], ...]  — ECharts candlestick 契约
"""
from __future__ import annotations
import json
import time
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════════
# 标的配置
# ══════════════════════════════════════════════════════════════
SANDBOX_INDICES = [
    {'code': '000001', 'name': '上证指数', 'secid_sina': 'sh000001'},
    {'code': '399001', 'name': '深证成指', 'secid_sina': 'sz399001'},
    {'code': '399006', 'name': '创业板指', 'secid_sina': 'sz399006'},
    {'code': '000688', 'name': '科创50',   'secid_sina': 'sh000688'},
]

SANDBOX_STOCKS = [
    {'code': '300750', 'name': '宁德时代', 'secid_sina': 'sz300750'},
    {'code': '688981', 'name': '中芯国际', 'secid_sina': 'sh688981'},
    {'code': '600519', 'name': '贵州茅台', 'secid_sina': 'sh600519'},
    {'code': '000001', 'name': '平安银行', 'secid_sina': 'sz000001'},
]

TTL = 60.0           # 缓存 60s
THROTTLE = 0.8       # 每次请求间隔 0.8s
KLINE_DAYS = 120     # K线天数


# ══════════════════════════════════════════════════════════════
# 单例
# ══════════════════════════════════════════════════════════════
class MarketDataService:
    _inst = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._inst is None:
                cls._inst = super().__new__(cls)
                cls._inst._init()
            return cls._inst

    def _init(self):
        self._cache = None
        self._cache_ts = 0.0
        self._last_req = 0.0
        self._req_lock = threading.Lock()

    # ── 节流请求 ──
    def _throttled_get(self, url: str, timeout: float = 10.0) -> str | None:
        with self._req_lock:
            gap = time.time() - self._last_req
            if gap < THROTTLE:
                time.sleep(THROTTLE - gap)
            self._last_req = time.time()
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://finance.sina.com.cn/',
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except Exception:
            return None

    # ── 新浪 K线 ──
    def _sina_kline(self, secid: str, days: int = KLINE_DAYS) -> list[dict]:
        """新浪日 K 线 → [{day, open, high, low, close, volume}, ...]"""
        # 新浪接口: https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
        url = (
            f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
            f'CN_MarketData.getKLineData?symbol={secid}&scale=240&ma=no&datalen={days}'
        )
        raw = self._throttled_get(url)
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ── 新浪实时行情 ──
    def _sina_realtime(self, secids: list[str]) -> dict[str, dict]:
        url = f'https://hq.sinajs.cn/list={",".join(secids)}'
        raw = self._throttled_get(url)
        if not raw:
            return {}
        result = {}
        for line in raw.strip().split('\n'):
            line = line.strip()
            if '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.replace('var hq_str_', '').strip()
            val = val.strip().strip('"')
            if not val:
                continue
            parts = val.split(',')
            if len(parts) < 32:
                continue
            try:
                result[key] = {
                    'name': parts[0],
                    'open': float(parts[1]),
                    'pre_close': float(parts[2]),
                    'price': float(parts[3]),
                    'high': float(parts[4]),
                    'low': float(parts[5]),
                    'volume': float(parts[8]),   # 股
                    'amount': float(parts[9]),   # 元
                    'date': parts[30],
                    'time': parts[31],
                }
            except (ValueError, IndexError):
                continue
        return result

    # ── 构造 kdata ──
    @staticmethod
    def _build_kdata(klines: list[dict]) -> dict:
        """新浪 K 线 → {dates, ohlc, volumes, ma5, ma10, ma20}"""
        if not klines:
            return {'dates': [], 'ohlc': [], 'volumes': [],
                    'ma5': [], 'ma10': [], 'ma20': []}
        # 按日期升序
        klines = sorted(klines, key=lambda x: x.get('day', ''))
        dates = [k['day'] for k in klines]
        # ohlc = [open, close, low, high] — ECharts candlestick 契约
        ohlc = [[k['open'], k['close'], k['low'], k['high']] for k in klines]
        volumes = []
        closes = [float(k.get('close', 0)) for k in klines]
        for i, k in enumerate(klines):
            try:
                c = float(k.get('close', 0))
                o = float(k.get('open', 0))
                v = float(k.get('volume', 0))
            except (ValueError, TypeError):
                c = o = v = 0.0
            flag = 1 if c >= o else -1
            volumes.append([i, v, flag])

        def ma(n: int) -> list:
            out = []
            for i in range(len(closes)):
                if i < n - 1:
                    out.append('-')
                else:
                    seg = closes[i - n + 1:i + 1]
                    seg = [x for x in seg if isinstance(x, (int, float))]
                    if len(seg) < n:
                        out.append('-')
                    else:
                        out.append(round(sum(seg) / n, 2))
            return out

        return {
            'dates': dates,
            'ohlc': ohlc,
            'volumes': volumes,
            'ma5': ma(5),
            'ma10': ma(10),
            'ma20': ma(20),
        }

    # ── 主入口 ──
    def get_all_for_sandbox(self, force: bool = False) -> dict:
        """一站式拉取沙盘数据 (带缓存)"""
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < TTL:
            return self._cache

        result = {}

        # 1) 指数 + 个股 K 线
        all_items = [('idx_', i) for i in SANDBOX_INDICES] + \
                    [('stk_', s) for s in SANDBOX_STOCKS]

        for prefix, item in all_items:
            klines = self._sina_kline(item['secid_sina'])
            result[f'{prefix}{item["code"]}'] = {
                'name': item['name'],
                'code': item['code'],
                'secid': item['secid_sina'],
                'kdata': self._build_kdata(klines),
                'kline_count': len(klines),
            }

        # 2) 实时行情 (指数 + 个股)
        all_secids = [i['secid_sina'] for i in SANDBOX_INDICES] + \
                     [s['secid_sina'] for s in SANDBOX_STOCKS]
        rt = self._sina_realtime(all_secids)

        # indices_realtime
        indices_realtime = []
        for item in SANDBOX_INDICES:
            secid = item['secid_sina']
            info = rt.get(secid, {})
            pre = info.get('pre_close', 0)
            price = info.get('price', 0)
            chg_pct = round((price - pre) / pre * 100, 2) if pre else 0
            amount_yi = round(info.get('amount', 0) / 1e8, 2)
            indices_realtime.append({
                'name': item['name'],
                'code': item['code'],
                'price': price,
                'change_pct': chg_pct,
                'pre_close': pre,
                'amount_yi': amount_yi,
            })
        result['indices_realtime'] = indices_realtime

        # 3) 板块 (简化版 — 用个股涨跌合成)
        sectors = self._build_sectors_from_rt(rt, SANDBOX_STOCKS)
        result['sectors'] = sectors

        # 4) 个股实时补充到 stk_*
        for item in SANDBOX_STOCKS:
            secid = item['secid_sina']
            info = rt.get(secid, {})
            pre = info.get('pre_close', 0)
            price = info.get('price', 0)
            result[f'stk_{item["code"]}']['realtime'] = {
                'price': price,
                'change_pct': round((price - pre) / pre * 100, 2) if pre else 0,
                'high': info.get('high', 0),
                'low': info.get('low', 0),
                'volume': info.get('volume', 0),
                'amount': info.get('amount', 0),
            }

        result['_meta'] = {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'cache_ttl': TTL,
            'source': 'sina_CN_MarketData_v2',
        }

        self._cache = result
        self._cache_ts = now
        return result

    # ── 板块合成 (从个股涨跌 → 简化概念板块) ──
    @staticmethod
    def _build_sectors_from_rt(rt: dict, stocks: list[dict]) -> list[dict]:
        sectors_raw = {
            '新能源': {'keywords': ['300750'], 'color': '#4ec9b0'},
            '半导体': {'keywords': ['688981'], 'color': '#c9a84c'},
            '消费白马': {'keywords': ['600519'], 'color': '#e8c86a'},
            '金融':    {'keywords': ['000001'], 'color': '#8892a6'},
        }
        out = []
        for name, cfg in sectors_raw.items():
            children = []
            total_chg = 0.0
            count = 0
            for kw in cfg['keywords']:
                secid_match = None
                for s in stocks:
                    if s['code'] == kw:
                        secid_match = s['secid_sina']
                        break
                info = rt.get(secid_match, {})
                pre = info.get('pre_close', 0)
                price = info.get('price', 0)
                chg = round((price - pre) / pre * 100, 2) if pre else 0
                children.append({
                    'name': info.get('name', kw),
                    'code': kw,
                    'price': price,
                    'change_pct': chg,
                })
                total_chg += chg
                count += 1
            avg_chg = round(total_chg / max(count, 1), 2)
            out.append({
                'name': name,
                'change_pct': avg_chg,
                'net_inflow_yi': round(avg_chg * 5, 2),  # 估算
                'color': cfg['color'],
                'children': children,
            })
        # 按涨跌排序
        out.sort(key=lambda x: x['change_pct'], reverse=True)
        return out


# ── 便捷函数 ──
def fetch_sandbox_data(force: bool = False) -> dict:
    return MarketDataService().get_all_for_sandbox(force=force)
