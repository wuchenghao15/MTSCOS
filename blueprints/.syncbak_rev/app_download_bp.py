#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
APP 下载中心 — 官网公开下载页
================================
flow_app_download_20261031 · flow_download_client_20261031 (五平台细分重构)

定位:
  官网唯一公开下载入口 — 全平台安装引导 + 原生客户端安装包下载:
    Android (Chrome/Edge)  → 原生 APK 下载 (WebView 壳·已签名, TH-20261031-0797) + PWA 安装
    iOS / iPadOS (Safari)  → 添加到主屏幕 (正式形态) + IPA 受苹果证书硬约束留痕 (TH-20261031-0797)
    Windows 10/11 x64      → NSIS 真 Setup.exe 安装器 + PWA 安装
    Mac Apple Silicon      → 真原生 .dmg 安装镜像 (.app, M1/M2/M3/M4) + PWA 安装
    Mac Intel              → 真原生 .dmg 安装镜像 (.app) + PWA 安装
  服务端扫描 static/clients/ 实际文件 → 「立即下载 / 开发中(已入大厅)」动态状态。
  冒烟检测定案 (2026-10-31): 旧三壳包 = 脚本跳转启动器非原生包 → 全部退役, 真包由
  大厅单 TH-20261031-0797 (flow_native_packages_20261031) 开发交付。

路由:
  GET /download                     下载中心页 (公开, 防盗链白名单放行)
  GET /api/app-download/info        下载信息 JSON (版本/入口/服务器/授权层/原生包状态)
  GET /download/client/<文件名>      原生安装包下载 (send_from_directory 防穿越)

关联:
  小龙 App 本体: /xiaolong (blueprints/xiaolong_app_bp.py, v22.25.42)
  游客畅聊入口: /ai
"""
from __future__ import annotations

import json
import os

from flask import Blueprint, Response, jsonify, send_from_directory

FLOW_ID = 'flow_app_download_20261031'
HALL_FLOW_ID = 'flow_native_packages_20261031'
APP_NAME = '小龙'
APP_VERSION = 'v22.25.42'
HALL_CODE = 'TH-20261031-0797'   # 真原生安装包开发单 (大厅 id=7565, 冒烟检测后立项)
HALL_ID = 7565

app_download_bp = Blueprint('app_download_bp', __name__)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENTS_DIR = os.path.join(_APP_DIR, 'static', 'clients')

# ── 全平台安装包清单: file 在 static/clients/ 实际存在 → 可下载; 否则 → 在研(已入大厅) ──
CLIENTS_SPEC = [
    {'key': 'windows-x64', 'file': 'MTSCOS-Xiaolong-Setup-win-x64.exe',
     'label': '🪟 Windows', 'sub': 'Windows 10/11 · x64 · NSIS 安装器'},
    {'key': 'mac-arm', 'file': 'MTSCOS-Xiaolong-mac-apple-silicon.dmg',
     'label': '💻 Mac · M 芯', 'sub': 'Apple Silicon M1/M2/M3/M4 · .dmg 镜像'},
    {'key': 'mac-intel', 'file': 'MTSCOS-Xiaolong-mac-intel.dmg',
     'label': '💻 Mac · Intel', 'sub': 'Intel 芯片 MacBook / iMac · .dmg 镜像'},
    {'key': 'android-apk', 'file': 'MTSCOS-Xiaolong-android.apk',
     'label': '📱 Android', 'sub': 'Android 8+ 原生 APK · WebView 壳'},
    {'key': 'ios-ipa', 'file': 'MTSCOS-Xiaolong-ios.ipa',
     'label': '🍎 iOS', 'sub': 'iOS 15+ 原生 IPA'},
]

# 真包形态文案 (available=True 时 info API / 页面展示)
_FORM_BY_KEY = {
    'windows-x64': '原生安装器 (NSIS Setup.exe · 向导+卸载)',
    'mac-arm': '原生 .dmg 安装镜像 (真 .app 拖装)',
    'mac-intel': '原生 .dmg 安装镜像 (真 .app 拖装)',
    'android-apk': '原生 APK (WebView 壳 · 已签名)',
    'ios-ipa': 'PWA 即正式形态 · IPA 挂苹果证书阻塞',
}


def _scan_clients():
    """扫描包目录 → 各平台交付状态 (exists/size/download url)"""
    out = []
    for spec in CLIENTS_SPEC:
        p = os.path.join(_CLIENTS_DIR, spec['file'])
        exists = os.path.isfile(p)
        out.append({
            **spec,
            'available': exists,
            'size': os.path.getsize(p) if exists else 0,
            'download': f'/download/client/{spec["file"]}' if exists else '',
            'form': _FORM_BY_KEY.get(spec['key'], '原生安装包') if exists
                    else 'PWA 即正式形态 · 原生包缺位(大厅留痕)',
            'hall_code': '' if exists else HALL_CODE,
        })
    return out


# ────────────────────────── 信息 API ──────────────────────────
@app_download_bp.route('/api/app-download/info', methods=['GET'])
def app_download_info():
    from datetime import datetime
    return jsonify({
        'success': True,
        'app': {
            'name': APP_NAME, 'slug': 'xiaolong', 'version': APP_VERSION,
            'form': 'PWA (免商店 · 免安装包 · 自动更新) + 全平台原生安装包',
            'description': '仙女座 AI 冰山专用聊天 App — 手机桌面图标直达, 全屏沉浸体验',
        },
        'install': {
            'page': '/download', 'app_entry': '/xiaolong', 'guest_entry': '/ai',
            'manifest': '/xiaolong/manifest', 'sw': '/xiaolong/sw.js',
            'icon': '/xiaolong/icon.svg',
            'modules': [{
                'key': 'archive_hall', 'name': '移动端历史档案馆',
                'entry': '/xiaolong/archive', 'manual': '/xiaolong/archive/manual',
                'desktop_entry': '/andromeda/archive', 'auth': 'login_or_xl_token',
                'description': '7 类历史档案跨库聚合 · 更新及时档案墙 (30s 巡检) · 统一时间线/检索/详情',
                'flow_id': 'flow_mobile_archive_20261031',
            }],
        },
        'native_packages': _scan_clients(),
        'hall_ref': {'flow_id': HALL_FLOW_ID, 'hall_code': HALL_CODE, 'hall_id': HALL_ID,
                     'note': '冒烟检测定案: 旧壳包=脚本跳转非原生包 → 真原生包开发单 (Mac dmg/Win NSIS/APK 已交付, IPA 苹果证书硬阻塞留痕)'},
        'servers': [
            {'key': 'public', 'label': '公网 (全球可达)', 'base': 'https://mtos.site', 'priority': 1},
            {'key': 'tailscale', 'label': 'Tailscale 直连', 'base': 'http://100.106.220.96:8888', 'priority': 2},
            {'key': 'same_origin', 'label': '当前入口 (同源)', 'base': '', 'priority': 3},
            {'key': 'lan', 'label': '局域网 (同网段)', 'base': 'http://192.168.31.9:8888', 'priority': 4},
        ],
        'auth_layers': ['L1 登录授权 (session)', 'L2 设备授权 (device_license)', 'L3 API Token (X-XL-Token)'],
        'guest_mode': True,
        'flow_id': FLOW_ID,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })


# ────────────────────────── 原生安装包下载 ──────────────────────────
@app_download_bp.route('/download/client/<path:fname>', methods=['GET'])
def download_client_file(fname: str):
    """原生安装包下载 — send_from_directory 防目录穿越; 缺包返回 404 JSON(含大厅单号)"""
    ok = any(s['file'] == fname for s in CLIENTS_SPEC) and os.path.isfile(os.path.join(_CLIENTS_DIR, fname))
    if not ok:
        return jsonify({'success': False, 'error': 'package_not_available',
                        'file': fname, 'status': 'IN_HALL_DEVELOPING',
                        'hall_code': HALL_CODE, 'hall_flow_id': HALL_FLOW_ID}), 404
    return send_from_directory(_CLIENTS_DIR, fname, as_attachment=True)


# ────────────────────────── 下载中心页 ──────────────────────────
_DOWNLOAD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b1020">
<title>小龙 App 下载中心 · MTSCOS 冰山系统</title>
<link rel="manifest" href="/xiaolong/manifest">
<link rel="icon" href="/xiaolong/icon.svg" type="image/svg+xml">
<style>
:root{--bg:#0b1020;--card:rgba(255,255,255,.055);--line:rgba(255,255,255,.12);--ink:#eef1ff;
--dim:#9aa3c7;--gold:#d8b45a;--cyan:#5eead4;--vio:#a78bfa;--r:18px}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:radial-gradient(1200px 600px at 70% -10%,#1b2450 0%,var(--bg) 55%) fixed;
color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Segoe UI',Roboto,sans-serif;
min-height:100vh;padding:max(20px,env(safe-area-inset-top)) 16px 40px}
.wrap{max-width:760px;margin:0 auto}
.hero{text-align:center;padding:26px 0 18px}
.hero .badge{display:inline-block;font-size:12px;color:var(--gold);border:1px solid rgba(216,180,90,.45);
border-radius:999px;padding:5px 14px;letter-spacing:2px;margin-bottom:14px}
.hero h1{font-size:clamp(26px,6vw,38px);font-weight:800;
background:linear-gradient(120deg,#fff,#c7d2fe 55%,#5eead4);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{color:var(--dim);margin-top:10px;font-size:14px;line-height:1.7}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);padding:22px;margin-top:16px}
.app{display:flex;gap:18px;align-items:center}
.app img{width:84px;height:84px;border-radius:22px;box-shadow:0 8px 30px rgba(94,234,212,.25);flex:none}
.app .meta{flex:1;min-width:0}
.app h2{font-size:22px;font-weight:800}
.app h2 small{font-size:12px;color:var(--gold);font-weight:600;border:1px solid rgba(216,180,90,.4);
border-radius:6px;padding:2px 8px;margin-left:8px;vertical-align:2px}
.app .desc{color:var(--dim);font-size:13px;margin-top:6px;line-height:1.6}
.state{margin-top:8px;font-size:13px;color:var(--cyan)}
.install-btn{display:block;width:100%;margin-top:18px;border:none;border-radius:14px;padding:16px;
font-size:17px;font-weight:800;color:#081018;cursor:pointer;letter-spacing:1px;
background:linear-gradient(120deg,#5eead4,#a78bfa);box-shadow:0 10px 30px rgba(94,234,212,.28);
transition:transform .15s, box-shadow .15s}
.install-btn:active{transform:scale(.97)}
.install-btn[disabled]{opacity:.55;box-shadow:none}
.entries{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}
.entries a{display:block;text-align:center;padding:13px;border-radius:12px;font-size:14px;font-weight:700;
text-decoration:none;color:var(--ink);border:1px solid var(--line);background:rgba(255,255,255,.04);transition:.15s}
.entries a.hot{color:#081018;background:linear-gradient(120deg,#fbbf24,#f59e0b);border-color:transparent}
.entries a:active{transform:scale(.97)}
.tabs{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:14px}
.tab{padding:10px 4px;border-radius:10px;text-align:center;font-size:12.5px;font-weight:700;color:var(--dim);
border:1px solid var(--line);background:rgba(255,255,255,.03);cursor:pointer;transition:.2s;white-space:nowrap}
.tab.on{color:#081018;background:linear-gradient(120deg,#5eead4,#7dd3fc);border-color:transparent}
.guide{display:none}
.guide.on{display:block}
.step{display:flex;gap:14px;padding:13px 0;border-bottom:1px dashed rgba(255,255,255,.09);align-items:flex-start}
.step:last-child{border-bottom:none}
.step .n{flex:none;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:800;
color:#081018;background:linear-gradient(120deg,#5eead4,#a78bfa)}
.step .tx{font-size:14px;line-height:1.7}
.step .tx b{color:var(--gold)}
.step .tx .kbd{display:inline-block;padding:1px 8px;border-radius:6px;border:1px solid var(--line);
background:rgba(255,255,255,.07);font-size:12.5px;margin:0 2px}
.note{margin-top:12px;font-size:12.5px;color:var(--dim);line-height:1.8;
border-left:3px solid var(--gold);padding:8px 12px;background:rgba(216,180,90,.06);border-radius:0 10px 10px 0}
.srv{width:100%;border-collapse:collapse;font-size:13px}
.srv td{padding:10px 8px;border-bottom:1px solid rgba(255,255,255,.07);vertical-align:middle}
.srv tr:last-child td{border-bottom:none}
.srv td:first-child{color:var(--dim);white-space:nowrap}
.srv code{color:var(--cyan);font-size:12.5px;word-break:break-all}
.pkg-label{font-weight:800;font-size:14px;color:var(--ink);white-space:nowrap}
.pkg-sub{font-size:12px;color:var(--dim);margin-top:2px}
a.dl{display:inline-block;padding:9px 16px;border-radius:10px;font-size:13px;font-weight:800;color:#081018;
background:linear-gradient(120deg,#5eead4,#7dd3fc);text-decoration:none;white-space:nowrap;transition:.15s}
a.dl:active{transform:scale(.96)}
.wip{display:inline-block;padding:8px 12px;border-radius:10px;font-size:12.5px;color:var(--gold);
border:1px dashed rgba(216,180,90,.5);background:rgba(216,180,90,.07);white-space:nowrap;line-height:1.6}
a.pwa{color:var(--cyan);text-decoration:none;font-size:12.5px}
h3.sec{font-size:15px;font-weight:800;margin-bottom:4px;letter-spacing:1px}
h3.sec::before{content:'◈';color:var(--vio);margin-right:8px}
footer{text-align:center;color:rgba(154,163,199,.6);font-size:12px;margin-top:26px;line-height:1.8}
@media(max-width:560px){.entries{grid-template-columns:1fr}.app{flex-direction:column;text-align:center}
.app h2 small{margin-left:0;display:inline-block;margin-top:6px}
.tabs{grid-template-columns:repeat(3,1fr)}.tab{font-size:11.5px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <span class="badge">MTSCOS · 冰山系统 · 官方下载</span>
    <h1>小龙 App 下载中心</h1>
    <p>仙女座 AI 冰山专用聊天 App · 全平台安装引导 + 桌面客户端安装包<br>
    手机 PWA 免商店直达 · 桌面原生安装包 · APK 已上架 · 自动更新</p>
  </div>

  <div class="card app-card">
    <div class="app">
      <img src="/xiaolong/icon.svg" alt="小龙 App 图标">
      <div class="meta">
        <h2>小龙 · 仙女座聊天 <small>__APP_VERSION__</small></h2>
        <div class="desc">AI 冰山 251+ 员工随叫随到 · 全科目学习陪伴 · 手机/平板/电脑五端通用</div>
        <div class="state" id="stateLine">正在检测您的设备…</div>
      </div>
    </div>
    <button class="install-btn" id="btnInstall" disabled>检测中…</button>
    <div class="entries">
      <a class="hot" href="/xiaolong">🚀 直接打开小龙 App</a>
      <a href="/ai">💬 游客免登录畅聊</a>
    </div>
  </div>

  <div class="card">
    <h3 class="sec">原生客户端安装包 · 全平台动态状态</h3>
    <table class="srv" id="pkgTable"><tbody></tbody></table>
    <div class="note">服务端实时扫描安装包仓库 (static/clients) 渲染状态：<b style="color:var(--cyan)">⬇️ 立即下载</b> = 包已交付；
    <b style="color:var(--gold)">开发中</b> = 已入任务大厅自动开发 (<a href="/xiaolong" style="color:var(--cyan)">大厅单 __HALL_CODE__</a>)，
    PWA 安装当前即为正式形态，无需等待。</div>
  </div>

  <div class="card">
    <h3 class="sec">安装引导（已按您的设备自动适配）</h3>
    <div class="tabs" id="tabs">
      <div class="tab" data-p="android">📱 Android</div>
      <div class="tab" data-p="ios">🍎 iPhone·iPad</div>
      <div class="tab" data-p="windows">🪟 Windows</div>
      <div class="tab" data-p="mac-arm">💻 Mac·M芯</div>
      <div class="tab" data-p="mac-intel">💻 Mac·Intel</div>
    </div>

    <div class="guide" id="g-android">
      <div class="step"><div class="n">1</div><div class="tx">点击上方 <b>「一键安装」</b> 按钮，弹出确认框后点 <span class="kbd">安装</span>。</div></div>
      <div class="step"><div class="n">2</div><div class="tx">若按钮未出现：点浏览器右上角 <span class="kbd">⋮ 菜单</span> → 选 <b>「安装应用」</b> 或 <b>「添加到主屏幕」</b>。</div></div>
      <div class="step"><div class="n">3</div><div class="tx">回到桌面点 <b>「小龙」</b> 图标即可全屏使用，与原生 App 体验一致。</div></div>
      <div class="note"><b style="color:var(--cyan)">真原生 APK 已上架</b>（上方「原生客户端安装包」点下载即得，WebView 壳直达 mtos.site，官方签名）：安装时按提示允许「未知来源 / 仍要安装」即可。PWA 一键安装仍然可用（自动更新 · 免商店）。微信 / QQ 内打开本页无法安装：点右上角 <span class="kbd">···</span> → 选择 <b>「在浏览器打开」</b> 后再操作。</div>
    </div>

    <div class="guide" id="g-ios">
      <div class="step"><div class="n">1</div><div class="tx">必须使用 <b>Safari 浏览器</b> 打开本页（微信内请点右上角 → <b>在 Safari 中打开</b>）。</div></div>
      <div class="step"><div class="n">2</div><div class="tx">点 Safari 底部工具栏的 <b>分享按钮</b> <span class="kbd">⬆︎</span>。</div></div>
      <div class="step"><div class="n">3</div><div class="tx">在菜单中下滑找到 <b>「添加到主屏幕」</b> 并点击。</div></div>
      <div class="step"><div class="n">4</div><div class="tx">确认名称后点右上角 <b>「添加」</b>，桌面即出现小龙图标。</div></div>
      <div class="note">原生 IPA 受苹果开发者证书（$99/年 + 签名身份）与 App Store 政策<b>硬约束</b>，大厅单 <b>__HALL_CODE__</b> 已如实留痕阻塞；<b style="color:var(--cyan)">添加到主屏幕当前即为正式形态</b>（苹果政策所限无法一键静默安装，4 步效果与安装 App 完全相同）。</div>
    </div>

    <div class="guide" id="g-windows">
      <div class="step"><div class="n">1</div><div class="tx">在上方 <b>「原生客户端安装包」</b> 下载 <b>MTSCOS-Xiaolong-Setup-win-x64.exe</b>（NSIS 真安装器），双击进入安装向导 → 一路 <b>下一步</b> 完成安装。</div></div>
      <div class="step"><div class="n">2</div><div class="tx">安装器自动创建 <b>开始菜单 + 桌面快捷方式</b>，可在「设置 → 应用」中正常卸载。</div></div>
      <div class="step"><div class="n">3</div><div class="tx">免安装替代（推荐）：用 <b>Edge</b> 打开 <a href="/xiaolong" style="color:var(--cyan)">/xiaolong</a> → 地址栏 <span class="kbd">⊕ 安装</span>，独立窗口 + 开始菜单入口 + 自动更新。</div></div>
    </div>

    <div class="guide" id="g-mac-arm">
      <div class="step"><div class="n">1</div><div class="tx">下载 <b>Mac · Apple Silicon (M 芯) .dmg 安装镜像</b>（适用 M1 / M2 / M3 / M4），双击挂载。</div></div>
      <div class="step"><div class="n">2</div><div class="tx">把 <b>MTSCOS小龙.app</b> 拖入右侧 <b>Applications</b> 文件夹完成安装；首次打开若被 Gatekeeper 拦截：右键 App → <b>打开</b> → 再点 <b>打开</b>（未签名 App 标准流程）。</div></div>
      <div class="step"><div class="n">3</div><div class="tx">免安装替代（推荐）：用 <b>Safari</b> 打开 <a href="/xiaolong" style="color:var(--cyan)">/xiaolong</a> → 菜单 <b>文件 → 添加到程序坞</b>；或 Chrome 地址栏 <span class="kbd">⊕ 安装</span>。</div></div>
      <div class="note">M 芯镜像内为真原生 .app（Info.plist + 图标齐全）；Intel 芯片 Mac 请切到 <b>Mac·Intel</b> 标签页。</div>
    </div>

    <div class="guide" id="g-mac-intel">
      <div class="step"><div class="n">1</div><div class="tx">下载 <b>Mac · Intel .dmg 安装镜像</b>（适用 Intel 芯片 MacBook / iMac），双击挂载。</div></div>
      <div class="step"><div class="n">2</div><div class="tx">把 <b>MTSCOS小龙.app</b> 拖入右侧 <b>Applications</b> 文件夹完成安装；首次打开若被 Gatekeeper 拦截：右键 App → <b>打开</b> → 再点 <b>打开</b>。</div></div>
      <div class="step"><div class="n">3</div><div class="tx">免安装替代（推荐）：用 <b>Safari</b> 打开 <a href="/xiaolong" style="color:var(--cyan)">/xiaolong</a> → 菜单 <b>文件 → 添加到程序坞</b>；或 Chrome 地址栏 <span class="kbd">⊕ 安装</span>。</div></div>
      <div class="note">Apple Silicon (M1/M2/M3/M4) 用户请切到 <b>Mac·M芯</b> 标签页下载对应版本。</div>
    </div>
  </div>

  <div class="card">
    <h3 class="sec">内置模块 · 移动端历史档案馆 🏛</h3>
    <table class="srv">
      <tr><td>App 内入口</td><td>小龙 App ☰ 菜单 → 「历史档案馆」，或 <a href="/xiaolong/archive" style="color:var(--cyan)">/xiaolong/archive</a></td></tr>
      <tr><td>更新及时档案墙</td><td>最新归档卡片墙 · 每 30 秒自动巡检，新档案亮提示</td></tr>
      <tr><td>使用说明书</td><td><a href="/xiaolong/archive/manual" style="color:var(--cyan)">/xiaolong/archive/manual</a>（安装引导 / 七类档案 / 检索方法 / FAQ）</td></tr>
      <tr><td>桌面端互链</td><td><a href="/andromeda/archive" style="color:var(--cyan)">/andromeda/archive</a>（双端同宗同数据，合并历史档案中心）</td></tr>
    </table>
    <div class="note">跨库聚合 7 类历史档案：版本 / 演化 / 开发流程 / 任务归档 / 规则变更 / 升级报告 / 文案存档。</div>
  </div>

  <div class="card">
    <h3 class="sec">服务器入口（App 内置四通道自动择优）</h3>
    <table class="srv">
      <tr><td>公网兜底</td><td><code>https://mtos.site</code></td></tr>
      <tr><td>Tailscale 直连</td><td><code>http://100.106.220.96:8888</code></td></tr>
      <tr><td>局域网</td><td><code>http://192.168.31.9:8888</code>（同网段）</td></tr>
      <tr><td>当前同源</td><td><code id="originTxt"></code></td></tr>
    </table>
    <div class="note">三层全覆盖授权：账号登录 + 设备绑定 + API Token；游客可从 <a href="/ai" style="color:var(--cyan)">/ai</a> 免登录畅聊。</div>
  </div>

  <footer>MTSCOS 冰山系统 · 小龙 App __APP_VERSION__<br>flow_app_download_20261031 · flow_download_client_20261031 (大厅单 __HALL_CODE__) · 官网下载中心</footer>
</div>

<script>
(function(){
var deferred=null, platform='desktop', tabPinned=false,
btn=document.getElementById('btnInstall'), state=document.getElementById('stateLine'),
HALL='__HALL_CODE__';
document.getElementById('originTxt').textContent=location.origin||'(同源自动识别)';

/* ── 原生安装包动态状态渲染 (服务端扫描注入) ── */
var CLIENTS=__CLIENTS_JSON__;
function fmt(b){return b>=1048576?(b/1048576).toFixed(1)+' MB':Math.max(1,Math.round(b/1024))+' KB';}
(function renderPkgs(){
  var tb=document.querySelector('#pkgTable tbody');
  var html='';
  for(var i=0;i<CLIENTS.length;i++){var p=CLIENTS[i];
    var right;
    if(p.available){
      right='<a class="dl" href="'+p.download+'" download>⬇️ 立即下载 ('+fmt(p.size)+')</a>';
    }else{
      right='<span class="wip">开发中 · 大厅 '+p.hall_code+'<br><a class="pwa" href="#tabs" data-goto="'+(p.key==='android-apk'?'android':'ios')+'">PWA 现在就能装 →</a></span>';
    }
    html+='<tr><td><div class="pkg-label">'+p.label+'</div><div class="pkg-sub">'+p.sub+'</div></td><td style="text-align:right">'+right+'</td></tr>';
  }
  tb.innerHTML=html;
})();
document.getElementById('pkgTable').addEventListener('click',function(e){
  var a=e.target.closest('a[data-goto]');if(!a)return;
  tabPinned=true;setTab(a.dataset.goto);
  document.getElementById('tabs').scrollIntoView({behavior:'smooth'});
});

/* ── 平台检测 (五端细分) ── */
function detect(){
  var ua=navigator.userAgent||'';
  if(/iPad|iPhone|iPod/.test(ua)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1))return 'ios';
  if(/Android/i.test(ua))return 'android';
  if(/Windows/i.test(ua))return 'windows';
  if(/Mac/i.test(ua)){
    return 'mac-arm'; /* 默认 M 芯 (2020 后出货主流), Chromium 下精测见下 */
  }
  return 'windows';
}
function refineMac(){
  /* macOS UA 历史原因恒写 "Intel Mac OS X"; 用 userAgentData 高熵位精判芯片 (Chromium 系) */
  try{
    if(navigator.userAgentData&&navigator.userAgentData.getHighEntropyValues){
      navigator.userAgentData.getHighEntropyValues(['architecture','model']).then(function(h){
        if(/iPad|iPhone/.test(h.model||''))return;
        if(h.architecture==='x86'){platform='mac-intel';if(!tabPinned)setTab(platform);}
      }).catch(function(){});
    }
  }catch(e){}
}
function setTab(p){
  var tabs=document.querySelectorAll('.tab'),gs=document.querySelectorAll('.guide');
  for(var i=0;i<tabs.length;i++)tabs[i].classList.toggle('on',tabs[i].dataset.p===p);
  for(var j=0;j<gs.length;j++)gs[j].classList.toggle('on',gs[j].id==='g-'+p);
}
document.getElementById('tabs').addEventListener('click',function(e){
  var t=e.target.closest('.tab');if(!t)return;tabPinned=true;setTab(t.dataset.p);
});
function iosMode(){
  btn.disabled=false;btn.textContent='🍎 查看安装步骤';
  btn.onclick=function(){document.getElementById('g-ios').scrollIntoView({behavior:'smooth'});};
  state.textContent='已识别 iOS 设备 · Safari 四步添加到主屏幕';
}
function installedMode(){
  btn.disabled=true;btn.textContent='✅ 已安装 · 点击打开';
  btn.disabled=false;
  btn.onclick=function(){location.href='/xiaolong';};
  state.textContent='检测到小龙已在本设备运行';
}
function manualMode(){
  btn.disabled=false;btn.textContent='🚀 打开小龙 App 后安装';
  btn.onclick=function(){location.href='/xiaolong';};
  state.textContent='当前浏览器不支持静默安装 · 点击打开 App 内按引导完成';
}
function nativeMode(){
  btn.disabled=false;btn.textContent='⬇️ 一键安装到本设备';
  btn.onclick=function(){
    if(!deferred){manualMode();return;}
    deferred.prompt();
    deferred.userChoice.then(function(c){
      if(c&&c.outcome==='accepted'){installedMode();}
      deferred=null;
    });
  };
  state.textContent='已就绪 · 点击即可完成安装';
}

window.addEventListener('beforeinstallprompt',function(e){
  e.preventDefault();deferred=e;
  if(platform!=='ios'&&!(window.matchMedia('(display-mode: standalone)').matches))nativeMode();
});
if(window.matchMedia('(display-mode: standalone)').matches){installedMode();}
else{
  platform=detect();setTab(platform);refineMac();
  if(platform==='ios'){iosMode();}
  else{setTimeout(function(){if(!deferred)manualMode();},2500);}
}
})();
</script>
</body>
</html>
"""

_DOWNLOAD_HTML = _DOWNLOAD_HTML.replace('__APP_VERSION__', APP_VERSION).replace('__HALL_CODE__', HALL_CODE)


@app_download_bp.route('/download', methods=['GET'])
def app_download_page():
    """官网公开下载中心 — 防盗链白名单放行, 免登录直达; 服务端扫包动态注入"""
    html = _DOWNLOAD_HTML.replace('__CLIENTS_JSON__', json.dumps(_scan_clients(), ensure_ascii=False))
    return Response(html, mimetype='text/html; charset=utf-8')
