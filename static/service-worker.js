// MTSCOS PWA Service Worker v1.0.0
const CACHE_NAME = 'mtscos-v1.0.0';
const STATIC_ASSETS = [
    '/mobile/home',
    '/mobile/login',
    '/static/css/_theme_tokens_source.css',
    '/assets/font-awesome/css/all.min.css'
];

// 安装：预缓存核心资源
self.addEventListener('install', function(e) {
    e.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return cache.addAll(STATIC_ASSETS).catch(function(err) {
                console.warn(window.t('auto.service-worker.swx__3063b011') || 'SW预缓存失败:', err);
            });
        }).then(function() {
            return self.skipWaiting();
        })
    );
});

// 激活：清理旧缓存
self.addEventListener('activate', function(e) {
    e.waitUntil(
        caches.keys().then(function(names) {
            return Promise.all(
                names.filter(function(name) { return name !== CACHE_NAME; })
                     .map(function(name) { return caches.delete(name); })
            );
        }).then(function() {
            return self.clients.claim();
        })
    );
});

// 拦截请求：缓存优先，网络回退
self.addEventListener('fetch', function(e) {
    var url = new URL(e.request.url);

    // 仅缓存同源GET请求
    if (e.request.method !== 'GET' || url.origin !== location.origin) {
        return e.respondWith(fetch(e.request));
    }

    // API请求：网络优先
    if (url.pathname.startsWith('/api/')) {
        return e.respondWith(
            fetch(e.request).catch(function() {
                return caches.match(e.request);
            })
        );
    }

    // 页面请求：网络优先，缓存回退
    if (e.request.mode === 'navigate' || e.request.headers.get('accept')?.includes('text/html')) {
        return e.respondWith(
            fetch(e.request).then(function(resp) {
                var clone = resp.clone();
                caches.open(CACHE_NAME).then(function(cache) { cache.put(e.request, clone); });
                return resp;
            }).catch(function() {
                return caches.match(e.request).then(function(cached) {
                    return cached || caches.match('/mobile/home');
                });
            })
        );
    }

    // 静态资源：缓存优先
    e.respondWith(
        caches.match(e.request).then(function(cached) {
            return cached || fetch(e.request).then(function(resp) {
                if (resp.status === 200) {
                    var clone = resp.clone();
                    caches.open(CACHE_NAME).then(function(cache) { cache.put(e.request, clone); });
                }
                return resp;
            });
        })
    );
});
