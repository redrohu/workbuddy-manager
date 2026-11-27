#!/bin/bash
# 生成/更新运行配置：管理端 .env 与自带网关 config.json。
set -u

APPDEST=${WB_APPDEST:?missing WB_APPDEST}
VAR=${WB_VAR_DIR:?missing WB_VAR_DIR}
PORT=${1:-7864}
ADMIN_PWD=${2:-}

# 数据根目录：共享目录优先（WB_SHARE_DIR 由 cmd/main 传入），否则用私有目录。
DATA=${WB_SHARE_DIR:-$VAR}
UP="$DATA/upstream"
mkdir -p "$UP/auths" "$UP/data" "$DATA/data"
# 清掉早期试验版本的接管标记，避免旧标记影响启动分支
rm -f "$VAR/mode"

# 自带网关监听地址：默认仅本机；安装/设置向导写入 gateway.listen 后生效。
GATEWAY_LISTEN=$(cat "$VAR/gateway.listen" 2>/dev/null | tr -d ' \r\n')
[ -z "$GATEWAY_LISTEN" ] && GATEWAY_LISTEN=127.0.0.1:7865
GW_HOST=${GATEWAY_LISTEN%:*}
GW_PORT=${GATEWAY_LISTEN##*:}
case "$GW_HOST" in
    ''|*[!0-9.]*) GW_HOST=127.0.0.1 ;;
esac
case "$GW_PORT" in
    ''|*[!0-9]*) GW_PORT=7865 ;;
esac
if [ "$GW_PORT" -lt 1024 ] 2>/dev/null || [ "$GW_PORT" -gt 65535 ] 2>/dev/null; then
    GW_PORT=7865
fi
GATEWAY_LISTEN="$GW_HOST:$GW_PORT"
# 管理端始终通过本机回环访问网关；绑定 0.0.0.0 时也必须用 127.0.0.1。
BASE_HOST=$GW_HOST
[ "$BASE_HOST" = "0.0.0.0" ] && BASE_HOST=127.0.0.1

escape_dq() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

cat > "$VAR/.env" <<EOF
# 由 fpk 启动脚本生成；改面板端口请到「应用设置」。
WB_MANAGER_HOST=0.0.0.0
WB_MANAGER_PORT=$PORT
WB_SECURE_COOKIE=false
WB_SESSION_DAYS=7
WB_SESSION_IDLE_HOURS=24
WB_AUTH_DIR=$UP/auths
WB_UPSTREAM_CONFIG=$UP/config.json
WB_UPSTREAM_DIR=$UP
WB_DATA_DIR=$DATA/data
WB_DB=$DATA/data/manager.db
WB_USERS_FILE=$DATA/data/users.json
WB_STATIC_DIR=$APPDEST/manager/out
WB2API_BASE=http://$BASE_HOST:$GW_PORT
WB2API_MODE=native
WB2API_START_SCRIPT=$APPDEST/bin/up-start.sh
WB2API_STOP_SCRIPT=$APPDEST/bin/up-stop.sh
WB2API_LOG_FILE=$UP/data/server.err.log
WB2API_CHAT_LOG_FILE=$UP/data/server.out.log
WB_UPSTREAM_TIMEOUT=120
WB_TRUST_PROXY=1
WB_ADMIN_PASSWORD="$(escape_dq "$ADMIN_PWD")"
EOF
chmod 600 "$VAR/.env" 2>/dev/null || true

if [ ! -f "$UP/config.json" ]; then
    KEY=$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 28)
    sed -e "s#\"listen\": *\"[^\"]*\"#\"listen\": \"$GATEWAY_LISTEN\"#" \
        -e "s#\"api_key\": \"test_key\"#\"api_key\": \"$KEY\"#" \
        "$APPDEST/config.example.json" > "$UP/config.json"
    chmod 600 "$UP/config.json" 2>/dev/null || true
else
    # 已有配置只同步 listen，其余账号/模型/密钥设置原样保留。
    if ! grep -q "\"listen\": \"$GATEWAY_LISTEN\"" "$UP/config.json"; then
        sed -i "s#\"listen\": *\"[^\"]*\"#\"listen\": \"$GATEWAY_LISTEN\"#" "$UP/config.json"
    fi
fi

# 上游 scripts：管理端的领奖/任务调用需要 <上游目录>/scripts/task_runner.py。
# 包内自带一份，首次启动（或缺失时）同步进数据目录，避免重装后功能失效。
if [ -d "$APPDEST/upstream-scripts" ] && [ ! -f "$UP/scripts/task_runner.py" ]; then
    mkdir -p "$UP/scripts"
    cp -a "$APPDEST/upstream-scripts/." "$UP/scripts/" 2>/dev/null
    chmod 755 "$UP/scripts"/*.sh 2>/dev/null
    chmod 644 "$UP/scripts"/*.py 2>/dev/null
fi

exit 0
