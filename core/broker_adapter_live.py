"""
📈 实盘证券适配器 — LiveAdapter (华泰/银河 QMT 通用)
══════════════════════════════════════════════════════════
架构:
  华泰/银河/国盛证券 → miniQMT (Windows) → xtquant
                                            ↓
                                    qmt-bridge 服务端 / xqshare
                                            ↓
                                  Mac 端 LiveAdapter 调用

后端自动选择 (优先级):
  ① qmt-bridge QMTClient  (v2.1.3, HTTP, 功能最全)
  ② xqshare XtQuantRemote (HTTP/RPyC)
  ③ xtquant               (Windows 本地)

⚠️⚠️⚠️ 安全条款:
  1. LIVE_TRADING_ENABLED=true + LIVE_TRADING_CONFIRMED=true (双重)
  2. CredentialManager.load() 运行时解密, 绝不硬编码
  3. 交易落库 mt_live_trade_log (独立表)
  4. 下单前过 RiskEngine (和模拟盘同一套风控)
══════════════════════════════════════════════════════════
"""
import os, json, datetime
from .broker_adapter import BrokerAdapter, RiskEngine

# ═══════════════════════════════════════════════════════════
# 🔒 安全门禁
# ═══════════════════════════════════════════════════════════
LIVE_TRADING_ENABLED = os.environ.get('LIVE_TRADING_ENABLED', '').lower() == 'true'
LIVE_TRADING_CONFIRMED = os.environ.get('LIVE_TRADING_CONFIRMED', '').lower() == 'true'
LIVE_TRADING_BROKER = os.environ.get('LIVE_TRADING_BROKER', 'huatai')

XQSHARE_ENDPOINT = os.environ.get('XQSHARE_ENDPOINT', 'http://127.0.0.1:9999')
XQSHARE_TOKEN = os.environ.get('XQSHARE_TOKEN', '')


def _parse_endpoint(endpoint: str):
    """'http://192.168.1.100:9999' → ('192.168.1.100', 9999)"""
    e = endpoint.replace('http://', '').replace('https://', '')
    if ':' in e:
        host, port = e.rsplit(':', 1)
        return host, int(port)
    return e, 9999


class LiveAdapter(BrokerAdapter):
    """实盘适配器 — 自动选最优后端"""

    def __init__(self, broker: str = None, endpoint: str = None, token: str = None):
        if not LIVE_TRADING_ENABLED:
            raise RuntimeError(
                "🛑 实盘未启用!\n"
                "  export LIVE_TRADING_ENABLED=true\n"
                "  export LIVE_TRADING_CONFIRMED=true"
            )
        if not LIVE_TRADING_CONFIRMED:
            raise RuntimeError("🛑 二次确认缺失! export LIVE_TRADING_CONFIRMED=true")

        self._broker = broker or LIVE_TRADING_BROKER
        self._endpoint = endpoint or XQSHARE_ENDPOINT
        self._token = token or XQSHARE_TOKEN
        self._backend = None
        self._session_id = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

        # 审计
        try:
            with open(os.path.expanduser('~/.mtscos_live_session.jsonl'), 'a') as f:
                f.write(json.dumps({
                    'session_id': self._session_id,
                    'start': datetime.datetime.now().isoformat(),
                    'broker': self._broker, 'warning': 'REAL MONEY AT RISK',
                }) + '\n')
        except Exception:
            pass

        # 凭据
        try:
            from core.credential_manager import CredentialManager
            self._creds = CredentialManager().load(self._broker)
            if not self._creds:
                raise RuntimeError(
                    f"[{self._broker}] 未绑定凭据!\n"
                    f"  cd /Users/wuchenghao/MTSCOS_AI_Project/flask-app\n"
                    f"  python -m core.credential_manager set --broker {self._broker}"
                )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"凭据加载失败: {e}")

        # 自动后端
        self._init_backend()

    # ── 后端选择 ──
    def _init_backend(self):
        tried = []
        host, port = _parse_endpoint(self._endpoint)

        # ① qmt-bridge QMTClient (v2.1.3, 功能最全)
        try:
            from qmt_bridge import QMTClient
            client = QMTClient(endpoint=self._endpoint, token=self._token)
            # health_check 验证连通
            status = client.health_check()
            self._backend = ('qmt-bridge', client)
            print(f"✅ LiveAdapter: qmt-bridge v2.1.3 @ {self._endpoint}")
            return
        except ImportError:
            tried.append('qmt-bridge (未装)')
        except Exception as e:
            tried.append(f'qmt-bridge ({str(e)[:50]})')

        # ② xqshare XtQuantRemote
        try:
            from xqshare import XtQuantRemote
            remote = XtQuantRemote(host=host, port=port, token=self._token)
            remote.ping()
            self._backend = ('xqshare', remote)
            print(f"✅ LiveAdapter: xqshare @ {self._endpoint}")
            return
        except ImportError:
            tried.append('xqshare (未装)')
        except Exception as e:
            tried.append(f'xqshare ({str(e)[:50]})')

        # ③ xtquant (Windows 本地)
        try:
            from xtquant import xtdata, xttrader
            self._backend = ('xtquant', (xtdata, xttrader))
            print("✅ LiveAdapter: 本地 xtquant")
            return
        except ImportError:
            tried.append('xtquant (未装)')

        raise RuntimeError(
            f"无可用实盘后端!\n  已尝试: {tried}\n"
            f"  Windows 端先装 miniQMT + xtquant + qmt-bridge 服务端\n"
            f"  Mac 端: pip install qmt-bridge xqshare\n"
            f"  端点: {self._endpoint}"
        )

    # ═══════════════════════════════════════════════════════════
    # 统一接口
    # ═══════════════════════════════════════════════════════════

    def place_order(self, symbol: str, action: str, qty: int, price: float,
                    agent: str = '', reason: str = '', **kwargs) -> dict:
        risk = RiskEngine.check(symbol, action, qty, price)
        if not risk['pass']:
            self._log(symbol, action, qty, price, 'BLOCKED', reason='risk_veto')
            return {'success': False, 'blocked': True, 'risk': risk}

        backend_name, backend = self._backend
        account = self._creds.get('account', '')
        try:
            if backend_name == 'qmt-bridge':
                # qmt-bridge: place_order(symbol, direction, qty, price, order_type)
                direction = 'BUY' if action == 'BUY' else 'SELL'
                result = backend.place_order(
                    symbol=symbol, direction=direction, qty=qty, price=price
                )
                order_id = str(result) if not isinstance(result, dict) else str(result.get('order_id', ''))
            elif backend_name == 'xqshare':
                func = backend.xttrader.buy_stock if action == 'BUY' else backend.xttrader.sell_stock
                order_id = str(func(account, symbol, price, qty))
            elif backend_name == 'xtquant':
                xtdata, xttrader = backend
                t = xttrader.XtQuantTrader(xtdata); t.start()
                side = xttrader.STOCK_BUY if action == 'BUY' else xttrader.STOCK_SELL
                order_id = str(t.order_stock(account, symbol, side, qty, price))
                t.stop()
            else:
                return {'success': False, 'error': f'未知后端: {backend_name}'}

            self._log(symbol, action, qty, price, 'PLACED', order_id=order_id)
            return {'success': True, 'order_id': order_id, 'broker': self._broker}
        except Exception as e:
            self._log(symbol, action, qty, price, 'FAILED', err=str(e))
            return {'success': False, 'error': str(e)}

    def query_cash(self) -> dict:
        backend_name, backend = self._backend
        account = self._creds.get('account', '')
        try:
            if backend_name == 'qmt-bridge':
                info = backend.query_asset(account) or {}
                return {
                    'total_capital': float(info.get('total_asset', info.get('asset', 0))),
                    'available_cash': float(info.get('available', info.get('cash', 0))),
                    'positions_value': float(info.get('market_value', 0)),
                    'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'trade_mode': 'live', 'broker': self._broker,
                }
            elif backend_name == 'xqshare':
                info = backend.xttrader.query_stock_asset(account)
                return {
                    'total_capital': float(getattr(info, 'total_asset', 0)),
                    'available_cash': float(getattr(info, 'cash', 0)),
                    'positions_value': float(getattr(info, 'market_value', 0)),
                    'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'trade_mode': 'live', 'broker': self._broker,
                }
            elif backend_name == 'xtquant':
                xtdata, xttrader = backend
                t = xttrader.XtQuantTrader(xtdata); t.start()
                a = t.query_stock_asset(account); t.stop()
                return {
                    'total_capital': float(a.total_asset),
                    'available_cash': float(a.cash),
                    'positions_value': float(a.market_value),
                    'ts': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'trade_mode': 'live', 'broker': self._broker,
                }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    query_positions = lambda self: self.query_position()  # alias

    def query_position(self, symbol: str = None) -> list:
        backend_name, backend = self._backend
        account = self._creds.get('account', '')
        try:
            if backend_name == 'qmt-bridge':
                positions = backend.query_positions(account) or []
                result = []
                for p in positions:
                    if isinstance(p, dict):
                        code = p.get('stock_code', p.get('code', ''))
                        qty = int(p.get('volume', p.get('qty', 0)))
                        cost = float(p.get('avg_cost', p.get('cost', 0)))
                        price = float(p.get('last_price', p.get('market_value', 0)))
                        if qty > 0 and (not symbol or code == symbol):
                            result.append({'symbol': code, 'qty': qty, 'cost': cost, 'current_price': price})
                return result
            elif backend_name in ('xqshare', 'xtquant'):
                if backend_name == 'xqshare':
                    pos_list = backend.xttrader.query_stock_positions(account)
                else:
                    xtdata, xttrader = backend
                    t = xttrader.XtQuantTrader(xtdata); t.start()
                    pos_list = t.query_stock_positions(account); t.stop()
                result = []
                for p in (pos_list or []):
                    code = getattr(p, 'stock_code', getattr(p, 'code', ''))
                    qty = int(getattr(p, 'volume', 0))
                    if qty > 0 and (not symbol or code == symbol):
                        result.append({
                            'symbol': code, 'qty': qty,
                            'cost': float(getattr(p, 'avg_cost', 0)),
                            'current_price': float(getattr(p, 'market_value', 0)) / qty if qty else 0,
                        })
                return result
        except Exception:
            return []

    def cancel_order(self, order_id: str) -> dict:
        backend_name, backend = self._backend
        account = self._creds.get('account', '')
        try:
            if backend_name == 'qmt-bridge':
                backend.cancel_order(str(order_id))
            elif backend_name == 'xqshare':
                backend.xttrader.cancel_order(account, str(order_id))
            elif backend_name == 'xtquant':
                xtdata, xttrader = backend
                t = xttrader.XtQuantTrader(xtdata); t.start()
                t.cancel_order(account, str(order_id)); t.stop()
            return {'ok': True, 'order_id': str(order_id)}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ── 内部 ──
    def _log(self, symbol, action, qty, price, status, err='', order_id='', reason=''):
        try:
            import sqlite3
            from core.broker_adapter import _get_db
            conn = _get_db()
            conn.execute('''
                INSERT INTO mt_live_trade_log
                (session_id, symbol, action, qty, price, order_id, status, error, broker, reason, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ''', (self._session_id, symbol, action, qty, price, order_id, status, err, self._broker, reason,
                  datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit(); conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 工厂
# ═══════════════════════════════════════════════════════════
def get_adapter(endpoint: str = None, token: str = None):
    if LIVE_TRADING_ENABLED:
        return LiveAdapter(endpoint=endpoint, token=token)
    from core.broker_adapter import SandboxAdapter
    return SandboxAdapter()
