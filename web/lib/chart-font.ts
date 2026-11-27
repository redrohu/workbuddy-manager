/**
 * 图表（recharts）里的字号。
 *
 * 为什么单独拎出来：recharts 的 `fontSize` / `contentStyle.fontSize` 是**内联**
 * 写进 SVG / style 的，Tailwind 的 `text-*` 类管不到它们。而界面字号设置
 * （设置 → 界面 → 字号，见 lib/display-prefs.ts）靠改根元素 rem 基准实现——
 * 写死 `fontSize={11}` 的坐标轴刻度会**不跟着放大**，在 125% 档位上显得格外小。
 *
 * 所以这里统一用 rem：`11px = 0.6875rem`、`12px = 0.75rem`，默认档位下与原来
 * 逐像素一致。SVG 的 `font-size` 表现属性接受 CSS 长度（含 rem），而
 * recharts 内部量刻度高度用的是 `getComputedStyle`，因此按放大后的真实字号
 * 计算间距，不会出现「字放大了、刻度重叠」。
 *
 * 取值与 `web/app/globals.css` 里 `text-[0.6875rem]` 那套是同一刻度；改这里的
 * 值时别只改一半——`server/tests/test_font_scale.py` 会把「图表里还留着 px 字号」
 * 钉成失败。
 */

/** 坐标轴刻度 / 图例：11px。 */
export const CHART_TICK_FONT = '0.6875rem';

/** 悬浮提示（Tooltip 内容）：12px。 */
export const CHART_TIP_FONT = '0.75rem';
