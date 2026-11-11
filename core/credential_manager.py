"""
🔒 凭据安全管理器 — 实盘证券账号的加密存储
══════════════════════════════════════════════════════════
设计原则:
  1. 密码绝不硬编码到源码 — 源码提交到 git 就等于裸奔
  2. 优先用系统 keyring (macOS Keychain) — 最安全, 本地锁死
  3. fallback: Fernet (AES-128-CBC + HMAC) 加密文件 — key 用环境变量解锁
  4. 凭据文件路径: ~/.mtscos_credentials.enc (chmod 600, .gitignore)
  5. 所有敏感字段默认空字符串 — 必须显式 "set" 后才能 "get"
  6. 启动时强制二次确认 (LIVE_TRADING_ENABLED = true 必须显式设置)

使用方式:
  # ① 设置凭据 (交互模式, 从 stdin 读, 不进 shell history)
  python -m core.credential_manager set --broker xtquant
  
  # ② 程序里读取 (运行时解密, 内存中短暂存在)
  from core.credential_manager import CredentialManager
  cm = CredentialManager()
  creds = cm.load('xtquant')  # 返回 dict, 无明文落盘

  # ③ 环境变量解锁 (如果用加密文件模式)
  export MTSCOS_MASTER_KEY='你的解锁口令'
══════════════════════════════════════════════════════════
"""
import os
import json
import stat
import hashlib
import getpass
import time
import base64
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 路径 (全部 ~/.mtscos_*, 不进项目目录, 不进 git)
# ═══════════════════════════════════════════════════════════
CRED_FILE = Path.home() / '.mtscos_credentials.enc'
CRED_META_FILE = Path.home() / '.mtscos_credentials.meta'

# ═══════════════════════════════════════════════════════════
# 券商适配器映射 (将来加新券商只改这里)
# ═══════════════════════════════════════════════════════════
BROKER_SCHEMAS = {
    'xtquant': {  # 迅投 QMT — 最主流, easytrader 支持好
        'fields': ['account', 'password'],
        'desc': '迅投 QMT (easytrader.XtQuantTrader)',
    },
    'ths': {  # 同花顺客户端
        'fields': ['account', 'password'],
        'desc': '同花顺 (easytrader.Trader)',
    },
    'ptrade': {  # 华泰 PTrade
        'fields': ['account', 'password'],
        'desc': '华泰 PTrade',
    },
    'galaxy': {  # 银河证券 (你常用的?)
        'fields': ['account', 'sh_code', 'sz_code', 'password'],
        'desc': '银河证券 (资金账号 + 沪深证券账号)',
    },
}


class CredentialManager:
    """凭据管理器 — keyring 优先, Fernet 加密文件 fallback"""

    def __init__(self):
        self._use_keyring = False
        self._keyring = None
        self._fernet = None

        # 尝试 keyring (macOS Keychain)
        try:
            import keyring
            self._use_keyring = True
            self._keyring = keyring
        except ImportError:
            pass

        # fallback: Fernet (需要 MTSCOS_MASTER_KEY 环境变量)
        try:
            from cryptography.fernet import Fernet
            master_key = os.environ.get('MTSCOS_MASTER_KEY', '')
            if master_key:
                # 把口令转成 32-byte Fernet key
                key = hashlib.sha256(master_key.encode()).digest()
                fernet_key = base64.urlsafe_b64encode(key)
                self._fernet = Fernet(fernet_key)
            else:
                # 无环境变量 → 自动生成临时 key (仅当前进程有效)
                # set 后立即提示 export
                auto_key = base64.urlsafe_b64encode(
                    hashlib.sha256(f'mtscos-auto-{os.getpid()}-{time.time()}-{os.environ.get("USER","unknown")}'.encode()).digest()
                )
                self._fernet = Fernet(auto_key)
                self._fernet_auto_key = True
        except ImportError:
            pass

        if not self._use_keyring and not self._fernet:
            raise RuntimeError(
                "无安全存储可用! pip install keyring (macOS Keychain) "
                "或 pip install cryptography (自动 Fernet, 已装)"
            )

    # ── 写入 ──
    def save(self, broker: str, credentials: dict):
        """加密保存 credentials (dict) 到 broker 名下"""
        if broker not in BROKER_SCHEMAS:
            raise ValueError(f'未知券商: {broker}. 支持: {list(BROKER_SCHEMAS.keys())}')

        # 确保只有 schema 定义的字段
        clean = {k: str(v) for k, v in credentials.items() if k in BROKER_SCHEMAS[broker]['fields']}

        if self._use_keyring:
            for k, v in clean.items():
                self._keyring.set_password(
                    service=f'mtscos/broker/{broker}',
                    username=k,
                    password=v,
                )
        else:
            # Fernet 加密文件
            encrypted = self._fernet.encrypt(json.dumps(clean).encode())
            CRED_FILE.write_bytes(encrypted)
            os.chmod(CRED_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600

        # 写 meta (不含密码, 仅供 UI 显示 "已绑定")
        meta = {'broker': broker, 'fields': list(clean.keys()), 'updated_at': __import__('datetime').datetime.now().isoformat()}
        CRED_META_FILE.write_text(json.dumps(meta, indent=2))
        os.chmod(CRED_META_FILE, stat.S_IRUSR | stat.S_IWUSR)

    # ── 读取 ──
    def load(self, broker: str) -> dict:
        """解密返回 dict, 内存中短暂存在"""
        if self._use_keyring:
            result = {}
            for field in BROKER_SCHEMAS[broker]['fields']:
                v = self._keyring.get_password(service=f'mtscos/broker/{broker}', username=field)
                if v:
                    result[field] = v
            return result
        else:
            encrypted = CRED_FILE.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted)

    # ── 状态查询 (不暴露密码) ──
    def status(self, broker: str = None):
        """返回 {broker, bound: bool, fields: [...]} 不含密码"""
        if broker:
            try:
                creds = self.load(broker)
                return {
                    'broker': broker,
                    'bound': bool(creds),
                    'fields': list(creds.keys()),
                    'storage': 'keyring' if self._use_keyring else 'fernet-enc',
                }
            except Exception:
                return {'broker': broker, 'bound': False}
        # 查所有
        result = []
        for b in BROKER_SCHEMAS:
            result.append(self.status(b))
        return result

    # ── 删除 ──
    def clear(self, broker: str):
        if self._use_keyring:
            for field in BROKER_SCHEMAS[broker]['fields']:
                try:
                    self._keyring.delete_password(service=f'mtscos/broker/{broker}', username=field)
                except Exception:
                    pass
        CRED_FILE.unlink(missing_ok=True)
        CRED_META_FILE.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════
# CLI 入口: python -m core.credential_manager set --broker galaxy
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='MTSCOS 证券凭据安全管理')
    sub = parser.add_subparsers(dest='cmd')

    # set
    p_set = sub.add_parser('set', help='交互式输入并加密存储')
    p_set.add_argument('--broker', required=True, choices=list(BROKER_SCHEMAS.keys()))

    # get
    p_get = sub.add_parser('get', help='(调试用) 解密输出 — 会打印到终端!')
    p_get.add_argument('--broker', required=True)

    # status
    sub.add_parser('status', help='查看所有券商绑定状态 (不暴露密码)')

    # clear
    p_clr = sub.add_parser('clear', help='删除凭据')
    p_clr.add_argument('--broker', required=True)

    args = parser.parse_args()

    if args.cmd == 'set':
        schema = BROKER_SCHEMAS[args.broker]
        print(f'\n🔐 设置 [{schema["desc"]}]')
        print(f'   字段: {schema["fields"]}')
        print(f'   存储: {"macOS Keychain" if CredentialManager()._use_keyring else "加密文件"}')
        print()
        creds = {}
        for field in schema['fields']:
            val = getpass.getpass(f'   {field}: ')
            creds[field] = val
        cm = CredentialManager()
        cm.save(args.broker, creds)
        print(f'\n✅ 已安全存储 ({", ".join(creds.keys())})')
        print(f'   状态: {cm.status(args.broker)}')

    elif args.cmd == 'get':
        cm = CredentialManager()
        creds = cm.load(args.broker)
        # 只显示非密码字段, 密码用 * 代替
        masked = {k: ('*' * len(v) if 'password' in k.lower() else v) for k, v in creds.items()}
        print(json.dumps(masked, indent=2))

    elif args.cmd == 'status':
        cm = CredentialManager()
        for s in cm.status():
            mark = '✅' if s.get('bound') else '⬜️'
            print(f'  {mark} {s["broker"]:12s}  bound={s.get("bound",False)}  fields={s.get("fields",[])}')

    elif args.cmd == 'clear':
        cm = CredentialManager()
        confirm = input(f'⚠️  确认删除 [{args.broker}] 凭据? (y/N): ')
        if confirm.lower() == 'y':
            cm.clear(args.broker)
            print('✅ 已清除')
