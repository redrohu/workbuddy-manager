/**
 * 字号设置的浏览器验收（开发工具，不参与构建 / 不跑 CI）。
 *
 * 为什么必须用真实浏览器：这一项改的是**根字号**与**首帧内联脚本**，静态导出的
 * HTML 里既看不到计算后的字号，也跑不到那段脚本。这里逐档位量真实元素的实际
 * 字号，并刷新页面确认脚本赶在第一帧生效。
 *
 *   node dev/verify_font_scale.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const BASE = process.env.WB_BASE || 'http://127.0.0.1:7864';
const USER = process.env.WB_USER || 'admin';
const PASS = process.env.WB_PASS || 'Wb-Test-2026-Demo!';

async function loadPlaywright() {
  const c = path.join(process.env.TEMP || '/tmp', 'wb-i18n-verify', 'node_modules',
    'playwright-core', 'index.js');
  const spec = fs.existsSync(c) ? pathToFileURL(c).href : 'playwright-core';
  const mod = await import(spec);
  return mod.chromium ?? mod.default?.chromium;
}

function exe() {
  const root = path.join(process.env.LOCALAPPDATA || '', 'ms-playwright');
  const dir = fs.existsSync(root)
    ? fs.readdirSync(root).find((d) => d.startsWith('chromium-'))
    : null;
  const p = dir ? path.join(root, dir, 'chrome-win64', 'chrome.exe') : '';
  return p && fs.existsSync(p) ? p : undefined;
}

const chromium = await loadPlaywright();
const browser = await chromium.launch({executablePath: exe()});
const context = await browser.newContext({viewport: {width: 1440, height: 900}});
const page = await context.newPage();

let failed = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${name}${ok ? '' : `\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`}`);
  if (!ok) failed += 1;
}

const near = (got, want, tol = 0.4) => Math.abs(got - want) <= tol;

await page.goto(`${BASE}/login`, {waitUntil: 'load'});
await page.fill('#username', USER);
await page.fill('#password', PASS);
await Promise.all([page.waitForURL(/dashboard/).catch(() => {}), page.click('button[type=submit]')]);

await page.goto(`${BASE}/settings/upstream`, {waitUntil: 'load'});
await page.waitForTimeout(1800);

/**
 * 关掉可能盖住页面的弹窗（升级公告 / 引导）。
 *
 * 不处理的话，后续点击会被 `[data-slot="dialog-overlay"]` 拦下 —— 表现是
 * 「点了没反应」，很容易被误判成控件坏了。
 */
async function dismissOverlays() {
  for (let i = 0; i < 3; i += 1) {
    if (!(await page.locator('[data-slot="dialog-overlay"]').count())) return;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(250);
    const close = page.locator('[data-slot="dialog-content"] button[aria-label]').first();
    if (await close.count()) {
      await close.click({force: true}).catch(() => {});
      await page.waitForTimeout(250);
    }
  }
}
await dismissOverlays();

/** 根字号 + 那行 11px 小字（`data-slot="font-scale-desc"`）的实际字号。 */
async function metrics() {
  return page.evaluate(() => {
    const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize);
    const probe = document.querySelector('[data-slot="font-scale-desc"]');
    const scale = getComputedStyle(document.documentElement)
      .getPropertyValue('--wb-font-scale').trim();
    return {
      rootPx: Math.round(rootPx * 100) / 100,
      scale,
      probe: probe ? Math.round(parseFloat(getComputedStyle(probe).fontSize) * 100) / 100 : null,
    };
  });
}

/** 用设置页那个真正的下拉逐档点选（不是直接改 CSS）。 */
const LABEL_RE = {
  small: /^小（×0\.9）/,
  default: /^标准（×1）/,
  large: /^大（×1\.1）/,
  xlarge: /^特大（×1\.2）/,
};

async function pick(choice) {
  await dismissOverlays();
  const target = page.locator(
    '[data-slot="select-trigger"][aria-label="字号"], [data-slot="select-trigger"][aria-label="Text size"]',
  ).first();
  await target.scrollIntoViewIfNeeded();
  await target.click();
  await page.waitForTimeout(200);
  await page.locator('[role="option"]').filter({hasText: LABEL_RE[choice]}).first().click();
  await page.waitForTimeout(400);
}

const CHOICES = [
  ['small', 0.9],
  ['default', 1],
  ['large', 1.1],
  ['xlarge', 1.2],
];

console.log('font scale:');
const base = await metrics();
check('default root font-size is 16px', near(base.rootPx, 16), true);
check('default scale var', base.scale, '1');
check('default 11px text stays 11px', near(base.probe ?? 0, 11), true);
for (const [choice, factor] of CHOICES) {
  await pick(choice);
  const m = await metrics();
  check(`${choice}: scale var = ${factor}`, m.scale, String(factor));
  check(`${choice}: root font-size ≈ ${Math.round(16 * factor * 100) / 100}px`,
    near(m.rootPx, 16 * factor), true);
  check(`${choice}: small text ≈ ${Math.round(11 * factor * 100) / 100}px`,
    near(m.probe ?? 0, 11 * factor), true);

  // 刷新后仍生效：首帧脚本读 localStorage，不是内存状态
  await page.reload({waitUntil: 'load'});
  await page.waitForTimeout(1400);
  const r = await metrics();
  check(`${choice}: survives reload`, near(r.rootPx, 16 * factor), true);
}

// 脏值：手改 localStorage 成 7，刷新后必须回默认（不能让界面放大到不可用）
await page.evaluate(() => window.localStorage.setItem('wb.font-scale', '7'));
await page.reload({waitUntil: 'load'});
await page.waitForTimeout(1400);
const junk = await metrics();
check('junk value falls back to scale 1', junk.scale, '1');
check('junk value keeps root at 16px', near(junk.rootPx, 16), true);

// 图表刻度：recharts 的字号是内联 SVG 属性，也得跟着放大
await page.goto(`${BASE}/dashboard`, {waitUntil: 'load'});
await page.waitForTimeout(2200);
await page.evaluate(() => window.localStorage.setItem('wb.font-scale', 'xlarge'));
await page.reload({waitUntil: 'load'});
await page.waitForTimeout(2600);
const tick = await page.evaluate(() => {
  const el = document.querySelector('.recharts-cartesian-axis-tick-value');
  if (!el) return null;
  return {
    text: (el.textContent || '').slice(0, 12),
    px: Math.round(parseFloat(getComputedStyle(el).fontSize) * 100) / 100,
  };
});
console.log('  · chart tick', JSON.stringify(tick));
if (!tick) {
  console.log('  FAIL 没找到图表刻度（页面没有图表数据？）');
  failed += 1;
} else {
  check('chart tick scales too (≈13.2px at ×1.2)', near(tick.px, 11 * 1.2), true);
}

// 收尾：恢复默认
await page.evaluate(() => window.localStorage.removeItem('wb.font-scale'));

await context.close();
await browser.close();
console.log(failed ? `\n${failed} failed` : '\nall passed');
process.exit(failed ? 1 : 0);
