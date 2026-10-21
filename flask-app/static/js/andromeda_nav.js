/* ===========================================================
   仙女座统一导航组件 · 共享 JS (flow_andromeda_chat_20261021)
   侧边栏 + 面包屑 + 底部快捷栏, 依赖 /static/css/andromeda_nav.css
   NI 增补: 🪐 总枢纽(/andromeda/hub) + 🤖 本地AI聊天(/local-chat)
   =========================================================== */
(function(){
var NI=[["🏠 入口",[{id:"home",label:"冰山主页",href:"/index",icon:"🏔️"},{id:"center",label:"控制中心",href:"/andromeda/iceberg_center",icon:"🧊"},{id:"dashboard",label:"仪表盘",href:"/andromeda/dashboard",icon:"🎛️"},{id:"hub",label:"总枢纽",href:"/andromeda/hub",icon:"🪐"}]],["🧊 冰山",[{id:"evolution",label:"演化时间线",href:"/andromeda/iceberg_evolution",icon:"📜"},{id:"collapse",label:"坍缩定理",href:"/andromeda/collapse_theorem",icon:"⚓"}]],["🧠 知识",[{id:"brain",label:"知识脑库",href:"/andromeda/knowledge_brain",icon:"🧠"},{id:"graph",label:"知识图谱",href:"/andromeda/knowledge_graph",icon:"🕸️"},{id:"chat",label:"AI 人格聊天室",href:"/andromeda/persona_chat",icon:"💬"},{id:"aichat",label:"本地AI聊天",href:"/local-chat",icon:"🤖"}]],["👥 天团",[{id:"eigenflux",label:"EigenFlux 矩阵",href:"/andromeda/eigenflux_council",icon:"👥"}]],["🛡️ 系统",[{id:"health",label:"健康度仪表盘",href:"/andromeda/health_board",icon:"🩺"},{id:"upgrade",label:"升级报告",href:"/andromeda/upgrade_board",icon:"📊"}]]];
var CP=location.pathname,FA=null,BL=0;
NI.forEach(g=>g.items.forEach(it=>{if(CP.startsWith(it.href)&&it.href.length>BL){FA=it;BL=it.href.length}}));
if(!FA&&(CP==="/iceberg"||CP==="/andromeda"))FA=NI[0].items[1];
var side=document.createElement("aside");side.className="andromeda-sidebar";
side.innerHTML='<div class="as-header"><div class="as-logo">🪐</div><div class="as-title">仙女座</div><div class="as-sub">Andromeda v22.1</div></div>'+NI.map(g=>'<div class="as-group"><div class="as-group-title">'+g.group+'</div>'+g.items.map(it=>'<a class="as-item '+(FA&&FA.id===it.id?"active":"")+'" href="'+it.href+'"><span class="as-icon">'+it.icon+'</span><span class="as-label">'+it.label+'</span></a>').join("")+"</div>").join("")+'<div class="as-footer"><div class="as-status"><span class="as-dot"></span><span>Flask 8888</span></div><a class="as-link" href="/api/sync/health" target="_blank">Sync 状态</a></div>';
var crumb=document.createElement("nav");crumb.className="andromeda-crumb";
crumb.innerHTML='<a href="/andromeda/iceberg_center">🧊 仙女座</a>'+(FA?' › <span>'+FA.label+'</span>':"")+'<a href="/index" class="crumb-home">🏠 回主页</a>';
var bot=document.createElement("nav");bot.className="andromeda-bottom";
bot.innerHTML=NI.flatMap(g=>g.items).map(it=>'<a href="'+it.href+'" class="'+(FA&&FA.id===it.id?"active":"")+'"><span>'+it.icon+'</span><b>'+it.label+'</b></a>').join("");
if(document.body){document.body.insertBefore(side,document.body.firstChild);document.body.insertBefore(crumb,document.body.children[1]||document.body.firstChild);document.body.appendChild(bot);document.body.classList.add("andromeda-has-nav")}
})();
