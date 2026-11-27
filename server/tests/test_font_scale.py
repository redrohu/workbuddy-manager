"""界面字号设置（设置 → 界面 → 字号）的源码级不变量。

字号这一项的实现链有三段，**任何一段断开都不报错**，只表现成「设置没生效」
或「升级后界面变了」，所以逐段钉住：

1. `web/lib/display-prefs.ts` 提供档位 / 倍数表 / 应用函数，并有 Node 行为测试
   （`web/lib/font-scale.test.mjs`，run by 本文件第一个用例）；
2. `web/app/globals.css` 把倍数落到根字号上——写漏这条，变量怎么改都没效果；
3. `web/app/layout.tsx` 在首帧前注入脚本，避免「先画默认字号再跳」；
4. 五个语言的文案齐全（键名是显式列出来的，`t()` 拼接扫不到）；
5. 图表里不再有写死的 px 字号（recharts 的字号是内联/SVG 属性，不吃 Tailwind
   类，也不吃根 rem —— 留一处就是「125% 档位下刻度没变大」）。

为什么值得有：这一项的正确性几乎无法靠界面肉眼发现——默认档位（×1）下外观
必须与引入该设置**逐像素一致**，所以「常量写错了」在日常使用中根本看不出来，
只有切换档位才暴露；而切换档位的人很少。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_ROOT = Path(__file__).resolve().parents[2]
_WEB = _ROOT / 'web'
_PREFS = _WEB / 'lib' / 'display-prefs.ts'
_SCRIPT = _WEB / 'lib' / 'font-scale.test.mjs'
_CSS = _WEB / 'app' / 'globals.css'
_LAYOUT = _WEB / 'app' / 'layout.tsx'
_SETTINGS = _WEB / 'app' / '(main)' / 'settings' / 'layout.tsx'
_LOCALES = _WEB / 'lib' / 'i18n' / 'locales'
_CHART_FONT = _WEB / 'lib' / 'chart-font.ts'

_LOCALES_ALL = ['zh-CN', 'zh-TW', 'en', 'ja', 'ko']

# 档位（与 display-prefs 的 FONT_SCALE_CHOICES 一致；这里只用于文案键核对）
_CHOICES = ['small', 'default', 'large', 'xlarge']

_NODE = shutil.which('node')
_MIN_MAJOR = 22


def _node_major() -> int | None:
    if not _NODE:
        return None
    try:
        out = subprocess.run([_NODE, '--version'], capture_output=True,
                             text=True, timeout=15).stdout.strip()
        return int(out.lstrip('v').split('.')[0])
    except Exception:  # noqa: BLE001
        return None


_MAJOR = _node_major()


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _fn_body(src: str, name: str) -> str:
    """取出某个导出函数的函数体源码（到第一个顶格 `}` 为止）。

    为什么不整份文件里搜：这个模块还有别的偏好（刷新间隔）也用 `Number(raw)`，
    全文搜会让一个无关实现把断言带偏。
    """
    start = src.index(f'export function {name}')
    # 从签名后的第一个 `{` 开始，到下一个顶格 `}` 结束
    brace = src.index('{', src.index(')', start))
    end = src.index('\n}\n', brace)
    return src[brace:end]


class FontScaleBehaviourTest(unittest.TestCase):
    """前端逻辑本身的行为（借 Node 跑真实实现，不是复制一份逻辑）。"""

    @unittest.skipUnless(_NODE, '未安装 node，跳过前端逻辑测试')
    @unittest.skipUnless(_MAJOR is not None and _MAJOR >= _MIN_MAJOR,
                         f'需要 node ≥ {_MIN_MAJOR}（type stripping），当前 {_MAJOR}')
    def test_node_behaviour_suite(self) -> None:
        self.assertTrue(_SCRIPT.is_file(), f'缺少测试脚本: {_SCRIPT}')
        proc = subprocess.run(
            [_NODE, '--experimental-strip-types', str(_SCRIPT)],
            capture_output=True, text=True, timeout=120, cwd=str(_ROOT),
        )
        out = (proc.stdout or '') + (proc.stderr or '')
        self.assertEqual(proc.returncode, 0, f'字号偏好的行为不符合预期：\n{out}')
        self.assertIn('all passed', out, f'脚本没有跑到通过：\n{out}')

    def test_default_factor_is_one(self) -> None:
        """默认档必须是 ×1：否则没动过这个设置的用户升级后界面会突然变大小。"""
        src = _read(_PREFS)
        self.assertIn('FONT_SCALE_FACTORS', src)
        # 从源码里读 `default: <数字>,` 那一行，别另抄一份表
        m = re.search(r'default:\s*([0-9.]+)\s*,', src)
        self.assertIsNotNone(m, '倍数表里找不到 default 档 —— 表格结构变了？')
        self.assertEqual(float(m.group(1)), 1.0,
                         '默认档的倍数必须是 1，否则所有没设置过的人升级后观感都会变')

    def test_getter_ignores_stored_junk(self) -> None:
        """读到的值必须过白名单。

        直接 `Number(raw)` 用会接受任意数字（手改过 localStorage 的 `7` 会把界面
        放大到不可用，且**在界面上调不回来**——选择器里只有四个合法档位）。
        """
        body = _fn_body(_read(_PREFS), 'getFontScale')
        self.assertIn('FONT_SCALE_CHOICES.find', body,
                      '读取时必须按档位白名单校验，不能直接 Number(raw)')
        self.assertNotIn('Number(raw)', body,
                         '不要把原始值当数字用：脏值（如 7）会让界面放大到不可用')

    def test_writer_applies_immediately(self) -> None:
        """`setFontScale` 必须同时写盘与应用到页面。

        只写盘的表现是「设置保存了、这一屏没变」，用户会以为没生效而反复点。
        """
        body = _fn_body(_read(_PREFS), 'setFontScale')
        self.assertIn('localStorage.setItem', body, 'setFontScale 没有写盘')
        self.assertIn('applyFontScale(', body, 'setFontScale 没有立即应用（这一屏不会变）')


class RootFontSizeTest(unittest.TestCase):
    """倍数必须真的落到根字号上——这是整条链唯一「看得见效果」的一环。"""

    def test_css_uses_the_variable_for_root_font_size(self) -> None:
        css = _read(_CSS)
        self.assertIn('--wb-font-scale', css,
                      'globals.css 里没有 --wb-font-scale 的默认值')
        # 必须有一个 html { font-size: calc(... * var(--wb-font-scale ...)) } 规则
        m = re.search(
            r'html\s*\{[^}]*font-size:\s*calc\([^)]*var\(--wb-font-scale[^}]*\}', css, re.S)
        self.assertIsNotNone(
            m,
            'globals.css 没有把 --wb-font-scale 乘进根字号 —— 那样改档位不会有任何效果',
        )

    def test_root_font_size_keeps_the_browser_default_as_base(self) -> None:
        """基准必须是 `100%`（浏览器默认字号），不能写死 16px。

        写死 16px 会把「用户在浏览器里设的默认字号」抹掉：那个人打开面板反而
        比浏览器里的其它站点更小。
        """
        css = _read(_CSS)
        m = re.search(r'font-size:\s*calc\(([^;]*?)var\(--wb-font-scale', css, re.S)
        self.assertIsNotNone(m)
        self.assertIn('100%', m.group(1),
                      '基准要写 100%（跟随浏览器默认字号），不要写死 16px')

    def test_no_fixed_px_font_sizes_remain_in_components(self) -> None:
        """组件里不该再有 `text-[11px]` 这种写死像素的字号。

        它们不跟随根字号，结果就是「125% 档位下这几处文字没变大」——散布在
        各个角落，肉眼几乎发现不了。统一用 rem（`text-[0.6875rem]`）。
        """
        offenders: list[str] = []
        for path in sorted(_WEB.rglob('*')):
            if path.suffix not in ('.tsx', '.ts'):
                continue
            if {'node_modules', '.next', 'out'} & set(path.parts):
                continue
            for m in re.finditer(r'text-\[(\d+(?:\.\d+)?)px\]', _read(path)):
                offenders.append(f'{path.relative_to(_WEB)}: {m.group(0)}')
        self.assertEqual(
            offenders[:5], [],
            f'还有 {len(offenders)} 处写死的 px 字号（不跟随界面字号设置）：{offenders[:5]}',
        )


class BootScriptTest(unittest.TestCase):
    """首帧脚本必须注入，且只能是「早于第一帧」的那种注入方式。"""

    def test_layout_injects_the_boot_script(self) -> None:
        src = _read(_LAYOUT)
        self.assertIn('fontScaleBootScript', src,
                      'app/layout.tsx 没有注入首帧字号脚本 —— 会先画默认字号再跳')
        self.assertIn('dangerouslySetInnerHTML', src,
                      '首帧脚本必须内联在 HTML 里（<script>…</script>），不能走外部文件')

    def test_boot_script_does_not_duplicate_the_table(self) -> None:
        """脚本内容必须由 display-prefs 生成，不能在这里另写一份 key/倍数。

        两份的失效方式很难查：设置里选了、刷新后回到默认。
        """
        src = _read(_LAYOUT)
        self.assertNotIn('wb.font-scale', src,
                         'layout.tsx 里出现了 localStorage 的 key —— 应当只由 display-prefs 提供')
        self.assertNotIn('--wb-font-scale', src,
                         'layout.tsx 里出现了 CSS 变量名 —— 应当只由 display-prefs 提供')


class SettingsUiTest(unittest.TestCase):
    """设置页的控件：选择器要有可读名称、要读当前档位、改完要立即应用。"""

    def setUp(self) -> None:
        self.src = _read(_SETTINGS)

    def test_select_has_accessible_name(self) -> None:
        self.assertRegex(
            self.src, r'aria-label=\{t\(\'settings\.fontScaleLabel\'\)\}',
            '字号选择器没有读屏名称（SelectTrigger 是 div/button，没有原生 label 关联）',
        )

    def test_change_applies_immediately(self) -> None:
        self.assertIn('setFontScale(next)', self.src,
                      '选择字号后没有立即应用 —— 会表现为「选了没反应」')

    def test_reads_current_value_on_mount(self) -> None:
        self.assertIn('getFontScale()', self.src, '没有读回已保存的档位，选择器会永远显示默认')

    def test_lives_in_the_display_prefs_card(self) -> None:
        """必须挂在「界面」那张卡里，而不是某个上游配置分组里。

        它不落 config.json；混进 GROUPS 会被当成上游字段去保存（段名对不上，
        保存被拒）。
        """
        card = self.src[self.src.index("t('settings.displayTitle')"):]
        card = card[:card.index('{GROUPS.map')]
        self.assertIn('fontScaleLabel', card, '字号控件不在「界面」卡片里')


class LocaleCopyTest(unittest.TestCase):
    """五个语言的文案：键名是**显式列出**的，`t()` 拼接扫不到，必须单独查。"""

    def _dict(self, locale: str) -> dict:
        return json.loads((_LOCALES / f'{locale}.json').read_text(encoding='utf-8'))

    def test_keys_exist_in_every_locale(self) -> None:
        keys = ['fontScaleLabel', 'fontScaleDesc'] + [
            f'fontScale{c[0].upper()}{c[1:]}' for c in _CHOICES]
        for locale in _LOCALES_ALL:
            settings = self._dict(locale)['settings']
            for key in keys:
                with self.subTest(locale=locale, key=key):
                    self.assertIn(key, settings, f'{locale} 缺少 settings.{key}')
                    self.assertTrue(str(settings[key]).strip(),
                                    f'{locale}.settings.{key} 是空译文')

    def test_choices_are_covered(self) -> None:
        """四个档位都要有名字：漏一个会在选择器里显示裸键名。"""
        src = _read(_PREFS)
        for choice in _CHOICES:
            with self.subTest(choice=choice):
                self.assertIn(f'{choice}:', src, f'倍数/文案表里没有 {choice} 档')


class ChartFontTest(unittest.TestCase):
    """图表里的字号也得跟着界面字号走。

    recharts 的 `fontSize` 是内联写进 SVG 的，Tailwind 类与根 rem 都管不到它
    （写死 11px 就永远是 11px），所以统一改成 rem 常量。
    """

    def test_chart_font_constants_are_rem(self) -> None:
        src = _read(_CHART_FONT)
        for name in ('CHART_TICK_FONT', 'CHART_TIP_FONT'):
            with self.subTest(const=name):
                m = re.search(rf'{name}\s*=\s*[\'"]([^\'"]+)[\'"]', src)
                self.assertIsNotNone(m, f'{name} 的定义没找到')
                self.assertTrue(m.group(1).endswith('rem'),
                                f'{name} 必须是 rem（写 px 就不会跟着界面字号变）')

    def test_no_px_font_size_left_in_charts(self) -> None:
        for rel in (('app', '(main)', 'dashboard', 'page.tsx'),
                    ('app', '(main)', 'stats', 'page.tsx'),
                    ('components', 'common', 'layout', 'RealtimeStatsStrip.tsx')):
            path = _WEB.joinpath(*rel)
            with self.subTest(file=str(path.relative_to(_WEB))):
                text = _read(path)
                leftovers = re.findall(r'fontSize\s*[:=]\s*\{?\s*\d+\s*\}?', text)
                self.assertEqual(leftovers, [],
                                 f'{path.name} 里还有写死的 px 字号：{leftovers}')


if __name__ == '__main__':
    unittest.main()
