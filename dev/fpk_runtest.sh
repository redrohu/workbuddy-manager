#!/bin/bash
# 在 WSL（x86_64）+ qemu-aarch64 里对打好的 fpk 做**真机行为级**验证。
#
# 能证明的事：
#   · 包内所有 shell 钩子语法正确；
#   · 内置 aarch64 Python 3.12 能跑、标准库齐全；
#   · 27 个 aarch64 wheel 能 --no-index 离线装上（这是 NAS 上首次启动的必经步骤）；
#   · server.main 能 import、能起 uvicorn、能响应 /healthz；
#   · gen-config.sh 生成的 .env 路径与端口正确。
#
# 前置（只为在 x86 上模拟 arm，真机上不需要）：
#   apt-get install -y qemu-user-static libc6-arm64-cross libgcc-s1-arm64-cross
set -u

STAGE=/root/fpktest
APPDEST=/opt/fnos-sim/apps/wbmgr
export QEMU_LD_PREFIX=/usr/aarch64-linux-gnu
PY=/tmp/pyrt/python/bin/python3.12
fail=0

note() { echo "  $1"; }
bad() { echo "  !! $1"; fail=1; }

echo "[1] shell 钩子语法（bash -n）"
n=0
for f in "$STAGE"/out/cmd/* "$APPDEST"/bin/*.sh "$APPDEST"/upstream-scripts/*.sh; do
    [ -f "$f" ] || continue
    if bash -n "$f"; then n=$((n + 1)); else bad "语法错误 $f"; fi
done
note "$n 个脚本通过"

echo "[2] 内置 Python"
rm -rf /tmp/pyrt && mkdir -p /tmp/pyrt
tar -xzf "$APPDEST/runtime/py.tar.gz" -C /tmp/pyrt || bad "解压失败"
ver=$("$PY" -V 2>&1)
note "$ver"
"$PY" -c 'import json,sqlite3,ssl,hashlib,sqlite3;print("stdlib ok")' >/dev/null 2>&1 \
    && note "标准库（json/sqlite3/ssl/hashlib）可用" || bad "标准库缺失"

echo "[3] 离线安装依赖（--no-index）"
rm -rf /tmp/pylibs && mkdir -p /tmp/pylibs
if "$PY" -m pip install --no-index --no-warn-script-location \
        --find-links "$APPDEST/wheels" --target /tmp/pylibs \
        -r "$APPDEST/manager/requirements.txt" > /tmp/pip.log 2>&1; then
    count=$(ls /tmp/pylibs | wc -l)
    note "成功，装入 $count 个包"
else
    bad "pip 失败"; tail -15 /tmp/pip.log
fi

echo "[4] 关键依赖可 import"
PYTHONPATH=/tmp/pylibs "$PY" -c '
import fastapi, uvicorn, httpx, pydantic, starlette, multipart, socksio
print("  fastapi", fastapi.__version__, "| pydantic", pydantic.VERSION,
      "| starlette", starlette.__version__)
' 2>&1 || bad "核心依赖 import 失败"

# psycopg 单独判：它是**按需导入**的可选功能（异地备份），不进启动路径。
# 这里模拟器常缺系统库（libz/libpq），所以只记录结论、不判失败。
PYTHONPATH=/tmp/pylibs "$PY" -c 'import psycopg; print("  psycopg 可用", psycopg.__version__)' 2>/dev/null \
    && note "psycopg（异地备份驱动）可用" \
    || note "psycopg 在模拟器里不可用（缺系统库 libz/libpq）；它只在「数据备份」页按需导入，不影响启动"

echo "[5] server.main 可加载"
rm -rf /tmp/wbdata && mkdir -p /tmp/wbdata
cd "$APPDEST/manager" || exit 1
if PYTHONPATH=/tmp/pylibs WB_DATA_DIR=/tmp/wbdata WB_STATIC_DIR="$APPDEST/manager/out" \
        WB_ADMIN_PASSWORD=Wb-Fpk-Smoke-2026 "$PY" -c '
import server.main as m
print("  version =", m.app.version, "| routes =", len(m.app.routes))
' 2>&1; then
    note "import OK"
else
    bad "import 失败"
fi

echo "[6] 起服务并探 /healthz（真跑 uvicorn）"
rm -rf /tmp/wbdata2 && mkdir -p /tmp/wbdata2
PYTHONPATH=/tmp/pylibs WB_DATA_DIR=/tmp/wbdata2 WB_STATIC_DIR="$APPDEST/manager/out" \
WB_ADMIN_PASSWORD=Wb-Fpk-Smoke-2026 WB2API_BASE=http://127.0.0.1:18655 \
WB_MANAGER_HOST=127.0.0.1 \
    "$PY" -m server.serve --host 127.0.0.1 --port 17864 --env-file /dev/null \
    > /tmp/serve.log 2>&1 &
SRV=$!
ok=0
for i in $(seq 1 60); do
    sleep 2
    if resp=$(curl -sS --max-time 3 http://127.0.0.1:17864/healthz 2>/dev/null); then
        note "HTTP 200  $resp"
        ok=1
        break
    fi
    kill -0 $SRV 2>/dev/null || break
done
if [ $ok -ne 1 ]; then
    bad "服务没起来"; tail -30 /tmp/serve.log
else
    # 静态首页也要能取到（前端产物路径是否正确）
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:17864/ 2>/dev/null)
    [ "$code" = "200" ] && note "首页 / → $code" || bad "首页 / → $code"
fi
kill $SRV 2>/dev/null; wait $SRV 2>/dev/null

echo "[7] gen-config.sh"
rm -rf /tmp/wbvar && mkdir -p /tmp/wbvar
if WB_APPDEST="$APPDEST" WB_VAR_DIR=/tmp/wbvar \
        WB_SHARE_DIR=/opt/fnos-sim/apps/@appshare/wbmgr \
        bash "$APPDEST/bin/gen-config.sh" 7864 "Test-Pass-2026!" > /tmp/gen.log 2>&1; then
    static=$(sed -n 's/^WB_STATIC_DIR=//p' /tmp/wbvar/.env)
    [ -d "$static" ] && note "WB_STATIC_DIR 存在" || bad "WB_STATIC_DIR 不存在：$static"
    grep -q '^WB_MANAGER_PORT=7864$' /tmp/wbvar/.env && note "端口写入正确" || bad "端口不对"
    # 生成的 config.json 必须能被上游解析（关键字段在）
    if [ -f /opt/fnos-sim/apps/@appshare/wbmgr/upstream/config.json ]; then
        "$PY" -c "import json,sys;d=json.load(open('/opt/fnos-sim/apps/@appshare/wbmgr/upstream/config.json'));print('  listen=',d['listen'],'api_key 长度=',len(d['api_key']))" \
            && note "config.json 合法" || bad "config.json 解析失败"
    fi
else
    bad "gen-config 失败"; cat /tmp/gen.log
fi

echo "[8] 桌面图标入口（manifest desktop_uidir → ui/config）"
# 这一步专门盯「装完飞牛桌面上看不到应用」：安装器读 manifest 的 desktop_uidir
# 与 desktop_applaunchname，去包内 ui/config 取 .url 条目，再把图标画到桌面上。
# 目录缺失时安装**照样成功**，只有桌面上没图标，安装日志一句错都没有。
MANIFEST="$STAGE/out/manifest"
if [ -f "$MANIFEST" ]; then
    uidir=$(sed -n 's/^desktop_uidir[[:space:]]*=[[:space:]]*//p' "$MANIFEST" | tr -d '\r')
    launch=$(sed -n 's/^desktop_applaunchname[[:space:]]*=[[:space:]]*//p' "$MANIFEST" | tr -d '\r')
    note "desktop_uidir=$uidir  desktop_applaunchname=$launch"
    UICFG="$APPDEST/$uidir/config"
    if [ ! -f "$UICFG" ]; then
        bad "包里没有 $uidir/config —— 装完桌面上不会出现图标"
    elif "$PY" - "$UICFG" "$launch" "$APPDEST/$uidir" <<'PYEOF'
import json, os, sys
cfg_path, launch, uidir = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = json.load(open(cfg_path, encoding='utf-8'))
entry = cfg.get('.url', {}).get(launch)
if not isinstance(entry, dict):
    print(f'  !! ui/config 里没有 .url.{launch}'); sys.exit(1)
port = entry.get('port')
if port != '${port}':
    print(f'  !! port 应为 ${{port}}，实际 {port!r}（改端口后桌面入口会失效）'); sys.exit(1)
icon = entry.get('icon', '')
if not icon.startswith('images/'):
    print(f'  !! icon 路径不对：{icon!r}'); sys.exit(1)
for size in ('64', '256'):
    p = os.path.join(uidir, icon.replace('{0}', size))
    if not os.path.isfile(p):
        print(f'  !! 缺图标 {p}'); sys.exit(1)
    if os.path.getsize(p) == 0:
        print(f'  !! 图标是空文件 {p}'); sys.exit(1)
print(f'  ✓ .url.{launch} type={entry.get("type")} port=${{port}} '
      f'图标 {icon} 齐备（64/256 均非空）')
PYEOF
    then
        note "桌面入口可被安装器解析"
    else
        bad "桌面入口解析失败"
    fi
else
    bad "缺 manifest，无法校验桌面入口"
fi

echo
if [ $fail -eq 0 ]; then echo "ALL PASS"; else echo "SOME FAILED"; fi
exit $fail
