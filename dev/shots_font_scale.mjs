/**
 * 字号档位的截图（开发工具）：用于肉眼确认「放大后没有挤坏布局」。
 *
 *   node dev/shots_font_scale.mjs
 *
 * 输出 dev/.font-scale-<档位>-<路由>.png（已 gitignore）。
 */
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const BASE = process.env.WB_BASE || 'http://127.0.0.1:7864';
const USER = process.env.WB_USER || 'admin';
const PASS = process.env.WB_PASS || 'Wb-Test-2026-Demo!';
const OUT = import.meta.dirname;

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
const context = await browser.newContext({viewport: {width: 1440, height: 950}});
const page = await context.newPage();

await page.goto(`${BASE}/login`, {waitUntil: 'load'});
await page.fill('#username', USER);
await page.fill('#password', PASS);
await Promise.all([page.waitForURL(/dashboard/).catch(() => {}), page.click('button[type=submit]')]);

async function dismissOverlays() {
  for (let i = 0; i < 3; i += 1) {
    if (!(await page.locator('[data-slot="dialog-overlay"]').count())) return;
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
  }
}

const ROUTES = ['/settings/upstream', '/accounts', '/dashboard'];

for (const scale of ['default', 'xlarge']) {
  await page.evaluate((s) => window.localStorage.setItem('wb.font-scale', s), scale);
  for (const route of ROUTES) {
    await page.goto(`${BASE}${route}`, {waitUntil: 'load'});
    await page.waitForTimeout(2200);
    await dismissOverlays();
    if (route.startsWith('/settings')) {
      // 滚到「界面」那张卡，截图时才看得到字号控件
      await page.locator('[data-slot="font-scale-label"]').scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
    }
    const name = `${scale}-${route.replace(/\//g, '') || 'home'}`;
    const file = path.join(OUT, `.font-scale-${name}.png`);
    await page.screenshot({path: file, fullPage: false});
    console.log(`${scale} ${route} → ${file}`);
  }
}

await page.evaluate(() => window.localStorage.removeItem('wb.font-scale'));
await context.close();
await browser.close();
