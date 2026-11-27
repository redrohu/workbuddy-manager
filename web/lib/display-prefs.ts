/**
 * 界面显示偏好：存在**浏览器本地**（localStorage），不落后端。
 *
 * 为什么不像上游配置那样存服务端：这一项决定的是「数字怎么摆」，不是系统的行为，
 * 每个使用者可以有自己的偏好——与语言、版本切换同类（它们的先例见
 * lib/i18n/config.ts 与 lib/realm-context.tsx）。
 *
 * 读不到时一律返回默认值：隐私模式下 localStorage 会抛错，那不该让页面白屏。
 */
import type {CreditExpiry} from './types';

/**
 * 界面字号档位：存在**浏览器本地**（localStorage），不落后端。
 *
 * 为什么存在本地而不是服务端配置：这是「我这块屏幕上字号多大合适」的个人
 * 偏好，与语言、版本切换同类（先例见 lib/i18n/config.ts 与 lib/realm-context.tsx）。
 * 同一台机器上不同人、不同显示器需要的字号本来就不一样，存服务端反而会让
 * 一个人改字号影响所有人的界面。
 *
 * 实现方式见 {@link applyFontScale} 与 app/globals.css：改 `html` 的
 * `--wb-font-scale`，根字号 = `浏览器默认字号 × 倍数`（默认字号通常 16px，
 * 所以 ×1.2 就是 19.2px），于是项目里所有 rem 字号（`text-xs` /
 * `text-[0.6875rem]` …）一起按比例变。
 *
 * **副作用是「等比缩放」而不是「只放大文字」**：Tailwind 的间距、图标、
 * 圆角同样以 rem 计量，会跟着一起变。这是**故意**的——只放大文字、间距不动，
 * 密集的胶囊徽标与固定高度的按钮会挤到裁字；等比缩放则像浏览器缩放一样
 * 处处保持原有比例。文案里如实写「整页按比例缩放」，不假装只动字号。
 */
export const FONT_SCALE_CHOICES = ['small', 'default', 'large', 'xlarge'] as const;

export type FontScale = (typeof FONT_SCALE_CHOICES)[number];

/** 默认档：与引入该设置之前**逐像素一致**（倍数为 1）。 */
export const DEFAULT_FONT_SCALE: FontScale = 'default';

/**
 * 档位 → 根字号倍数。
 *
 * 档位写成语义名而不是直接存倍数（0.9 / 1.1 …）：倍数一旦进了 localStorage，
 * 手改过的脏值（比如 7）会把界面放大到不可用且**没法在界面上调回来**；
 * 存语义名则任何不认识的取值都回落到默认档。倍数只能通过这份表改。
 */
export const FONT_SCALE_FACTORS: Record<FontScale, number> = {
  small: 0.9,
  default: 1,
  large: 1.1,
  // 上限 1.2：1.25 在 1366 / 1440 宽的笔记本与手机上容易把密集布局挤到溢出
  xlarge: 1.2,
};

const FONT_SCALE_KEY = 'wb.font-scale';

/**
 * 档位 → 文案键。
 *
 * 与 {@link FONT_SCALE_CHOICES} 分开列在这里、而**不**在组件里写
 * `t(\`settings.fontScale_${choice}\`)`：拼出来的键不会被
 * `server/tests/test_web_i18n.py` 的字面量扫描看到，漏翻时界面上直接显示裸键名
 * （`settings.fontScale_large`），而且没有任何测试会红。列成常量外加一条
 * 「这四个键在五种语言里都存在」的守卫（`server/tests/test_font_scale.py`）。
 */
export const FONT_SCALE_LABEL_KEYS: Record<FontScale, string> = {
  small: 'settings.fontScaleSmall',
  default: 'settings.fontScaleDefault',
  large: 'settings.fontScaleLarge',
  xlarge: 'settings.fontScaleXlarge',
};

/** 读取字号档位：读不到 / 存了不认识的值 / localStorage 不可用 → 默认档。 */
export function getFontScale(): FontScale {
  try {
    const raw = window.localStorage.getItem(FONT_SCALE_KEY);
    const hit = FONT_SCALE_CHOICES.find((c) => c === raw);
    return hit ?? DEFAULT_FONT_SCALE;
  } catch {
    return DEFAULT_FONT_SCALE;
  }
}

/**
 * 写入字号档位，并**立即**把它应用到当前页面。
 *
 * 两件事放一起而不是让调用方各写一次：漏掉 `applyFontScale` 的表现是
 * 「设置保存了、这一屏没变」，用户会以为没生效而反复点。
 */
export function setFontScale(v: FontScale): void {
  try {
    window.localStorage.setItem(FONT_SCALE_KEY, v);
  } catch {
    /* 写不进去只影响下次打开；本次会话仍按调用方给的档位渲染 */
  }
  applyFontScale(v);
}

/**
 * 把档位应用到当前文档（改 `html` 上的 CSS 变量，见 app/globals.css）。
 *
 * 用 CSS 变量而不是直接写 `documentElement.style.fontSize`：变量只承载「倍数」，
 * 「浏览器默认字号 × 倍数」这条算法留在 CSS 里一份，两边不会各算一套。
 */
export function applyFontScale(v: FontScale): void {
  try {
    document.documentElement.style.setProperty(
      '--wb-font-scale',
      String(FONT_SCALE_FACTORS[v] ?? 1),
    );
  } catch {
    /* 没有 document（SSR / 测试环境）时无事可做 */
  }
}

/**
 * 首屏渲染**之前**应用字号的内联脚本源码（由 app/layout.tsx 注入）。
 *
 * 为什么需要它：`useEffect` 里读 localStorage 要等 React 挂载，用户会先看到
 * 一帧默认字号再跳成自己选的字号（视觉上像闪一下）。内联脚本在解析 HTML 时
 * 同步执行，赶在第一帧之前。
 *
 * 脚本内容由本模块的常量拼出来，**不另写一份**：key 名或倍数表改了而脚本没跟上，
 * 表现是「设置里选了、刷新后回到默认」，很难查。`web/lib/font-scale.test.mjs`
 * 会真的把这段脚本跑一遍，断言它把倍数写到 `--wb-font-scale` 上。
 */
export function fontScaleBootScript(): string {
  const factors = JSON.stringify(FONT_SCALE_FACTORS);
  const key = JSON.stringify(FONT_SCALE_KEY);
  return (
    '(function(){try{var f=' + factors + '[localStorage.getItem(' + key + ')];' +
    'if(typeof f==="number"){document.documentElement.style.setProperty(' +
    '"--wb-font-scale",String(f));}}catch(e){}})();'
  );
}

/** 仪表盘「最近到期积分」是否按天归并。 */
const EXPIRY_DAILY_KEY = 'wb.expiry-daily-group';

/**
 * 读取「到期积分按天模糊统计」开关。
 *
 * **默认关闭**（返回 false）：这是改变既有数字含义的选项——开启后仪表盘上那个
 * 数字从「最近一笔到期多少」变成「最近这一天共到期多少」，两者数量级不同。
 * 默认为关，升级后看到的还是原来那个数，想按天看的人自己打开。
 */
export function getExpiryDailyGroup(): boolean {
  try {
    return window.localStorage.getItem(EXPIRY_DAILY_KEY) === '1';
  } catch {
    return false;   // 隐私模式/被禁用：用默认值
  }
}

export function setExpiryDailyGroup(on: boolean): void {
  try {
    window.localStorage.setItem(EXPIRY_DAILY_KEY, on ? '1' : '0');
  } catch {
    /* 写不进去就算了：本次会话仍按用户的选择渲染（state 在调用方），
       只是下次打开会回到默认值 */
  }
}

/** 仪表盘「积分收支」的图形：双轴折线（现状）或单轴发散柱。 */
export type CreditsChartType = 'line' | 'bar';

const CREDITS_CHART_KEY = 'wb.credits-chart';

/**
 * 读取「积分收支」图形偏好。
 *
 * **默认柱状**（issue #263）：双轴折线里两条线各自缩放，「哪根更高」不再代表
 * 数值高低；单轴发散柱把收支放在同一根轴上，量级差与净增正负都能直接读。
 * 折线仍保留，一键切回。
 */
export function getCreditsChartType(): CreditsChartType {
  try {
    return window.localStorage.getItem(CREDITS_CHART_KEY) === 'line' ? 'line' : 'bar';
  } catch {
    return 'bar';
  }
}

export function setCreditsChartType(v: CreditsChartType): void {
  try {
    window.localStorage.setItem(CREDITS_CHART_KEY, v);
  } catch {
    /* 写不进去只影响下次打开；本次会话仍按调用方的 state 渲染 */
  }
}

/**
 * 抓包页的自动刷新间隔（秒）。
 *
 * 存在**浏览器本地**：这是「我这块屏幕怎么看」的偏好，不是系统行为 —— 与语言、
 * 版本切换同类（先例见 lib/i18n/config.ts 与 lib/realm-context.tsx），不落后端。
 *
 * 默认 20 秒：详情层一次要拉整个会话的轮次（几百轮时不小），太短会给后端
 * 造成无谓的压力；20 秒既能让「刚才那条请求」及时冒出来，又不至于打爆它。
 * 想更快的人可以自己调小（见 {@link REFRESH_INTERVAL_CHOICES}）。
 */

/** 可选的刷新间隔（秒）。第一个是默认值。 */
export const REFRESH_INTERVAL_CHOICES = [20, 10, 30, 60, 5] as const;

export type RefreshInterval = (typeof REFRESH_INTERVAL_CHOICES)[number];

/** 默认间隔（秒）。 */
export const DEFAULT_REFRESH_INTERVAL: RefreshInterval = 20;

const REFRESH_INTERVAL_KEY = 'wb.tap-refresh-interval';

/**
 * 读取刷新间隔（秒）。
 *
 * 读不到 / 存的不是合法值 → 回到默认。隐私模式下 localStorage 会抛错，
 * 那不该让页面白屏；存了乱值（比如上一版留下的）同样按默认处理。
 */
export function getRefreshInterval(): RefreshInterval {
  try {
    const raw = window.localStorage.getItem(REFRESH_INTERVAL_KEY);
    if (raw === null) return DEFAULT_REFRESH_INTERVAL;
    const n = Number(raw);
    const hit = REFRESH_INTERVAL_CHOICES.find((c) => c === n);
    return hit ?? DEFAULT_REFRESH_INTERVAL;
  } catch {
    return DEFAULT_REFRESH_INTERVAL;
  }
}

export function setRefreshInterval(v: RefreshInterval): void {
  try {
    window.localStorage.setItem(REFRESH_INTERVAL_KEY, String(v));
  } catch {
    /* 写不进去只影响下次打开；本次会话仍按调用方的 state 渲染 */
  }
}

/**
 * 把到期明细按**本地日历日**归并：同一天到期的多笔合并成一条。
 *
 * 为什么是本地日历日而不是「相隔 24 小时」：用户看的是日历——
 * 「9 月 30 日到期三笔」比「最早那笔 12.4 天后、其余 12.6 天后」好读得多，
 * 而且那天能采取行动（多跑任务把它花掉）也是按日算的。
 *
 * 合并后的时刻取该日**最早**的那一笔：倒计时宁可保守。用户看到「还有 12 天」
 * 时会按 12 天安排，若实际是当天 00:00 作废，那这一天就用不上了。
 *
 * 不修改传入的数组与其中的对象（调用方可能还要用原始明细）。
 */
export function groupExpiriesByDay(expiries: CreditExpiry[]): CreditExpiry[] {
  const byDay = new Map<string, CreditExpiry>();
  for (const e of expiries) {
    const d = new Date(e.at * 1000);
    // 用本地年月日作 key。不要用 `at / 86400`：那是 UTC 日切，
    // 东八区会把当天 08:00 前的到期算进前一天。
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    const cur = byDay.get(key);
    if (cur) {
      cur.amount += e.amount;
      if (e.at < cur.at) cur.at = e.at;
    } else {
      // 新建对象而不是引用 e：后面要就地累加 amount，不能改到调用方的数据
      byDay.set(key, {at: e.at, amount: e.amount});
    }
  }
  return [...byDay.values()].sort((a, b) => a.at - b.at);
}
