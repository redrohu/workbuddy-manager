# 打包成飞牛 OS（fnOS）可安装的 fpk

本目录是 **fpk 的包骨架**：`manifest` 之外的固定结构都放在这里，由
`dev/build_fpk.py` 组装成最终安装包。想改启动逻辑、安装向导、默认端口，改这里的
文件即可，不需要碰打包脚本。

> 目前只打 **arm（aarch64）** 包。x86 的 fnOS 机型暂不提供，也装不了本包。

## 第一次打包前的准备

打包用的素材缓存在 `dev/.fpk-cache/`（已在 `.gitignore` 里，不进版本库）：

| 文件 | 怎么来 | 缺了会怎样 |
|---|---|---|
| `wb2api` | aarch64 的上游网关二进制，放进缓存目录，或打包时用 `--upstream-bin <路径>` 指定 | 报「找不到 aarch64 的 wb2api 二进制」；放错架构会报「是 x86_64 的二进制」 |
| `cpython-3.12.16-aarch64-install_only.tar.gz` | 第一次打包加 `--fetch-python` 自动下载（需联网，约 28 MB） | 报缺内置 Python 运行时 |
| `wheels/` | 打包时按 `server/requirements.txt` 自动解析下载，之后复用 | 需联网；缓存里混进非 aarch64 的 wheel 会直接报错 |
| `upstream-scripts/` | 上游任务脚本（可选），找不到时退而用仓库里的 `upstream/scripts` | 包照样能装，只是缺上游自带的成长任务脚本 |

另外需要 Node.js（构建前端）和 Python 3.12（运行打包脚本）。

## 打包

```bash
# 1) 构建前端（改了前端代码就必须重跑；旧产物会被打包脚本拦下）
cd web && npm run build:export && cd ..

# 2) 打包。版本号默认取 server/main.py 的 version
python dev/build_fpk.py

#    指定包的版本号（只改包，不改仓库代码），或在原版本上自动递增
python dev/build_fpk.py --version 2.11.29
python dev/build_fpk.py --bump patch

#    只做打包前的检查，不生成文件
python dev/build_fpk.py --check
```

产物在 `dist/wbmgr-<版本>.fpk`（`-o` 可改输出目录），结尾会打印文件大小和 sha256。

## 校验

打完建议跑一遍，装不上时它会先指出问题：

```bash
python dev/check_fpk.py dist/wbmgr-2.11.29.fpk

# 手头有一个已知能装的包时，可以加 --ref 逐项对比外层结构
python dev/check_fpk.py dist/wbmgr-2.11.29.fpk --ref _fpk/wbmgr.fpk
```

它检查外层文件与权限、manifest 必需字段、checksum、内层必需文件、wb2api 与
wheel 的架构、后端换行、桌面入口和前端产物是否为新版。全部通过时最后一行是
「✓ 全部校验通过」。

## 安装与升级

1. 把 `.fpk` 拷到电脑上，打开 fnOS 应用中心 → 手动安装 → 选择该文件；
2. 首次安装按向导设置管理员密码与端口；
3. 装好后从飞牛桌面图标打开，或访问 `http://<NAS-IP>:7864/`（端口以向导里填的为准）。

**升级必须用更高的版本号。** fnOS 只在新包版本**高于**已装版本时才当作升级；
版本相同或更低会被拒绝，或被当成重装。打包前先确认 NAS 上装的是哪个版本
（也要看应用源里发布过的版本），不够高就用 `--version` 或 `--bump` 抬上去。

升级不会动共享目录里的数据（见下面第 6 条）；包内「一键更新」在 fpk 版里不适用，
更新统一走应用中心。

## 发布到第三方应用源（可选）

飞牛的第三方应用源（例如 [mingk326/FnDepot](https://github.com/mingk326/FnDepot)）
只放清单 `fnpack.json`、图标和说明，fpk 本身挂在 GitHub Release 上。发新版时：

1. 把 fpk 上传到该仓库的 Release；
2. 在 `fnpack.json` 对应应用的 `releases` 下加一条：`changelog`、`updated_at`，
   以及 `packages.arm` 的 `download_url`、`sha256`、`size`（打包结尾打印的
   sha256 与文件字节数）；
3. 推送后，在飞牛里刷新应用源即可看到新版本。

应用源里的命名、版本号和本仓库不必完全一致，只要版本号比已发布的高即可升级。

## 目录说明

```
deploy/fpk/
├── ICON.PNG / ICON_256.PNG   256×256 应用图标（两处用同一张）
├── cmd/                      安装器调用的钩子（以 bash 执行）
│   ├── main                  启动 / 停止 / 查状态（收到 start|stop|status）
│   ├── install_callback      装完：建共享目录、写网关监听地址
│   ├── config_callback       「应用设置」保存后：重写 .env 与 config.json
│   ├── upgrade_callback      升级后：清依赖标记，让下次启动按新包重装
│   ├── uninstall_callback    卸载：按向导选择保留或删除数据
│   └── *_init                各阶段的前置钩子（这里都是空实现）
├── config/
│   ├── privilege             run-as: package（不用 root 跑业务进程）
│   └── resource              声明共享目录 wbmgr（文件管理 → 应用文件 可见）
├── wizard/                   安装 / 设置 / 卸载 的表单向导
├── ui/                       桌面图标入口（manifest 的 desktop_uidir 指向这里）
│   ├── config                .url 条目：应用名、协议、端口占位 ${port}、图标路径
│   └── images/icon_{64,256}.png
└── bin/                      运行期脚本，原样进包内 bin/
    ├── gen-config.sh         生成 .env 与上游 config.json
    ├── run-manager.sh        解内置 Python、离线装依赖、启动管理端
    ├── up-start/stop.sh      自带网关的启停
    └── up-watch.sh           网关掉线自愈（30 秒巡检）
```

## 包内运行时布局

`dev/build_fpk.py` 会把这些东西装进 `app.tgz`：

| 包内路径 | 来源 | 说明 |
|---|---|---|
| `bin/wb2api` | `--upstream-bin` 或 `dev/.fpk-cache/wb2api` | aarch64 ELF，上游 Go 网关 |
| `runtime/py.tar.gz` | `dev/.fpk-cache/cpython-*.tar.gz` | 内置 CPython 3.12（aarch64） |
| `wheels/` | 由 `server/requirements.txt` 解析 | 全部 aarch64，供 `--no-index` 离线安装 |
| `manager/server/` | 仓库 `server/` | 管理端代码 |
| `manager/out/` | `web/out` | 前端静态产物 |
| `manager/server/deploy/update.py` | 仓库 `deploy/update.py` | 面板内「一键更新」用 |
| `upstream-scripts/` | `dev/.fpk-cache/upstream-scripts` | 上游任务脚本（可选） |
| `ui/` | 本目录 `ui/` | 桌面图标入口，缺了桌面上不显示应用 |
| `config.example.json` | 本目录 | 上游配置模板（首次启动据此生成） |

## 几个容易踩的坑

**1. wheel 必须是 aarch64 的。**
在 x86 机器上打出来的包拿到 NAS 上起不来，报 `No matching distribution found`。
`build_fpk.py` 会给 `pip download` 加 `--platform ...aarch64`，并逐个核对 wheel
文件名里的平台标签。

**2. `uvloop` 这类「只在 Linux 上装」的依赖会被静默漏掉。**
`pip download --platform` 只影响**挑哪个 wheel**，不影响 `Requires-Dist` 里的
**环境标记**——那些标记仍按**宿主**求值。于是 `uvicorn[standard]` 里的
`uvloop; sys_platform != "win32"` 在 Windows 上被判为「不需要」。
打包脚本会读每个 wheel 的 METADATA，用**目标环境**（linux/aarch64/cpython-3.12）
重新求值 extra 分支，把漏掉的补下一轮。这条以前真的漏过，表现是「装完启动失败」。

**3. 前端产物要是新的。**
`build_fpk.py` 会检查 `web/out` 的 CSS 里有没有本次的字号设置样式
（`--wb-font-scale`），旧产物直接报错，避免「打出来的包里界面还是旧版」。

**4. `manifest` 的 `checksum` 是内层 `app.tgz` 的 MD5**（不是整个 fpk 的）。
参考包实证如此；写错时安装器只报「安装失败」。

**5. 钩子脚本的换行必须是 LF。**
`.gitattributes` 已把 `*.sh` 锁成 LF；`deploy/fpk/cmd/*` 没有扩展名，所以
`build_fpk.py` 在打包时统一做换行归一（读进来替换 `\r\n`），不依赖 git 配置。

**6. 数据目录在共享目录，不在包里。**
`@appshare/wbmgr`（文件管理 → 应用文件 → wbmgr）存 `data/manager.db` 与
`upstream/`。升级不动它，卸载时按向导选择保留或删除。

**7. `ui/` 缺了，装完桌面上找不到应用。**
`manifest` 里 `desktop_uidir = ui`、`desktop_applaunchname = wbmgr.Application`，
飞牛据此到包内 `ui/config` 读 `.url` 条目，把图标画到桌面上。这个目录缺失时
**安装照样成功、应用中心里也能点开**，只是桌面上没有图标，安装器一句错都不报，
所以极难定位。`ui/config` 里的 `port` 必须写成 `${port}`（向导变量），写死数字
则改端口后桌面入口会指向旧端口。`build_fpk.py` 与 `check_fpk.py` 都会拦住这类问题。

## 换版本时要做的事

1. 改 `server/main.py` 的 `version='x.y.z'`（界面的「关于」读它）；
2. 在 `CHANGELOG.md` 里加该版本段落。`manifest` 的 changelog 优先取
   `[未发布]` 段，它为空时才取同名版本段；
3. `python dev/build_fpk.py --version x.y.z`。

只是想让 NAS 能升级、不打算正式发版时，可以只做第 3 步：`--version` 只改包的
版本号。代价是面板「关于」里显示的仍是 `server/main.py` 的版本号，两者会不一致。

## 在 x86 上验证 aarch64 包（可选）

`dev/fpk_runtest.sh` 会借助 qemu 在 WSL 里把包装起来真跑一遍（解压 → 装依赖 →
起服务 → 探 `/healthz`）。前置：

```bash
wsl -d Debian12 -- bash -lc 'apt-get install -y qemu-user-static libc6-arm64-cross libgcc-s1-arm64-cross'
```

然后用 WSL 跑该脚本。它证明的是「包内 Python 能跑、依赖装得上、服务起得来」，
这些恰恰是 fpk 装完最常见的失败点；装不上或起不来时，它比安装器那句
「安装失败」有用得多。

脚本假定包已经解到固定位置（外层在 `/root/fpktest/out`，`app.tgz` 解到
`/opt/fnos-sim/apps/wbmgr`），路径见脚本开头的变量，按需修改。

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 安装器只说「安装失败」 | 先跑 `dev/check_fpk.py`，结构、checksum、换行问题它都会指出来 |
| 装上了，但飞牛桌面上没有图标 | `ui/` 缺失或 `ui/config` 写错（见第 7 条）；`check_fpk.py` 会检查 |
| 装上了，但启动失败 | 多半是依赖没装上：wheel 架构不对或漏了依赖（见第 1、2 条）；可用 `dev/fpk_runtest.sh` 在本机复现 |
| 选了新包，应用中心不认为是升级 | 版本号不够高，见「安装与升级」 |
| 界面还是旧的 | 打包前没重新 `npm run build:export`；打包脚本会拦住缺字号样式的旧产物，但其他前端改动拦不住，改了前端就重建 |
