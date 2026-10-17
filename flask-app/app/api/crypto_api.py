#!/usr/bin/env python3
"""
§五 密码学 API
=============
8 个端点：encrypt/decrypt/sign/verify/fingerprint/keypair/benchmark/logs
"""
import sqlite3, os, json, base64
from flask import Blueprint, jsonify, request
from ai_engines import crypto_engine as ce

crypto_api = Blueprint('crypto_api', __name__)

def _db():
    for p in [os.path.expanduser("~/mtscos/_runtime/databases/Database/app.db")]:
        if os.path.exists(p):
            conn = sqlite3.connect(p); conn.row_factory = sqlite3.Row; conn.execute("PRAGMA journal_mode=WAL")
            return conn

def _b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode()

def _b64_decode(s: str) -> bytes:
    return base64.b64decode(s)

@crypto_api.route('/api/crypto/encrypt', methods=['POST'])
def encrypt():
    body = request.get_json(force=True) or {}
    plaintext = body.get('plaintext', '').encode()
    if not plaintext:
        return jsonify({"success": False, "error": "缺少 plaintext"}), 400
    aad = body.get('aad', '').encode()
    r = ce.aes_gcm_encrypt(plaintext, aad=aad)
    return jsonify({"success": True, **r})

@crypto_api.route('/api/crypto/decrypt', methods=['POST'])
def decrypt():
    body = request.get_json(force=True) or {}
    try:
        pt = ce.aes_gcm_decrypt(
            body['ciphertext_b64'], body['nonce_b64'], body['key_b64'],
            aad=body.get('aad', '').encode()
        )
        return jsonify({"success": True, "plaintext": pt.decode(errors='replace'), "length": len(pt)})
    except Exception as e:
        return jsonify({"success": False, "error": f"解密失败: {str(e)}"}), 400

@crypto_api.route('/api/crypto/sign', methods=['POST'])
def sign():
    body = request.get_json(force=True) or {}
    data = body.get('data', '').encode()
    key = _b64_decode(body['key_b64']) if body.get('key_b64') else None
    if not data: return jsonify({"success": False, "error": "缺少 data"}), 400
    r = ce.hmac_sign(data, key=key)
    return jsonify({"success": True, **r})

@crypto_api.route('/api/crypto/verify', methods=['POST'])
def verify():
    body = request.get_json(force=True) or {}
    ok = ce.hmac_verify(
        body['data'].encode(), body['signature_b64'], body['key_b64']
    )
    return jsonify({"success": True, "valid": ok})

@crypto_api.route('/api/crypto/fingerprint', methods=['POST', 'GET'])
def fingerprint():
    if request.method == 'POST':
        body = request.get_json(force=True) or {}
        data = body.get('data', '').encode()
    else:
        data = request.args.get('data', '').encode()
    if not data: return jsonify({"success": False, "error": "缺少 data"}), 400
    return jsonify({"success": True, **ce.data_fingerprint(data)})

@crypto_api.route('/api/crypto/keypair', methods=['POST', 'GET'])
def keypair():
    return jsonify({"success": True, **ce.nacl_keypair()})

@crypto_api.route('/api/crypto/benchmark', methods=['GET'])
def benchmark():
    return jsonify({"success": True, "results": ce.bench(), "unit": "ms (encrypt+decrypt/sign+verify)"})

@crypto_api.route('/api/crypto/logs', methods=['GET'])
def logs():
    limit = int(request.args.get('limit', 20))
    conn = _db()
    rows = conn.execute("""
        SELECT operation, algorithm, data_len, latency_ms, success, created_at
        FROM mt_crypto_log ORDER BY op_id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return jsonify({"success": True, "data": [dict(r) for r in rows], "total": len(rows)})

print("[CRYPTO-API] Blueprint crypto_api 注册: 8 路由")
