# 🚀 部署指南

> 从零启动 MTSCOS AI 系统 · macOS 原生

---

## 1. 环境要求

| 组件 | 要求 | 推荐版本 |
|------|------|---------|
| macOS | 13+ (Metal iGPU 可用) | Sonoma 14.x |
| Python | ≥ 3.10 | 3.14 |
| Git | 最新 | 2.40+ |
| Ollama | ≥ 0.5 | 11435 端口 |
| Android SDK | build-tools 34.0.0 | 可选（APK 打包） |
| Java | 21+ | openjdk |

### Python 安装
```bash
brew install python@3.14
python3.14 --version  # 确认
```

### Ollama 安装（本地推理核心）
```bash
brew install ollama
ollama pull qwen2.5:14b          # 🥇 通用主力
ollama pull qwen2.5-coder:14b    # 🆕 代码主力
ollama pull nomic-embed-text     # 768 维嵌入

ollama serve &                   # 11435 端口启动
ollama list                      # 确认模型就绪
```

### Android SDK + apktool（APK 打包）
```bash
# SDK (Android Studio 或 cmdline-tools)
brew install --cask android-platform-tools
brew install --cask android-commandlinetools

# 设置环境变量 (~/.zshrc)
export ANDROID_HOME=~/Library/Android/sdk
export PATH=$ANDROID_HOME/build-tools/34.0.0:$PATH

# apktool
brew install apktool

# Java (apksigner 依赖)
brew install openjdk@21
export JAVA_HOME=/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home
```

---

## 2. 项目安装

```bash
git clone git@github.com:wuchenghao15/MTSCOS.git
cd MTSCOS

# Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 依赖安装
cd flask-app
pip install -r requirements.txt
cd ..
```

---

## 3. Flask 启动

```bash
cd flask-app
python3 modular_start.py

# 输出:
# * Running on http://127.0.0.1:8888
# * Running on http://172.20.10.2:8888
```

### 端口占用？改端口
编辑 `flask-app/modular_start.py`：
```python
PORT = 8888  # → 改成你需要的
```

### LaunchAgent 开机自启
创建 `~/Library/LaunchAgents/com.mtscos.flask.plist`（略）。

---

## 4. 移动端 APK

### 安装 APK
```bash
# 方式 1: 手机同 WiFi 浏览器打开
# http://<电脑局域网IP>:8888/mobile/apk
# 直接下载安装

# 方式 2: adb
adb install -r MTSCOS-AI-Mobile-v25.5.0-debug.apk

# 方式 3: AirDrop 微信传过去点开
```

### APK 默认 URL
v25.5.0 默认连接：`http://172.20.10.2:8888/iceberg/mobile`（iPhone 热点）

### 改 URL（不用重打包）
```bash
# adb 写 SharedPreferences
adb shell run-as com.mtscos.mobile \
  sh -c 'echo "<?xml version=\"1.0\"?><map><string name=\"server_url\">http://新IP:8888/mobile/login</string></map>" > shared_prefs/mtscos_prefs.xml'

# 重启 APP 生效
adb shell am force-stop com.mtscos.mobile
adb shell monkey -p com.mtscos.mobile -c android.intent.category.LAUNCHER 1
```

### 重打包 APK（需要改默认 URL）
```bash
# 1. apktool 解码
apktool d MTSCOS-AI-Iceberg-Mobile-v25.3.0-debug.apk -o /tmp/apk -f

# 2. 改 smali 里的 constructor URL
sed -i '' 's|http://172.20.10.2:8888/iceberg/mobile|新URL|g' \
  /tmp/apk/smali_classes4/com/mtscos/mobile/MainActivity.smali

# 3. 改版本号
sed -i '' 's/versionCode: 253/versionCode: 255/' /tmp/apk/apktool.yml
sed -i '' 's/versionName: 25.3.0/versionName: 25.5.0/' /tmp/apk/apktool.yml

# 4. 重打包
apktool b /tmp/apk -o new.apk

# 5. zipalign + 签名
zipalign -f 4 new.apk new_aligned.apk
apksigner sign \
  --ks ~/.android/debug.keystore \
  --ks-key-alias androiddebugkey \
  --ks-pass pass:android \
  --key-pass pass:android \
  new_aligned.apk

# 6. 验证 + 安装
apksigner verify new_aligned.apk && echo "✅ 签名有效"
adb install -r new_aligned.apk
```

---

## 5. 公网穿透（外部访问）

### Serveo SSH（最简单，每次 URL 变）
```bash
cd MTSCOS_AI_Project
ssh -o StrictHostKeyChecking=no \
    -o ServerAliveInterval=20 \
    -R 80:localhost:8888 \
    serveo.net

# 输出: Forwarding HTTP traffic from https://xxx.serveousercontent.com
# 把 APK SharedPreferences 改成这个 URL + /mobile/login
```

### ngrok（推荐，可保留子域名）
```bash
brew install ngrok
ngrok http 8888
# 类似: https://mtscos.ngrok-free.app/mobile/login
```

### frp（自建穿透，稳定）
服务器部署 frps，本地 frpc 配置：
```toml
[[proxies]]
name = flask
type = tcp
localIP = 127.0.0.1
localPort = 8888
remotePort = 8888
```

---

## 6. VIKEY 硬件加密狗（SA 登录必备）

```
SA (wuchenghao15) 7 要素认证:
├── 1. 用户名
├── 2. 密码 (bcrypt)
├── 3. VIKEY USB 加密狗
│   ├─ 硬件 ID 实时匹配
│   └─ 指纹 + 签名验证
├── 4. 设备指纹
├── 5. IP 白名单
├── 6. 会话状态
└── 7. 时间戳校验
```

普通用户（student）不需要 VIKEY，直接密码登录。

---

## 7. 常见问题

### Q: Flask 启动报 端口占用
```bash
lsof -i :8888 | head -5     # 看谁占了
kill $(lsof -t -i :8888)    # 杀掉
```

### Q: Ollama 连不上
```bash
curl http://localhost:11435/api/tags  # 应该返回模型列表
ollama serve &                        # 重启服务
```

### Q: APK 安装失败 "签名不一致"
```bash
# 先卸载旧版本
adb uninstall com.mtscos.mobile
adb install new.apk
```

### Q: 移动端 302 重定向回 PC 端
Flask server_real_db.py 的 `_REDIRECT_MAP` 里 `/mobile/*` 可能被重定向了。检查：
```bash
grep -n "mobile" flask-app/server_real_db.py | head -10
```

### Q: CSRF 403 on POST /mobile/login
`_CSRF_EXEMPT_PREFIXES` 需包含 `/mobile/` 和 `/iceberg/mobile`。检查：
```bash
grep -n "CSRF_EXEMPT" flask-app/server_real_db.py | head -5
```
