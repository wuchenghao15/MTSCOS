// 小龙小程序 API 封装 — 统一 mini 地址 + X-XL-Token 授权
const BASE = 'http://100.106.220.96:8888';

function headers() {
  const h = { 'Content-Type': 'application/json' };
  const t = wx.getStorageSync('xl_token');
  if (t) h['X-XL-Token'] = t;
  return h;
}

function request(path, method, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: BASE + path,
      method: method || 'GET',
      data: data || {},
      header: headers(),
      timeout: 20000,
      success: (res) => {
        if (res.statusCode === 401) {
          wx.removeStorageSync('xl_token');
          reject({ code: 'login_required', message: '请先登录' });
          return;
        }
        if (res.statusCode === 403) {
          reject({ code: 'scope_locked', message: (res.data && res.data.message) || '需在网页端申请开通' });
          return;
        }
        resolve(res.data);
      },
      fail: (err) => reject({ code: 'network', message: '与 mini 连接失败: ' + (err.errMsg || '') }),
    });
  });
}

function login(username, password) {
  return request('/api/xiaolong/token', 'POST', {
    username, password, device_id: wx.getStorageSync('xl_device_id'),
  }).then((j) => {
    if (j.success) wx.setStorageSync('xl_token', j.token);
    return j;
  });
}

function register(username, password) {
  return request('/api/xiaolong/register', 'POST', {
    username, password, device_id: wx.getStorageSync('xl_device_id'),
  }).then((j) => {
    if (j.success) wx.setStorageSync('xl_token', j.token);
    return j;
  });
}

// 流式发送: 小程序用 enableChunked 接收 SSE
function sendStream(payload, onToken, onDone, onError) {
  const task = wx.request({
    url: BASE + '/api/local-chat/send',
    method: 'POST',
    data: payload,
    header: headers(),
    enableChunked: true,
    responseType: 'arraybuffer',
    success: (res) => {
      if (res.statusCode === 401) { onError('请先登录'); return; }
      if (res.statusCode >= 400) { onError('发送失败 ' + res.statusCode); return; }
    },
    fail: () => onError('网络异常, 请检查与 mini 的连接'),
  });
  let buf = '';
  task.onChunkReceived((r) => {
    buf += decodeUtf8(r.data);
    const lines = buf.split('\n');
    buf = lines.pop();
    lines.forEach((ln) => {
      if (ln.indexOf('data:') !== 0) return;
      const body = ln.slice(5).trim();
      if (body === '[thinking]' || body === '') return;
      if (body.indexOf('[done]') === 0) { onDone(); return; }
      if (body.indexOf('[error]') === 0) { onError(body.slice(7)); return; }
      if (body.charAt(0) === '[') return;
      try {
        const o = JSON.parse(body);
        if (o.token) onToken(o.token);
      } catch (e) { /* 忽略半包 */ }
    });
  });
}

// 微信小程序无 TextDecoder 时的手工 UTF-8 解码
function decodeUtf8(arrayBuffer) {
  if (typeof TextDecoder !== 'undefined') {
    return new TextDecoder('utf-8').decode(arrayBuffer, { stream: true });
  }
  const bytes = new Uint8Array(arrayBuffer);
  let out = '', i = 0;
  while (i < bytes.length) {
    const b = bytes[i];
    if (b < 0x80) { out += String.fromCharCode(b); i += 1; }
    else if (b >= 0xC0 && b < 0xE0 && i + 1 < bytes.length) {
      out += String.fromCharCode(((b & 0x1F) << 6) | (bytes[i + 1] & 0x3F)); i += 2;
    } else if (b >= 0xE0 && b < 0xF0 && i + 2 < bytes.length) {
      out += String.fromCharCode(((b & 0x0F) << 12) | ((bytes[i + 1] & 0x3F) << 6) | (bytes[i + 2] & 0x3F)); i += 3;
    } else if (b >= 0xF0 && i + 3 < bytes.length) {
      const cp = ((b & 0x07) << 18) | ((bytes[i + 1] & 0x3F) << 12) | ((bytes[i + 2] & 0x3F) << 6) | (bytes[i + 3] & 0x3F);
      const s = cp - 0x10000;
      out += String.fromCharCode(0xD800 + (s >> 10), 0xDC00 + (s & 0x3FF)); i += 4;
    } else { i += 1; }
  }
  return out;
}

module.exports = {
  BASE, request, login, register, sendStream,
  bootstrap: (deviceId) => request('/api/xiaolong/bootstrap?device_id=' + deviceId),
  heartbeat: (deviceId) => request('/api/xiaolong/heartbeat', 'POST', { device_id: deviceId }),
  history: (sid) => request('/api/local-chat/history?session_id=' + sid),
  sessions: () => request('/api/local-chat/sessions'),
  scopeMy: () => request('/api/xiaolong/scope/my'),
};
