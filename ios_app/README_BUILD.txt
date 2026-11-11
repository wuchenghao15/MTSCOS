# 小龙 iOS — 原生 iPhone 聊天 App 构建指南

════ 前置要求 ════
1. macOS + Xcode 15+ (App Store 安装)
2. XcodeGen (可选, 二选一):
   brew install xcodegen
3. 苹果开发者账号 (免费账号可真机调试 7 天; 付费账号可 TestFlight/上架)

════ 生成 Xcode 项目 (方式一: XcodeGen 推荐) ════
cd ~/MTSCOS_AI_Project/flask-app/ios_app
xcodegen generate        # 生成 XiaolongIOS.xcodeproj
open XiaolongIOS.xcodeproj

════ 生成 Xcode 项目 (方式二: 手动) ════
Xcode → File → New → Project → iOS App
  名称 XiaolongIOS, Interface SwiftUI, Language Swift
创建后删除模板 ContentView.swift
把 XiaolongIOS/ 目录下的 5 个 .swift 文件 + Info.plist 拖入项目
  (勾选 Copy items if needed; Info.plist 替换模板同名文件)

════ 配置签名 ════
Xcode → Target XiaolongIOS → Signing & Capabilities
  Team: 选择你的账号
  Bundle Identifier: com.mtscos.xiaolongios (自定义唯一值)

════ 服务器地址 ════
App 设置页可改, 三个通道 (iPhone 无需装 Tailscale):
  1. 局网直连 (同Wi-Fi):  http://192.168.11.180:5001        ← 家里/办公室首选
  2. 公网 Funnel (任何网络): https://macbook-pro.tail5140cb.ts.net  ← 4G/5G/外网通用
     (Tailscale Funnel 已开启, 固定域名, 自动HTTPS证书, KeepAlive)
  3. Tailscale IP:        http://100.121.98.15:5001         ← iPhone装了Tailscale时
  4. cloudflared 应急:    cat /tmp/mtscos_public_url.txt    ← URL随重启变
Info.plist 已允许 HTTP 明文 (NSAllowsArbitraryLoads); Funnel 走 HTTPS 更安全。
注: 本机 curl 测 Funnel 会被 MagicDNS hairpin 干扰(HTTP 000), 外部节点/iPhone 实测正常。

════ 功能对照 (与 PWA 小龙完全一致) ════
- 登录/注册      POST /api/xiaolong/token | /register (X-XL-Token 认证)
- SSE 流式聊天   POST /api/xiaolong/chat/stream (delta 逐字 + 工具事件胶囊)
- 反馈闭环       👍👎 → /api/chat-feedback (点踩自动入质量工单)
- 个性化主题     GET /api/user-theme (粉色/海洋/绿… 映射 App 主题色)
- 模型切换       5 档 qwen2.5 模型 (设置页)

════ 真机调试 ════
iPhone 数据线连 Mac → Xcode 选择设备 → Cmd+R
首启需: 设置 → 通用 → VPN与设备管理 → 信任开发者证书

════ TestFlight 分发 (付费账号) ════
Xcode → Product → Archive → Distribute App → TestFlight
内部测试员 100 人 / 外部最多 10000 人
