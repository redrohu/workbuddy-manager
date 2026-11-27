"""把本项目打成飞牛 OS（fnOS）可安装的 fpk 包。

## 为什么需要一个脚本，而不是一条 tar 命令

fpk 是「fnOS 应用包」：外层是 tar.gz，里面固定放着 `manifest`、`cmd/`、`config/`、
`wizard/`、`APP.tgz` 这套东西，**任何一项缺失或路径写错，安装器只给一句
「安装失败」，不说是哪一步**。所以这里把整条链路做成一条命令，并对每个易错点
做显式校验（见 `main()` 里的 `_check_*`）。

## 包内结构（与参考包 wbmgr.fpk 对齐）

    wbmgr.fpk                     外层 tar.gz
    ├── manifest                  应用元信息（含 app.tgz 的 md5）
    ├── ICON.PNG / ICON_256.PNG   256×256 图标
    ├── cmd/                      安装/启动/停止/升级/卸载 钩子
    ├── config/                   privilege（以 package 用户运行）、resource（共享目录）
    ├── wizard/                   安装 / 设置 / 卸载 向导表单
    └── app.tgz                   实际程序（下面这层）
        ├── VERSION / LICENSE-*
        ├── bin/                  gen-config.sh、run-manager.sh、up-*.sh、wb2api
        ├── config.example.json   上游配置模板
        ├── runtime/py.tar.gz     内置 CPython（aarch64）
        ├── wheels/               全部依赖的 aarch64 wheel（离线安装）
        ├── manager/              server/ + out/（前端产物）+ requirements.txt
        └── upstream-scripts/     上游 Python 任务脚本

## 为什么要内置 Python 与 wheel

fnOS 上不保证有 Python，版本也不可控；`run-manager.sh` 在首次启动时把
`runtime/py.tar.gz` 解到私有目录，再用 `--no-index --find-links wheels`
离线装依赖。所以**打进来的 wheel 必须是 aarch64 的**——在 x86 机器上热热闹闹
打出来的包拿到 NAS 上是起不来的（那些 wheel 平台标签不匹配，pip 会报
`No matching distribution`）。本脚本默认按 `--platform aarch64` 解析 wheel，
并在打包前核对每个 wheel 的平台标签。

## 用法

    # 常用：前端产物齐全、上游二进制已缓存 → 一条命令
    python dev/build_fpk.py

    # 首次 / 换版本：显式指定版本号与上游二进制
    python dev/build_fpk.py --version 2.11.29 --upstream-bin D:/path/wb2api

    # 只校验不写包
    python dev/build_fpk.py --check

前置：
  · `web/out` 已构建（`cd web && npm run build:export`）；
  · aarch64 的上游二进制 `wb2api`（11 MB ELF，脚本会校验 `e_machine=183`）；
  · 内置 Python 运行时 `py.tar.gz`（aarch64 CPython 3.12，约 28 MB）。
    第一次用 `--fetch-python` 自动下载（需要网络），之后复用缓存。

产物默认写 `dist/wbmgr-<version>.fpk`。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
SERVER = ROOT / 'server'
TEMPLATE = ROOT / 'deploy' / 'fpk'
CACHE = ROOT / 'dev' / '.fpk-cache'
DIST = ROOT / 'dist'

# 应用标识：与参考包一致，升级时才会被识别成「同一个应用」。
APPNAME = 'wbmgr'
DISPLAY_NAME = 'WorkBuddy Manager'

# 内置 Python：aarch64 CPython 3.12（install_only = 只有解释器与标准库）。
PY_URL = ('https://github.com/astral-sh/python-build-standalone/releases/download/'
          '20261124/cpython-3.12.16+20261124-aarch64-unknown-linux-gnu-install_only.tar.gz')
PY_CACHE_NAME = 'cpython-3.12.16-aarch64-install_only.tar.gz'

# 目标平台。fnOS 的盒子绝大多数是 arm64（N100/J4125 那批 x86 机型另说），
# 参考包 manifest 里写的就是 platform = arm。
TARGET_PLATFORM = 'arm'
WHEEL_PLATFORMS = [
    'manylinux2014_aarch64',
    'manylinux_2_17_aarch64',
    'manylinux_2_28_aarch64',
    'manylinux_2_27_aarch64',
]
PY_TAG = ('3.12', 'cp312')

# 归档格式。参考包（能被 fnOS 安装器正常处理的那两个）都是 **GNU 老式 tar**
# （magic `ustar  \0`）；Python tarfile 的 'w:gz' 默认写 POSIX/PAX（`ustar\000`）。
# 用 GNU_FORMAT 复现参考包，不去赌安装器的兼容性。
TAR_FORMAT = tarfile.GNU_FORMAT


# ── 小工具 ────────────────────────────────────────────────

def _log(msg: str) -> None:
    print(f'· {msg}')


def _warn(msg: str) -> None:
    print(f'! {msg}', file=sys.stderr)


def _die(msg: str) -> None:
    print(f'✗ {msg}', file=sys.stderr)
    raise SystemExit(1)


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8').replace('\r\n', '\n')


def _version() -> str:
    """版本号：以 server/main.py 的 app.version 为准（界面「关于」也用它）。"""
    src = _read_text(SERVER / 'main.py')
    m = re.search(r"version='([^']+)'", src)
    if not m:
        _die("server/main.py 里找不到 version='...'：版本号从哪来？")
    return m.group(1)


# ── 平台校验 ──────────────────────────────────────────────

ELF_MACHINE = {62: 'x86_64', 183: 'aarch64'}


def _elf_arch(path: Path) -> str:
    with path.open('rb') as fh:
        head = fh.read(20)
    if head[:4] != b'\x7fELF':
        _die(f'{path.name} 不是 ELF 文件')
    machine = struct.unpack('<H', head[18:20])[0]
    return ELF_MACHINE.get(machine, f'unknown({machine})')


def _wheel_tags(name: str) -> set[str]:
    """从 wheel 文件名里取平台标签（第三段之后的 aarch64… 那部分）。"""
    parts = name[:-4].split('-') if name.endswith('.whl') else name.split('-')
    tags: set[str] = set()
    for part in parts:
        for piece in part.split('.'):
            if 'aarch64' in piece or 'x86_64' in piece or 'armv7' in piece:
                tags.add(piece)
    return tags


def _tar_safe_filter(member: tarfile.TarInfo, dest: str):  # pragma: no cover
    return member


# ── 目标平台的标记环境 ────────────────────────────────────
#
# 为什么需要它：`pip download --platform …` 只影响**挑哪个 wheel**，不影响
# `Requires-Dist` 里的**环境标记**——那些标记仍按**宿主**求值。于是
# `uvicorn[standard]` 的 `uvloop; sys_platform != "win32"` 在 Windows 上被判定为
# 「不需要」，这个包就永远进不来；拿到 NAS 上首次启动时 pip 才报
# `No matching distribution found for uvloop`，而那时用户已经装完、只看到「启动失败」。
#
# 修法：下载完之后，把每个 wheel 的 METADATA 读一遍，用**目标环境**重新求值
# `Requires-Dist` 的 extra 分支，把漏掉的再下一轮。这样不依赖硬编码包名，
# 将来 requirements 换成别的带平台分支的库也一样覆盖。
TARGET_MARKER_ENV = {
    'implementation_name': 'cpython',
    'implementation_version': '3.12.16',
    'os_name': 'posix',
    'platform_machine': 'aarch64',
    'platform_release': '',
    'platform_system': 'Linux',
    'platform_version': '',
    'python_full_version': '3.12.16',
    'platform_python_implementation': 'CPython',
    'python_version': '3.12',
    'sys_platform': 'linux',
}


def _extra_names(requirement: str) -> list[str]:
    """从 `uvicorn[standard]>=0.30` 里取出 extras 名字（保留给调用方复用）。"""
    m = re.match(r'^\s*([A-Za-z0-9_.\-]+)\s*\[([^\]]+)\]', requirement)
    if not m:
        return []
    return [e.strip().lower() for e in m.group(2).split(',') if e.strip()]


def _required_for_target(metadata_text: str) -> dict[str, set[str]]:
    """读 METADATA，返回 {包名: {需要它的 extra 名}} —— 只保留目标平台成立的项。"""
    from packaging.markers import Marker, default_environment
    from packaging.requirements import Requirement

    out: dict[str, set[str]] = {}
    for line in metadata_text.splitlines():
        if not line.startswith('Requires-Dist:'):
            continue
        spec = line.split(':', 1)[1].strip()
        try:
            req = Requirement(spec)
        except Exception:      # noqa: BLE001  非标准行，跳过
            continue
        marker = req.marker
        if marker is None:
            continue
        # 找出这条依赖声明里涉及的 extra（`extra == "standard"` 之类）。
        # 只对「由某个 extra 引入」的依赖做补齐：无条件依赖 pip 已经按
        # --platform 正常处理过了，重复下一遍没有意义。
        candidates = set(re.findall(r'extra\s*==\s*["\']([^"\']+)["\']', spec))
        if not candidates:
            continue
        env_base = dict(default_environment())
        env_base.update(TARGET_MARKER_ENV)
        for extra in candidates:
            env_try = dict(env_base)
            env_try['extra'] = extra
            try:
                ok = Marker(str(marker)).evaluate(env_try)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                out.setdefault(_canon(req.name), set()).add(extra)
    return out


def _wheel_metadata(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if name.endswith('.dist-info/METADATA'):
                return zf.read(name).decode('utf-8', 'replace')
    return ''


def _canon(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def _fill_platform_gated(wheels: Path, requested_extras: dict[str, set[str]]) -> int:
    """补齐被宿主标记挡掉的依赖，返回补下几个。"""
    have = {_canon(n[:-4].split('-')[0]) for n in (p.name for p in wheels.glob('*.whl'))}
    need: dict[str, set[str]] = {}
    for whl in wheels.glob('*.whl'):
        meta = _wheel_metadata(whl)
        if not meta:
            continue
        pkg = _canon(whl.name[:-4].split('-')[0])
        extras = requested_extras.get(pkg)
        if not extras:
            continue
        for dep, dep_extras in _required_for_target(meta).items():
            if dep in have:
                continue
            # 只有当我们确实请求了那个 extra 时才算
            if dep_extras & extras:
                need.setdefault(dep, set()).update(dep_extras)
    if not need:
        return 0

    _log(f'补下被宿主平台标记漏掉的依赖：{sorted(need)}')
    cmd = [sys.executable, '-m', 'pip', 'download', '--only-binary=:all:',
           '--python-version', PY_TAG[0], '--implementation', 'cp',
           '--abi', PY_TAG[1], '-d', str(wheels)]
    for plat in WHEEL_PLATFORMS:
        cmd += ['--platform', plat]
    cmd += sorted(need)
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    if proc.returncode != 0:
        _die('补齐依赖失败：' + (proc.stderr or proc.stdout or '')[-800:])
    return len(need)


# ── 各段校验 ──────────────────────────────────────────────

def _check_web_out() -> None:
    index = WEB / 'out' / 'index.html'
    if not index.is_file():
        _die('缺 web/out（前端产物）。先执行：cd web && npm run build:export')
    css = list((WEB / 'out' / '_next' / 'static' / 'css').glob('*.css'))
    if not css:
        _die('web/out 里没有 CSS —— 产物不完整')
    # 目录里必须带上本次的字号设置样式，否则说明产物是旧的（改完没重新构建）
    if not any('--wb-font-scale' in p.read_text(encoding='utf-8', errors='ignore')
               for p in css):
        _die('web/out 是旧产物：CSS 里没有 --wb-font-scale。'
             '改过前端就要重新 `npm run build:export`')
    _log(f'前端产物 OK（{len(css)} 个 CSS，含字号设置样式）')


def _check_ui() -> None:
    """校验 ui/ 桌面入口。

    这不是个「有更好」的目录：`desktop_uidir = ui` 指向它，飞牛靠它把应用图标
    画到桌面上。缺了它包照样能装、能在应用中心点开，但**桌面没有图标**，
    且安装过程不报错。这里提前拦住，别等装到 NAS 上才发现。
    """
    import json

    ui = TEMPLATE / 'ui'
    cfg_path = ui / 'config'
    if not cfg_path.is_file():
        _die('缺 deploy/fpk/ui/config —— 桌面图标入口缺失，装完飞牛桌面上不会出现应用图标')
    try:
        cfg = json.loads(_read_text(cfg_path))
    except json.JSONDecodeError as exc:
        _die(f'deploy/fpk/ui/config 不是合法 JSON：{exc}')
    entry = cfg.get('.url', {}).get(f'{APPNAME}.Application')
    if not isinstance(entry, dict):
        _die(f'deploy/fpk/ui/config 里没有 .url.{APPNAME}.Application 条目')
    if entry.get('type') != 'url':
        _die(f'ui/config 的 type 必须是 "url"，当前是 {entry.get("type")!r}')
    # 端口必须用向导变量，否则改名端口后桌面图标会指向旧端口
    if entry.get('port') != '${port}':
        _die(f'ui/config 的 port 必须是 "${{port}}"，当前是 {entry.get("port")!r}')
    for size in ('64', '256'):
        icon = ui / 'images' / f'icon_{size}.png'
        if not icon.is_file():
            _die(f'缺桌面图标 deploy/fpk/ui/images/icon_{size}.png')
    _log('ui/ 桌面入口 OK（.url 条目、端口占位、图标齐备）')


def _check_server() -> None:
    required = ('main.py', 'serve.py', 'config.py', 'requirements.txt')
    missing = [n for n in required if not (SERVER / n).is_file()]
    if missing:
        _die(f'server/ 缺关键文件：{missing}')
    reqs = _read_text(SERVER / 'requirements.txt')
    if 'psycopg[binary]' not in reqs:
        _warn('server/requirements.txt 里没有 psycopg[binary]：异地备份功能会缺驱动')
    _log('server/ OK')


def _resolve_upstream_bin(explicit: str | None) -> Path:
    """找 aarch64 的下游网关二进制。

    为什么不从源码编：上游是 Go 项目、需要其源码（本项目不打包上游代码）。
    这里只接受**已经拿到的**二进制：显式传参 > dev/.fpk-cache/wb2api >
    参考包里那份（若有）。校验 ELF 架构，避免 x86 的混进去。
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(CACHE / 'wb2api')
    for p in candidates:
        if p.is_file():
            arch = _elf_arch(p)
            if arch != 'aarch64':
                _die(f'{p} 是 {arch} 的二进制，fnOS 包需要 aarch64。'
                     '换一份 arm64 的 wb2api（或用 --upstream-bin 指定）')
            _log(f'下游网关二进制 OK（aarch64，{p.stat().st_size / 1048576:.1f} MB）')
            return p
    _die(
        '找不到 aarch64 的 wb2api 二进制。\n'
        '  放一份到 dev/.fpk-cache/wb2api，或用 --upstream-bin 指定。\n'
        '  它来自上游发布包（workbuddy2api 的 arm64 构建），本项目不重新编译上游。'
    )
    raise AssertionError('unreachable')


def _resolve_python(fetch: bool) -> Path:
    """内置 Python 运行时（aarch64、install_only 布局）。"""
    cached = CACHE / PY_CACHE_NAME
    if cached.is_file():
        _log(f'内置 Python 运行时 OK（{cached.stat().st_size / 1048576:.1f} MB）')
        return cached
    if not fetch:
        _die(
            f'缺内置 Python 运行时 {cached}。\n'
            '  第一次打包请加 --fetch-python（会从 python-build-standalone 下载\n'
            f'  {PY_URL}）'
        )
    CACHE.mkdir(parents=True, exist_ok=True)
    _log('下载内置 Python 运行时（aarch64 CPython 3.12，约 53 MB）…')
    tmp = cached.with_suffix('.part')
    with urllib.request.urlopen(PY_URL, timeout=120) as resp, tmp.open('wb') as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(cached)
    _log(f'下载完成（{cached.stat().st_size / 1048576:.1f} MB）')
    return cached


def _requested_extras(requirements: Path) -> dict[str, set[str]]:
    """requirements.txt 里显式请求了哪些 extra（`uvicorn[standard]>=0.30`）。"""
    from packaging.requirements import Requirement

    out: dict[str, set[str]] = {}
    for raw in _read_text(requirements).splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        try:
            req = Requirement(line)
        except Exception:   # noqa: BLE001
            continue
        if req.extras:
            out[_canon(req.name)] = {e.lower() for e in req.extras}
    return out


def _resolve_wheels() -> Path:
    """解析出全部依赖的 aarch64 wheel；已缓存且标签正确就直接复用。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    wheels = CACHE / 'wheels'
    marker = wheels / '.ok'
    extras = _requested_extras(SERVER / 'requirements.txt')

    if marker.is_file():
        names = sorted(p.name for p in wheels.glob('*.whl'))
        bad = [n for n in names if any('x86_64' in t or 'armv7' in t
                                       for t in _wheel_tags(n))]
        if names and not bad:
            _log(f'依赖 wheel 缓存 OK（{len(names)} 个，全部 aarch64/纯 Python）')
            added = _fill_platform_gated(wheels, extras)
            if added:
                marker.write_text(
                    '\n'.join(sorted(p.name for p in wheels.glob('*.whl'))),
                    encoding='utf-8')
                _log(f'  补下 {added} 个，现共 '
                     f'{len(list(wheels.glob("*.whl")))} 个 wheel')
            return wheels

    wheels.mkdir(parents=True, exist_ok=True)
    marker.unlink(missing_ok=True)
    for old in wheels.glob('*.whl'):
        old.unlink()

    _log('解析依赖 wheel（aarch64，离线安装用）…')
    cmd = [
        sys.executable, '-m', 'pip', 'download',
        '--only-binary=:all:',
        '--python-version', PY_TAG[0],
        '--implementation', 'cp',
        '--abi', PY_TAG[1],
        '-d', str(wheels),
    ]
    for plat in WHEEL_PLATFORMS:
        cmd += ['--platform', plat]
    cmd += ['-r', str(SERVER / 'requirements.txt')]

    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or '')[-1500:]
        _die(f'依赖解析失败：\n{tail}')

    # 关键一步：补上被**宿主**平台标记挡掉的依赖（见 TARGET_MARKER_ENV 的说明）
    added = _fill_platform_gated(wheels, extras)
    if added:
        _log(f'  补下 {added} 个被宿主标记漏掉的依赖')

    names = sorted(p.name for p in wheels.glob('*.whl'))
    if not names:
        _die('依赖解析后没有 wheel —— pip 的行为变了？')
    bad = [n for n in names if any('x86_64' in t or 'armv7' in t
                                   for t in _wheel_tags(n))]
    if bad:
        _die(f'解析出 {len(bad)} 个非 aarch64 的 wheel：{bad[:3]}')
    marker.write_text('\n'.join(names), encoding='utf-8')
    _log(f'依赖解析完成（{len(names)} 个 wheel）')
    return wheels


def _find_upstream_scripts() -> Path | None:
    """上游的 Python 任务脚本（面板「成长任务」要执行）。

    仓库里不存上游代码，所以这里只在缓存/参考位置找；找不到就**不静默跳过**，
    而是明确告知包内会少这个目录及其后果。
    """
    for cand in (CACHE / 'upstream-scripts', ROOT / 'upstream' / 'scripts'):
        if cand.is_dir() and any(cand.glob('*.py')):
            _log(f'上游任务脚本 OK（{cand}）')
            return cand
    _warn('没有上游任务脚本目录（upstream-scripts）。包内会缺 task_runner.py 等，'
          '面板的「成长任务 / 一键领奖」在 NAS 上会报找不到脚本。'
          '把上游源码里的 scripts/ 放到 dev/.fpk-cache/upstream-scripts/ 再打包。')
    return None


# ── 组装 ──────────────────────────────────────────────────

# 本次打包已写过的目录成员。tar 不要求目录先于文件出现，但**参考包里
# `ui/`、`manager/out/`、`wheels/` 都是显式条目**；补齐它们，
# 解包后的目录归属与权限才与参考包一致（而不是靠 tar 自动补全）。
_SEEN_DIRS: set[str] = set()


def _add_dir(tf: tarfile.TarFile, name: str) -> None:
    name = name.rstrip('/')
    if not name or name in _SEEN_DIRS:
        return
    _SEEN_DIRS.add(name)
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    info.mtime = 0
    tf.addfile(info)


def _ensure_parents(tf: tarfile.TarFile, name: str) -> None:
    """把 `a/b/c.txt` 的 `a`、`a/b` 目录成员按层级补上。"""
    parts = name.split('/')[:-1]
    for i in range(1, len(parts) + 1):
        _add_dir(tf, '/'.join(parts[:i]))


def _add(tf: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644) -> None:
    _ensure_parents(tf, name)
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    info.mtime = 0                      # 归一：同内容两次打包逐字节一致
    tf.addfile(info, io.BytesIO(data))


def _add_file(tf: tarfile.TarFile, name: str, path: Path, mode: int = 0o644,
              *, lf: bool = False) -> None:
    """写一个文件进 tar。

    `lf=True` 用于**脚本**：把 CRLF 压成 LF。钩子文件（`cmd/main` 等）没有扩展名，
    `.gitattributes` 的 `*.sh eol=lf` 管不到它们；而 CRLF 的 bash 脚本在 Linux 上
    会报 `bad interpreter: /bin/bash^M`——在 Windows 本机完全看不出来。

    文本类文件一律走 LF 归一（见 `_add_tree` 的 `TEXT_EXTS`）：包是在 Linux 上跑的，
    仓库在 Windows 上是 CRLF。后端 .py 带 CRLF 虽然 Python 也能解析，但
    `import` 出来的一致性、以及和参考包逐字节比对都会出岔子，索性统一成 LF。
    """
    data = path.read_bytes()
    if lf:
        data = data.replace(b'\r\n', b'\n')
    _add(tf, name, data, mode)


# 进包前必须转成 LF 的文本类扩展名。二进制（.whl/.png/.so/.tar.gz）不在其中，
# 它们里的 0x0D0A 是数据，替换会直接损坏文件。
TEXT_EXTS = frozenset({
    '.py', '.txt', '.md', '.json', '.sh', '.cfg', '.ini', '.yaml', '.yml',
    '.js', '.mjs', '.css', '.html', '.map', '.svg', '.tsv', '.csv', '',
})


def _add_tree(tf: tarfile.TarFile, arc_prefix: str, src: Path,
              skip: tuple[str, ...] = (), exts: tuple[str, ...] | None = None) -> int:
    """按路径排序把一棵树写进 tar（顺序稳定 → 产物可复现）。

    文本类文件按 `TEXT_EXTS` 自动做 LF 归一；二进制原样写入。
    """
    count = 0
    # 根目录自身也要有成员：参考包里 `ui/`、`manager/out/` 都是显式条目。
    if arc_prefix:
        _add_dir(tf, arc_prefix)
    for p in sorted(src.rglob('*'), key=lambda x: x.relative_to(src).as_posix()):
        rel = p.relative_to(src).as_posix()
        if any(part in skip for part in p.parts):
            continue
        if exts and p.is_file() and p.suffix not in exts:
            continue
        arc = f'{arc_prefix}/{rel}' if arc_prefix else rel
        if p.is_dir():
            _add_dir(tf, arc)
            continue
        if p.is_file():
            is_text = p.suffix.lower() in TEXT_EXTS
            _add_file(tf, arc, p, lf=is_text)
            count += 1
    return count


def _build_app_tgz(path: Path, *, upstream_bin: Path, python_rt: Path,
                   wheels: Path, upstream_scripts: Path | None,
                   version: str) -> None:
    with tarfile.open(path, 'w:gz', compresslevel=9, format=TAR_FORMAT) as tf:
        _SEEN_DIRS.clear()
        # 顶层杂项
        # VERSION 是**上游协议版本**（不是本包版本），与参考包保持一致。
        _add(tf, 'VERSION', b'2.11.21\n')
        _add_file(tf, 'LICENSE-manager', ROOT / 'LICENSE', lf=True)
        # 上游是另一个项目（Sliverkiss 的 workbuddy2api），许可证要如实署名，
        # 不能拿管理端自己的 MIT 顶替——那是错标的版权声明。
        _add_file(tf, 'LICENSE-upstream', TEMPLATE / 'LICENSE-upstream')
        _add_file(tf, 'config.example.json', TEMPLATE / 'config.example.json')

        # bin/：脚本 0755，二进制 0755
        for name in ('gen-config.sh', 'run-manager.sh', 'up-noop.sh',
                     'up-start.sh', 'up-stop.sh', 'up-watch.sh'):
            _add_file(tf, f'bin/{name}', TEMPLATE / 'bin' / name, 0o755, lf=True)
        _add_file(tf, 'bin/wb2api', upstream_bin, 0o755)

        # ui/：桌面图标入口。manifest 里的 `desktop_uidir = ui` 指的就是它——
        # 缺了目录，包能装上、应用中心里能开，但**飞牛桌面上不会出现图标**，
        # 而且安装过程不报任何错，非常难查。所以这里必须打进去。
        n = _add_tree(tf, 'ui', TEMPLATE / 'ui')
        _log(f'  打包 ui/（桌面图标入口）：{n} 个文件')

        # runtime / wheels
        _add_file(tf, 'runtime/py.tar.gz', python_rt)
        for whl in sorted(wheels.glob('*.whl')):
            _add_file(tf, f'wheels/{whl.name}', whl)

        # manager/：server + 前端产物 + requirements + .version
        n = _add_tree(tf, 'manager/server', SERVER,
                      skip=('__pycache__', '.pytest_cache'))
        _log(f'  打包 server/：{n} 个文件')
        _add_file(tf, 'manager/server/CHANGELOG.md', ROOT / 'CHANGELOG.md', lf=True)
        _add_file(tf, 'manager/server/deploy/update.py',
                  ROOT / 'deploy' / 'update.py', lf=True)
        _add_file(tf, 'manager/requirements.txt', SERVER / 'requirements.txt', lf=True)
        _add(tf, 'manager/.version', f'v{version}\n'.encode())
        # manager/data：运行期挂载点（空目录必须存在，run-manager 会往里写）
        _add_dir(tf, 'manager/data')

        out_dir = WEB / 'out'
        n = _add_tree(tf, 'manager/out', out_dir)
        _log(f'  打包 web/out：{n} 个文件')

        if upstream_scripts is not None:
            n = _add_tree(tf, 'upstream-scripts', upstream_scripts)
            _log(f'  打包 upstream-scripts：{n} 个文件')


def _build_manifest(app_tgz_md5: str, version: str, changelog: str) -> bytes:
    desc = (
        '<p>WorkBuddy Manager —— 腾讯 CodeBuddy 账号池管理控制台，内置 OpenAI 兼容反代网关。</p>'
        '<p>面板：http://NAS-IP:7864/ （安装时可改端口）。支持扫码纳管、定时签到保活、'
        '多密钥分发、IP 与模型白名单、调用日志与用量统计。</p>'
        '<p>本包为原生 fpk：内置 Python 运行时、上游 workbuddy2api 二进制与 scripts 任务脚本，'
        '不依赖 Docker、不需要系统 Python。自带网关固定监听 127.0.0.1:7865，并带掉线自愈守护。</p>'
        '<p>账号与用量数据存放在应用共享目录：文件管理 → 应用文件 → wbmgr'
        '（data/manager.db、upstream/），可直接查看和删除；升级自动迁移旧数据。</p>'
        '<p>自带网关默认仅监听 127.0.0.1:7865，可在安装 / 设置向导改为 0.0.0.0:7865 '
        '供局域网直接调用；务必注意网关密钥与防火墙，不要暴露到公网。</p>'
    )
    lines = [
        f'appname                    = {APPNAME}',
        f'version                    = {version}',
        f'display_name               = {DISPLAY_NAME}',
        f'desc                       = {desc}',
        f'platform                   = {TARGET_PLATFORM}',
        'source                     = thirdparty',
        'maintainer                 = ithtelab',
        'maintainer_url             = https://github.com/ithtelab/workbuddy-manager',
        'distributor                = mingk326',
        'distributor_url            = https://github.com/mingk326/FnDepot',
        'ctl_stop                   = true',
        'desktop_uidir              = ui',
        f'desktop_applaunchname      = {APPNAME}.Application',
        'checkport                  = true',
        'disable_authorization_path = true',
        f'changelog                  = {changelog}',
        f'checksum                   = {app_tgz_md5}',
    ]
    return ('\n'.join(lines) + '\n').encode('utf-8')


def _changelog_for(version: str) -> str:
    """取 CHANGELOG 里该版本的段落作为 manifest 的 changelog（单行）。

    优先用 `[未发布]`：发版时那一段会被改名为版本号，所以它非空就意味着「这个版本
    是已发布的旧版本 + 树上还有没发出去的新改动」。此时若直接取同名版本段落，装包
    界面会拿旧版本的说明来介绍新功能（实测就发生过：包里是新的字号设置，changelog
    却在讲上一个版本的 Docker 修复）。
    """
    text = _read_text(ROOT / 'CHANGELOG.md')

    def section(heading_re: str) -> str:
        m = re.search(rf'^{heading_re}.*?$(.*?)(?=^##\s*\[|\Z)', text, re.S | re.M)
        return m.group(1) if m else ''

    body = ''
    for pattern in (r'##\s*\[未发布\]', rf'##\s*\[{re.escape(version)}\]'):
        body = section(pattern)
        if body.strip():
            break

    # manifest 的 changelog 是**单行**值：去掉标题/空行/列表符号，压成一段话。
    chunks: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or set(line) <= {'-', '#', '='}:
            continue
        if line.startswith('###'):
            continue
        line = re.sub(r'^[-*]\s*', '', line)
        line = line.replace('**', '').replace('`', '')
        chunks.append(line)
    joined = ' '.join(chunks)
    return joined or f'{DISPLAY_NAME} {version}'


def _build_outer(out_path: Path, *, app_tgz: Path, manifest: bytes) -> None:
    order = [
        'app.tgz',
        'cmd/', 'cmd/config_callback', 'cmd/install_callback', 'cmd/install_init',
        'cmd/main', 'cmd/uninstall_callback', 'cmd/uninstall_init',
        'cmd/upgrade_callback', 'cmd/upgrade_init',
        'config/', 'config/privilege', 'config/resource',
        'wizard/', 'wizard/config', 'wizard/install', 'wizard/uninstall',
        'ICON.PNG', 'ICON_256.PNG', 'manifest',
    ]
    with tarfile.open(out_path, 'w:gz', compresslevel=9, format=TAR_FORMAT) as tf:
        _SEEN_DIRS.clear()
        for name in order:
            if name == 'app.tgz':
                _add_file(tf, 'app.tgz', app_tgz)
            elif name == 'manifest':
                _add(tf, 'manifest', manifest)
            elif name in ('ICON.PNG', 'ICON_256.PNG'):
                _add_file(tf, name, TEMPLATE / name)
            elif name.endswith('/'):
                _add_dir(tf, name)
            else:
                mode = 0o755 if name.startswith('cmd/') else 0o644
                _add_file(tf, name, TEMPLATE / name, mode,
                          lf=name.startswith('cmd/'))


# ── 入口 ──────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description='把本项目打成 fnOS 可安装的 fpk',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('--version', default=None,
                    help='包版本（默认读 server/main.py 的 app.version；'
                         '--bump 可自动递增）')
    ap.add_argument('--bump', choices=('patch', 'minor', 'major'), default=None,
                    help='把版本号递增。fnOS 只在包版本**高于**已装版本时才当升级处理，'
                         '同版本或更低会被拒绝或当成重装')
    ap.add_argument('--upstream-bin', default=None,
                    help='aarch64 的下游网关二进制 wb2api')
    ap.add_argument('--fetch-python', action='store_true',
                    help='缺内置 Python 运行时则自动下载')
    ap.add_argument('--check', action='store_true', help='只做校验，不写包')
    ap.add_argument('-o', '--output-dir', default=str(DIST),
                    help=f'产物目录（默认 {DIST}）')
    args = ap.parse_args()

    version = (args.version or _version()).lstrip('v')
    if args.bump:
        major, minor, patch = (int(x) for x in version.split('.')[:3])
        if args.bump == 'major':
            major, minor, patch = major + 1, 0, 0
        elif args.bump == 'minor':
            minor, patch = minor + 1, 0
        else:
            patch += 1
        version = f'{major}.{minor}.{patch}'
    _log(f'目标版本 {version}（platform={TARGET_PLATFORM}）')

    _check_web_out()
    _check_server()
    _check_ui()
    upstream_bin = _resolve_upstream_bin(args.upstream_bin)
    python_rt = _resolve_python(args.fetch_python)
    wheels = _resolve_wheels()
    upstream_scripts = _find_upstream_scripts()

    if args.check:
        _log('校验全部通过（--check 未写包）')
        return 0

    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'{APPNAME}-{version}.fpk'

    with tempfile.TemporaryDirectory(prefix='wb-fpk-') as tmp:
        tmpdir = Path(tmp)
        app_tgz = tmpdir / 'app.tgz'
        _log('组装 app.tgz …')
        _build_app_tgz(app_tgz, upstream_bin=upstream_bin, python_rt=python_rt,
                       wheels=wheels, upstream_scripts=upstream_scripts,
                       version=version)
        _log(f'  app.tgz {app_tgz.stat().st_size / 1048576:.1f} MB')

        checksum = _md5(app_tgz)
        manifest = _build_manifest(checksum, version, _changelog_for(version))
        _log('组装外层 fpk …')
        _build_outer(out_path, app_tgz=app_tgz, manifest=manifest)

    size = out_path.stat().st_size / 1048576
    print()
    print(f'✓ {out_path}  ({size:.1f} MB)')
    print(f'  sha256 {hashlib.sha256(out_path.read_bytes()).hexdigest()}')
    print(f'  安装：fnOS 应用中心 → 手动安装 → 选择该文件')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
