#!/bin/bash
# 上游守护：管理端存活期间每 30s 检查一次自带网关，掉线自动拉起。
set -u
VAR=${WB_VAR_DIR:?missing WB_VAR_DIR}
APPDEST=${WB_APPDEST:?missing WB_APPDEST}
MANAGER_PID=${1:-}
LOG="$VAR/info.log"
UP=$(sed -n 's/^WB_UPSTREAM_DIR=//p' "$VAR/.env" 2>/dev/null | head -n 1 | tr -d ' \r')
[ -z "$UP" ] && UP="$VAR/upstream"
PIDF="$UP/wb2api.pid"

log_msg() { echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG"; }

[ -z "$MANAGER_PID" ] && exit 1
sleep 20
while kill -0 "$MANAGER_PID" 2>/dev/null; do
    cur=$(tr -d '[:space:]' < "$VAR/manager.pid" 2>/dev/null || true)
    [ "$cur" != "$MANAGER_PID" ] && exit 0
    up=$(tr -d '[:space:]' < "$PIDF" 2>/dev/null || true)
    if [ -z "$up" ] || ! kill -0 "$up" 2>/dev/null; then
        # 等启停脚本释放控制锁再判断，避免维护窗口内误拉起。
        exec 9>"$UP/control.lock"
        if flock -w 65 9; then
            up=$(tr -d '[:space:]' < "$PIDF" 2>/dev/null || true)
            if [ -z "$up" ] || ! kill -0 "$up" 2>/dev/null; then
                log_msg "上游网关未运行，自动拉起"
                # 等子脚本时释放外层锁，让 up-start.sh 自行完成二次检查。
                flock -u 9
                bash "$APPDEST/bin/up-start.sh" >> "$LOG" 2>&1 &
                wait $!
            fi
            flock -u 9
        fi
    fi
    sleep 30
done
exit 0
