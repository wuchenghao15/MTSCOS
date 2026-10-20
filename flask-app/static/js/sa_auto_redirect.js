/* flow_sa_rejoin_20261020: SA 双钥自动回归公共心跳
 * 适用页面: index 首页 (被踢出后重插钥自动跳回) + admin_app/base.html 全部 admin 页
 * 行为: 不在 /sa/ 区时每 5s 轮询双钥状态; both_present → location.replace('/sa/dashboard')
 *       403/非JSON(302登录跳转) → 停止轮询 (fail-closed, 不打扰普通用户)
 * 服务端: /api/hardware/dual-status?hardware_only=1 仅 loopback 放行 (fail-closed)
 */
(function () {
  if (location.pathname.indexOf('/sa/') === 0) return;  /* 已在 SA 区, 由 sa_dashboard 自有 keepalive 心跳负责 */
  if (window.__MT_SA_REJOIN__) return;                  /* 防重复注入 */
  window.__MT_SA_REJOIN__ = true;

  var _stopped = false;
  var K_REJOIN = 'mt_sa_last_rejoin', K_KICK = 'mt_sa_last_kick';
  function _poll() {
    if (_stopped) return;
    fetch('/api/hardware/dual-status?hardware_only=1', { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 403) { _stopped = true; return null; }   /* 非 loopback/非放行 → 停 */
        var ct = (r.headers.get('content-type') || '');
        if (ct.indexOf('json') === -1) { _stopped = true; return null; }  /* 302→登录页HTML → 停 */
        return r.json();
      })
      .then(function (j) {
        if (!j) return;
        if ((j.both_present || j.both_authenticated) === true) {
          /* flow_sa_loop_20261020: 重入冷却 — 12s 内刚跳过/刚被踢出不再跳, 防乒乓刷屏+限流 */
          var now = Date.now();
          var lastRe = parseInt(sessionStorage.getItem(K_REJOIN) || '0', 10);
          var lastKick = parseInt(sessionStorage.getItem(K_KICK) || '0', 10);
          if (now - lastRe < 12000 || now - lastKick < 12000) { setTimeout(_poll, 8000); return; }
          sessionStorage.setItem(K_REJOIN, String(now));
          location.replace('/sa/dashboard');
          return;
        }
        setTimeout(_poll, 5000);
      })
      .catch(function () { setTimeout(_poll, 8000); });
  }
  setTimeout(_poll, 2000);

  /* 回前台立即检测 (插钥后切回浏览器不用等下一轮) */
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && !_stopped) _poll();
  });
})();
