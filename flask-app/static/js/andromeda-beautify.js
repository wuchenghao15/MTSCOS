/* ╔══════════════════════════════════════════════════════════════╗
 * ║     仙女座自动美化页面引擎 · Andromeda Beautify Engine         ║
 * ║  渐进增强 · 纯原生 JS · <3KB · 与冰山极简风格共存             ║
 * ╚══════════════════════════════════════════════════════════════╝
 * 工作原理:
 *  ① 自动识别页面关键节点 (冰山横幅/佛教/登录卡/AI生态)
 *  ② 扫描 data-andromeda-reveal / glow / elevate 属性
 *  ③ IntersectionObserver → 滚动揭示入场动画
 *  ④ requestAnimationFrame → 入场级联 stagger
 *  ⑤ MutationObserver → 动态插入元素自动增强
 * 约束:
 *  - 纯 CSS class toggle, 不修改 inline style
 *  - JS 加载失败 → 页面照常可用 (fail-closed)
 *  - 已有 CSS keyframes 共存 (pulse/nebula/iceberg-spectrum...)
 */
(function(){
'use strict';

// ── 配置 ──
var CFG = {
    revealClass: 'andromeda-reveal',
    revealActive: 'andromeda-reveal-active',
    staggerMs: 80,         // 级联延迟
    threshold: 0.15,       // Intersection 阈值
    rootMargin: '0px 0px -40px 0px',
    autoSelectors: [       // 自动识别的关键节点 (无需 data 属性)
        // ── 冰山 index.html 专属 ──
        '.iceberg-intro', '.mts-buddhist', '.mts-eco', '.mts-login-wrap', '.mts-top',
        // ── 全站通用卡片/面板 ──
        '.card', '.panel', '.box', '.widget', '.tile',
        '.admin-card', '.dashboard-card', '.stat-card', '.info-card', '.data-card',
        '.feature-card', '.content-card', '.chart-card', '.list-card',
        '[class*="-card"]', '[class*="-panel"]', '[class*="-box"]',
        '[class*="Card"]', '[class*="Panel"]', '[class*="Box"]',
        // ── 全站通用容器 ──
        'main section', 'main > div[class*="container"]',
        '.page-header', '.content-header', '.section-title', '.breadcrumb',
        // ── 侧边栏/导航 ──
        '.sidebar a.active', '.side-nav a.active',
        // ── 表格 ──
        'table thead th', 'table tbody tr:not(.no-theme)',
        // ── 表单 ──
        'form:not(.no-beautify) .field', 'form:not(.no-beautify) .form-group',
        // ── 按钮 ──
        'button[type="submit"]:not(.no-beautify)',
        '.btn-primary:not(.no-beautify)',
        '.btn-success:not(.no-beautify)'
    ]
};

// ── 注入 andromeda-reveal CSS (如果外部没加载) ──
function injectRevealCSS() {
    if (document.getElementById('andromeda-reveal-css')) return;
    var s = document.createElement('style');
    s.id = 'andromeda-reveal-css';
    s.textContent = [
        '.andromeda-reveal {',
        '  opacity: 0;',
        '  transform: translateY(16px);',
        '  transition: opacity .6s cubic-bezier(.22,1,.36,1), transform .6s cubic-bezier(.22,1,.36,1);',
        '  will-change: opacity, transform;',
        '}',
        '.andromeda-reveal.andromeda-reveal-active {',
        '  opacity: 1;',
        '  transform: translateY(0);',
        '}',
        '.andromeda-glow {',
        '  transition: box-shadow .4s, border-color .4s;',
        '}',
        '.andromeda-glow:hover {',
        '  box-shadow: 0 0 0 3px rgba(139,92,246,.12), 0 8px 28px -8px rgba(99,102,241,.22);',
        '}',
        '.andromeda-elevate {',
        '  transition: transform .35s cubic-bezier(.22,1,.36,1), box-shadow .35s;',
        '}',
        '.andromeda-elevate:hover {',
        '  transform: translateY(-2px);',
        '  box-shadow: 0 10px 32px -12px rgba(11,31,58,.18);',
        '}',
        // 减少动效偏好降级 (可访问性)
        '@media (prefers-reduced-motion: reduce) {',
        '  .andromeda-reveal { opacity:1 !important; transform:none !important; transition:none !important; }',
        '  .andromeda-elevate:hover { transform:none !important; }',
        '}'
    ].join('');
    document.head.appendChild(s);
}

// ── 给目标节点加 reveal class ──
function markElements(root) {
    root = root || document;
    var targets = [];

    // 1. 显式 data-andromeda-reveal 属性
    root.querySelectorAll('[data-andromeda-reveal]').forEach(function(el){
        targets.push(el);
    });

    // 2. 自动识别关键节点
    CFG.autoSelectors.forEach(function(sel){
        root.querySelectorAll(sel).forEach(function(el){
            if (!el.classList.contains(CFG.revealClass)) targets.push(el);
        });
    });

    // 3. 给 AI 生态数字加 glow
    root.querySelectorAll('[data-andromeda-glow]').forEach(function(el){
        el.classList.add('andromeda-glow');
    });
    root.querySelectorAll('.eco-num, .eco-label').forEach(function(el){
        el.classList.add('andromeda-glow');
    });

    // 4. 登录卡 elevate
    root.querySelectorAll('.mts-login').forEach(function(el){
        el.classList.add('andromeda-elevate');
    });

    // 去重 + 打 class + 设置 stagger 延迟
    var seen = new WeakSet();
    var idx = 0;
    targets.forEach(function(el){
        if (seen.has(el)) return;
        seen.add(el);
        el.classList.add(CFG.revealClass);
        el.style.setProperty('--andromeda-delay', (idx * CFG.staggerMs) + 'ms');
        idx++;
    });

    return targets;
}

// ── IntersectionObserver 滚动揭示 ──
var observer = null;
function createObserver() {
    if ('IntersectionObserver' in window) {
        observer = new IntersectionObserver(function(entries){
            entries.forEach(function(entry){
                if (entry.isIntersecting) {
                    var el = entry.target;
                    var delay = parseInt(el.style.getPropertyValue('--andromeda-delay')) || 0;
                    setTimeout(function(){
                        el.classList.add(CFG.revealActive);
                    }, delay);
                    observer.unobserve(el);
                }
            });
        }, {
            threshold: CFG.threshold,
            rootMargin: CFG.rootMargin
        });
    }
}

// ── MutationObserver 监听动态插入 ──
function watchMutations() {
    if ('MutationObserver' in window) {
        var mo = new MutationObserver(function(mutations){
            mutations.forEach(function(m){
                m.addedNodes.forEach(function(node){
                    if (node.nodeType === 1 && node.querySelectorAll) {
                        var targets = markElements(node);
                        targets.forEach(function(t){ if (observer) observer.observe(t); });
                    }
                });
            });
        });
        mo.observe(document.body, { childList: true, subtree: true });
    }
}

// ── 入场动画 (首屏立即播放, 不等滚动) ──
function entranceSweep() {
    requestAnimationFrame(function(){
        var els = document.querySelectorAll('.' + CFG.revealClass);
        els.forEach(function(el){
            var rect = el.getBoundingClientRect();
            if (rect.top < window.innerHeight * 1.2) {
                var delay = parseInt(el.style.getPropertyValue('--andromeda-delay')) || 0;
                setTimeout(function(){
                    el.classList.add(CFG.revealActive);
                }, delay);
            } else if (observer) {
                observer.observe(el);
            }
        });
    });
}

// ── 🌌 仙女座深度绑定: 实时数据轮询 ──
// 30s setTimeout 循环 (非 setInterval, 防请求堆积)
// document.hidden 时跳过 (省资源)
// fail-closed: 网络错不影响现有 DOM
var _pollTimer = null, _pollLoading = false;
function startPolling() {
    var INTERVAL = 30000; // 30s
    var POLL_URL = '/api/andromeda/state'; // 完整端点 (health 端点被 Ollama 路由抢占)
    function tick() {
        _pollTimer = setTimeout(tick, INTERVAL);
        if (document.hidden) return;
        if (_pollLoading) return;
        _pollLoading = true;
        fetch(POLL_URL, { cache: 'no-store' })
            .then(function(r){ return r.ok ? r.json() : null; })
            .then(function(resp){
                _pollLoading = false;
                var data = resp && resp.data ? resp.data : resp; // 兼容两种格式
                if (!data || !data.health) return;
                // ── 刷新 daemon 健康度条 ──
                document.querySelectorAll('.health-fill').forEach(function(el){
                    el.style.width = (data.daemon_pct || 0) + '%';
                    el.classList.remove('medium','low');
                    if (data.daemon_pct < 60) el.classList.add('low');
                    else if (data.daemon_pct < 90) el.classList.add('medium');
                });
                // ── 刷新健康度状态文字 ──
                document.querySelectorAll('.hl-status').forEach(function(el){
                    el.classList.remove('ok','warn','crit');
                    el.classList.add(data.health || 'ok');
                    el.textContent = (data.daemon_running || 0) + '/' + (data.daemon_total || 0) + ' · ' + (data.daemon_pct || 0) + '%';
                });
                // ── 刷新顶栏绿点 (ok=亮, warn=脉动, crit=红) ──
                document.querySelectorAll('.mts-status .dot, .sa-status-dot').forEach(function(el){
                    el.classList.remove('dot-warn','dot-crit');
                    if (data.health === 'warn') el.classList.add('dot-warn');
                    else if (data.health === 'crit') el.classList.add('dot-crit');
                });
                // ── 刷新顶栏 DAEMON 计数 ──
                document.querySelectorAll('[class*="cnt-daemon"], .daemon-count').forEach(function(el){
                    el.textContent = (data.daemon_running || 0) + '/' + (data.daemon_total || 0);
                });
                // 广播 (其他模块可监听)
                try { document.dispatchEvent(new CustomEvent('andromeda:state', {detail: data})); } catch(e){}
            })
            .catch(function(){ _pollLoading = false; }); // fail-closed
    }
    tick(); // 立即开始第一次
}

// ── 初始化 ──
function init() {
    try {
        injectRevealCSS();
        createObserver();
        markElements(document);
        entranceSweep();
        watchMutations();
        startPolling();
        // 暴露到 window (调试用)
        window.AndromedaBeautify = {
            version: '1.0.0',
            rescan: function(){ markElements(document); entranceSweep(); },
            config: CFG
        };
    } catch (e) {
        // fail-closed: 任何 JS 错误都不影响页面
        console.warn('[AndromedaBeautify] degraded:', e.message);
    }
}

// ── 启动 ──
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
} else {
    init();
}

})();
