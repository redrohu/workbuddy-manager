#!/bin/bash
# 管理端启动器：首次运行解出内置 Python、离线安装依赖，之后直接启动。
set -u

APPDEST=${WB_APPDEST:?missing WB_APPDEST}
VAR=${WB_VAR_DIR:?missing WB_VAR_DIR}
PY="$VAR/python/bin/python3"
LIBS="$VAR/pylibs"
STAMP="$VAR/.deps-ok"
LOG="$VAR/info.log"

mkdir -p "$VAR"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') - [bootstrap] $1" >> "$LOG"; }

if [ ! -x "$PY" ]; then
    log "解出内置 Python 运行时"
    tar -xzf "$APPDEST/runtime/py.tar.gz" -C "$VAR" >> "$LOG" 2>&1 || { log "Python 运行时解压失败"; exit 1; }
fi
[ -x "$PY" ] || { log "内置 Python 不可执行：$PY"; exit 1; }

if [ ! -f "$STAMP" ]; then
    log "安装 Python 依赖（离线）"
    "$PY" -m pip install --no-index --no-warn-script-location \
        --find-links "$APPDEST/wheels" --target "$LIBS" \
        -r "$APPDEST/manager/requirements.txt" >> "$VAR/deps.log" 2>&1
    if [ $? -ne 0 ]; then
        log "依赖安装失败，详见 $VAR/deps.log"
        tail -n 20 "$VAR/deps.log" >> "$LOG" 2>/dev/null
        exit 1
    fi
    date '+%Y-%m-%d %H:%M:%S' > "$STAMP"
fi

cd "$APPDEST/manager" || exit 1
export PYTHONPATH="$LIBS"
export PYTHONUNBUFFERED=1

ENV_PORT=$(sed -n 's/^WB_MANAGER_PORT=//p' "$VAR/.env" 2>/dev/null | head -n 1 | tr -d ' \r')
ENV_HOST=$(sed -n 's/^WB_MANAGER_HOST=//p' "$VAR/.env" 2>/dev/null | head -n 1 | tr -d ' \r')
exec "$PY" -m server.serve --host "${ENV_HOST:-0.0.0.0}" \
    --port "${ENV_PORT:-${WB_MANAGER_PORT:-7864}}" --env-file "$VAR/.env"
