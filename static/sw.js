/* ═══════════════════════════════════════════════════════════════════════
   仙女座沙盘 · PWA Service Worker
   策略: 网络优先 + 运行时缓存静态资源
   ═══════════════════════════════════════════════════════════════════════ */
const SW = 'andromeda-sandbox-v1';
const STATIC = [
  '/static/sandbox-trading-terminal.html',
  '/static/manifest.json',
];

// ── 安装: 预缓存核心文件 ──
self.addEventListener('install', e => {
  e.waitUntil(caches.open(SW).then(c => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

// ── 激活: 清理旧缓存 ──
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== SW).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// ── 拦截: API 网络优先 / 静态缓存优先 ──
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // API 请求 -> 网络优先 (失败才用缓存)
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).then(r => {
        const copy = r.clone();
        caches.open(SW).then(c => c.put(e.request, copy)).catch(()=>{});
        return r;
      }).catch(() => caches.match(e.request).then(r => r || new Response('{"error":"offline"}', {headers:{'Content-Type':'application/json'}})))
    );
    return;
  }

  // 静态 HTML/资源 -> 缓存优先 (后台更新)
  e.respondWith(
    caches.match(e.request).then(cached => {
      const net = fetch(e.request).then(r => {
        if (r.ok && r.type === 'basic') {
          caches.open(SW).then(c => c.put(e.request, r.clone())).catch(()=>{});
        }
        return r;
      }).catch(() => cached);
      return cached || net;
    })
  );
});
