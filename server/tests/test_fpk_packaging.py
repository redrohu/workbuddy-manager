"""fpk 打包链路的不变量（飞牛 OS 安装包）。

为什么需要：fpk 的失效方式**全部是静默的**——打出来的包结构完备、字节数正常，
只有拿到 NAS 上装/启时才炸，而且安装器只给一句「安装失败」，不说是哪一项。
这里把几条踩过的坑钉成测试：

1. **包骨架齐全**（cmd/、config/、wizard/、图标），少一个装不上；
2. **钩子脚本是 LF**：CRLF 的 bash 钩子在 Linux 上会报
   `bad interpreter: /bin/bash^M`，而这一点在本机（Windows）完全看不出来；
3. **platform-gated 依赖不会被漏掉**：`uvicorn[standard]` 的 `uvloop` 声明为
   `sys_platform != "win32"`，在 Windows 上解析 wheel 时会被静默跳过，装到 NAS
   上首次启动才报 `No matching distribution found for uvloop`。这条真的踩过。
4. **wheel 必须是 aarch64**：x86 的 wheel 打进去，NAS 上装不上；
5. **打包脚本自己会拒绝**这些情况（不是靠人记得）。

真正的「装得上、起得来」验证在 `dev/fpk_runtest.sh`（需要 WSL + qemu），
本文件只做静态可查的那部分。
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_ROOT = Path(__file__).resolve().parents[2]
_FPK = _ROOT / 'deploy' / 'fpk'
_BUILD = _ROOT / 'dev' / 'build_fpk.py'
_CHECK = _ROOT / 'dev' / 'check_fpk.py'
_RUNTEST = _ROOT / 'dev' / 'fpk_runtest.sh'


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


class PackageSkeletonTest(unittest.TestCase):
    """包骨架：这些文件缺任何一个，fnOS 安装器都不会接受。"""

    REQUIRED = (
        'ICON.PNG',
        'ICON_256.PNG',
        'cmd/main',
        'cmd/install_callback',
        'cmd/install_init',
        'cmd/config_callback',
        'cmd/upgrade_callback',
        'cmd/upgrade_init',
        'cmd/uninstall_callback',
        'cmd/uninstall_init',
        'config/privilege',
        'config/resource',
        'wizard/install',
        'wizard/config',
        'wizard/uninstall',
        'ui/config',
        'ui/images/icon_64.png',
        'ui/images/icon_256.png',
        'bin/gen-config.sh',
        'bin/run-manager.sh',
        'bin/up-start.sh',
        'bin/up-stop.sh',
        'bin/up-watch.sh',
        'config.example.json',
    )

    def test_all_files_present(self) -> None:
        missing = [p for p in self.REQUIRED if not (_FPK / p).is_file()]
        self.assertEqual(missing, [], f'包骨架缺文件：{missing}')

    def test_hooks_are_lf_only(self) -> None:
        """钩子脚本不能有 CRLF：Linux 会报 `bad interpreter: /bin/bash^M`。

        这些文件没有扩展名，`.gitattributes` 的 `*.sh eol=lf` 管不到它们 ——
        所以要么在这里钉住，要么就只能等用户装不上时才发现。
        """
        offenders: list[str] = []
        for path in sorted(_FPK.rglob('*')):
            if not path.is_file():
                continue
            if path.suffix not in ('.sh', '') and path.name not in ('main',):
                continue
            if b'\r\n' in path.read_bytes():
                offenders.append(str(path.relative_to(_FPK)))
        self.assertEqual(offenders, [],
                         f'这些脚本是 CRLF，拿到 NAS 上会报 bad interpreter：{offenders}')

    def test_manifest_template_not_committed(self) -> None:
        """`manifest` 是**生成物**（含 checksum），不放仓库。

        放进来就会有人手改版本号或 checksum，然后打出来的包与文件对不上。
        """
        self.assertFalse((_FPK / 'manifest').exists(),
                         'deploy/fpk/manifest 不该进仓库：它由打包脚本按 app.tgz 的 md5 生成')

    def test_privilege_runs_as_package(self) -> None:
        """业务进程以 package 用户跑，不用 root。

        用 root 跑，网关刷新 token 会把 auths/*.json 原子重写成 root:root 600，
        之后以 package 身份运行的服务就读不到账号（表现为「账号全丢了」）。
        """
        data = json.loads(_read(_FPK / 'config/privilege'))
        self.assertEqual(data.get('defaults', {}).get('run-as'), 'package')

    def test_shared_dir_is_declared(self) -> None:
        """数据要落在共享目录（文件管理 → 应用文件可见），否则用户找不到自己的库。"""
        data = json.loads(_read(_FPK / 'config/resource'))
        shares = data.get('data-share', {}).get('shares', [])
        names = [s.get('name') for s in shares]
        self.assertIn('wbmgr', names, f'config/resource 没声明 wbmgr 共享目录：{names}')

    def test_wizard_collects_port_and_password(self) -> None:
        """安装向导必须能改端口与管理员密码（否则用户只能接受默认 7864 与随机密码）。"""
        steps = json.loads(_read(_FPK / 'wizard/install'))
        fields = {item['field'] for step in steps for item in step.get('items', [])}
        for need in ('port', 'pwd'):
            self.assertIn(need, fields, f'安装向导没有 {need} 字段')

    def test_desktop_ui_entry_matches_manifest(self) -> None:
        """`ui/` 是桌面图标入口，必须与 manifest 的两个字段对得上。

        这个坑很隐蔽：`ui/` 缺失时**安装照样成功、应用中心里也能点开**，
        只是飞牛桌面上不出现图标，安装器不报任何错。所以这里逐项钉住：
        application 名要与 `desktop_applaunchname` 一致，端口要用 `${port}`
        占位（写死数字则改端口后桌面入口指向旧端口），图标文件要真的在。
        """
        cfg = json.loads(_read(_FPK / 'ui/config'))
        entry = cfg.get('.url', {}).get('wbmgr.Application')
        self.assertIsInstance(entry, dict,
                              'ui/config 里没有 .url.wbmgr.Application —— 桌面上不会显示应用')
        self.assertEqual(entry.get('type'), 'url')
        self.assertEqual(entry.get('port'), '${port}',
                         'ui/config 的 port 必须是 ${port}，否则改端口后桌面入口失效')
        icon = entry.get('icon', '')
        self.assertTrue(icon.startswith('images/'), f'图标路径不对：{icon!r}')
        for size in ('64', '256'):
            path = _FPK / 'ui' / icon.replace('{0}', size)
            self.assertTrue(path.is_file(), f'缺桌面图标 {path.relative_to(_FPK)}')


class BuildScriptTest(unittest.TestCase):
    """打包脚本自己的守卫：这些条件不满足时必须**报错**，不能默默产出坏包。"""

    def setUp(self) -> None:
        self.src = _read(_BUILD)

    def test_targets_aarch64_wheels(self) -> None:
        self.assertIn("'--platform'", self.src, '没有给 pip 指定 --platform，会下成宿主的 wheel')
        self.assertIn('manylinux2014_aarch64', self.src,
                      '缺 aarch64 平台标签：NAS 上 pip 会说 No matching distribution')

    def test_fills_platform_gated_extras(self) -> None:
        """必须有「按目标平台重算 extra 标记」这一步。

        缺了它，`uvicorn[standard]` 的 uvloop 在 Windows 上被静默跳过 ——
        包看起来完整，装到 NAS 上首次启动才失败。
        """
        self.assertIn('_fill_platform_gated', self.src,
                      '没有补齐被宿主平台标记漏掉的依赖（uvloop 就是这么丢的）')
        self.assertIn('TARGET_MARKER_ENV', self.src,
                      '标记环境必须显式指向目标平台（linux/aarch64）')

    def test_manifest_checksum_is_app_tgz_md5(self) -> None:
        """参考包实证：`checksum` 是内层 app.tgz 的 MD5，不是整个 fpk 的。"""
        self.assertRegex(
            self.src, r'checksum\s*=\s*\{?app_tgz_md5|_build_manifest\(checksum',
            'manifest 的 checksum 应该来自 app.tgz 的 md5')
        self.assertIn('_md5(', self.src)

    def test_verifies_elf_arch_of_upstream_binary(self) -> None:
        """上游二进制是 aarch64 才行；x86 的混进去，NAS 上 exec format error。"""
        self.assertIn('_elf_arch', self.src)
        self.assertIn('183', self.src, 'aarch64 的 e_machine 是 183')

    def test_refuses_stale_frontend_build(self) -> None:
        """旧的前端产物打进去，界面就还是上一版——而包里其它东西都是新的，最难查。"""
        self.assertIn('--wb-font-scale', self.src,
                      '没有校验 web/out 是否含当前样式，旧产物会被静默打进包')

    def test_normalizes_line_endings(self) -> None:
        """脚本进包前必须把 CRLF 压成 LF（钩子没有扩展名，git 管不到）。"""
        self.assertIn("replace(b'\\r\\n', b'\\n')", self.src)

    def test_reproducible_timestamps(self) -> None:
        """成员 mtime 归零：同内容两次打包逐字节一致，便于比对与校验。"""
        self.assertIn('info.mtime = 0', self.src)

    def test_packs_desktop_ui_dir(self) -> None:
        """`ui/` 必须真的进包 —— 否则装完飞牛桌面上看不到应用图标。

        实测踩过：外层结构、manifest、内层运行时全都对，唯独漏了 `ui/`。
        包能装、应用中心能开、日志无异常，就是桌面上没有图标。
        """
        self.assertIn("_add_tree(tf, 'ui'", self.src,
                      'app.tgz 没有打进 ui/，装完桌面上不会有图标')
        self.assertIn('_check_ui', self.src,
                      '缺少 ui/ 的预检（缺文件时应报错而不是静默出包）')


class CheckerTest(unittest.TestCase):
    """`dev/check_fpk.py` 必须真的检查那些易错点，而不是只数文件个数。"""

    def test_checks_manifest_checksum(self) -> None:
        src = _read(_CHECK)
        self.assertIn('checksum', src)
        self.assertIn('md5', src.lower())

    def test_checks_binary_arch_matches_platform(self) -> None:
        src = _read(_CHECK)
        self.assertIn('e_machine', src)
        self.assertIn('183', src)

    def test_checks_wheels_are_aarch64(self) -> None:
        src = _read(_CHECK)
        self.assertIn('x86_64', src)
        self.assertIn('wheels/', src)

    def test_checks_desktop_ui_entry(self) -> None:
        """校验脚本要能独立发现「桌面上没图标」这一类残缺。"""
        src = _read(_CHECK)
        self.assertIn('ui/config', src,
                      'check_fpk.py 没有检查 ui/config，漏打时它不会报警')
        self.assertIn('desktop_applaunchname', src,
                      '没有核对 manifest 的应用名与 ui/config 的 .url 条目是否一致')


class RuntimeSmokeTest(unittest.TestCase):
    """真跑验证脚本本身：它是「装不上」时唯一能定位原因的东西。"""

    def test_runtest_covers_the_real_failure_points(self) -> None:
        self.assertTrue(_RUNTEST.is_file(), f'缺 {_RUNTEST}')
        src = _read(_RUNTEST)
        for needle, why in (
            ('bash -n', '钩子语法错误是安装失败最常见的原因'),
            ('runtime/py.tar.gz', '内置 Python 解不开就起不来'),
            ('--no-index', 'NAS 上没网，依赖必须离线装'),
            ('/healthz', '最终要证明服务真的起来了'),
            ('gen-config.sh', '.env 路径写错的话服务能起但没有数据目录'),
        ):
            self.assertIn(needle, src, f'fpk_runtest.sh 缺少 {needle}：{why}')


if __name__ == '__main__':
    unittest.main()
