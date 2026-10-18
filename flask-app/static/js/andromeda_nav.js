/*
 * andromeda_nav.js — 冰山系统统一侧边导航 (自包含: 样式内联, 零依赖)
 * ================================================================
 * flow_integration_20261018 · v1.1.0
 *
 * 注入方式二选一:
 *   1. Flask after_request 自动注入 (server_real_db.py, 全站 184 页生效)
 *   2. 手动: <script src="/static/js/andromeda_nav.js"></script>
 *
 * 幂等: window.__ANDROMEDA_NAV_MOUNTED__ 防重复挂载
 * 孤岛清零: 覆盖入口/冰山/Aurora/知识/天团/治理/系统 全部功能页
 */
(function(){
  'use strict';
  if (window.__ANDROMEDA_NAV_MOUNTED__) return;
  window.__ANDROMEDA_NAV_MOUNTED__ = true;

  var NAV_ITEMS = [
    { group:'🏠 入口', items:[
      { id:'home',        label:'冰山主页',        href:'/index',                        icon:'🏔️' },
      { id:'hub',         label:'仙女座总枢纽',    href:'/andromeda/hub',                icon:'🪐' },
      { id:'ai-chat',     label:'AI 聊天入口',     href:'/ai',                           icon:'💬' },
      { id:'dashboard',   label:'仙女座仪表盘',    href:'/andromeda/dashboard',          icon:'🎛️' },
    ]},
    { group:'🧊 冰山', items:[
      { id:'iceberg-center', label:'冰山控制中心', href:'/andromeda/iceberg_center',     icon:'🧊' },
      { id:'evolution',   label:'演化时间线',      href:'/andromeda/iceberg_evolution',  icon:'📜' },
      { id:'collapse',    label:'坍缩定理',        href:'/andromeda/collapse_theorem',   icon:'⚓' },
      { id:'meta',        label:'冰山元数据',      href:'/andromeda/iceberg_meta',       icon:'📋' },
    ]},
    { group:'✨ Aurora', items:[
      { id:'aurora',      label:'极光注册表',      href:'/aurora/center',                icon:'✨' },
      { id:'empower',     label:'AI 员工赋能',     href:'/empower/center',               icon:'🤖' },
      { id:'gray',        label:'灰度发布中心',    href:'/andromeda/gray_center',        icon:'🌗' },
    ]},
    { group:'🧠 知识', items:[
      { id:'brain',       label:'知识脑库',        href:'/andromeda/knowledge_brain',    icon:'🧠' },
      { id:'graph',       label:'知识图谱',        href:'/andromeda/knowledge_graph',    icon:'🕸️' },
      { id:'chat',        label:'AI 人格聊天室',   href:'/andromeda/persona_chat',       icon:'🗨️' },
      { id:'wenquxing',   label:'文曲星教辅',      href:'/andromeda/wenquxing',          icon:'📖' },
    ]},
    { group:'👥 EigenFlux', items:[
      { id:'eigenflux',   label:'EigenFlux 交流',  href:'/andromeda/eigenflux_council',  icon:'👥' },
      { id:'ef-center',   label:'EigenFlux 中心',  href:'/admin_app/eigenflux_center',   icon:'🌐' },
      { id:'team',        label:'AI 团队中枢',     href:'/admin_app/ai_team_hub',        icon:'🏢' },
    ]},
    { group:'🧩 治理中心', items:[
      { id:'devflow',     label:'§14 开发流程',    href:'/admin_app/dev_flow_dashboard', icon:'🔀' },
      { id:'brainbank',   label:'脑库浏览器',      href:'/admin_app/brain_bank_explorer',icon:'💾' },
      { id:'neural',      label:'神经网络矩阵',    href:'/admin_app/neural_array_matrix',icon:'🧿' },
      { id:'errors',      label:'错误异常处理中心', href:'/error-center',                icon:'🚑' },
      { id:'theme',       label:'主题排版研究中心', href:'/theme-layout/center',         icon:'🎨' },
    ]},
    { group:'🛡️ 系统', items:[
      { id:'health',      label:'健康度仪表盘',    href:'/andromeda/health_board',       icon:'🩺' },
      { id:'upgrade',     label:'升级报告',        href:'/andromeda/upgrade_board',      icon:'📊' },
      { id:'stats',       label:'系统统计',        href:'/andromeda/stats',              icon:'📈' },
    ]},
  ];

  /* ── 当前路径 → active 项 (最长前缀匹配) ── */
  var curPath = location.pathname;
  var active = null, bestLen = 0;
  NAV_ITEMS.forEach(function(g){ g.items.forEach(function(it){
    if (curPath.indexOf(it.href) === 0 && it.href.length > bestLen){ active = it; bestLen = it.href.length; }
  });});

  /* ── 内联样式 (自包含) ── */
  var css = [
    '.andromeda-sidebar{position:fixed;left:0;top:0;bottom:0;width:212px;background:rgba(11,16,32,.94);',
    'border-right:1px solid rgba(99,102,241,.18);backdrop-filter:blur(14px);z-index:9800;',
    'overflow-y:auto;padding:14px 0 90px;font-size:13px;transition:transform .25s;}',
    '.andromeda-sidebar.collapsed{transform:translateX(-100%);}',
    '.as-header{padding:6px 16px 12px;border-bottom:1px solid rgba(99,102,241,.15);margin-bottom:8px;}',
    '.as-logo{font-size:26px;line-height:1;}',
    '.as-title{font-weight:700;color:#e8edf7;margin-top:4px;}',
    '.as-sub{color:#64748b;font-size:11px;}',
    '.as-group-title{color:#64748b;font-size:11px;padding:10px 16px 4px;letter-spacing:.06em;}',
    '.as-item{display:flex;align-items:center;gap:9px;padding:7px 16px;color:#cbd5e1;text-decoration:none;}',
    '.as-item:hover{background:rgba(99,102,241,.12);color:#fff;}',
    '.as-item.active{background:rgba(99,102,241,.22);color:#fff;border-right:2px solid #6366f1;}',
    '.as-icon{width:18px;text-align:center;}',
    '.as-footer{position:absolute;bottom:14px;left:0;right:0;padding:10px 16px;color:#475569;font-size:11px;}',
    '.as-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#22c55e;margin-right:6px;}',
    '.as-link{color:#64748b;text-decoration:none;}',
    '.andromeda-crumb{position:fixed;top:0;left:0;right:0;height:0;z-index:9790;}',
    '.as-toggle{position:fixed;left:10px;bottom:12px;z-index:9900;width:40px;height:40px;border-radius:50%;',
    'border:1px solid rgba(99,102,241,.35);background:rgba(11,16,32,.9);color:#a5b4fc;font-size:18px;cursor:pointer;}',
    'body.andromeda-has-nav{padding-left:212px;}',
    'body.andromeda-has-nav.nav-collapsed{padding-left:0;}',
    '@media(max-width:900px){body.andromeda-has-nav{padding-left:0;}',
    '.andromeda-sidebar{transform:translateX(-100%);}body.andromeda-has-nav.nav-open .andromeda-sidebar{transform:none;}}'
  ].join('');

  function mount(){
    if (!document.body) { setTimeout(mount, 60); return; }

    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    var side = document.createElement('aside');
    side.className = 'andromeda-sidebar';
    side.innerHTML =
      '<div class="as-header"><div class="as-logo">🪐</div><div class="as-title">仙女座</div>' +
      '<div class="as-sub">冰山功能导航 v1.1</div></div>' +
      NAV_ITEMS.map(function(g){
        return '<div class="as-group"><div class="as-group-title">' + g.group + '</div>' +
          g.items.map(function(it){
            return '<a class="as-item ' + (active && active.id === it.id ? 'active' : '') +
              '" href="' + it.href + '"><span class="as-icon">' + it.icon +
              '</span><span class="as-label">' + it.label + '</span></a>';
          }).join('') + '</div>';
      }).join('') +
      '<div class="as-footer"><span class="as-dot"></span>Flask SERVER · <a class="as-link" href="/index">回主页</a></div>';

    var crumb = document.createElement('nav');
    crumb.className = 'andromeda-crumb';

    var toggle = document.createElement('button');
    toggle.className = 'as-toggle';
    toggle.title = '展开/收起导航';
    toggle.innerHTML = '🪐';
    toggle.addEventListener('click', function(){
      document.body.classList.toggle('nav-collapsed');
      side.classList.toggle('collapsed');
      document.body.classList.toggle('nav-open');
    });

    document.body.insertBefore(side, document.body.firstChild);
    document.body.appendChild(toggle);
    document.body.classList.add('andromeda-has-nav');
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
