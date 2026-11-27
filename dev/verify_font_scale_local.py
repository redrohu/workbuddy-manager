"""本机一键验收：字号设置（设置 → 上游配置 → 界面 → 字号）。

把「起 mock 上游 + 起管理端 + 塞演示数据 + 跑浏览器断言」串成一条命令，用完自动清理，
不碰你真实的 `data/` 与上游账号目录。

    # 1) 先构建前端产物（改了前端代码才需要重跑）
    cd web && npm run build:export

    # 2) 一键验收（自动起停全部服务，跑完打印结果）
    python dev/verify_font_scale_local.py

    # 只想自己点点看（打印地址与密码，Ctrl+C 退出时自动清理）
    python dev/verify_font_scale_local.py --manual

    # 保留临时数据目录（排查用）
    python dev/verify_font_scale_local.py --keep

前置：Node ≥ 22.6 + `web/node_modules`；浏览器断言还要 playwright-core
（脚本会给出安装命令，缺了只是跳过浏览器那一段，不判失败）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'

# 与 dev/verify_font_scale.mjs 的默认值一致；只用于本机临时实例
ADMIN_USER = 'admin'
ADMIN_PASS = 'Wb-Test-2026-Demo!'

MOCK_PORT = 7863
MGR_PORT = 7864


# ── 小工具 ────────────────────────────────────────────────

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def _wait_health(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return False


def _node_ok() -> tuple[bool, str]:
    node = shutil.which('node')
    if not node:
        return False, '未安装 node'
    try:
        out = subprocess.run([node, '--version'], capture_output=True, text=True,
                             timeout=15).stdout.strip()
        major = int(out.lstrip('v').split('.')[0])
    except Exception as exc:  # noqa: BLE001
        return False, f'读不到 node 版本：{exc}'
    if major < 22:
        return False, f'需要 node ≥ 22.6（type stripping），当前 {out}'
    return True, out


def _playwright_ready() -> bool:
    base = Path(os.environ.get('TEMP') or '/tmp') / 'wb-i18n-verify' / 'node_modules'
    return (base / 'playwright-core' / 'index.js').is_file()


def _chrome_exe() -> Path | None:
    root = Path(os.environ.get('LOCALAPPDATA') or '') / 'ms-playwright'
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir()):
        if entry.name.startswith('chromium-'):
            exe = entry / 'chrome-win64' / 'chrome.exe'
            if exe.is_file():
                return exe
    return None


def _env_for(data_dir: Path, auth_dir: Path, mock_port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        'WB_ADMIN_PASSWORD': ADMIN_PASS,
        'WB_DATA_DIR': str(data_dir),
        'WB_AUTH_DIR': str(auth_dir),
        'WB2API_BASE': f'http://127.0.0.1:{mock_port}',
        # 上游 config.json 不存在时界面会显示「无法读取上游配置」，那是**如实提示**，
        # 不影响字号设置（它不落上游配置）。这里指到临时目录，避免误读真实部署。
        'WB_UPSTREAM_CONFIG': str(data_dir / 'upstream-config.json'),
        'PYTHONUTF8': '1',
        'PYTHONIOENCODING': 'utf-8',
    })
    return env


# ── 主流程 ────────────────────────────────────────────────

def main() -> int:
    # 行缓冲：本脚本会先打印进度、再跑子进程（node 直接写同一终端）。默认的块缓冲
    # 会把进度全憋到退出时才吐出来，输出顺序颠倒，看起来像「先跑断言后起服务」。
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001  # 老 Python / 非 tty 上不支持就算了
        pass

    ap = argparse.ArgumentParser(description='本机验收字号设置')
    ap.add_argument('--manual', action='store_true',
                    help='只起服务，打印地址与密码，由你自己点（Ctrl+C 退出并清理）')
    ap.add_argument('--keep', action='store_true', help='保留临时数据目录')
    ap.add_argument('--skip-browser', action='store_true', help='跳过浏览器断言')
    args = ap.parse_args()

    ok, node_ver = _node_ok()
    if not ok:
        print(f'✗ {node_ver}')
        return 1
    print(f'· node {node_ver}')

    if not (WEB / 'node_modules').is_dir():
        print('✗ 缺 web/node_modules，先执行：cd web && npm ci')
        return 1

    if not (WEB / 'out' / 'index.html').is_file():
        print('✗ 缺前端产物 web/out，先执行：cd web && npm run build:export')
        return 1
    css = list((WEB / 'out' / '_next' / 'static' / 'css').glob('*.css'))
    has_scale = any('--wb-font-scale' in f.read_text(encoding='utf-8', errors='ignore')
                    for f in css)
    if not has_scale:
        print('✗ web/out 是旧产物（CSS 里没有 --wb-font-scale），重跑 npm run build:export')
        return 1
    print('· 前端产物已就绪（含字号档位样式）')

    if not _port_free(MOCK_PORT):
        print(f'✗ {MOCK_PORT} 已被占用（可能有真的 workbuddy2api 在跑），'
              '关掉它再试，或先停掉本机已有实例')
        return 1
    if not _port_free(MGR_PORT):
        print(f'✗ {MGR_PORT} 已被占用（本机已有管理端在跑），先停掉它再试')
        return 1

    tmp = Path(tempfile.mkdtemp(prefix='wb-font-scale-'))
    data_dir = tmp / 'data'
    auth_dir = tmp / 'auths'
    data_dir.mkdir()
    auth_dir.mkdir()
    print(f'· 临时数据目录 {tmp}')

    mock: subprocess.Popen | None = None
    mgr: subprocess.Popen | None = None
    try:
        mock = subprocess.Popen(
            [sys.executable, str(ROOT / 'dev' / 'mock_upstream.py')],
            cwd=ROOT, env=_env_for(data_dir, auth_dir, MOCK_PORT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)
        if mock.poll() is not None:
            print('✗ mock 上游起不来（看 dev/mock_upstream.py 的报错）')
            return 1

        mgr = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'server.main:app',
             '--host', '127.0.0.1', '--port', str(MGR_PORT)],
            cwd=ROOT, env=_env_for(data_dir, auth_dir, MOCK_PORT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace',
        )
        if not _wait_health(f'http://127.0.0.1:{MGR_PORT}/healthz'):
            print('✗ 管理端起不来，最后几行输出：')
            if mgr.stdout:
                for line in list(mgr.stdout)[-15:]:
                    print('   ', line.rstrip())
            return 1
        print(f'· 管理端就绪 http://127.0.0.1:{MGR_PORT}')

        # 演示数据要在服务建表之后塞
        seed = subprocess.run(
            [sys.executable, str(ROOT / 'dev' / 'seed_demo_data.py')],
            cwd=ROOT, env=_env_for(data_dir, auth_dir, MOCK_PORT),
            capture_output=True, text=True, encoding='utf-8', errors='replace',
        )
        print('· 演示数据：' + (seed.stdout or seed.stderr or '').strip().splitlines()[-1])

        if args.manual:
            print()
            print('=' * 62)
            print(f'  浏览器打开  http://127.0.0.1:{MGR_PORT}')
            print(f'  用户名 admin    密码 {ADMIN_PASS}')
            print('  要测的地方：设置 → 上游配置 → 往下滚到「界面」卡片 → 字号')
            print('  试试：切到「特大」看整页放大；刷新看是否保持；切回「标准」')
            print('  Ctrl+C 退出（会自动清掉临时目录与后台进程）')
            print('=' * 62)
            while True:
                time.sleep(1)

        if args.skip_browser:
            print('· 跳过浏览器断言')
            return 0
        if not _playwright_ready():
            print('· 跳过浏览器断言：缺 playwright-core。装法：')
            print('    $d = Join-Path $env:TEMP "wb-i18n-verify"; New-Item -ItemType Directory -Force $d')
            print('    cd $d; npm install playwright-core')
            return 0
        if not _chrome_exe():
            print('· 跳过浏览器断言：ms-playwright 里没有 chromium。装法：')
            print('    npx playwright install chromium')
            return 0

        env = _env_for(data_dir, auth_dir, MOCK_PORT)
        env['WB_BASE'] = f'http://127.0.0.1:{MGR_PORT}'
        env['WB_USER'] = ADMIN_USER
        env['WB_PASS'] = ADMIN_PASS
        print()
        proc = subprocess.run(
            [shutil.which('node') or 'node', str(ROOT / 'dev' / 'verify_font_scale.mjs')],
            cwd=ROOT, env=env,
        )
        return proc.returncode
    except KeyboardInterrupt:
        print('\n· 收到 Ctrl+C，清理中…')
        return 0
    finally:
        for p in (mgr, mock):
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
        if args.keep:
            print(f'· 已保留临时目录 {tmp}')
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
