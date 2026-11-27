/**
 * 底栏（浮动 Dock）的「当前页」判定——纯函数，零运行时依赖。
 *
 * 为什么单独放一个模块：
 *   · 零依赖保证 Node type-stripping 能直接 import 本文件跑测试；
 *   · 匹配规则有几个容易写错的边界（trailing slash、basePath 前缀、相似前缀
 *     误判、子路由与另一项同名），单独测比在渲染层里测容易得多。
 *
 * 匹配规则（与 settingsTabFromPath 同理，不依赖 BASE_PATH）：
 *   1. 路径先去除尾斜杠（export 模式开了 trailingSlash）；
 *   2. 按**完整路径段**匹配：在 pathname 里找 `/<href 的段>`，后面必须是结尾或 `/`
 *      （/accounts 不会误匹配 /accounts-extra）；前面允许有别的段，子路径部署下照样成立；
 *   3. 外部链接（http:// / https://）与空 href（customComponent）不参与；
 *   4. 一组导航里**只取一项**（findActiveHref）：匹配位置最靠前的那项胜出。
 *
 * 第 4 条为什么按「位置最靠前」而不是「最长 href」：设置页有个子 Tab 叫 models，
 * `/settings/models` 里同时含有 `/settings` 与 `/models` 两段，两项都「匹配」。
 * 用户此刻在「设置」里，所以应当是离路径开头最近的那一段说了算。
 * 位置相同（如 `/settings` 与 `/settings/upstream` 都从 0 开始）时再取更长、更精确的那个。
 */

/**
 * 某个 href 在 pathname 里的匹配位置；不匹配返回 -1。
 *
 * @param pathname  来自 `usePathname()` 的值（可能带尾斜杠）
 * @param href      dock 项的 `href`（如 '/dashboard'、'/settings'）
 */
export function dockMatchIndex(pathname: string | null | undefined, href: string | undefined): number {
  if (!href || href.startsWith('https://') || href.startsWith('http://')) return -1;
  if (!pathname) return -1;

  const path = pathname.replace(/\/+$/, '') || '/';
  const target = href.replace(/\/+$/, '') || '/';

  // 根路径只与根路径相等（`/` 不能当成「所有页面的前缀」）
  if (target === '/') return path === '/' ? 0 : -1;

  // 去掉前导 / 再转义，然后要求前面是开头或 /、后面是结尾或 /
  const segment = target.replace(/^\/+/, '');
  const escaped = segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = new RegExp(`(?:^|/)${escaped}(?=$|/)`).exec(path);
  return m ? m.index : -1;
}

/** 单个 dock 项是否「匹配」当前路径（不保证唯一，唯一性见 findActiveHref）。 */
export function isDockItemActive(pathname: string | null | undefined, href: string | undefined): boolean {
  return dockMatchIndex(pathname, href) >= 0;
}

/**
 * 在一组 dock 项的 href 里找出「当前页」那一项，没有则返回 null。
 *
 * 匹配位置最靠前者胜；位置相同取更长的 href。保证同一时刻最多一项高亮。
 */
export function findActiveHref(
  hrefs: (string | undefined)[],
  pathname: string | null | undefined,
): string | null {
  let best: string | null = null;
  let bestIndex = Infinity;
  for (const h of hrefs) {
    if (!h) continue;
    const i = dockMatchIndex(pathname, h);
    if (i < 0) continue;
    if (i < bestIndex || (i === bestIndex && best !== null && h.length > best.length)) {
      best = h;
      bestIndex = i;
    }
  }
  return best;
}
