# AGENTS.md

给在本仓库里工作的 AI 助手看的约定。日常开发照常进行；下面主要说明两件常做的事：
**同步上游**和**打飞牛 fpk 包**。

## 仓库与 remote

- `origin`：`https://github.com/redrohu/workbuddy-manager.git`，本 fork，推送到 `origin/main`。
- `upstream`：`https://github.com/ithtelab/workbuddy-manager.git`，只拉取，不推送。
- 新机器上如果没有 `upstream`：`git remote add upstream https://github.com/ithtelab/workbuddy-manager.git`
- 环境：Windows + PowerShell，回复用中文。

## 同步上游

1. 先确认工作区干净（`git status`）。不干净时先 `git stash`，或先提交，不要带着未提交改动合并。
2. `git fetch upstream`，然后 `git log --oneline main..upstream/main` 看有哪些新提交。
3. `git merge upstream/main`。
4. 解决冲突的原则：
   - **业务逻辑以上游为准**：先取上游版本（`git checkout --theirs <文件>`），再把本地改动重新套上去。
   - 本地需要保留的改动主要有：
     - 前端字号从 px 改成 rem（`text-[11px]` 之类改为 rem 写法）；上游新增的代码里出现 px 字号时也一并改成 rem；
     - 图表字号常量 `CHART_TICK_FONT`、`CHART_TIP_FONT`；
     - fpk 打包相关文件：`deploy/fpk/`、`dev/build_fpk.py`、`dev/check_fpk.py`。
   - `CHANGELOG.md` 两边的内容都保留。
5. 合并完先跑测试（见下一节），通过后再提交并推送到 `origin/main`。

## 测试

```powershell
# 前端
cd web
node --test lib/*.test.mjs
npx tsc --noEmit
cd ..

# 后端
python -m pytest server/tests -q
```

- 前端的 node 测试和 tsc 必须全部通过。
- 后端目前有 **13 个已知失败**，在干净的上游代码上同样失败，不算本次改动造成的回归：
  - 10 个：node 输出 `MODULE_TYPELESS_PACKAGE_JSON` 警告，测试因此找不到 “all passed”；
  - `test_docker_deploy`；
  - `test_gateway_error_contract`（期望 404，实际返回 405）；
  - `test_readme_i18n`。
- 判断是否引入回归：拿失败列表和合并前（或 `upstream/main`）的结果对比，只看新增的失败。
- 改 `.ps1` 文件时保存为 **UTF-8 带 BOM**（Windows PowerShell 5.1 需要），否则 `test_windows_scripts` 会失败；可用 `dev/add-ps1-bom.ps1` 批量补上。

## 打飞牛 fpk 包

详细说明见 `deploy/fpk/README.md`。常用流程：

```powershell
cd web; npm run build:export; cd ..          # 改了前端就必须重新构建
python dev/build_fpk.py --version <版本号>
python dev/check_fpk.py dist/wbmgr-<版本号>.fpk --ref _fpk/wbmgr.fpk
```

- **只打 arm（aarch64）包，不打 x86。** 包结构不要求与 FnDepot 里的包完全一致，能装、能用即可。
- **版本号必须高于已发布的版本**，否则飞牛不会当作升级。打包前先查 NAS 上已安装的版本，以及
  [FnDepot](https://github.com/mingk326/FnDepot) 的 `fnpack.json` 里 wbmgr 的最新版本，再用 `--version` 指定
  （或用 `--bump patch` 在 `server/main.py` 的版本上递增）。
- `--version` 只修改包的版本号，不会改 `server/main.py`。
- 打包素材缓存在 `dev/.fpk-cache/`（不进版本库）：aarch64 的 `wb2api`、cpython 3.12 运行时、`wheels/`、
  `upstream-scripts/`。缺素材时按 README 说明补齐，首次打包可加 `--fetch-python`。
- `check_fpk.py` 最后一行是「✓ 全部校验通过」才算打包成功。向用户汇报时给出 fpk 路径、大小和 sha256，
  并说明是否已在 NAS 上实际安装验证过。
- `dist/`、`_fpk/` 是产物和参考包，不要提交。

## 不需要做的事

- 不打 x86 包。
- 不自动修改 FnDepot 的 `fnpack.json`，也不自动发布 Release，除非用户明确要求。
- 不向 `upstream` 推送。
