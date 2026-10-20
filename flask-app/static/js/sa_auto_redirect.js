/* flow_sa_hw_state_20261020: 全页面硬件插入状态机 (实时检测)
 * ================================================================
 * 状态: NONE(无钥) / HALF(单钥=无效) / DUAL(双钥) / DUAL_ARDUINO(双钥+Arduino)
 * 迁移 (用户规则):
 *   - 双密钥有一个插入 → 无效 (HALF, 不产生任何进入动作)
 *   - 双密钥一起插入   → 强制进入 SA 系统 (/sa/dashboard)
 *   - 双钥 + Arduino   → 强制跳转 Arduino 编辑页面 (/admin_app/arduino_ide)
 * 实时: 4s 轮询 dual-status (hardware_only force_refresh); 状态变化 → CustomEvent
 *       'mt-hw-state-change' 广播 (页面可监听) + sessionStorage 留痕
 * 注入面: index.html 冰山主页 + admin_app/base.html 全部 admin 页 + /sa/ 区 (含 SA 面板)
 * 排除: /admin_app/arduino_ide 目标页自身 (防回环), from=sa_denied 权限拒绝落点
 * 安全: 403/非JSON 停轮询; kick/rejoin 12s 重入冷却握手 (flow_sa_loop/jsstop 沿袭)
 */
(function () {
  if (window.__MT_HW_SM__) return;                    /* 防重复注入 */
  if (location.pathname.indexOf('/admin_app/arduino_ide') === 0) return;  /* 目标页防回环 */
  /* flow_sa_hw_state_20261020 FIX: 权限拒绝落点改 30s 冷却 (原永久停会死锁 —
   * 会话重新登录为 SA 后本应恢复自动跳转) */
  var K_DENIED = 'mt_sa_last_denied';
  if (location.search.indexOf('from=sa_denied') !== -1) {
    try { sessionStorage.setItem(K_DENIED, String(Date.now())); } catch (e) {}
  }
  window.__MT_HW_SM__ = true;

  var K_REJOIN = 'mt_sa_last_rejoin', K_KICK = 'mt_sa_last_kick', K_PREV = 'mt_hw_state_prev';
  var _stopped = false;
  var TARGET_ARD = '/admin_app/arduino_ide';
  var TARGET_SA = '/sa/dashboard';

  function _target(state) {
    if (state === 'DUAL_ARDUINO') return TARGET_ARD;   /* 双钥+Arduino → Arduino 编辑页 */
    if (state === 'DUAL') return TARGET_SA;            /* 双钥 → 强制进 SA */
    return null;                                        /* HALF/NONE: 无效, 无动作 */
  }

  function _apply(state, saEntry) {
    var prev = sessionStorage.getItem(K_PREV) || '';
    /* 实时状态变化广播 (所有页面可监听: window.addEventListener('mt-hw-state-change', e => e.detail.state)) */
    if (state !== prev) {
      sessionStorage.setItem(K_PREV, state);
      window.MT_HW_STATE = state;
      try { window.dispatchEvent(new CustomEvent('mt-hw-state-change', { detail: { from: prev, to: state } })); } catch (e) {}
      if (window.console && console.info) console.info('[MT-HW-SM]', prev || '(init)', '→', state);
    }
    window.MT_HW_STATE = state;

    var tgt = _target(state);
    if (!tgt) return;                                   /* HALF 单钥无效 / NONE 无动作 */

    /* flow_sa_hw_state_20261020 FIX: sa_entry 门禁 — 服务端明确该会话不可进 SA(非SA用户)
     * 时不跳, 防 非SA→SA守卫弹回→再推 的乒乓 */
    if (saEntry === false) return;

    /* 重入冷却 (12s): 刚跳过/刚被踢出不跳, 防乒乓 (flow_sa_loop_20261020) */
    var now = Date.now();
    var lastRe = parseInt(sessionStorage.getItem(K_REJOIN) || '0', 10);
    var lastKick = parseInt(sessionStorage.getItem(K_KICK) || '0', 10);
    if (now - lastRe < 12000 || now - lastKick < 12000) return;
    /* 权限拒绝 30s 冷却 (非永久停, 允许重新登录后恢复) */
    var lastDenied = parseInt(sessionStorage.getItem(K_DENIED) || '0', 10);
    if (now - lastDenied < 30000) return;
    /* 已在目标页不跳 */
    if (location.pathname === tgt) return;
    sessionStorage.setItem(K_REJOIN, String(now));
    location.replace(tgt);
  }

  function _poll() {
    if (_stopped) return;
    fetch('/api/hardware/dual-status?hardware_only=1', { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 403) { _stopped = true; return null; }        /* 非放行 → 停 */
        var ct = (r.headers.get('content-type') || '');
        if (ct.indexOf('json') === -1) { _stopped = true; return null; } /* 302→HTML → 停 */
        return r.json();
      })
      .then(function (j) {
        if (!j) return;
        /* 服务端 hw_state 权威; 老响应兜底用布尔推导 */
        var state = j.hw_state;
        if (!state) {
          var vp = j.vikey_present === true, sp = j.szu100_present === true;
          var ard = j.arduino_present === true;
          state = (vp && sp) ? (ard ? 'DUAL_ARDUINO' : 'DUAL') : (vp || sp ? 'HALF' : 'NONE');
        }
        _apply(state, j.sa_entry);
        setTimeout(_poll, 4000);
      })
      .catch(function () { setTimeout(_poll, 8000); });
  }

  setTimeout(_poll, 1500);
  /* 回前台立即检测 (插拔后切回不用等下一轮) */
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && !_stopped) _poll();
  });
})();
