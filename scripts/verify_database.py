"""Read-only canonical reconciliation plus rolled-back PostgreSQL constraint probes."""
import json
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

from marketpulse.cli import connection
from marketpulse.db.load import read_artifacts, records


def main():
    root = Path.cwd()
    load_dotenv(root / '.env')
    features, quality, raw, _, calendar, issues = read_artifacts(root)
    dataset = features['dataset_sha256']
    expected = {}
    for entry in quality['outputs']:
        if entry.get('kind') == 'aligned' or 'quarantine' in Path(entry['path']).parts:
            continue
        for r in records(pd.read_parquet(root / entry['path'])):
            expected[(r['symbol'], r['session_date'])] = r
    with connection() as conn:
        rows = conn.execute('''SELECT symbol,session_date,open,high,low,close,adj_close,volume,
            provider,run_id FROM marketpulse.daily_prices WHERE provider=%s AND
            session_date >= %s AND session_date < %s''',
                            (raw['provider'], raw['request']['start_inclusive'],
                             raw['request']['end_exclusive'])).fetchall()
        if {(r[0], str(r[1])) for r in rows} != set(expected):
            raise ValueError('Canonical keys differ')
        for r in rows:
            e = expected[(r[0], str(r[1]))]
            for column, value in zip(['open', 'high', 'low', 'close', 'adj_close'], r[2:7], strict=True):
                if value is None and e[column] is None:
                    continue
                if value is None or e[column] is None or abs(float(value) - e[column]) > .000001:
                    raise ValueError('Canonical numeric mismatch')
            if r[7] != e['volume'] or str(r[9]) != e['run_id']:
                raise ValueError('Canonical volume/provenance mismatch')
        actual_calendar = conn.execute('''SELECT session_date,expected_open,session_kind,source
            FROM marketpulse.session_calendars WHERE dataset_id=%s ORDER BY session_date''',
                                       (dataset,)).fetchall()
        exp_calendar = [(r['session_date'], r['expected_open'], r['session_kind'], r['source'])
                        for r in records(calendar.sort_values('session_date'))]
        if [(str(d), o, k, s) for d, o, k, s in actual_calendar] != exp_calendar:
            raise ValueError('Calendar mismatch')
        actual_issues = [r[0] for r in conn.execute('''SELECT details FROM
            marketpulse.dataset_quality_issues WHERE dataset_id=%s ORDER BY issue_number''', (dataset,))]
        if actual_issues != records(issues):
            raise ValueError('Issue dispositions differ')
        # Each deliberate failure is inside a savepoint: no invalid data persists.
        for sql in ["UPDATE marketpulse.daily_prices SET close=-1 WHERE symbol='NIFTY50'",
                    "UPDATE marketpulse.daily_prices SET volume=-1 WHERE symbol='NIFTY50'"]:
            try:
                with conn.transaction():
                    conn.execute(sql)
            except psycopg.errors.CheckViolation:
                pass
            else:
                raise ValueError('Expected constraint rejection')
        report = {'status': 'passed', 'canonical_rows_verified': len(rows),
                  'price_tolerance': '0.000001 (numeric scale 6)',
                  'calendar_rows_verified': len(actual_calendar), 'issue_rows_verified': len(actual_issues),
                  'negative_price_and_volume_rejected': True, 'dataset_id': dataset}
    (root / 'reports/stage5/verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
