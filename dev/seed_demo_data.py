"""本机验收用：往临时库里塞一点用量与请求日志，让仪表盘/用量页的图表有数据。

只在 `WB_DATA_DIR` 指向的临时目录上用（本机验证），不碰真实部署的 data/。
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

DB = Path(os.environ.get('WB_DATA_DIR', '.tmptest/data')) / 'manager.db'


def main() -> int:
    conn = sqlite3.connect(DB)
    today = date.today()
    now = int(time.time())

    conn.execute('delete from request_logs')
    rcols = [r[1] for r in conn.execute('pragma table_info(request_logs)')]
    rows = []
    for day in range(9):
        for hour in range(0, 24, 2):
            ts = now - day * 86400 - (now % 86400) + hour * 3600
            if ts > now:
                continue
            rows.append({
                'ts': ts, 'key_id': None, 'ip': '127.0.0.1',
                'model': 'glm-5.2', 'mapped_model': 'glm-5.2',
                'status': 200 if hour % 6 else 429,
                'prompt_tokens': 800 + day * 40 + hour * 11,
                'completion_tokens': 300 + day * 20 + hour * 5,
                'latency_ms': 900 + hour * 3, 'first_token_ms': 220,
                'ua': 'demo', 'error': None, 'stream': 1,
                'credit': 1.5 + day * 0.1, 'cost': 0.02,
                'realm': 'cn', 'channel': 'api',
                'cache_hit_tokens': 0, 'cache_miss_tokens': 40,
                'cache_write_tokens': 0,
                'account': '黑天鹅(89374120)',
                'account_expected': None, 'effort': None,
            })
    use = {k: v for k, v in rows[0].items() if k in rcols}
    conn.executemany(
        'INSERT INTO request_logs ({}) VALUES ({})'.format(
            ', '.join(use), ', '.join('?' for _ in use)),
        [tuple(r[k] for k in use) for r in rows])

    conn.execute('delete from usage_daily')
    conn.execute('delete from usage_hourly')
    dcols = [r[1] for r in conn.execute('pragma table_info(usage_daily)')]
    hcols = [r[1] for r in conn.execute('pragma table_info(usage_hourly)')]
    drows, hrows = [], []
    for i in range(9):
        day = (today - timedelta(days=i)).isoformat()
        drows.append({
            'day': day, 'key_id': 0, 'model': 'glm-5.2',
            'requests': 40 + i * 3, 'prompt_tokens': 90000 - i * 1200,
            'completion_tokens': 30000 - i * 400,
            'credit': 120.5 - i * 4, 'cache_hit_tokens': 0,
            'cache_miss_tokens': 900, 'cost': 1.2, 'realm': 'cn',
        })
        if i == 0:
            for h in range(0, min(24, time.localtime().tm_hour + 1)):
                hrows.append({
                    'day': day, 'hour': h, 'key_id': 0, 'model': 'glm-5.2',
                    'requests': 2 + h % 5, 'prompt_tokens': 4000 + h * 90,
                    'completion_tokens': 1200 + h * 40,
                    'credit': 5.0 + h * 0.2, 'cache_hit_tokens': 0,
                    'cache_miss_tokens': 40, 'cost': 0.05, 'realm': 'cn',
                })
    use = {k: v for k, v in drows[0].items() if k in dcols}
    conn.executemany(
        'INSERT INTO usage_daily ({}) VALUES ({})'.format(
            ', '.join(use), ', '.join('?' for _ in use)),
        [tuple(r[k] for k in use) for r in drows])
    use = {k: v for k, v in hrows[0].items() if k in hcols}
    conn.executemany(
        'INSERT INTO usage_hourly ({}) VALUES ({})'.format(
            ', '.join(use), ', '.join('?' for _ in use)),
        [tuple(r[k] for k in use) for r in hrows])
    conn.commit()
    print(f'request_logs={len(rows)} usage_daily={len(drows)} usage_hourly={len(hrows)}')
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
