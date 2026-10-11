#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  MTSCOS Andromeda — macOS Apache 反向代理一键配置
#  目标: http://192.168.31.9 → Apache :80 → Flask :8888
#  用法: curl -sL http://192.168.31.203:8080/setup_apache_proxy.sh | bash
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
CYAN='\033[36m'
NC='\033[0m'

say()    { echo -e "${BOLD}${CYAN}▸${NC} $*"; }
ok()     { echo -e "  ${GREEN}✓${NC} $*"; }
warn()   { echo -e "  ${YELLOW}⚠${NC} $*"; }
fail()   { echo -e "  ${RED}✗${NC} $*"; }

APP_PORT="${APP_PORT:-8888}"
PROXY_CONF="/etc/apache2/other/mtscos-proxy.conf"
HTTPD_CONF="/etc/apache2/httpd.conf"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  MTSCOS Andromeda · Apache Reverse Proxy    ║"
echo "║  :80 → Flask :${APP_PORT}                   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 0. 检查 Apache 是否存在 ──────────────────────────────────────
say "[0/5] 检查环境"

if ! command -v apachectl &>/dev/null; then
    fail "apachectl 没找到 — macOS 预装 Apache 应该在 /usr/sbin/apachectl"
    echo "  你的系统: $(uname -s) $(uname -m)"
    exit 1
fi
ok "apachectl 存在: $(which apachectl)"

if ! lsof -i :${APP_PORT} -sTCP:LISTEN 2>/dev/null | grep -q .; then
    warn "Flask :${APP_PORT} 没在监听 — 先跑 ./mtscos.sh start"
else
    ok "Flask :${APP_PORT} 正在监听"
fi

# ── 1. 备份 httpd.conf ──────────────────────────────────────────
say "[1/5] 备份 httpd.conf"
if [ -f "$HTTPD_CONF" ]; then
    cp "$HTTPD_CONF" "${HTTPD_CONF}.bak.$(date +%Y%m%d%H%M%S)"
    ok "已备份 → ${HTTPD_CONF}.bak.<timestamp>"
else
    fail "$HTTPD_CONF 不存在"
    exit 1
fi

# ── 2. 启用 proxy 模块 ────────────────────────────────────────────
say "[2/5] 启用 Apache proxy 模块"

MODULES=(
    "proxy_module"
    "proxy_http_module"
    "proxy_connect_module"
    "proxy_wstunnel_module"
    "headers_module"
)

for mod in "${MODULES[@]}"; do
    # 两种写法都试: #LoadModule xxx / libexec/apache2/xxx.so
    if grep -qE "^LoadModule ${mod} " "$HTTPD_CONF"; then
        ok "${mod} 已启用"
    else
        # 从注释行反推路径
        commented=$(grep -nE "^#LoadModule ${mod} " "$HTTPD_CONF" | head -1 || true)
        if [ -n "$commented" ]; then
            sed -i '' "s|^#LoadModule ${mod} |LoadModule ${mod} |" "$HTTPD_CONF"
            ok "${mod} 已启用 (取消注释)"
        else
            # 手动追加 — macOS Apache 默认路径
            echo "LoadModule ${mod} libexec/apache2/${mod}.so" >> "$HTTPD_CONF"
            ok "${mod} 已追加到 httpd.conf"
        fi
    fi
done

# ── 3. 写反向代理配置 ─────────────────────────────────────────────
say "[3/5] 写入反向代理配置 → ${PROXY_CONF}"

sudo tee "$PROXY_CONF" > /dev/null <<EOF
# ═══════════════════════════════════════════
#  MTSCOS Andromeda → Flask :${APP_PORT}
#  生成时间: $(date '+%Y-%m-%d %H:%M:%S')
# ═══════════════════════════════════════════

ProxyPreserveHost On
ProxyRequests Off
ProxyTimeout 300

# 全部请求代理到 Flask
ProxyPass / http://127.0.0.1:${APP_PORT}/
ProxyPassReverse / http://127.0.0.1:${APP_PORT}/

# WebSocket 升级支持
RewriteEngine On
RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule /(.*) ws://127.0.0.1:${APP_PORT}/\$1 [P,L]

# 转发真实客户端信息
RequestHeader set X-Forwarded-Proto "http"
RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
RequestHeader set X-Forwarded-Port "80"
EOF

ok "已写入 ${PROXY_CONF}"

# ── 4. 检查 Include conf/other/*.conf 是否已启用 ─────────────────
say "[4/5] 确认 other/*.conf 自动加载"

if grep -qE "^Include.*other" "$HTTPD_CONF"; then
    ok "Include other/*.conf 已启用"
else
    # macOS 默认有这行, 以防万一
    echo "" >> "$HTTPD_CONF"
    echo "# MTSCOS — load proxy config" >> "$HTTPD_CONF"
    echo "Include /etc/apache2/other/*.conf" >> "$HTTPD_CONF"
    ok "已追加 Include /etc/apache2/other/*.conf"
fi

# ── 5. configtest + restart ───────────────────────────────────────
say "[5/5] configtest + 重启 Apache"

if sudo apachectl configtest 2>&1; then
    ok "configtest 通过"
else
    fail "configtest 失败!"
    echo ""
    echo "  常见原因:"
    echo "    1) 模块路径不对 — 检查 /usr/libexec/apache2/ 下有没有 proxy_module.so"
    echo "    2) 语法错误 — 检查 ${PROXY_CONF}"
    echo ""
    echo "  手动调试:"
    echo "    sudo apachectl configtest"
    echo "    cat ${PROXY_CONF}"
    exit 1
fi

# 优先 graceful, 不行就 full restart
if sudo apachectl graceful 2>/dev/null; then
    ok "apachectl graceful 成功"
else
    warn "graceful 失败, 尝试 full restart"
    sudo apachectl restart
    ok "apachectl restart 成功"
fi

# ── 验证 ─────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════"
echo "  验证中..."
echo "════════════════════════════════════════════════"
sleep 2

# 本地 IPv4
status_local=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 http://127.0.0.1/)
body_local=$(curl -s --connect-timeout 3 http://127.0.0.1/ | head -c 200 || true)

# 局域网 IP
lan_ip=$(ipconfig getifaddr en0 2>/dev/null || echo "192.168.31.9")
status_lan=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://${lan_ip}/" || echo "000")

echo ""
echo -e "  ${BOLD}本地 (127.0.0.1):${NC}  HTTP ${BOLD}${status_local}${NC}"
echo -e "  ${BOLD}局域网 (${lan_ip}):${NC}  HTTP ${BOLD}${status_lan}${NC}"
echo ""

if [ "$status_local" = "302" ] && echo "$body_local" | grep -qi "location: /index\|mtscos_sid"; then
    echo -e "  ${GREEN}═══════════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}  🎉  Apache 反向代理配置成功!${NC}"
    echo -e "  ${GREEN}═══════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${BOLD}访问地址:${NC}"
    echo -e "    🌐  http://${lan_ip}/            (局域网任意设备)"
    echo -e "    🌐  http://127.0.0.1:8888/        (直连 Flask, 仍可用)"
    echo ""
    echo -e "  ${BOLD}Apache 管理:${NC}"
    echo "    sudo apachectl start|stop|restart|graceful"
    echo ""
    echo -e "  ${BOLD}配置文件:${NC}"
    echo "    ${PROXY_CONF}"
    echo ""
    exit 0
fi

# 如果 body 里还有 "It works! Apache httpd" — proxy 没生效
if echo "$body_local" | grep -qi "It works.*Apache"; then
    warn "还是 'It works! Apache' — proxy 配置没加载"
    echo ""
    echo "  排查:"
    echo "    sudo apachectl -S              # 虚拟主机汇总"
    echo "    sudo apachectl configtest      # 语法检查"
    echo "    ls -la /etc/apache2/other/     # 确认 mtscos-proxy.conf 在"
    echo "    cat ${PROXY_CONF}              # 内容对不对"
    exit 1
fi

warn "HTTP ${status_local} — 不是预期的 302"
echo "  body 预览: ${body_local:0:150}"
exit 1
