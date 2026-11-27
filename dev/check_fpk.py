"""校验打出来的 fpk 是否与参考包（可正常安装的 wbmgr.fpk）结构一致。

为什么值得单独有：fpk 装不上时，安装器只会给一句「安装失败」或干脆没反应，
不说是哪一项。这里把「结构对不对」变成可自动判定的东西——缺文件、路径写错、
权限位不对、checksum 对不上、内层包路径不匹配，都在打包后立刻暴露。

    python dev/check_fpk.py dist/wbmgr-2.11.23.fpk
    python dev/check_fpk.py dist/wbmgr-2.11.23.fpk --ref _fpk/wbmgr.fpk
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 参考包（能装的那个）的外层清单与权限
REQUIRED_FILES = {
    'app.tgz': 0o644,
    'manifest': 0o644,
    'ICON.PNG': 0o644,
    'ICON_256.PNG': 0o644,
    'cmd/main': 0o755,
    'cmd/install_callback': 0o755,
    'cmd/install_init': 0o755,
    'cmd/config_callback': 0o755,
    'cmd/upgrade_callback': 0o755,
    'cmd/upgrade_init': 0o755,
    'cmd/uninstall_callback': 0o755,
    'cmd/uninstall_init': 0o755,
    'config/privilege': 0o644,
    'config/resource': 0o644,
    'wizard/install': 0o644,
    'wizard/config': 0o644,
    'wizard/uninstall': 0o644,
}
REQUIRED_DIRS = ('cmd', 'config', 'wizard')

# 内层 app.tgz 必须有的东西（缺任何一个，装完起不来）
APP_REQUIRED = (
    'VERSION',
    'bin/gen-config.sh',
    'bin/run-manager.sh',
    'bin/up-start.sh',
    'bin/up-stop.sh',
    'bin/up-watch.sh',
    'bin/wb2api',
    'config.example.json',
    'runtime/py.tar.gz',
    'manager/requirements.txt',
    'manager/.version',
    'manager/server/main.py',
    'manager/server/serve.py',
    'manager/server/config.py',
    'manager/out/index.html',
    # 桌面图标入口：manifest 的 desktop_uidir = ui 指向它。缺了它包能装、
    # 应用中心能开，但飞牛桌面上没有图标，且安装不报错。
    'ui/config',
    'ui/images/icon_64.png',
    'ui/images/icon_256.png',
)

MANIFEST_KEYS = (
    'appname', 'version', 'display_name', 'desc', 'platform', 'source',
    'maintainer', 'maintainer_url', 'ctl_stop', 'desktop_uidir',
    'desktop_applaunchname', 'checkport', 'changelog', 'checksum',
)


def _fail(msg: str, errors: list[str]) -> None:
    errors.append(msg)
    print(f'  ✗ {msg}')


def _ok(msg: str) -> None:
    print(f'  ✓ {msg}')


def main() -> int:
    ap = argparse.ArgumentParser(description='校验 fpk 结构')
    ap.add_argument('fpk', help='要校验的 fpk')
    ap.add_argument('--ref', default=None, help='参考包（可选，用于对比清单）')
    args = ap.parse_args()

    path = Path(args.fpk)
    if not path.is_file():
        print(f'✗ 文件不存在：{path}', file=sys.stderr)
        return 1

    errors: list[str] = []
    size_mb = path.stat().st_size / 1048576
    print(f'校验 {path.name}（{size_mb:.1f} MB）')

    with tarfile.open(path, 'r:gz') as tf:
        members = {m.name: m for m in tf.getmembers()}

        # ── 外层结构 ──
        print('外层结构：')
        for name, mode in REQUIRED_FILES.items():
            m = members.get(name)
            if m is None:
                _fail(f'缺 {name}', errors)
                continue
            if not m.isfile():
                _fail(f'{name} 不是普通文件', errors)
                continue
            if m.mode & 0o777 != mode:
                _fail(f'{name} 权限是 {m.mode:04o}，应为 {mode:04o}', errors)
        for name in REQUIRED_DIRS:
            m = members.get(name)
            if m is None or not m.isdir():
                _fail(f'缺目录 {name}/', errors)
        if not errors:
            _ok(f'全部 {len(REQUIRED_FILES)} 个文件 + {len(REQUIRED_DIRS)} 个目录齐备，权限正确')

        # 与参考包对比清单（多出/缺少都报）
        if args.ref:
            ref_path = Path(args.ref)
            if ref_path.is_file():
                with tarfile.open(ref_path, 'r:gz') as rf:
                    ref_names = {m.name for m in rf.getmembers()}
                extra = sorted(set(members) - ref_names)
                missing = sorted(ref_names - set(members))
                if extra or missing:
                    _fail(f'与参考包清单不一致：多 {extra}；缺 {missing}', errors)
                else:
                    _ok('外层清单与参考包完全一致')

        # ── manifest ──
        print('manifest：')
        mf = members.get('manifest')
        if mf is None:
            _fail('缺 manifest', errors)
            meta: dict[str, str] = {}
        else:
            text = tf.extractfile(mf).read().decode('utf-8')
            meta = {}
            for line in text.splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    k, _, v = line.partition('=')
                    meta[k.strip()] = v.strip()
            missing_keys = [k for k in MANIFEST_KEYS if k not in meta]
            if missing_keys:
                _fail(f'manifest 缺字段：{missing_keys}', errors)
            else:
                _ok(f'{len(MANIFEST_KEYS)} 个必需字段齐备')

            # checksum 必须是内层 app.tgz 的 md5（参考包实证）
            app = members.get('app.tgz')
            if app is not None:
                actual = hashlib.md5(tf.extractfile(app).read()).hexdigest()
                if meta.get('checksum', '').lower() != actual:
                    _fail(f'manifest checksum 与 app.tgz 的 md5 不符'
                          f'（manifest={meta.get("checksum")} 实际={actual}）', errors)
                else:
                    _ok('checksum 与 app.tgz 的 md5 一致')
            if meta.get('platform') not in ('arm', 'x86'):
                _fail(f'platform 取值异常：{meta.get("platform")}', errors)
            if meta.get('appname') != 'wbmgr':
                _fail(f'appname 应为 wbmgr，实际 {meta.get("appname")}', errors)
            # changelog 是单行值：带换行会把 manifest 结构撑坏
            if '\n' in meta.get('changelog', ''):
                _fail('changelog 含换行（manifest 是逐行 key = value）', errors)

    # ── 内层 app.tgz ──
    print('内层 app.tgz：')
    with tarfile.open(path, 'r:gz') as tf:
        app_member = tf.getmember('app.tgz')
        app_bytes = tf.extractfile(app_member).read()
    import io
    with tarfile.open(fileobj=io.BytesIO(app_bytes), mode='r:gz') as inner:
        names = {m.name for m in inner.getmembers()}
        missing_app = [n for n in APP_REQUIRED if n not in names]
        if missing_app:
            _fail(f'缺必需文件：{missing_app}', errors)
        else:
            _ok(f'{len(APP_REQUIRED)} 个必需文件齐备（共 {len(names)} 个条目）')

        # 关键脚本必须可执行
        for script in ('bin/gen-config.sh', 'bin/run-manager.sh', 'bin/wb2api',
                       'bin/up-start.sh', 'bin/up-stop.sh', 'bin/up-watch.sh'):
            m = inner.getmember(script)
            if m.mode & 0o111 == 0:
                _fail(f'{script} 没有执行位（{m.mode:04o}）', errors)

        # 平台一致性：wb2api 必须是 aarch64，wheel 不能混进 x86
        wb = inner.extractfile(inner.getmember('bin/wb2api')).read(20)
        machine = int.from_bytes(wb[18:20], 'little')
        expect = 183 if (meta.get('platform') == 'arm') else 62
        if machine != expect:
            _fail(f'wb2api 的 ELF 架构与 platform={meta.get("platform")} 不符'
                  f'（e_machine={machine}）', errors)
        else:
            _ok(f'wb2api 架构正确（e_machine={machine}）')

        bad_wheels = [n for n in names
                      if n.startswith('wheels/') and ('x86_64' in n or 'armv7' in n)]
        if bad_wheels:
            _fail(f'混入了非 aarch64 的 wheel：{bad_wheels[:3]}', errors)
        wheels = [n for n in names if n.startswith('wheels/') and n.endswith('.whl')]
        _ok(f'{len(wheels)} 个 wheel，全部 aarch64 或纯 Python')

        # 依赖清单必须与仓库一致：不一致说明包里装的是旧依赖，
        # 或者加了新依赖却没往 wheels/ 补（飞牛上离线装会失败）。
        local_req = (ROOT / 'server' / 'requirements.txt').read_bytes()
        if 'manager/requirements.txt' in names:
            packed_req = inner.extractfile(
                inner.getmember('manager/requirements.txt')).read()
            if packed_req.replace(b'\r\n', b'\n') != local_req.replace(b'\r\n', b'\n'):
                _fail('manager/requirements.txt 与 server/requirements.txt 不一致：'
                      '包里是旧依赖清单', errors)
            else:
                _ok('依赖清单与仓库一致')

        # 后端不能带 CRLF 进包（包在 Linux 上跑，仓库在 Windows 上是 CRLF）
        crlf = []
        for name in names:
            if not name.startswith('manager/server/') or not name.endswith('.py'):
                continue
            m = inner.getmember(name)
            if m.isfile() and b'\r\n' in inner.extractfile(m).read():
                crlf.append(name)
        if crlf:
            _fail(f'{len(crlf)} 个后端 .py 带 CRLF（例：{crlf[:2]}）：'
                  '包在 Linux 上跑，文本文件应统一成 LF', errors)
        else:
            _ok('后端 .py 全部 LF')

        # 归档格式：参考包是 GNU 老式 tar，不去赌安装器对 PAX 的兼容性
        for label, data in (('外层', path.read_bytes()), ):
            import gzip as _gz
            if _gz.decompress(data)[257:265] != b'ustar  \x00':
                _fail(f'{label} tar 不是 GNU 格式（magic 应为 ustar\\0\\0）', errors)
            else:
                _ok(f'{label} tar 为 GNU 格式（与参考包一致）')

        # 桌面图标入口：manifest 的 desktop_uidir 必须真的在包里，且指向正确的应用名。
        # 整个包最容易在「装完桌面上没图标」上翻车，这里逐项核对。
        import json
        uidir = meta.get('desktop_uidir')
        launch = meta.get('desktop_applaunchname')
        if not uidir:
            _fail('manifest 没有 desktop_uidir：桌面上不会有图标', errors)
        elif f'{uidir}/config' not in names:
            _fail(f'manifest 声明 desktop_uidir={uidir}，但包里没有 {uidir}/config'
                  '（装完飞牛桌面上不会出现图标）', errors)
        else:
            try:
                ui_cfg = json.loads(
                    inner.extractfile(inner.getmember(f'{uidir}/config')).read())
                entry = ui_cfg.get('.url', {}).get(launch)
            except (json.JSONDecodeError, KeyError, AttributeError):
                entry = None
            if not isinstance(entry, dict):
                _fail(f'{uidir}/config 里没有 .url.{launch} 条目'
                      '（与 manifest 的 desktop_applaunchname 对不上，桌面不会显示）', errors)
            else:
                if entry.get('type') != 'url':
                    _fail(f'{uidir}/config 的 type 不是 "url"（{entry.get("type")!r}）', errors)
                if entry.get('port') != '${port}':
                    _fail(f'{uidir}/config 的 port 不是 "${{port}}"'
                          f'（{entry.get("port")!r}）：向导改端口后桌面入口会失效', errors)
                icon = entry.get('icon')
                if not icon or not icon.startswith('images/'):
                    _fail(f'{uidir}/config 的 icon 应形如 "images/icon_{{0}}.png"，'
                          f'当前是 {icon!r}', errors)
                else:
                    for size in ('64', '256'):
                        probe = f'{uidir}/' + icon.replace('{0}', size)
                        if probe not in names:
                            _fail(f'缺桌面图标 {probe}', errors)
                    _ok(f'桌面入口正确（.url.{launch}，port=${{port}}，图标齐备）')

        # 前端产物必须带本次的字号样式（否则是旧 out 打进来的）
        import re
        css_names = [n for n in names if re.match(r'manager/out/_next/static/css/.*\.css$', n)]
        if not css_names:
            _fail('manager/out 里没有 CSS 产物', errors)
        else:
            hit = False
            for name in css_names:
                data = inner.extractfile(inner.getmember(name)).read()
                if b'--wb-font-scale' in data:
                    hit = True
                    break
            if hit:
                _ok('前端 CSS 含字号设置样式（产物是新的）')
            else:
                _fail('前端 CSS 没有 --wb-font-scale —— 打进旧产物了', errors)

    print()
    if errors:
        print(f'✗ {len(errors)} 项不通过')
        return 1
    print('✓ 全部校验通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
