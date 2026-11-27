#!/bin/bash
set -u
VAR=${WB_VAR_DIR:?missing WB_VAR_DIR}
CFG=$(sed -n 's/^WB_UPSTREAM_CONFIG=//p' "$VAR/.env" 2>/dev/null | head -n 1 | tr -d ' \r')
[ -z "$CFG" ] && CFG="$VAR/upstream/config.json"
UP=$(dirname "$CFG")
PIDF="$UP/wb2api.pid"
# 与 30 秒巡检互斥：维护期间禁止守护抢先拉起旧配置进程。
exec 9>"$UP/control.lock"
flock -x 9
[ -f "$PIDF" ] || exit 0
pid=$(tr -d '[:space:]' < "$PIDF" 2>/dev/null || true)
rm -f "$PIDF"
[ -z "$pid" ] && exit 0
kill -0 "$pid" 2>/dev/null || exit 0
kill -TERM "$pid" 2>/dev/null || true
count=0
while kill -0 "$pid" 2>/dev/null && [ $count -lt 10 ]; do sleep 1; count=$((count + 1)); done
kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
exit 0
