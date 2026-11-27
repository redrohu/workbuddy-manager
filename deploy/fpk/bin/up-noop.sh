#!/bin/bash
# 接管模式（复用同机已有 wb2api）下的启停占位：上游由它自己的应用管理，
# 这里只记一行日志并返回成功，避免管理端点「重启上游」时误起第二个网关。
VAR=${WB_VAR_DIR:-/tmp}
echo "$(date '+%Y-%m-%d %H:%M:%S') - [up-noop] 当前为接管模式，上游由既有 wb2api 应用管理，未执行启停" >> "$VAR/info.log" 2>/dev/null
exit 0
