#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# build_ios.sh — 小龙 iOS App 自动化构建 + IPA 导出
# flow_ios_build_20261030
#
# 依赖: Xcode 15+ 或 xcodegen (`brew install xcodegen`)
# 产物: build/XiaolongIOS.app + XiaolongIOS.ipa
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"
BUILD_DIR="$ROOT/build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo "🔧 Step 1/4: 生成 Xcode 工程 (xcodegen)"
if command -v xcodegen &>/dev/null; then
    xcodegen generate -s project.yml
elif [ -d XiaolongIOS.xcodeproj ]; then
    echo "  xcodegen 未装, 用已存在的 .xcodeproj"
else
    echo "  安装 xcodegen..."
    brew install xcodegen
    xcodegen generate -s project.yml
fi
echo "  ✅ Xcode 工程就绪"

echo "📦 Step 2/4: xcodebuild 模拟器构建 (Debug)"
xcodebuild -project XiaolongIOS.xcodeproj \
    -scheme XiaolongIOS \
    -sdk iphonesimulator \
    -configuration Debug \
    -derivedDataPath "$BUILD_DIR/DerivedData" \
    -allowProvisioningUpdates \
    CODE_SIGNING_ALLOWED=NO \
    build 2>&1 | tail -15

echo "📱 Step 3/4: 真机构建 (Release + Enterprise)"
xcodebuild -project XiaolongIOS.xcodeproj \
    -scheme XiaolongIOS \
    -configuration Release \
    -destination generic/platform=iOS \
    -derivedDataPath "$BUILD_DIR/DerivedData" \
    -allowProvisioningUpdates \
    build 2>&1 | tail -15

echo "📦 Step 4/4: 导出 IPA"
APP_PATH=$(find "$BUILD_DIR/DerivedData" -name "XiaolongIOS.app" -not -path "*/Debug-*" | head -1)
if [ -z "$APP_PATH" ]; then
    APP_PATH=$(find "$BUILD_DIR/DerivedData" -name "XiaolongIOS.app" | head -1)
fi

if [ -n "$APP_PATH" ]; then
    mkdir -p "$BUILD_DIR/Payload"
    cp -r "$APP_PATH" "$BUILD_DIR/Payload/"
    cd "$BUILD_DIR"
    zip -r -q XiaolongIOS.ipa Payload
    ls -lh XiaolongIOS.ipa
    cd "$ROOT"
    echo "  ✅ IPA 导出: $BUILD_DIR/XiaolongIOS.ipa"
else
    echo "  ⚠️ 未找到 .app, 跳过 IPA 导出 (检查 xcodebuild 日志)"
fi

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ 构建完成"
echo "  .xcodeproj: $ROOT/XiaolongIOS.xcodeproj"
echo "  IPA:        $BUILD_DIR/XiaolongIOS.ipa"
echo "  模拟器运行: xcrun simctl boot <device_id>; open -a Simulator"
echo "  真机安装:   ideviceinstaller -i $BUILD_DIR/XiaolongIOS.ipa"
echo "═══════════════════════════════════════════════════════"
