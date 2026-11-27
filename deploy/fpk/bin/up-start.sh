#!/bin/bash
# 启动自带上游（仅 own 模式）：后台拉起并立即返回；日志写 data/server.{out,err}.log。
set -u

VAR=${WB_VAR_DIR:?missing WB_VAR_DIR}
APPDEST=${WB_APPDEST:?missing WB_APPDEST}

# 防呆：被 root 调用（例如手工 sudo）时必须先降权到数据目录属主。
# 网关以 root 运行时，刷新 token 会把 auths/*.json 原子重写成 root:root 600，
# 之后以 package 用户运行的正常服务就读不到账号（表现为账号全丢）。
# 降权必须在任何文件/目录创建之前完成；这里只写 stderr，不碰日志文件。
if [ "$(id -u)" = "0" ]; then
    owner=$(stat -c '%U' "$VAR" 2>/dev/null || true)
    if [ -z "$owner" ] || [ "$owner" = "root" ]; then
        echo "up-start: refuse to start as root (owner of $VAR is ${owner:-unknown})" >&2
        exit 1
    fi
    if command -v setpriv >/dev/null 2>&1; then
        exec setpriv --reuid="$(id -u "$owner")" --regid="$(id -g "$owner")" \
            --init-groups -- "$0" "$@"
    fi
    echo "up-start: running as root but setpriv not found; setpriv is required to drop privileges" >&2
    exit 1
fi

CFG=$(sed -n 's/^WB_UPSTREAM_CONFIG=//p' "$VAR/.env" 2>/dev/null | head -n 1 | tr -d ' \r')
[ -z "$CFG" ] && CFG="$VAR/upstream/config.json"
UP=$(dirname "$CFG")
PIDF="$UP/wb2api.pid"
mkdir -p "$UP/data" "$UP/auths"
# 与停止/守护串行，防止配置重启时重复拉起网关。
exec 9>"$UP/control.lock"
flock -x 9
OUT="$UP/data/server.out.log"
ERR="$UP/data/server.err.log"
mkdir -p "$UP/data" "$UP/auths"

if [ -f "$PIDF" ]; then
    pid=$(tr -d '[:space:]' < "$PIDF" 2>/dev/null || true)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        exit 0
    fi
    rm -f "$PIDF"
fi
[ -f "$CFG" ] || { echo "missing $CFG" >> "$ERR"; exit 1; }

cd "$UP" || exit 1
# 网关不能继承控制锁，否则启动脚本退出后锁仍被常驻进程持有。
nohup "$APPDEST/bin/wb2api" -config "$CFG" 9>&- >> "$OUT" 2>> "$ERR" &
echo $! > "$PIDF"
exit 0
