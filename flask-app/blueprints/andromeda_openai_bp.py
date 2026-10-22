#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仙女座 · OpenAI 兼容层 (flow_andromeda_openai_compat_20261022)

目的: 让 IDE / 客户端 (Trae「自定义模型」等) 直接把「仙女座」当成一个模型接入。
只做协议翻译, 推理仍走 ai_engines/local_ai_unified_gateway.chat
(Ollama 云端优先 + 本地零 token 兜底 + 脑库 RAG), 不新增任何云端依赖。

对外接口:
  GET  /v1/models                  → 模型清单 (andromeda / andromeda-multi)
  POST /v1/chat/completions        → OpenAI Chat Completions (支持 stream)
  POST /v1/responses               → OpenAI Responses API (支持 stream)

鉴权: Authorization: Bearer <key>, key 默认 andromeda, 可用环境变量 MTSCOS_MODEL_API_KEY 覆盖。
"""
import json
import os
import time
import uuid

from flask import Blueprint, Response, jsonify, request, stream_with_context

andromeda_openai_bp = Blueprint('andromeda_openai', __name__)

_MODEL_ID = 'andromeda'
_DEFAULT_KEY = os.environ.get('MTSCOS_MODEL_API_KEY') or 'andromeda'


def _auth_ok() -> bool:
    """Bearer key 校验; 允许无 Authorization (本机回环调试)"""
    provided = ''
    raw = request.headers.get('Authorization') or ''
    if raw.lower().startswith('bearer '):
        provided = raw[7:].strip()
    if not provided:
        provided = (request.headers.get('x-api-key') or '').strip()
    if not provided:
        return request.remote_addr in ('127.0.0.1', '::1', None)
    return provided == _DEFAULT_KEY


def _err(msg: str, code: int = 401, etype: str = 'invalid_request_error'):
    return jsonify({'error': {'message': msg, 'type': etype, 'code': etype}}), code


def _split_messages(msgs):
    """OpenAI messages → (system, prompt); 多轮历史压平进 prompt"""
    system, parts = '', []
    for m in msgs or []:
        role = (m.get('role') or 'user').strip()
        c = m.get('content')
        if isinstance(c, list):     # [{type:'text', text:'...'}]
            c = '\n'.join(str(x.get('text') or '') for x in c if isinstance(x, dict))
        c = str(c or '').strip()
        if not c:
            continue
        if role == 'system':
            system = (system + '\n' + c) if system else c
        else:
            parts.append(('用户' if role == 'user' else 'AI') + ': ' + c)
    return system, '\n'.join(parts[-12:])


def _ask(system: str, prompt: str) -> dict:
    """调用仙女座统一网关 (本地推理 + 脑库RAG)"""
    try:
        from ai_engines.local_ai_unified_gateway import chat as _chat
        r = _chat(prompt, system, flow_id='flow_andromeda_openai_compat_20261022')
        return {'ok': bool(r.get('success')), 'text': (r.get('response') or '').strip(),
                'model': r.get('model') or 'local', 'error': (r.get('error') or '')[:200]}
    except Exception as e:
        return {'ok': False, 'text': '', 'model': 'local', 'error': str(e)[:200]}


@andromeda_openai_bp.route('/v1/models', methods=['GET'])
def list_models():
    if not _auth_ok():
        return _err('Invalid API key')
    now = int(time.time())
    return jsonify({'object': 'list', 'data': [
        {'id': _MODEL_ID, 'object': 'model', 'created': now, 'owned_by': 'mtscos-andromeda',
         'description': '仙女座 · 本地推理 + 脑库RAG (零云端 token)'},
        {'id': _MODEL_ID + '-coder', 'object': 'model', 'created': now, 'owned_by': 'mtscos-andromeda',
         'description': '仙女座 · 代码向 (qwen2.5-coder 本地)'},
    ]})


@andromeda_openai_bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    if not _auth_ok():
        return _err('Invalid API key')
    data = request.get_json(silent=True) or {}
    system, prompt = _split_messages(data.get('messages'))
    if not prompt:
        return _err('messages 中没有任何 user/assistant 内容', 400)
    res = _ask(system, prompt)
    if not res['ok'] and not res['text']:
        return _err(res['error'] or '仙女座推理失败', 502, 'upstream_error')

    cid = 'chatcmpl-' + uuid.uuid4().hex[:24]
    created = int(time.time())
    text = res['text']
    if data.get('stream'):
        def gen():
            first = {'id': cid, 'object': 'chat.completion.chunk', 'created': created,
                     'model': _MODEL_ID,
                     'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': text},
                                  'finish_reason': None}]}
            yield 'data: ' + json.dumps(first, ensure_ascii=False) + '\n\n'
            last = {'id': cid, 'object': 'chat.completion.chunk', 'created': created,
                    'model': _MODEL_ID,
                    'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}
            yield 'data: ' + json.dumps(last, ensure_ascii=False) + '\n\n'
            yield 'data: [DONE]\n\n'
        return Response(stream_with_context(gen()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    return jsonify({'id': cid, 'object': 'chat.completion', 'created': created,
                    'model': _MODEL_ID,
                    'choices': [{'index': 0, 'finish_reason': 'stop',
                                 'message': {'role': 'assistant', 'content': text}}],
                    'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0},
                    'system_fingerprint': 'mtscos-andromeda'})


def _responses_input(body) -> tuple:
    """Responses API 的 input → (system, prompt)"""
    raw = body.get('input')
    if isinstance(raw, str):
        inst = body.get('instructions') or ''
        return inst, raw
    return _split_messages([{'role': 'system', 'content': body.get('instructions') or ''}] + list(raw or []))


@andromeda_openai_bp.route('/v1/responses', methods=['POST'])
def responses():
    if not _auth_ok():
        return _err('Invalid API key')
    data = request.get_json(silent=True) or {}
    system, prompt = _responses_input(data)
    if not prompt:
        return _err('input 为空', 400)
    res = _ask(system, prompt)
    if not res['ok'] and not res['text']:
        return _err(res['error'] or '仙女座推理失败', 502, 'upstream_error')

    rid = 'resp_' + uuid.uuid4().hex[:24]
    created = int(time.time())
    text = res['text']

    def _payload(status='completed'):
        return {'id': rid, 'object': 'response', 'created_at': created, 'model': _MODEL_ID,
                'status': status, 'output': [{'id': 'msg_' + rid[5:], 'type': 'message',
                                              'role': 'assistant', 'status': 'completed',
                                              'content': [{'type': 'output_text',
                                                           'text': text, 'annotations': []}]}],
                'usage': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}

    if data.get('stream'):
        def gen():
            seq = [('response.created', _payload('in_progress')),
                   ('response.output_item.added', {'id': rid, 'type': 'response.output_item.added',
                                                   'output_index': 0,
                                                   'item': {'id': 'msg_' + rid[5:], 'type': 'message',
                                                            'role': 'assistant', 'status': 'in_progress',
                                                            'content': []}}),
                   ('response.output_text.delta', {'type': 'response.output_text.delta',
                                                   'item_id': 'msg_' + rid[5:],
                                                   'output_index': 0, 'content_index': 0,
                                                   'delta': text}),
                   ('response.completed', _payload())]
            for ev, payload in seq:
                yield 'event: ' + ev + '\ndata: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'
        return Response(stream_with_context(gen()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    return jsonify(_payload())
