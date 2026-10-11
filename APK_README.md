# 📱 MTSCOS AI 冰山移动管理 APK

## 文件
- **MTSCOS-AI-Iceberg-Mobile-v25.3.0-debug.apk** (5.3MB)

## 构建信息
- 构建工具: Gradle 8.5 + AGP 8.2.2
- 编译 SDK: android-34
- minSdk: 24 (Android 7.0+)
- JDK: Adoptium OpenJDK 21
- Android Studio: 不需要 (纯命令行构建)
- 签名: debug keystore (用于测试)

## 功能 (WebView 壳 + Flask 后端)
- 📊 冰山仪表盘
- 🧊 意识脉冲
- ✨ Aurora 极光能力
- 🤖 AI 员工赋能
- 📡 蓝牙 BLE
- 🛡️ Mac mini 同步
- 🔐 AI Passport (FaceID/TouchID) 生物识别

## 连接的 Flask 服务器
默认: http://172.20.10.2:8888/iceberg/mobile (局域网 Mac mini)

如需改服务器地址:
  MainActivity.kt → URL 常量 → 重新构建 APK

## 安装测试
  1. 手机连同一 WiFi
  2. adb install MTSCOS-AI-Iceberg-Mobile-v25.3.0-debug.apk
  3. 打开 App → 自动加载 Flask 移动管理端

## 生成 Release APK (生产签名)
  # 需要 release keystore
  ./gradlew :app:assembleRelease
  # APK: app/build/outputs/apk/release/app-release.apk

## 源码
Android 工程: /tmp/MTSCOSMobile/
Flask 后端:   flask-app/
