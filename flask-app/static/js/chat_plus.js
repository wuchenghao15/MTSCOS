/* 仙女座 · 聊天系统增强面板 (flow_chat_complete_20261022)
 * 依赖: /api/local-chat/* 既有接口 + andromeda_chat_bp 新增接口
 * 功能: 跨会话检索 / 未读 / 归档 / 导出 / 消息编辑删除引用反馈 / @天团派单
 */
(function () {
  'use strict';
  if (window.__chatPlusLoaded) return;
  window.__chatPlusLoaded = true;

  var CSS = ''
    + '#cp-fab{position:fixed;right:22px;bottom:96px;z-index:9998;width:46px;height:46px;border-radius:50%;'
    + 'border:0;cursor:pointer;font-size:20px;color:#fff;background:linear-gradient(135deg,#4f8cff,#8b5cf6);'
    + 'box-shadow:0 8px 26px rgba(79,140,255,.45)}'
    + '#cp-fab .cp-dot{position:absolute;top:-4px;right:-4px;min-width:18px;height:18px;border-radius:9px;'
    + 'background:#ef4444;color:#fff;font-size:10px;line-height:18px;padding:0 4px;display:none}'
    + '#cp-panel{position:fixed;right:22px;bottom:152px;z-index:9999;width:400px;max-width:92vw;height:560px;'
    + 'max-height:76vh;background:#0e1730;border:1px solid rgba(120,160,255,.3);border-radius:16px;'
    + 'display:none;flex-direction:column;color:#e6edff;font:13px/1.5 -apple-system,"PingFang SC",sans-serif;'
    + 'box-shadow:0 18px 60px rgba(0,0,0,.5);overflow:hidden}'
    + '#cp-panel.show{display:flex}'
    + '.cp-head{padding:11px 14px;border-bottom:1px solid rgba(120,160,255,.18);display:flex;align-items:center;gap:8px}'
    + '.cp-head b{flex:1;font-size:13px}'
    + '.cp-head span{cursor:pointer;color:#8fa3c8}'
    + '.cp-tabs{display:flex;border-bottom:1px solid rgba(120,160,255,.14)}'
    + '.cp-tab{flex:1;text-align:center;padding:8px 0;font-size:12px;color:#8fa3c8;cursor:pointer}'
    + '.cp-tab.on{color:#fff;background:rgba(79,140,255,.16)}'
    + '.cp-body{flex:1;overflow:auto;padding:10px 12px}'
    + '.cp-row{padding:8px 0;border-bottom:1px dashed rgba(120,160,255,.14)}'
    + '.cp-t{font-size:12.5px;color:#e6edff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
    + '.cp-s{font-size:11px;color:#8fa3c8;margin-top:2px}'
    + '.cp-btn{border:1px solid rgba(120,160,255,.4);background:transparent;color:#9bb6ff;border-radius:7px;'
    + 'font-size:11px;padding:2px 8px;margin-left:5px;cursor:pointer}'
    + '.cp-btn:hover{background:rgba(79,140,255,.14)}'
    + '.cp-btn.warn{border-color:rgba(239,68,68,.45);color:#f87171}'
    + '.cp-btn.ok{border-color:rgba(16,185,129,.45);color:#34d399}'
    + '.cp-input{width:100%;box-sizing:border-box;background:rgba(255,255,255,.05);border:1px solid rgba(120,160,255,.25);'
    + 'border-radius:9px;color:#e6edff;padding:7px 10px;font-size:12px;outline:none}'
    + '.cp-empty{color:#8fa3c8;text-align:center;padding:26px 0;font-size:12px}'
    + '.cp-chip{display:inline-block;border:1px solid rgba(139,92,246,.45);color:#c4b5fd;border-radius:999px;'
    + 'padding:2px 9px;margin:3px 4px 0 0;font-size:11px;cursor:pointer}'
    + '.cp-jump{color:#7dd3fc;text-decoration:none;border-bottom:1px dotted rgba(125,211,252,.6);cursor:pointer}'
    + '.cp-jump:hover{color:#fff;background:rgba(79,140,255,.22)}'
    + '.cp-kv{display:flex;gap:8px;padding:3px 0;font-size:12px}'
    + '.cp-kv b{color:#8fa3c8;font-weight:400;min-width:58px}'
    + '.cp-ev{padding:5px 0;border-bottom:1px dashed rgba(120,160,255,.12);font-size:11.5px}'
    + '@media(max-width:520px){#cp-panel{width:calc(100vw - 16px);right:8px;bottom:70px;height:72vh;max-height:none}'
    + '#cp-fab{right:14px;bottom:86px}}';

  var style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  var fab = document.createElement('button');
  fab.id = 'cp-fab';
  fab.innerHTML = '✨<i class="cp-dot"></i>';
  fab.title = '仙女座聊天增强';
  document.body.appendChild(fab);

  var panel = document.createElement('div');
  panel.id = 'cp-panel';
  panel.innerHTML = ''
    + '<div class="cp-head"><b>✨ 仙女座 · 聊天增强</b><span id="cp-close">✕</span></div>'
    + '<div class="cp-tabs">'
    + '  <div class="cp-tab on" data-tab="search">检索</div>'
    + '  <div class="cp-tab" data-tab="sess">会话</div>'
    + '  <div class="cp-tab" data-tab="msg">消息</div>'
    + '  <div class="cp-tab" data-tab="team">天团</div>'
    + '</div>'
    + '<div class="cp-body" id="cp-body"></div>';
  document.body.appendChild(panel);

  var body = panel.querySelector('#cp-body');
  var TAB = 'search';
  var CUR = null;

  function api(url, opt) {
    var o = opt || {};
    // 小龙 App(WebView) 用 X-XL-Token 鉴权, 面板请求需带上, 否则 401
    var o2 = Object.assign({}, o, { headers: Object.assign({}, o.headers || {}) });
    try {
      var tok = localStorage.getItem('xl_token');
      if (tok) o2.headers['X-XL-Token'] = tok;
    } catch (e) { /* 隐私模式忽略 */ }
    return fetch(url, o2).then(function (r) {
      return r.json().catch(function () { return { success: false, error: 'bad_json' }; });
    });
  }
  function post(url, data, method) {
    return api(url, {
      method: method || 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data || {})
    });
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* ── AI 跳转: 把 [[jump|标签|kind:key]] / TH-任务号 / @天团 变成可点击链接 ── */
  var TOKEN_RE = /\[\[jump\|([^|\]]{1,60})\|([a-z]+):([^\]\[]+)\]\]/g;
  function jumpAnchor(label, kind, key) {
    return '<a class="cp-jump" href="#" data-jump-kind="' + kind + '" data-jump-key="'
      + key + '" title="跳转: ' + kind + '">' + label + '</a>';
  }
  function linkifyBare(txt) {
    txt = txt.replace(/(^|[^\w>])(TH-\d{8}-\d{4})/g, function (_, pre, code) {
      return pre + jumpAnchor(code, 'task', code);
    });
    txt = txt.replace(/(^|[\s（(])(@[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9·_-]{1,19})/g,
      function (_, pre, name) {
        return pre + jumpAnchor(name, 'team', name.slice(1));
      });
    return txt;
  }
  function richText(raw) {
    var s = esc(raw == null ? '' : raw);
    var out = '', last = 0, m;
    TOKEN_RE.lastIndex = 0;
    while ((m = TOKEN_RE.exec(s)) !== null) {
      out += linkifyBare(s.slice(last, m.index));
      out += jumpAnchor(m[1], m[2], m[3]);
      last = m.index + m[0].length;
    }
    out += linkifyBare(s.slice(last));
    return out.replace(/\n/g, '<br>');
  }
  function inputBox() {
    return document.querySelector('textarea') || document.querySelector('input[type="text"]');
  }
  function insertText(txt) {
    var el = inputBox();
    if (!el) { navigator.clipboard && navigator.clipboard.writeText(txt); return false; }
    var s = el.selectionStart || 0, e = el.selectionEnd || 0;
    var v = el.value || '';
    el.value = v.slice(0, s) + txt + v.slice(e);
    el.focus();
    el.selectionStart = el.selectionEnd = s + txt.length;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  }
  function toast(msg) {
    var t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText = 'position:fixed;left:50%;bottom:120px;transform:translateX(-50%);z-index:10000;'
      + 'background:rgba(14,23,48,.96);border:1px solid rgba(120,160,255,.35);color:#e6edff;'
      + 'padding:8px 16px;border-radius:10px;font-size:12px';
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2200);
  }

  function refreshUnread() {
    api('/api/local-chat/unread').then(function (d) {
      var dot = fab.querySelector('.cp-dot');
      if (!d.success || !d.total) { dot.style.display = 'none'; return; }
      dot.style.display = 'block';
      dot.textContent = d.total > 99 ? '99+' : d.total;
    }).catch(function () {});
  }

  function viewSearch() {
    body.innerHTML = '<input class="cp-input" id="cp-q" placeholder="跨会话检索消息内容…">'
      + '<div id="cp-qres" class="cp-empty">输入关键词后回车</div>';
    var q = body.querySelector('#cp-q');
    q.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      var kw = q.value.trim();
      if (!kw) return;
      var res = body.querySelector('#cp-qres');
      res.className = 'cp-empty';
      res.textContent = '检索中…';
      api('/api/local-chat/search?q=' + encodeURIComponent(kw) + '&limit=40').then(function (d) {
        if (!d.success) { res.textContent = d.error || '检索失败'; return; }
        if (!d.items.length) { res.textContent = '无匹配消息'; return; }
        res.className = '';
        res.innerHTML = d.items.map(function (it) {
          return '<div class="cp-row"><div class="cp-t">' + esc(it.title || it.session_id) + '</div>'
            + '<div class="cp-s">' + esc(it.role) + ' · ' + esc(it.created_at) + '</div>'
            + '<div class="cp-s">' + esc(it.snippet) + '</div>'
            + '<button class="cp-btn" data-sid="' + esc(it.session_id) + '">打开消息</button></div>';
        }).join('');
        res.querySelectorAll('button[data-sid]').forEach(function (b) {
          b.onclick = function () { CUR = b.dataset.sid; switchTab('msg'); };
        });
      });
    });
  }

  function viewSessions() {
    body.innerHTML = '<div class="cp-empty">加载会话…</div>';
    api('/api/local-chat/sessions').then(function (d) {
      if (!d.success) { body.innerHTML = '<div class="cp-empty">' + esc(d.error || '加载失败') + '</div>'; return; }
      var rows = d.sessions || [];
      if (!rows.length) { body.innerHTML = '<div class="cp-empty">暂无会话</div>'; return; }
      body.innerHTML = rows.map(function (s) {
        return '<div class="cp-row"><div class="cp-t">' + esc(s.title || s.session_id) + '</div>'
          + '<div class="cp-s">' + esc(s.session_id) + ' · ' + (s.message_count || 0) + ' 条</div>'
          + '<div style="margin-top:4px">'
          + '<button class="cp-btn" data-act="open" data-sid="' + esc(s.session_id) + '">消息</button>'
          + '<button class="cp-btn ok" data-act="read" data-sid="' + esc(s.session_id) + '">已读</button>'
          + '<button class="cp-btn" data-act="export" data-sid="' + esc(s.session_id) + '">导出md</button>'
          + '<button class="cp-btn warn" data-act="arch" data-sid="' + esc(s.session_id) + '">归档</button>'
          + '</div></div>';
      }).join('');
      body.querySelectorAll('button[data-act]').forEach(function (b) {
        var sid = b.dataset.sid, act = b.dataset.act;
        b.onclick = function () {
          if (act === 'open') { CUR = sid; switchTab('msg'); return; }
          if (act === 'export') { window.open('/api/local-chat/session/' + encodeURIComponent(sid) + '/export?fmt=md', '_blank'); return; }
          var url = act === 'read'
            ? '/api/local-chat/session/' + encodeURIComponent(sid) + '/read'
            : '/api/local-chat/session/' + encodeURIComponent(sid) + '/archive';
          post(url, { archived: 1 }).then(function (r) {
            toast(r.success ? (act === 'read' ? '已标记已读' : '已归档') : (r.error || '失败'));
            if (act === 'arch') refreshUnread();
          });
        };
      });
    });
  }

  function viewMessages() {
    if (!CUR) { body.innerHTML = '<div class="cp-empty">先在「会话」或「检索」里选择一个会话</div>'; return; }
    body.innerHTML = '<div class="cp-s" style="margin-bottom:6px">' + esc(CUR) + '</div>'
      + '<div class="cp-empty">加载消息…</div>';
    api('/api/local-chat/msg/list?session_id=' + encodeURIComponent(CUR) + '&limit=100').then(function (d) {
      if (!d.success) { body.innerHTML = '<div class="cp-empty">' + esc(d.error || '加载失败') + '</div>'; return; }
      var ms = d.messages || [];
      if (!ms.length) { body.innerHTML = '<div class="cp-empty">该会话暂无消息</div>'; return; }
      body.innerHTML = '<div class="cp-s" style="margin-bottom:6px">共 ' + ms.length + ' 条'
        + (d.has_more ? ' (仅显示最近 100 条)' : '') + '</div>'
        + ms.map(function (m) {
          return '<div class="cp-row">'
            + '<div class="cp-s">#' + m.id + ' ' + esc(m.role) + ' · ' + esc(m.created_at)
            + (m.edited_at ? ' · 已编辑' : '') + (m.feedback === 1 ? ' · 👍' : m.feedback === -1 ? ' · 👎' : '') + '</div>'
            + '<div class="cp-t" style="white-space:normal">' + richText(String(m.content || '').slice(0, 300)) + '</div>'
            + '<div style="margin-top:5px">'
            + '<button class="cp-btn" data-quote="' + esc(String(m.content || '').slice(0, 200)) + '">引用</button>'
            + (m.role === 'user' ? '<button class="cp-btn" data-edit="' + m.id + '">编辑</button>' : '')
            + '<button class="cp-btn" data-fb="' + m.id + '" data-v="up">👍</button>'
            + '<button class="cp-btn" data-fb="' + m.id + '" data-v="down">👎</button>'
            + '<button class="cp-btn warn" data-del="' + m.id + '">删除</button>'
            + '</div></div>';
        }).join('');

      body.querySelectorAll('button[data-quote]').forEach(function (b) {
        b.onclick = function () {
          var txt = b.dataset.quote.split('\n').map(function (l) { return '> ' + l; }).join('\n') + '\n\n';
          toast(insertText(txt) ? '已插入引用' : '已复制引用');
        };
      });
      body.querySelectorAll('button[data-edit]').forEach(function (b) {
        b.onclick = function () {
          var mid = b.dataset.edit;
          var row = b.closest('.cp-row').querySelector('.cp-t');
          var nv = prompt('编辑消息内容:', row.textContent);
          if (nv == null) return;
          post('/api/local-chat/msg/' + mid, { content: nv }, 'PUT').then(function (r) {
            toast(r.success ? '已保存' : (r.error || '保存失败'));
            if (r.success) viewMessages();
          });
        };
      });
      body.querySelectorAll('button[data-fb]').forEach(function (b) {
        b.onclick = function () {
          post('/api/local-chat/msg/' + b.dataset.fb + '/feedback', { verdict: b.dataset.v }).then(function (r) {
            toast(r.success ? '反馈已投喂脑库' : (r.error || '反馈失败'));
            if (r.success) viewMessages();
          });
        };
      });
      body.querySelectorAll('button[data-del]').forEach(function (b) {
        b.onclick = function () {
          if (!confirm('确认删除该消息?')) return;
          api('/api/local-chat/msg/' + b.dataset.del, { method: 'DELETE' }).then(function (r) {
            toast(r.success ? '已删除' : (r.error || '删除失败'));
            if (r.success) viewMessages();
          });
        };
      });
    });
  }

  function viewTeams() {
    body.innerHTML = '<div class="cp-empty">加载天团…</div>';
    api('/api/local-chat/plus/meta').then(function (d) {
      if (!d.success) { body.innerHTML = '<div class="cp-empty">' + esc(d.error || '加载失败') + '</div>'; return; }
      var teams = d.teams || [];
      body.innerHTML = '<div class="cp-s">点击天团插入 @, 再点「派单」把输入框内容派成任务大厅任务</div>'
        + '<div style="margin:8px 0 10px">' + teams.map(function (t) {
          return '<span class="cp-chip" data-team="' + esc(t.name) + '">@' + esc(t.name) + '</span>';
        }).join('') + '</div>'
        + '<button class="cp-btn ok" id="cp-dispatch" style="margin:0;padding:6px 12px">🚀 派单给已 @ 的天团</button>'
        + '<div id="cp-dres" class="cp-s" style="margin-top:8px"></div>';
      body.querySelectorAll('.cp-chip').forEach(function (c) {
        c.onclick = function () { insertText('@' + c.dataset.team + ' '); toast('已插入 @' + c.dataset.team); };
      });
      body.querySelector('#cp-dispatch').onclick = function () {
        var el = inputBox();
        var txt = ((el && el.value) || '').trim();
        if (!txt) { toast('输入框为空'); return; }
        if (!/@[^\s@，,。;；:：]{1,24}/.test(txt)) { toast('请先 @ 一个天团'); return; }
        if (!CUR) { toast('请先在「会话」里选一个会话'); return; }
        post('/api/local-chat/mention', { session_id: CUR, text: txt }).then(function (r) {
          var out = body.querySelector('#cp-dres');
          if (!r.success) { out.textContent = r.error || '派单失败'; return; }
          out.innerHTML = r.created.map(function (c) {
            return '<div>' + jumpAnchor(esc(c.hall_code), 'task', c.task_id) + ' @'
              + jumpAnchor(esc(c.team), 'team', esc(c.team)) + ' → '
              + esc(c.center || '待分派') + ' [' + esc(c.status) + ']'
              + (c.dispatch_error ? ' <span style="color:#f87171">⚠️' + esc(c.dispatch_error) + '</span>' : '')
              + '</div>';
          }).join('');
          toast('已派单 ' + r.created.length + ' 条');
        });
      };
    });
  }

  function showPanel() { panel.classList.add('show'); }

  function openJump(kind, key) {
    if (kind === 'task') { showPanel(); viewTask(key); return; }
    if (kind === 'team') { showPanel(); viewTeam(key); return; }
    if (kind === 'center') { showPanel(); viewCenter(key); return; }
    if (kind === 'session') { location.href = '/local-chat?sid=' + encodeURIComponent(key); }
  }

  function viewCenter(name) {
    body.innerHTML = '<div class="cp-empty">加载中心 ' + esc(name) + ' …</div>';
    api('/api/local-chat/jump/center?name=' + encodeURIComponent(name)).then(function (d) {
      if (!d.success) {
        body.innerHTML = '<div class="cp-empty">' + esc(d.error || '未找到任务中心') + '</div>'
          + '<div style="text-align:center"><button class="cp-btn" id="cp-back">← 返回消息</button></div>';
        var b = body.querySelector('#cp-back'); if (b) b.onclick = function () { switchTab('msg'); };
        return;
      }
      var st = d.stats || {};
      var statHtml = Object.keys(st).map(function (k) {
        return '<span class="cp-chip">' + esc(k) + ' ' + st[k] + '</span>';
      }).join('') || '<span class="cp-empty">暂无任务</span>';
      var tks = (d.tasks || []).map(function (k) {
        return '<div class="cp-ev">' + jumpAnchor(esc(k.hall_code || ('#' + k.id)), 'task', k.id)
          + ' ' + esc(k.title || '') + ' <span style="color:#8fa3c8">[' + esc(k.status || '') + ']</span></div>';
      }).join('') || '<div class="cp-empty">暂无任务</div>';
      body.innerHTML = '<button class="cp-btn" id="cp-back" style="margin:0 0 8px 0">← 返回消息</button>'
        + '<div class="cp-t" style="white-space:normal;font-size:14px;color:#7dd3fc">'
        + esc((d.center || {}).name || name) + '</div>'
        + '<div class="cp-kv"><b>任务总数</b><span>' + (d.total || 0) + '</span></div>'
        + '<div style="margin:6px 0">' + statHtml + '</div>'
        + '<div style="margin:8px 0"><button class="cp-btn" id="cp-goto-hall">任务大厅</button></div>'
        + '<div class="cp-s" style="margin-top:6px">近期任务</div>' + tks;
      body.querySelector('#cp-back').onclick = function () { switchTab('msg'); };
      body.querySelector('#cp-goto-hall').onclick = function () {
        window.open('/admin/center#hall-section', '_blank');
      };
    });
  }

  function viewTeam(name) {
    body.innerHTML = '<div class="cp-empty">加载天团 ' + esc(name) + ' …</div>';
    api('/api/local-chat/jump/team?name=' + encodeURIComponent(name)).then(function (d) {
      if (!d.success) {
        body.innerHTML = '<div class="cp-empty">' + esc(d.error || '未找到天团') + '</div>'
          + '<div style="text-align:center"><button class="cp-btn" id="cp-back">← 返回消息</button></div>';
        var b = body.querySelector('#cp-back'); if (b) b.onclick = function () { switchTab('msg'); };
        return;
      }
      var t = d.team || {}, keyw = String(t.skill_keywords || '').split(',').filter(Boolean).slice(0, 12);
      var mem = (d.members || []).map(function (m) {
        return '<div class="cp-ev"><b>' + esc(m.member_name || '-') + '</b>'
          + (m.skill_level ? ' · Lv.' + esc(m.skill_level) : '')
          + (m.capabilities ? '<div style="color:#8fa3c8">' + esc(String(m.capabilities).slice(0, 80)) + '</div>' : '')
          + '</div>';
      }).join('') || '<div class="cp-empty">该天团暂无成员记录</div>';
      var tks = (d.tasks || []).map(function (k) {
        return '<div class="cp-ev">' + jumpAnchor(esc(k.hall_code || ('#' + k.id)), 'task', k.id)
          + ' ' + esc(k.title || '') + ' <span style="color:#8fa3c8">[' + esc(k.status || '') + ']</span></div>';
      }).join('') || '<div class="cp-empty">暂无大厅任务</div>';
      body.innerHTML = '<button class="cp-btn" id="cp-back" style="margin:0 0 8px 0">← 返回消息</button>'
        + '<div class="cp-t" style="white-space:normal;font-size:14px;color:#c4b5fd">' + esc(d.name) + '</div>'
        + '<div class="cp-kv"><b>成员数</b><span>' + (t.member_count || (d.members || []).length) + '</span></div>'
        + (d.center ? '<div class="cp-kv"><b>对口中心</b><span>' + jumpAnchor(esc(d.center), 'center', esc(d.center)) + '</span></div>' : '')
        + '<div style="margin:6px 0">' + keyw.map(function (k) {
          return '<span class="cp-chip">' + esc(k.trim()) + '</span>';
        }).join('') + '</div>'
        + '<div style="margin:8px 0"><button class="cp-btn" id="cp-ask-team">@该天团 派单</button></div>'
        + '<div class="cp-s" style="margin-top:6px">成员</div>' + mem
        + '<div class="cp-s" style="margin-top:8px">近期承接</div>' + tks;
      body.querySelector('#cp-back').onclick = function () { switchTab('msg'); };
      body.querySelector('#cp-ask-team').onclick = function () {
        toast(insertText('@' + d.name + ' ') ? '已插入 @' + d.name : '请手动输入 @' + d.name);
      };
    });
  }

  function viewTask(key) {
    body.innerHTML = '<div class="cp-empty">解析任务 ' + esc(key) + ' …</div>';
    api('/api/local-chat/jump/resolve?kind=task&key=' + encodeURIComponent(key)).then(function (d) {
      if (!d.success) {
        body.innerHTML = '<div class="cp-empty">' + esc(d.error || '任务未找到') + '</div>'
          + '<div style="text-align:center"><button class="cp-btn" id="cp-back">← 返回</button></div>';
        body.querySelector('#cp-back').onclick = function () { switchTab('msg'); };
        return;
      }
      api('/api/local-chat/jump/task/' + d.task_id).then(function (t) {
        if (!t.success) { body.innerHTML = '<div class="cp-empty">' + esc(t.error || '任务详情不可用') + '</div>'; return; }
        var task = t.task || {};
        var evs = (t.events || []).map(function (e) {
          return '<div class="cp-ev"><b>' + esc(e.event) + '</b> · ' + esc(e.actor || '-')
            + ' <span style="color:#8fa3c8">' + esc(e.created_at || '') + '</span>'
            + (e.note ? '<div style="color:#8fa3c8">' + esc(e.note) + '</div>' : '') + '</div>';
        }).join('') || '<div class="cp-empty">暂无轨迹</div>';
        body.innerHTML = '<button class="cp-btn" id="cp-back" style="margin:0 0 8px 0">← 返回消息</button>'
          + '<div class="cp-t" style="white-space:normal;font-size:13px">' + esc(task.title || '') + '</div>'
          + '<div class="cp-kv"><b>任务号</b><span>' + jumpAnchor(esc(task.hall_code || String(d.task_id)), 'task', task.id) + '</span></div>'
          + '<div class="cp-kv"><b>状态</b><span>' + esc(task.status || '-') + '</span></div>'
          + '<div class="cp-kv"><b>中心</b><span>' + esc(t.center || '待分派') + '</span></div>'
          + '<div class="cp-kv"><b>优先级</b><span>' + esc(task.priority || '-') + '</span></div>'
          + '<div class="cp-kv"><b>发布人</b><span>' + esc(task.publisher || '-') + '</span></div>'
          + '<div class="cp-kv"><b>验收</b><span>' + esc(task.acceptance_criteria || '-') + '</span></div>'
          + '<div class="cp-kv"><b>创建</b><span>' + esc(task.created_at || '-') + '</span></div>'
          + '<div style="margin:8px 0"><button class="cp-btn" id="cp-quote-task">引用任务号</button>'
          + '<button class="cp-btn" id="cp-goto-hall">任务大厅</button></div>'
          + '<div class="cp-s" style="margin-top:6px">状态机轨迹</div>' + evs;
        body.querySelector('#cp-back').onclick = function () { switchTab('msg'); };
        body.querySelector('#cp-quote-task').onclick = function () {
          var code = task.hall_code || '';
          toast(insertText(code + ' ') ? '已插入任务号' : '已复制任务号');
        };
        body.querySelector('#cp-goto-hall').onclick = function () {
          window.open(t.href || '/admin/center#hall-section', '_blank');
        };
      });
    });
  }

  var VIEWS = { search: viewSearch, sess: viewSessions, msg: viewMessages, team: viewTeams };
  function switchTab(t) {
    TAB = t;
    panel.querySelectorAll('.cp-tab').forEach(function (el) {
      el.classList.toggle('on', el.dataset.tab === t);
    });
    VIEWS[t]();
  }
  panel.querySelectorAll('.cp-tab').forEach(function (el) {
    el.onclick = function () { switchTab(el.dataset.tab); };
  });

  fab.onclick = function () {
    panel.classList.toggle('show');
    if (panel.classList.contains('show')) { switchTab(TAB); refreshUnread(); }
  };
  panel.querySelector('#cp-close').onclick = function () { panel.classList.remove('show'); };

  // 全站委托: 聊天正文里的任务号 / @天团 也能点击跳转
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('.cp-jump') : null;
    if (!a) return;
    e.preventDefault();
    openJump(a.getAttribute('data-jump-kind'), a.getAttribute('data-jump-key'));
  });

  window.ChatPlus = {
    richText: richText,
    openJump: openJump,
    openTask: function (key) { showPanel(); viewTask(key); },
    openTeam: function (name) { showPanel(); viewTeam(name); }
  };

  // 深链: /local-chat?task=TH-xxxx / ?team=天团名 (任务大厅/导出链接直达)
  (function deepLink() {
    try {
      var q = new URLSearchParams(location.search);
      var tk = q.get('task') || q.get('hall'), tm = q.get('team'), ct = q.get('center');
      if (tk) { showPanel(); viewTask(tk); }
      else if (tm) { showPanel(); viewTeam(tm); }
      else if (ct) { showPanel(); viewCenter(ct); }
    } catch (e) { /* 老浏览器忽略 */ }
  })();

  refreshUnread();
  setInterval(refreshUnread, 60000);
})();
