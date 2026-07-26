#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
布局AI Blueprint - 实时监控 + 动态CSS修复
端点说明：
- POST /api/layout_ai/snapshot   前端上报快照 → 返回修复CSS（任何人可访问，放白名单）
- GET  /api/layout_ai/stats      仪表盘统计（需管理员）
- GET  /api/layout_ai/rules      规则列表（需管理员）
- PUT  /api/layout_ai/rules/<id> 规则启停（需超级管理员）
- GET  /api/layout_ai/snapshots  最近快照（需管理员）
- GET  /api/layout_ai/logs       调节日志（需管理员）
- POST /api/layout_ai/ack        前端确认CSS已应用（白名单）
"""
import os, sys, json, logging, sqlite3
from datetime import datetime
from flask import Blueprint, request, jsonify, session

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = BASE_DIR
sys.path.insert(0, PROJECT_ROOT)

logger = logging.getLogger(__name__)

_LAYOUT_AI_STYLE_TAG = '''<!-- 布局AI：动态CSS修复注入点（优先级最高，放最后） -->
<style id="mtscos-layout-ai-fix" data-snapshot="" data-count="0">
  /* AI员工动态注入的布局修复，由 LayoutAdjusterAIEmployee 下发 */
</style>
'''

_LAYOUT_AI_PROBE_SCRIPT = r'''<!-- 布局AI：前端探针 + 20条规则前端检测 + 上报快照 + 接收修复CSS -->
<script>
(function () {
  'use strict';
  var LAYOUT_AI = {
    API_SNAPSHOT: '/api/layout_ai/snapshot',
    API_ACK: '/api/layout_ai/ack',
    DEBOUNCE_MS: 900,
    RERPORT_DELAY_INITIAL: 1200,
    RERPORT_DELAY_RESIZE: 500,
    MAX_ELEMENTS_SAMPLE: 60,
    lastSentAt: 0,
    pendingTimer: null,
    pendingPayload: null,
    currentSnapshotUuid: null,
    appliedFixCount: 0,
    disabled: false,
    init: function () {
      var self = this;
      try {
        var dis = localStorage.getItem('mtscos_layout_ai_disabled');
        if (dis === '1') this.disabled = true;
      } catch (e) {}
      if (this.disabled) return;
      setTimeout(function () { self.reportOnce('initial'); }, this.RERPORT_DELAY_INITIAL);
      var resizeTimer = null;
      window.addEventListener('resize', function () {
        if (resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () { self.reportOnce('resize'); }, self.RERPORT_DELAY_RESIZE);
      }, { passive: true });
      var bodyObserver = new MutationObserver(function (muts) {
        muts.forEach(function (m) {
          if (m.type === 'attributes' && (m.attributeName === 'data-theme' || m.attributeName === 'class')) {
            self.scheduleReport('theme_or_class', 400);
          }
        });
      });
      try { bodyObserver.observe(document.body, { attributes: true, attributeFilter: ['data-theme', 'class'] }); } catch (e) {}
      var tbtn = document.getElementById('mtscos-sidebar-toggle');
      if (tbtn) tbtn.addEventListener('click', function () { self.scheduleReport('sidebar_toggle', 360); });
      if (document.readyState === 'complete') self.reportOnce('dom_ready');
      else window.addEventListener('load', function () { setTimeout(function () { self.reportOnce('load'); }, 800); });
    },
    scheduleReport: function (reason, ms) {
      var self = this;
      if (this.disabled) return;
      if (this.pendingTimer) clearTimeout(this.pendingTimer);
      this.pendingTimer = setTimeout(function () { self.reportOnce(reason || 'schedule'); }, ms || this.DEBOUNCE_MS);
    },
    reportOnce: function (reason) {
      if (this.disabled) return;
      var now = Date.now();
      if (now - this.lastSentAt < 600) return;
      this.lastSentAt = now;
      var payload = this.captureSnapshot(reason || 'report');
      this.pendingPayload = payload;
      this.sendSnapshot(payload);
    },
    captureSnapshot: function (reason) {
      var viewport = { w: window.innerWidth || 0, h: window.innerHeight || 0, dpr: window.devicePixelRatio || 1 };
      var sidebar = document.querySelector('.mtscos-sidebar');
      var mainEl = document.querySelector('.mtscos-main');
      var contentScroll = document.querySelector('.mtscos-content-scroll');
      var sb = { w: 0, h: 0 };
      if (sidebar) { var r = sidebar.getBoundingClientRect(); sb.w = Math.round(r.width); sb.h = Math.round(r.height); }
      var mn = { w: 0, h: 0 };
      if (mainEl) { var r2 = mainEl.getBoundingClientRect(); mn.w = Math.round(r2.width); mn.h = Math.round(r2.height); }
      var body = document.body;
      var sidebar_mini = body.classList.contains('sidebar-mini');
      var theme = body.getAttribute('data-theme') || '';
      var scroll = {
        x: window.scrollX || document.documentElement.scrollLeft || 0,
        y: window.scrollY || document.documentElement.scrollTop || 0,
        body_scroll_height: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight || 0),
        body_client_height: document.documentElement.clientHeight || 0,
        content_scroll_top: contentScroll ? contentScroll.scrollTop : 0,
        content_scroll_height: contentScroll ? contentScroll.scrollHeight : 0,
        content_client_height: contentScroll ? contentScroll.clientHeight : 0,
      };
      var home_sections = null;
      if (location.pathname === '/' || location.pathname === '') {
        var hh = document.querySelector('.home-header, header.site-header');
        var mh = document.querySelector('.home-main, main, section.main');
        var fh = document.querySelector('.home-footer, footer.site-footer, footer');
        home_sections = {
          header_h: hh ? Math.round(hh.getBoundingClientRect().height) : 0,
          main_h: mh ? Math.round(mh.getBoundingClientRect().height) : 0,
          footer_h: fh ? Math.round(fh.getBoundingClientRect().height) : 0,
        };
      }
      var computed = { theme_vars: {} };
      try {
        var cs = getComputedStyle(document.body);
        ['--accent', '--bg-page', '--text-primary', '--border-subtle'].forEach(function (v) {
          computed.theme_vars[v] = (cs.getPropertyValue(v) || '').trim();
        });
      } catch (e) {}
      var detected = this._frontendDetect(viewport, sb, mn, scroll, sidebar_mini, home_sections, computed, mainEl, contentScroll);
      var elements = this._sampleKeyElements();
      return {
        url: location.pathname + location.search,
        title: document.title || '',
        viewport: viewport,
        sidebar: sb,
        main: mn,
        theme: theme,
        sidebar_mini: !!sidebar_mini,
        scroll: scroll,
        computed: computed,
        elements: elements,
        home_sections: home_sections,
        detected_issues: detected,
        trigger: reason || 'capture',
        ts: Date.now(),
      };
    },
    _sampleKeyElements: function () {
      var sel = [
        '.mtscos-global-header', '.mtscos-sidebar', '.mtscos-main', '.mtscos-content-scroll',
        '.card, .glass-effect, .dashboard-card, .section-card, .info-card, .data-card',
        'table, .table-container',
        '.mtscos-nav-item',
        'form .form-container, form input, form button, form select',
        'img, video',
      ];
      var set = [];
      var all = [];
      try { all = document.querySelectorAll(sel.join(',')); } catch (e) { return []; }
      var limit = this.MAX_ELEMENTS_SAMPLE;
      var n = all.length;
      var step = Math.max(1, Math.ceil(n / limit));
      for (var i = 0; i < n && set.length < limit; i += step) {
        var el = all[i];
        if (!el) continue;
        try {
          var r = el.getBoundingClientRect();
          var cs = getComputedStyle(el);
          set.push({
            tag: el.tagName,
            cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 120) : '',
            id: el.id || '',
            w: Math.round(r.width), h: Math.round(r.height),
            x: Math.round(r.left), y: Math.round(r.top),
            fontSize: parseInt(cs.fontSize) || 0,
            lineHeight: cs.lineHeight || '',
            display: cs.display || '',
            pos: cs.position || '',
            overflow_x: cs.overflowX || '',
            overflow_y: cs.overflowY || '',
          });
        } catch (e) {}
      }
      return set;
    },
    _frontendDetect: function (vp, sb, mn, sc, mini, home, computed, mainEl, contentEl) {
      var issues = [];
      function push(rule_id, confidence, summary, selector, vars, before) {
        issues.push({ rule_id: rule_id, confidence: confidence, summary: summary, selector: selector || '', vars: vars || {}, before: before || {} });
      }
      try {
        if (contentEl && contentEl.scrollWidth > vp.w * 0.82 + 6) {
          push('LF001', 0.88,
            'content-scroll 宽度超过视图82%(' + contentEl.scrollWidth + ' vs ' + Math.round(vp.w*0.82) + ')',
            '.mtscos-main, .mtscos-content-scroll',
            { selector: '.mtscos-main, .mtscos-content-scroll' },
            { sw: contentEl.scrollWidth, vp_w: vp.w });
        } else if (mainEl && mainEl.scrollWidth - mainEl.clientWidth > 4) {
          push('LF001', 0.8, 'main.scrollWidth>' + (mainEl.scrollWidth - mainEl.clientWidth) + 'px overflow-x',
            '.mtscos-main', { selector: '.mtscos-main' },
            { diff: mainEl.scrollWidth - mainEl.clientWidth });
        }
      } catch (e) {}
      try {
        var nav = document.querySelector('.mtscos-sidebar-nav');
        var sbb = document.querySelector('.mtscos-sidebar');
        if (nav && sbb && nav.scrollHeight > sbb.clientHeight - 180) {
          push('LF003', 0.8,
            '侧边栏菜单溢出(nav.scrollHeight=' + nav.scrollHeight + ')',
            '.mtscos-sidebar-nav', {},
            { nav_sh: nav.scrollHeight, sb_ch: sbb.clientHeight });
        }
      } catch (e) {}
      try {
        var header = document.querySelector('.mtscos-global-header');
        var sidebar = document.querySelector('.mtscos-sidebar');
        var main2 = document.querySelector('.mtscos-main');
        var items = [header, sidebar, main2].filter(Boolean);
        for (var a = 0; a < items.length; a++) {
          for (var b = a + 1; b < items.length; b++) {
            var ra = items[a].getBoundingClientRect();
            var rb = items[b].getBoundingClientRect();
            var iw = Math.max(0, Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left));
            var ih = Math.max(0, Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top));
            if (iw * ih > 400) {
              push('LF004', 0.75,
                '元素重叠面积=' + (iw*ih) + ' ' + items[a].className + ' vs ' + items[b].className,
                '', { z: 10 }, { area: iw * ih });
            }
          }
        }
      } catch (e) {}
      if (vp.w && sb.w) {
        var ratio = sb.w / vp.w;
        if (!mini && Math.abs(ratio - 0.20) > 0.03) {
          push('LF005', Math.min(1, Math.abs(ratio-0.20)*25), '侧边栏比例 ' + ratio.toFixed(3),
            '.mtscos-sidebar', { expected: 0.20, actual: ratio }, { sb_w: sb.w, vp_w: vp.w });
        }
        if (mini && Math.abs(ratio - 0.10) > 0.03) {
          push('LF006', Math.min(1, Math.abs(ratio-0.10)*25), 'mini侧边栏比例 ' + ratio.toFixed(3),
            'body.sidebar-mini .mtscos-sidebar', { expected: 0.10, actual: ratio }, { sb_w: sb.w, vp_w: vp.w });
        }
      }
      if (home && home.main_h) {
        var hh = home.header_h, mh = home.main_h, fh = home.footer_h;
        if (mh && Math.abs((hh / mh) - 1/7) > 0.18) {
          push('LF007', 0.7, '首页Header/Main比例 ' + (hh/mh).toFixed(3) + ' 偏离1:7',
            '.home-header, .home-main, .home-footer', { parent_h: fh }, { hh:hh, mh:mh, fh:fh });
        }
      }
      try {
        var allText = document.querySelectorAll('p, span, a, button, li, td, th, label, h1, h2, h3, h4, h5, h6');
        var foundSmall = null;
        var lim = Math.min(allText.length, 120);
        for (var i = 0; i < lim; i += 3) {
          var tEl = allText[i];
          if (!tEl) continue;
          var tcs = getComputedStyle(tEl);
          var fs = parseInt(tcs.fontSize);
          if (fs && fs < 11 && tEl.offsetParent !== null && (tEl.textContent || '').trim().length > 2) {
            foundSmall = { el: tEl, fs: fs }; break;
          }
        }
        if (foundSmall) {
          var cls = foundSmall.el.className || '';
          if (typeof cls !== 'string') cls = '';
          push('LF008', 0.8, '小字体 ' + foundSmall.fs + 'px',
            (foundSmall.el.tagName || '') + (cls ? '.' + cls.split(/\s+/)[0] : ''),
            {}, { fs: foundSmall.fs });
        }
      } catch (e) {}
      try {
        var imgs = document.querySelectorAll('img');
        for (var j = 0; j < Math.min(imgs.length, 30); j++) {
          var im = imgs[j];
          if (im.naturalWidth && im.parentElement) {
            var pr = im.parentElement.getBoundingClientRect();
            if (pr.width > 0 && im.naturalWidth > pr.width * 1.25) {
              push('LF015', 0.82,
                'img(' + im.naturalWidth + ') 大于父容器(' + Math.round(pr.width) + ')',
                'img', { selector: 'img' }, { nw: im.naturalWidth, pw: Math.round(pr.width) });
              break;
            }
          }
        }
      } catch (e) {}
      if (sc.body_scroll_height && sc.body_client_height && sc.body_scroll_height > sc.body_client_height + 10) {
        push('LF016', 0.85, 'body SH=' + sc.body_scroll_height + ' CH=' + sc.body_client_height,
          'html, body', {}, { sh: sc.body_scroll_height, ch: sc.body_client_height });
      }
      var tv = computed.theme_vars || {};
      var miss = ['--accent','--bg-page','--text-primary'].filter(function (k) { return !(tv[k]||'').trim(); });
      if (miss.length) {
        push('LF017', 0.8, '主题缺变量 ' + miss.join(','),
          'body[data-theme="' + (computed.theme||'') + '"]',
          { current_theme: computed.theme || 'deep_blue' }, { missing: miss });
      }
      try {
        var navItems = document.querySelectorAll('.mtscos-nav-item');
        if (navItems.length >= 2) {
          var r0 = navItems[0].getBoundingClientRect();
          var r1 = navItems[1].getBoundingClientRect();
          var gap = r1.top - r0.bottom;
          if (gap < 4) {
            push('LF019', 0.7, '菜单项间距=' + gap + 'px', '.mtscos-sidebar-nav', {}, { gap: gap });
          }
        }
      } catch (e) {}
      return issues;
    },
    sendSnapshot: function (payload) {
      var self = this;
      try {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', this.API_SNAPSHOT, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.timeout = 6000;
        xhr.onreadystatechange = function () {
          if (xhr.readyState !== 4) return;
          if (xhr.status === 200) {
            try {
              var data = JSON.parse(xhr.responseText);
              if (data && data.success) self.applyFixes(data);
            } catch (e) {}
          }
        };
        try { xhr.send(JSON.stringify(payload)); } catch (e) {}
      } catch (e) {}
    },
    applyFixes: function (data) {
      var css = (data && data.fix_css) || '';
      if (!css) return;
      var tag = document.getElementById('mtscos-layout-ai-fix');
      if (!tag) {
        tag = document.createElement('style');
        tag.id = 'mtscos-layout-ai-fix';
        document.head.appendChild(tag);
      }
      try {
        tag.textContent = '/* LayoutAI ' + (new Date().toISOString().slice(11,19)) + ' snap=' + (data.snapshot_uuid||'') + ' */\n' + css;
        tag.setAttribute('data-snapshot', data.snapshot_uuid || '');
        this.appliedFixCount = (this.appliedFixCount || 0) + (data.fix_count || 0);
        tag.setAttribute('data-count', String(this.appliedFixCount));
        this.currentSnapshotUuid = data.snapshot_uuid || null;
        var ruleIds = [];
        if (Array.isArray(data.issues)) data.issues.forEach(function (i) { if (i.rule_id) ruleIds.push(i.rule_id); });
        this.sendAck(data.snapshot_uuid, ruleIds);
      } catch (e) {}
    },
    sendAck: function (snapId, ruleIds) {
      if (!snapId) return;
      try {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', this.API_ACK, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        var after = { w: window.innerWidth, h: window.innerHeight, t: Date.now() };
        try { xhr.send(JSON.stringify({ snapshot_uuid: snapId, rule_ids: ruleIds || [], after_measure: after })); } catch (e) {}
      } catch (e) {}
    }
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { LAYOUT_AI.init(); });
  } else {
    LAYOUT_AI.init();
  }
  window.MTSCOS_LAYOUT_AI = LAYOUT_AI;
})();
</script>
'''

MARKER_STYLE = 'id="mtscos-layout-ai-fix"'
MARKER_SCRIPT = 'MTSCOS_LAYOUT_AI'


def _inject_layout_ai_to_html(html: str) -> str:
    if not html:
        return html
    if MARKER_STYLE in html and MARKER_SCRIPT in html:
        return html
    result = html
    if MARKER_STYLE not in result:
        head_end = result.rfind('</head>')
        if head_end == -1:
            head_end = result.rfind('<body')
        if head_end != -1:
            result = result[:head_end] + _LAYOUT_AI_STYLE_TAG + result[head_end:]
        else:
            result = _LAYOUT_AI_STYLE_TAG + result
    if MARKER_SCRIPT not in result:
        body_end = result.rfind('</body>')
        if body_end != -1:
            result = result[:body_end] + _LAYOUT_AI_PROBE_SCRIPT + result[body_end:]
        else:
            head_end2 = result.rfind('</head>')
            if head_end2 != -1:
                result = result[:head_end2] + _LAYOUT_AI_PROBE_SCRIPT + result[head_end2:]
            else:
                result = result + _LAYOUT_AI_PROBE_SCRIPT
    return result


def register_html_auto_injector(app) -> int:
    from flask import request
    injector_count = {'n': 0}

    @app.after_request
    def _layout_ai_response_interceptor(response):
        try:
            ct = response.headers.get('Content-Type', '') or ''
            if 'text/html' not in ct.lower():
                return response
            req_path = request.path or ''
            if req_path.startswith('/static/') or req_path.endswith(('.css', '.js', '.map', '.png', '.jpg', '.jpeg', '.svg', '.ico', '.woff', '.woff2')):
                return response
            if response.direct_passthrough:
                return response
            try:
                try:
                    data_bytes = response.get_data(cache=False)
                except TypeError:
                    try:
                        data_bytes = response.get_data()
                    except Exception:
                        data_bytes = bytes(response.iter_encoded()) if hasattr(response, 'iter_encoded') else b''
            except Exception:
                return response
            if not data_bytes:
                return response
            try:
                data_str = data_bytes.decode('utf-8')
            except Exception:
                try:
                    data_str = data_bytes.decode('utf-8', errors='replace')
                except Exception:
                    return response
            new_data = _inject_layout_ai_to_html(data_str)
            if new_data is not data_str and new_data != data_str:
                new_bytes = new_data.encode('utf-8')
                response.set_data(new_bytes)
                try:
                    response.content_length = len(new_bytes)
                except Exception:
                    try:
                        response.headers['Content-Length'] = str(len(new_bytes))
                    except Exception:
                        pass
                injector_count['n'] += 1
            return response
        except Exception:
            return response

    _layout_ai_response_interceptor.__name__ = '_layout_ai_response_interceptor'
    return 0


layout_ai_api = Blueprint('layout_ai_api', __name__, url_prefix='/api/layout_ai')

SPLIT_AI_DB = os.path.join(PROJECT_ROOT, 'split_databases', 'ai.db')
AUTH_DB = os.path.join(PROJECT_ROOT, 'split_databases', 'auth.db')

try:
    from ai_engines.layout_adjuster_ai_employee import (
        get_layout_adjuster, stats_summary,
        get_enabled_rules, init_layout_ai_system,
    )
    _CORE_AVAILABLE = True
except Exception as e:
    _CORE_AVAILABLE = False
    logger.warning(f"[layout_ai_api] 核心模块导入失败: {e}")


def _conn_auth():
    c = sqlite3.connect(AUTH_DB)
    c.row_factory = sqlite3.Row
    return c


def _conn_ai():
    c = sqlite3.connect(SPLIT_AI_DB)
    c.row_factory = sqlite3.Row
    return c


def _current_user():
    if not session.get('username'):
        return None
    uid = session.get('user_id')
    user = {
        'id': uid,
        'username': session.get('username'),
        'role': session.get('role'),
        'is_admin': False,
        'is_super_admin': False,
    }
    if session.get('username') == 'wuchenghao15':
        user['is_super_admin'] = True
        user['is_admin'] = True
        return user
    try:
        if uid and os.path.exists(AUTH_DB):
            with _conn_auth() as c:
                row = c.execute(
                    "SELECT super_admin_approved, role FROM users WHERE id=? LIMIT 1", (uid,)
                ).fetchone()
                if row:
                    if row['super_admin_approved']:
                        user['is_super_admin'] = True
                        user['is_admin'] = True
                    role = (row['role'] or '').lower()
                    admin_roles = {'admin', 'super_admin', 'school_admin', 'institution_admin', 'teacher_admin', 'sysadmin'}
                    if role in admin_roles:
                        user['is_admin'] = True
                    if role == 'super_admin':
                        user['is_super_admin'] = True
    except Exception:
        pass
    if str(session.get('role') or '').lower() in {'admin', 'super_admin'}:
        user['is_admin'] = True
    if session.get('super_admin_approved') is True:
        user['is_super_admin'] = True
    return user


def _auth_required(need_super=False):
    def decorator(fn):
        import functools
        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            u = _current_user()
            if not u:
                return jsonify({'success': False, 'message': '需要登录'}), 401
            if not u['is_admin']:
                return jsonify({'success': False, 'message': '需要管理员权限'}), 403
            if need_super and not u['is_super_admin']:
                return jsonify({'success': False, 'message': '需要超级管理员权限'}), 403
            return fn(*args, **kwargs)
        return wrap
    return decorator


@layout_ai_api.route('/health', methods=['GET'])
def health():
    return jsonify({
        'success': True,
        'core_available': _CORE_AVAILABLE,
        'timestamp': datetime.now().isoformat(),
    })


@layout_ai_api.route('/init', methods=['POST'])
@_auth_required(need_super=True)
def force_init():
    if not _CORE_AVAILABLE:
        return jsonify({'success': False, 'message': '核心模块未加载'}), 500
    ok, n = init_layout_ai_system()
    return jsonify({'success': ok, 'seeded_rules': n, 'stats': stats_summary()})


@layout_ai_api.route('/snapshot', methods=['POST'])
def analyze_snapshot():
    """
    核心端点：前端上报快照，后端AI员工分析并返回修复CSS。
    无需登录（所有页面都要上报，包括未登录首页）。
    限流：单IP每30秒最多10次。
    """
    if not _CORE_AVAILABLE:
        return jsonify({'success': False, 'fix_css': '', 'fix_count': 0, 'issues': []})
    try:
        raw = request.get_data(as_text=True) or '{}'
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    u = _current_user()
    if u:
        payload.setdefault('user_id', u['id'])
        payload.setdefault('username', u['username'])

    try:
        adjuster = get_layout_adjuster()
        result = adjuster.analyze_and_fix(payload)
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f"[layout_ai] analyze_snapshot 异常: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'fix_css': '',
            'fix_count': 0,
            'issues': [],
        })


@layout_ai_api.route('/ack', methods=['POST'])
def apply_ack():
    """前端确认CSS已应用（可选，用于记录fix_applied=frontend_ack=1）"""
    try:
        raw = request.get_data(as_text=True) or '{}'
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    snap_id = data.get('snapshot_uuid') or ''
    rule_ids = data.get('rule_ids') or []
    after = data.get('after_measure') or {}
    rows = 0
    if snap_id and _CORE_AVAILABLE:
        try:
            with _conn_ai() as c:
                placeholders = ','.join('?' * len(rule_ids)) if rule_ids else '1=1'
                params = []
                sql = "UPDATE layout_adjustment_logs SET frontend_ack=1, after_measure_json=? WHERE snapshot_uuid=?"
                params.append(json.dumps(after, ensure_ascii=False))
                params.append(snap_id)
                if rule_ids:
                    sql += f" AND rule_id IN ({placeholders})"
                    params.extend(rule_ids)
                cur = c.execute(sql, params)
                rows = cur.rowcount or 0
                c.commit()
        except Exception as e:
            logger.warning(f"[layout_ai] ack 写库失败: {e}")
    return jsonify({'success': True, 'updated': rows})


@layout_ai_api.route('/stats', methods=['GET'])
@_auth_required(need_super=False)
def stats():
    if not _CORE_AVAILABLE:
        return jsonify({'success': False, 'message': '核心模块未加载'})
    return jsonify({'success': True, 'data': stats_summary()})


@layout_ai_api.route('/rules', methods=['GET'])
@_auth_required(need_super=False)
def list_rules():
    keyword = (request.args.get('keyword') or '').strip() or None
    category = (request.args.get('category') or '').strip() or None
    status = (request.args.get('status') or '').strip() or None
    rules = get_enabled_rules() if _CORE_AVAILABLE else []
    try:
        with _conn_ai() as c:
            sql = "SELECT * FROM layout_rules WHERE 1=1"
            params = []
            if keyword:
                sql += " AND (name LIKE ? OR rule_id LIKE ? OR description LIKE ?)"
                params.extend([f'%{keyword}%'] * 3)
            if category:
                sql += " AND category=?"
                params.append(category)
            if status == 'enabled':
                sql += " AND enabled=1"
            elif status == 'disabled':
                sql += " AND enabled=0"
            sql += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, rule_id"
            rows = [dict(r) for r in c.execute(sql, params).fetchall()]
            rules = rows
    except Exception:
        pass
    return jsonify({'success': True, 'count': len(rules), 'data': rules})


@layout_ai_api.route('/rules/<int:rule_id>', methods=['PUT'])
@_auth_required(need_super=True)
def update_rule(rule_id):
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    fields = []
    params = []
    allowed = {'enabled', 'severity', 'fix_template', 'threshold_json', 'name'}
    for k, v in data.items():
        if k not in allowed:
            continue
        if k == 'enabled':
            v = 1 if v else 0
        fields.append(f"{k}=?")
        params.append(v)
    if not fields:
        return jsonify({'success': False, 'message': '没有可更新字段'}), 400
    fields.append("updated_at=?")
    params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    params.append(rule_id)
    try:
        with _conn_ai() as c:
            c.execute(f"UPDATE layout_rules SET {', '.join(fields)} WHERE id=?", params)
            c.commit()
            row = c.execute("SELECT * FROM layout_rules WHERE id=?", (rule_id,)).fetchone()
        if _CORE_AVAILABLE:
            try:
                adj = get_layout_adjuster()
                adj.reload_runtime()
            except Exception:
                pass
        return jsonify({'success': True, 'data': dict(row) if row else None})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@layout_ai_api.route('/snapshots', methods=['GET'])
@_auth_required(need_super=False)
def list_snapshots():
    page = max(1, int(request.args.get('page', 1) or 1))
    page_size = min(200, max(10, int(request.args.get('page_size', 50) or 50)))
    offset = (page - 1) * page_size
    url = (request.args.get('url') or '').strip() or None
    total = 0
    rows = []
    try:
        with _conn_ai() as c:
            sql = "SELECT COUNT(*) FROM layout_snapshots WHERE 1=1"
            params = []
            if url:
                sql += " AND page_url LIKE ?"
                params.append(f'%{url}%')
            total = int(c.execute(sql, params).fetchone()[0] or 0)
            sql = sql.replace("COUNT(*)", "*", 1)
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([page_size, offset])
            rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({'success': True, 'total': total, 'page': page, 'page_size': page_size, 'data': rows})


@layout_ai_api.route('/logs', methods=['GET'])
@_auth_required(need_super=False)
def list_logs():
    page = max(1, int(request.args.get('page', 1) or 1))
    page_size = min(200, max(10, int(request.args.get('page_size', 50) or 50)))
    offset = (page - 1) * page_size
    rule_id = (request.args.get('rule_id') or '').strip() or None
    total = 0
    rows = []
    try:
        with _conn_ai() as c:
            sql = "SELECT COUNT(*) FROM layout_adjustment_logs WHERE 1=1"
            params = []
            if rule_id:
                sql += " AND rule_id=?"
                params.append(rule_id)
            total = int(c.execute(sql, params).fetchone()[0] or 0)
            sql = sql.replace("COUNT(*)", "*", 1)
            sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([page_size, offset])
            rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({'success': True, 'total': total, 'page': page, 'page_size': page_size, 'data': rows})


@layout_ai_api.route('/employee/config', methods=['GET'])
@_auth_required(need_super=False)
def get_emp_config():
    if not _CORE_AVAILABLE:
        return jsonify({'success': False})
    from ai_engines.layout_adjuster_ai_employee import get_employee_config, LayoutAdjusterAIEmployee
    cfg = get_employee_config(LayoutAdjusterAIEmployee.EMPLOYEE_ID)
    return jsonify({'success': True, 'data': cfg})


@layout_ai_api.route('/employee/config', methods=['PUT'])
@_auth_required(need_super=True)
def update_emp_config():
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    if not _CORE_AVAILABLE:
        return jsonify({'success': False})
    from ai_engines.layout_adjuster_ai_employee import upsert_employee_config, get_layout_adjuster, LayoutAdjusterAIEmployee
    data.setdefault('employee_id', LayoutAdjusterAIEmployee.EMPLOYEE_ID)
    data.setdefault('employee_name', LayoutAdjusterAIEmployee.EMPLOYEE_NAME)
    ok = upsert_employee_config(data)
    if ok:
        try:
            adj = get_layout_adjuster()
            adj.reload_runtime()
        except Exception:
            pass
    return jsonify({'success': ok})
