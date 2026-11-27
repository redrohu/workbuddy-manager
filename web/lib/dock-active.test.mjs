/**
 * `web/lib/dock-active.ts` 的行为测试（Node 直接跑 .ts 源码）。
 *
 * 跑法（Node >= 22.6）：
 *     node --experimental-strip-types web/lib/dock-active.test.mjs
 * 或走 Python 包装：`python -m pytest server/tests/test_dock_groups.py`
 * （DockActiveTest 类会调这里）。
 */
import {isDockItemActive, findActiveHref, dockMatchIndex} from './dock-active.ts';

let failed = 0;

function check(name, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) {
    console.log(`  ok  ${name}`);
  } else {
    console.log(`  FAIL ${name}\n       got  ${g}\n       want ${w}`);
    failed += 1;
  }
}

// -- isDockItemActive --

console.log('\nisDockItemActive:');

check('空 pathname → false', isDockItemActive(null, '/dashboard'), false);
check('空 href → false',     isDockItemActive('/dashboard', undefined), false);
check('空字符串 href → false', isDockItemActive('/dashboard', ''), false);
check('外链 https 不高亮',    isDockItemActive('/dashboard', 'https://example.com'), false);
check('外链 http 不高亮',     isDockItemActive('/dashboard', 'http://example.com'), false);

check('/dashboard 精确',         isDockItemActive('/dashboard', '/dashboard'), true);
check('/accounts 精确',          isDockItemActive('/accounts', '/accounts'), true);
check('/settings 精确',          isDockItemActive('/settings', '/settings'), true);

check('/dashboard/ 尾斜杠',      isDockItemActive('/dashboard/', '/dashboard'), true);
check('/accounts/ 尾斜杠',       isDockItemActive('/accounts/', '/accounts'), true);
check('/settings/upstream/ 尾斜杠', isDockItemActive('/settings/upstream/', '/settings'), true);

check('/settings/upstream → settings', isDockItemActive('/settings/upstream', '/settings'), true);
check('/settings/models  → settings',  isDockItemActive('/settings/models', '/settings'), true);
check('/settings/about   → settings',  isDockItemActive('/settings/about', '/settings'), true);

check('/accounts-extra 不匹配 /accounts', isDockItemActive('/accounts-extra', '/accounts'), false);
check('/accountsfoo   不匹配 /accounts', isDockItemActive('/accountsfoo', '/accounts'), false);
check('/xsettings     不匹配 /settings', isDockItemActive('/xsettings', '/settings'), false);
check('/pre-settings  不匹配 /settings', isDockItemActive('/pre-settings', '/settings'), false);

check('basePath 前缀 /wb/dashboard',    isDockItemActive('/wb/dashboard', '/dashboard'), true);
check('basePath 前缀 /wb/settings/up',  isDockItemActive('/wb/settings/upstream', '/settings'), true);
check('深层 basePath /a/b/c/settings',  isDockItemActive('/a/b/c/settings', '/settings'), true);

check('/dashboard 不匹配 /accounts',    isDockItemActive('/dashboard', '/accounts'), false);
check('/accounts  不匹配 /dashboard',   isDockItemActive('/accounts', '/dashboard'), false);
check('/stats     不匹配 /settings',    isDockItemActive('/stats', '/settings'), false);

check('根路径 / 精确',    isDockItemActive('/', '/'), true);
check('根路径 / 不匹配子路由', isDockItemActive('/dashboard', '/'), false);

// -- findActiveHref --

console.log('\nfindActiveHref:');

const navHrefs = ['/dashboard', '/accounts', '/keys', '/models', '/stats',
  '/logs', '/traces', '/security', '/settings'];

check('dashboard 页找到 /dashboard',
  findActiveHref(navHrefs, '/dashboard'), '/dashboard');

check('accounts 页找到 /accounts',
  findActiveHref(navHrefs, '/accounts'), '/accounts');

check('settings/upstream 页找到 /settings（最长匹配）',
  findActiveHref(navHrefs, '/settings/upstream'), '/settings');

check('无匹配返回 null',
  findActiveHref(navHrefs, '/unknown-page'), null);

check('空列表返回 null',
  findActiveHref([], '/dashboard'), null);

check('含 undefined 的列表不崩溃',
  findActiveHref([undefined, '/dashboard', undefined], '/dashboard'), '/dashboard');

check('最长匹配：/settings/upstream 比 /settings 更精确',
  findActiveHref(['/settings', '/settings/upstream'], '/settings/upstream'),
  '/settings/upstream');

check('trailing slash /accounts/ 找到 /accounts',
  findActiveHref(navHrefs, '/accounts/'), '/accounts');

check('basePath 前缀也能找到',
  findActiveHref(navHrefs, '/wb/settings/models'), '/settings');

check('含 undefined href 的列表（customComponent）',
  findActiveHref([...navHrefs, undefined, undefined], '/dashboard'), '/dashboard');

// 设置页的子 Tab 与另一个导航项同名：/settings/models 里同时有 /settings 与 /models，
// 必须只亮「设置」（离路径开头最近的那段）
check('settings/models 只亮设置，不亮模型',
  findActiveHref(navHrefs, '/settings/models'), '/settings');
check('settings/models/ 尾斜杠同样只亮设置',
  findActiveHref(navHrefs, '/settings/models/'), '/settings');
check('basePath 下 settings/models 只亮设置',
  findActiveHref(['/models', '/settings'], '/wb/settings/models'), '/settings');
check('模型页本身亮模型',
  findActiveHref(navHrefs, '/models'), '/models');
check('根路径 / 不亮任何项',
  findActiveHref(navHrefs, '/'), null);
check('空路径不亮任何项',
  findActiveHref(navHrefs, ''), null);

console.log('\ndockMatchIndex:');
check('不匹配返回 -1', dockMatchIndex('/dashboard', '/accounts'), -1);
check('开头匹配返回 0', dockMatchIndex('/settings/models', '/settings'), 0);
check('中段匹配返回段起点', dockMatchIndex('/settings/models', '/models'), 9);

if (failed > 0) {
  console.log(`\n${failed} 项失败`);
  process.exit(1);
}
console.log('\nall passed');
