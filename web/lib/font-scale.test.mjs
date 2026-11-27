/**
 * 界面字号偏好的行为测试（Node 直接跑 .ts 源码）。
 *
 * 跑法（Node ≥ 22.6）：
 *     node --experimental-strip-types web/lib/display-prefs.test.mjs
 * 或走 Python 包装：`python -m pytest server/tests/test_font_scale.py`
 * （没有 node 时那条会 skip，不会阻塞后端测试套件）。
 *
 * 为什么值得单独测：这一项看着只是「三个函数 + 一份倍数表」，但有四个坑
 * 都**不会在界面上报错**，只会表现成「设置没生效」或「界面被搞坏」：
 *
 *  1. **存了脏值**（手改 localStorage、旧版本遗留）→ 必须回落到默认档，
 *     不能算出 `NaN` 塞进 `calc()`（那会让根字号失效，整页变成浏览器默认大小，
 *     看起来像样式全丢了）；
 *  2. **localStorage 抛错**（隐私模式）→ 读要吞异常、写不能抛，否则页面白屏；
 *  3. **首帧脚本与 setter 不同步** → 设置里选了 125%、刷新后却回到 100%，
 *     因为内联脚本里那份 key/倍数表跟这边对不上；
 *  4. **默认档位漂移** → 默认必须是 ×1，否则所有没动过这个设置的用户升级后
 *     界面会突然变大或变小（这类「升级后观感变化」最难被归因）。
 */
import {
  applyFontScale,
  DEFAULT_FONT_SCALE,
  FONT_SCALE_CHOICES,
  FONT_SCALE_FACTORS,
  FONT_SCALE_LABEL_KEYS,
  fontScaleBootScript,
  getFontScale,
  setFontScale,
} from './display-prefs.ts';

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

/** 造一个可写的 localStorage + 假 document 替身（Node 里没有 window/document）。 */
function withEnv(initial, fn) {
  const store = new Map(Object.entries(initial ?? {}));
  const vars = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => { store.set(k, String(v)); },
    },
  };
  globalThis.document = {
    documentElement: {
      style: {
        setProperty: (name, value) => { vars.set(name, value); },
      },
    },
  };
  try {
    return fn(store, vars);
  } finally {
    delete globalThis.window;
    delete globalThis.document;
  }
}

/** localStorage 一抛错就回默认值（隐私模式）。 */
function withBrokenStorage(fn) {
  globalThis.window = {
    localStorage: {
      getItem: () => { throw new Error('denied'); },
      setItem: () => { throw new Error('denied'); },
    },
  };
  try {
    return fn();
  } finally {
    delete globalThis.window;
  }
}

console.log('font scale:');

/* ── 档位与倍数表本身 ─────────────────────────────────── */

check('default is default', DEFAULT_FONT_SCALE, 'default');
check('default factor is 1', FONT_SCALE_FACTORS[DEFAULT_FONT_SCALE], 1);
check('choices include default', FONT_SCALE_CHOICES.includes(DEFAULT_FONT_SCALE), true);

// 倍数必须递增：档位顺序就是「小 → 标准 → 大 → 特大」，写反了界面上的
// 选择器会给出反直觉的结果，而代码层面看不出任何异常。
const factors = FONT_SCALE_CHOICES.map((c) => FONT_SCALE_FACTORS[c]);
check(
  'factors ascend with the labels',
  factors.every((f, i) => i === 0 || f > factors[i - 1]),
  true,
);

// 每个档位都要有文案键，且不能重复（重复 = 两个档位显示同一个名字，选不出差别）
check('every choice has a label key', FONT_SCALE_CHOICES.every((c) => FONT_SCALE_LABEL_KEYS[c]), true);
check(
  'label keys are distinct',
  new Set(FONT_SCALE_CHOICES.map((c) => FONT_SCALE_LABEL_KEYS[c])).size,
  FONT_SCALE_CHOICES.length,
);

/* ── 读取 ─────────────────────────────────────────────── */

withEnv({}, () => {
  check('defaults when unset', getFontScale(), DEFAULT_FONT_SCALE);
});

withEnv({'wb.font-scale': 'xlarge'}, () => {
  check('reads stored choice', getFontScale(), 'xlarge');
});

// 脏值一律回默认：这些都不能变成 NaN 或未知档位
withEnv({'wb.font-scale': 'huge'}, () => {
  check('rejects unknown choice', getFontScale(), DEFAULT_FONT_SCALE);
});
withEnv({'wb.font-scale': '1.2'}, () => {
  check('rejects a raw factor', getFontScale(), DEFAULT_FONT_SCALE);
});
withEnv({'wb.font-scale': ''}, () => {
  check('rejects empty', getFontScale(), DEFAULT_FONT_SCALE);
});

/* ── 应用 ─────────────────────────────────────────────── */

withEnv({}, (_store, vars) => {
  applyFontScale('large');
  check('apply writes the factor', vars.get('--wb-font-scale'), String(FONT_SCALE_FACTORS.large));
});

withEnv({}, (_store, vars) => {
  applyFontScale('nonexistent');
  check('apply falls back to 1 for junk', vars.get('--wb-font-scale'), '1');
});

/* ── 写入 + 应用（setter 两件事一起做）────────────────── */

withEnv({}, (store, vars) => {
  setFontScale('small');
  check('setter persists', store.get('wb.font-scale'), 'small');
  check('setter applies', vars.get('--wb-font-scale'), String(FONT_SCALE_FACTORS.small));
  check('setter round-trips', getFontScale(), 'small');
});

// 隐私模式：读回默认、写不抛（写不进去只影响下次打开）
withBrokenStorage(() => {
  check('survives denied read', getFontScale(), DEFAULT_FONT_SCALE);
  let threw = false;
  try {
    setFontScale('large');
  } catch {
    threw = true;
  }
  check('survives denied write', threw, false);
});

/* ── 首帧内联脚本 ─────────────────────────────────────── */

// 真的把那段脚本跑一遍：它必须读同一个 key、写出同一个倍数。
// 只做字符串断言（`assertIn('wb.font-scale', script)`）挡不住「读对了 key 但
// 写错变量名」这类错误——那正是「设置了、刷新后回到默认」的成因。
function runBootScript(stored) {
  const vars = new Map();
  const sandboxDocument = {
    documentElement: {style: {setProperty: (name, value) => vars.set(name, String(value))}},
  };
  const sandboxLocalStorage = {
    getItem: (k) => (k in stored ? stored[k] : null),
  };
  // 用 Function 而不是 eval：脚本是立即执行表达式，作用域里的 document /
  // localStorage 由参数注入，不污染全局。
  const fn = new Function('document', 'localStorage', fontScaleBootScript());
  fn(sandboxDocument, sandboxLocalStorage);
  return vars;
}

check('boot script applies the stored factor',
  runBootScript({'wb.font-scale': 'xlarge'}).get('--wb-font-scale'),
  String(FONT_SCALE_FACTORS.xlarge));

check('boot script is silent when unset',
  runBootScript({}).has('--wb-font-scale'),
  false);

check('boot script is silent on junk',
  runBootScript({'wb.font-scale': 'garbage'}).has('--wb-font-scale'),
  false);

// 首屏脚本必须与 setter 落在同一个 CSS 变量名上：两处写不一样的变量，
// 表现是「设置里改了立即生效，一刷新就没了」——最难归因的一类。
withEnv({'wb.font-scale': 'large'}, (_store, vars) => {
  applyFontScale('large');
  const viaSetter = vars.get('--wb-font-scale');
  const viaBoot = runBootScript({'wb.font-scale': 'large'}).get('--wb-font-scale');
  check('boot script and setter target the same variable', viaBoot, viaSetter);
});

// 脚本里的 key 必须就是 get/set 用的那个 key
check('boot script reads the same storage key',
  fontScaleBootScript().includes('wb.font-scale'),
  true);

console.log(failed ? `\n${failed} failed` : '\nall passed');
process.exit(failed ? 1 : 0);
