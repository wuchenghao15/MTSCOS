#!/bin/bash
# =============================================================================
# MTSCOS AI —— Mac mini 仓库安全对齐到 origin/main (mini_realign_repo.sh)
# =============================================================================
# 背景:
#   Mac mini 的 ~/MTSCOS_AI_Project 是一个"git init 后从未对接主干"的半初始化
#   仓库 —— HEAD 为 unborn main, index 把整个旧工作区标成 A, 与 origin/main 差
#   11911 个文件。直接 git pull 会被 "untracked would be overwritten" 拒绝。
#
# 本脚本做什么 (在 mini 本机通过 ssh 编排):
#   1. 只读预检: 可达性 / origin/main 基线 / 服务是否在跑 / 冲突项清单;
#   2. 备份: 15 个"本地 untracked 且主干 tracked 同名"的冲突文件(保留 mini 版本,
#      便于事后 diff 拣回本地定制) + DB + .env (双保险) 到 mini 本地备份目录;
#   3. 建立 HEAD 指向 origin/main, git reset --hard 对齐工作区与 index;
#   4. 验证: git status / VERSION / v23 关键文件 / py_compile 抽查。
#
# 永不触碰:
#   - *.db / .env / keys 等被 .gitignore 忽略的本地数据 (reset --hard 不影响 untracked);
#   - 主干中不存在的纯本地独有文件 (实测为 0 个; 脚本仍动态识别并保留)。
#
# 安全护栏:
#   - 默认 **dry-run**, 只打印不动手; 真正执行必须显式 --execute;
#   - 检测到 mini 的 flask(modular_start)/ai_smart_mount 在跑 → 立即中止,
#     需 SA 先 launchctl 停服务再跑 (脚本绝不自行 kill/launchctl);
#   - 不自动重启服务、不自动同步 DB、不动 VERSION (均为 SA 域)。
#
# 用法 (在开发机):
#   bash _entry_wrappers/mini_realign_repo.sh              # 只读预检
#   bash _entry_wrappers/mini_realign_repo.sh --execute    # SA 停服后执行对齐
# =============================================================================
set -euo pipefail

MINI_USER="wuchenghao"
MINI_HOST="100.106.220.96"
MINI_REPO="~/MTSCOS_AI_Project"

EXECUTE=0
[ "${1:-}" = "--execute" ] && EXECUTE=1

# 远程执行体: 通过 stdin 用 'bash -s' 送到 mini, 避免引号嵌套
read -r -d '' REMOTE_BODY <<'REMOTE_EOF' || true
set -euo pipefail
EXECUTE="${1:-0}"
cd "$HOME/MTSCOS_AI_Project"

c_g(){ printf '\033[32m'; }
c_r(){ printf '\033[31m'; }
c_y(){ printf '\033[33m'; }
c_n(){ printf '\033[0m'; }
log(){ echo "[$(date '+%H:%M:%S')] $*"; }
ok(){  echo "  $(c_g)✅ $*$(c_n)"; }
warn(){ echo "  $(c_y)⚠️  $*$(c_n)"; }
bad(){  echo "  $(c_r)❌ $*$(c_n)"; }

log "=== Mac mini 仓库对齐预检 ($(hostname)) ==="
[ -d .git ] || { bad "不是 git 仓库: $PWD/.git"; exit 2; }
git fetch origin --quiet
BASE="refs/remotes/origin/main"
git rev-parse --verify "$BASE" >/dev/null 2>&1 || { bad "origin/main 不存在"; exit 2; }
log "origin/main = $(git log --oneline -1 "$BASE")"

# ── 服务状态 (execute 时在跑即中止; dry-run 仅展示, 继续只读诊断) ──
SVC_RUNNING=0
if pgrep -f "modular_start.py|ai_smart_mount_engine" >/dev/null 2>&1; then
  SVC_RUNNING=1
  warn "检测到 mini 正在运行 flask/smart_mount:"
  pgrep -fl "modular_start.py|ai_smart_mount_engine" | sed 's/^/      /'
  if [ "$EXECUTE" = "1" ]; then
    bad "请 SA 先 launchctl 停服务, 再运行本脚本 (脚本不会自行停/启服务)"
    exit 3
  fi
else
  ok "未检测到运行中的 flask/smart_mount"
fi

# ── 识别冲突项: untracked(含被忽略之外) 中, 在 origin/main 也 tracked 同名的路径 ──
# 用 NUL 分隔, 正确处理空格/中文/引号文件名
CONFLICTS=()
while IFS= read -r -d '' f; do
  if git cat-file -e "$BASE:$f" 2>/dev/null; then
    CONFLICTS+=("$f")
  fi
done < <(git ls-files -z --others --exclude-standard)

log "阻挡对齐的同名冲突文件: ${#CONFLICTS[@]} 个 (将备份后采用主干版本)"
for f in "${CONFLICTS[@]:-}"; do [ -n "${f:-}" ] && echo "      C  $f"; done

# ── 待保护的本地数据 (ignored, reset 本不触碰, 仍额外备份双保险) ──
PROTECT=()
for p in flask-app/database/app.db flask-app/engines/app.db flask-app/.env .env; do
  [ -e "$p" ] && PROTECT+=("$p")
done
log "本地数据保护项: ${#PROTECT[@]} 个 (ignored, reset 不触碰, 额外备份)"
for p in "${PROTECT[@]:-}"; do [ -n "${p:-}" ] && echo "      P  $p"; done

cur_v="$(cat flask-app/VERSION 2>/dev/null || echo '?')"
base_v="$(git show "$BASE:flask-app/VERSION" 2>/dev/null || echo '?')"
log "VERSION: 本地=$cur_v  主干=$base_v"
if [ "$cur_v" != "$base_v" ]; then
  bad "VERSION 不一致, 拒绝在跨版本状态下对齐 (请先走 v23 终审使两端版本一致)"
  exit 4
fi
ok "两端 VERSION 一致 ($cur_v)"

if [ "$EXECUTE" != "1" ]; then
  if [ "$SVC_RUNNING" = "1" ]; then
    warn "DRY-RUN 完成(只读, 未改任何内容)。当前服务在跑 —— SA 需先 launchctl 停 flask/smart_mount, 再 --execute。"
  else
    warn "DRY-RUN 完成(只读, 未改任何内容)。服务已停, 可 --execute 执行对齐。"
  fi
  exit 0
fi

# ═══════════════ 以下仅 --execute 执行 ═══════════════
TS="$(date +%Y%m%d_%H%M%S)"
BK="$HOME/mtscos_realign_backup_$TS"
mkdir -p "$BK"
log "备份目录: $BK"

# 1) 备份并移走冲突文件 (保留相对路径)
for f in "${CONFLICTS[@]:-}"; do
  [ -z "${f:-}" ] && continue
  mkdir -p "$BK/conflicts/$(dirname "$f")"
  cp -p "$f" "$BK/conflicts/$f"
  rm -f "$f"
done
ok "已备份并移走 ${#CONFLICTS[@]} 个冲突文件"

# 2) 额外备份本地数据 (DB/.env)
for p in "${PROTECT[@]:-}"; do
  [ -z "${p:-}" ] && continue
  mkdir -p "$BK/protect/$(dirname "$p")"
  cp -p "$p" "$BK/protect/$p"
done
ok "已额外备份 ${#PROTECT[@]} 个本地数据项 (原位置保留不动)"

# 3) unborn main → 指向 origin/main, 再硬对齐 tracked 工作区/index
git symbolic-ref HEAD refs/heads/main
git update-ref refs/heads/main "$BASE"
git reset --hard "$BASE"
ok "git reset --hard origin/main 完成"

# 4) 验证
log "=== 对齐后验证 ==="
echo "HEAD      : $(git log --oneline -1)"
echo "VERSION   : $(cat flask-app/VERSION)"
echo "status 行数: $(git status --short | wc -l | tr -d ' ')  (预期仅剩 ignored 不显示/0)"
for probe in _entry_wrappers/tri_sync.sh \
             flask-app/scripts/ops/v23_upgrade_finalize.py \
             flask-app/server_real_db.py \
             flask-app/templates/base.html; do
  if [ -f "$probe" ]; then ok "存在 $probe"; else bad "缺失 $probe"; fi
done
if /usr/bin/python3 -m py_compile flask-app/server_real_db.py 2>/dev/null; then
  ok "py_compile server_real_db.py 通过"
else
  warn "py_compile server_real_db.py 有告警 (请人工确认)"
fi

cat <<TIP

  对齐完成。备份(可 diff 拣回本地定制): $BK
  后续由 SA 手动 (脚本不自动执行):
    1) 检查备份里是否有需拣回的本地定制:  diff -r "$BK/conflicts" "\$HOME/MTSCOS_AI_Project"
    2) launchctl 重新拉起 mini 的 flask 与 smart_mount
    3) 两端版本一致前, tri_sync 的 DB 同步受跨 major 守卫保护
TIP
REMOTE_EOF

echo "=============================================================="
echo " Mac mini 仓库对齐  →  $MINI_USER@$MINI_HOST:$MINI_REPO"
echo " 模式: $([ "$EXECUTE" = 1 ] && echo '⚠️  EXECUTE (将真实改动)' || echo 'DRY-RUN (只读)')"
echo "=============================================================="
ssh -o ConnectTimeout=10 -o BatchMode=yes "$MINI_USER@$MINI_HOST" "bash -s" -- "$EXECUTE" <<<"$REMOTE_BODY"
