#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信回调协议加解密工具 WeCom Crypto (flow_wecom_callback_20261026)
======================================================================
企微回调协议标准实现: SHA1 验签 + AES-256-CBC 加解密

参考: 企业微信官方回调协议文档 + Open WeCom Skills

协议:
  ┌─ GET 验证 ──────────────────────────────────────────────────────┐
  │  URL: /wecom/callback?msg_signature=S&timestamp=T&nonce=N&echostr=E
  │  Step 1: 验签  SHA1(token + T + N + E) == msg_signature
  │  Step 2: 解密  AES-256-CBC(E) → 明文 echostr
  │  Step 3: 返回  明文 echostr
  └─────────────────────────────────────────────────────────────────┘
  
  ┌─ POST 消息回调 ─────────────────────────────────────────────────┐
  │  Body: <xml><Encrypt>ENCRYPTED</Encrypt></xml>
  │  Step 1: 验签  SHA1(token + timestamp + nonce + ENCRYPTED) == msg_signature
  │  Step 2: 解密  AES-256-CBC(ENCRYPTED) → 明文 XML (FromUserName/Content/MsgType...)
  │  Step 3: 处理业务 (本地零token推理)
  │  Step 4: 加密回复  构造回复 XML → AES 加密 → 组装回调 XML
  │  Step 5: 返回  <xml><Encrypt>...</Encrypt><MsgSignature>...</MsgSignature><TimeStamp>...</TimeStamp><Nonce>...</Nonce></xml>
  │           (必须 5s 内返回, 否则企微重试3次后丢弃)
  └─────────────────────────────────────────────────────────────────┘

依赖: pip install pycryptodome
"""
from __future__ import annotations

import os, base64, hashlib, time, random, socket
import struct
import xml.etree.ElementTree as ET
from Crypto.Cipher import AES


class WeComCrypto:
    """企业微信回调加解密 (协议标准实现, 参考官方 SDK)"""
    
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str = None):
        """
        Args:
            token:           企微回调 URL 校验 Token (自定义)
            encoding_aes_key: 企微消息加密 Key (43位, 官方生成, 补2个=后 base64 解码为 32字节)
            corp_id:         企业 ID
        """
        self.token = token
        # 企微 EncodingAESKey 是 43 字符纯 base64 → 补 "==" 凑够 44 字符 → b64decode → 32 字节 AES-256 key
        padded_key = encoding_aes_key + "=" * (4 - len(encoding_aes_key) % 4)
        self.aes_key = base64.b64decode(padded_key)
        assert len(self.aes_key) == 32, f"AES key 长度应为 32 bytes, 实际 {len(self.aes_key)}"
        self.iv = self.aes_key[:16]
        self.corp_id = corp_id or os.environ.get('WECOM_CORPID', '')
    
    # ════════════════════════════════════════════════════════
    # 验签 (SHA1(token + timestamp + nonce + encrypt))
    # ════════════════════════════════════════════════════════
    def verify_signature(self, msg_signature: str, timestamp: str, 
                          nonce: str, encrypt: str) -> bool:
        """校验消息签名 — 任何加密消息处理前必须先验签"""
        sort_list = sorted([self.token, timestamp, nonce, encrypt])
        sha1 = hashlib.sha1(''.join(sort_list).encode('utf-8')).hexdigest()
        return sha1 == msg_signature
    
    # ════════════════════════════════════════════════════════
    # 解密 AES-256-CBC → 明文
    # ════════════════════════════════════════════════════════
    def decrypt(self, encrypted: str) -> str:
        """
        解密企微回调消息:
          AES-256-CBC 解密 → 去除 PKCS7 padding → 解析 16字节随机串 + 4字节msg_len + msg + corp_id
        
        Returns:
            明文 XML (企微回调消息内容)
        """
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        plain_data = cipher.decrypt(base64.b64decode(encrypted))
        
        # 去除 PKCS7 padding
        pad_len = plain_data[-1]
        plain_data = plain_data[:-pad_len]
        
        # 解析: 16字节随机串 + 4字节msg_len(big-endian) + msg + corp_id
        msg_len = socket.ntohl(struct.unpack("I", plain_data[16:20])[0])
        msg = plain_data[20:20 + msg_len].decode('utf-8')
        from_corp_id = plain_data[20 + msg_len:].decode('utf-8')
        
        # 校验 corp_id (防止伪造)
        if from_corp_id != self.corp_id:
            raise ValueError(f"corp_id 不匹配: 期望 {self.corp_id}, 实际 {from_corp_id}")
        
        return msg
    
    # ════════════════════════════════════════════════════════
    # 加密明文 → 企微回调格式
    # ════════════════════════════════════════════════════════
    def encrypt(self, reply_msg: str) -> tuple:
        """
        加密回复消息:
          16字节随机串 + 4字节msg_len + msg + corp_id → PKCS7 padding → AES-256-CBC → Base64
        
        Returns:
            (encrypted, timestamp, nonce, signature)  # 用于组装回调 XML
        """
        # 16 字节随机串
        random_str = os.urandom(16)
        msg_bytes = reply_msg.encode('utf-8')
        corp_id_bytes = self.corp_id.encode('utf-8')
        
        # 拼接: random(16) + msg_len(4, big-endian) + msg + corp_id
        msg_len = struct.pack("I", socket.htonl(len(msg_bytes)))
        raw = random_str + msg_len + msg_bytes + corp_id_bytes
        
        # PKCS7 padding (AES block size = 16)
        pad_len = 32 - len(raw) % 32
        raw += bytes([pad_len] * pad_len)
        
        # AES-256-CBC 加密
        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.iv)
        encrypted = base64.b64encode(cipher.encrypt(raw)).decode('utf-8')
        
        # 生成签名
        timestamp = str(int(time.time()))
        nonce = str(random.randint(1000000000, 9999999999))
        sort_list = sorted([self.token, timestamp, nonce, encrypted])
        signature = hashlib.sha1(''.join(sort_list).encode('utf-8')).hexdigest()
        
        return encrypted, timestamp, nonce, signature
    
    # ════════════════════════════════════════════════════════
    # 解析明文 XML 消息
    # ════════════════════════════════════════════════════════
    @staticmethod
    def parse_message(xml_str: str) -> dict:
        """把企微明文回调 XML 解析为 dict"""
        try:
            root = ET.fromstring(xml_str)
            return {
                'to_user': _xml_text(root, 'ToUserName'),
                'from_user': _xml_text(root, 'FromUserName'),
                'create_time': int(_xml_text(root, 'CreateTime') or 0),
                'msg_type': _xml_text(root, 'MsgType'),
                'content': _xml_text(root, 'Content'),
                'msg_id': _xml_text(root, 'MsgId'),
                'agent_id': int(_xml_text(root, 'AgentID') or 0),
                'xml': xml_str,
            }
        except Exception as e:
            raise ValueError(f"XML 解析失败: {e}")
    
    # ════════════════════════════════════════════════════════
    # 构造回复 XML
    # ════════════════════════════════════════════════════════
    @staticmethod
    def build_reply_xml(to_user: str, from_user: str, content: str) -> str:
        """构造明文回复 XML (企微加密模式需要这个)"""
        return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content[:2000]}]]></Content>
</xml>"""
    
    # ════════════════════════════════════════════════════════
    # 组装加密回调响应 XML (企微要求的最终格式)
    # ════════════════════════════════════════════════════════
    def build_callback_response(self, reply_msg: str) -> str:
        """加密明文回复 → 企微回调要求的加密 XML"""
        encrypted, ts, nonce, sig = self.encrypt(reply_msg)
        return f"""<xml>
<Encrypt><![CDATA[{encrypted}]]></Encrypt>
<MsgSignature>{sig}</MsgSignature>
<TimeStamp>{ts}</TimeStamp>
<Nonce>{nonce}</Nonce>
</xml>"""


def _xml_text(root: ET.Element, tag: str) -> str:
    el = root.find(tag)
    return el.text if el is not None else ''


# ═══════════════════════════════════════════════════════════
# 单元测试 (验签 + 加解密往返)
# ═══════════════════════════════════════════════════════════
def selftest():
    """往返加密测试: encrypt → decrypt → 应还原"""
    # 企微 EncodingAESKey 格式: base64(32字节 AES key).rstrip('=') = 43 字符
    # 所以补 1 个 '=' 就能还原 base64 → 32 bytes
    TOKEN = "MTSCOSAIcallbackToken2026wecom8888"
    # 下面这个 43 字符是 base64(32字节key) 去掉 =
    AES_KEY_43 = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTI"  # 43 chars → +1 '=' → 44 → 32 bytes
    CORP_ID = "ww1234567890abcdef"
    
    wc = WeComCrypto(TOKEN, AES_KEY_43, CORP_ID)
    print(f"AES key: {len(wc.aes_key)} bytes, IV: {len(wc.iv)} bytes")
    
    original_xml = WeComCrypto.build_reply_xml(
        to_user=CORP_ID,
        from_user="UserID_test123",
        content="这是一条测试回复消息"
    )
    print(f"\n原文 ({len(original_xml)} bytes): {original_xml[:80]}...")
    
    # 加密
    encrypted, ts, nonce, sig = wc.encrypt(original_xml)
    print(f"加密后: {encrypted[:60]}... (签名={sig})")
    
    # 验签
    assert wc.verify_signature(sig, ts, nonce, encrypted), "验签失败!"
    print("✅ 签名校验通过")
    
    # 解密 (模拟企微服务器送回来)
    decrypted = wc.decrypt(encrypted)
    print(f"解密还原: {decrypted[:80]}...")
    assert decrypted == original_xml, f"解密不匹配!"
    print("✅ 加解密往返通过!")
    
    response = wc.build_callback_response(original_xml)
    print(f"\n完整加密回调响应 XML:\n{response}")
    
    print("\n✅ WeComCrypto selftest ALL PASS")
    return True


if __name__ == '__main__':
    selftest()
