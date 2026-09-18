"""One bounded narrow-window provider recheck per missing symbol/session.

The raw response and outcome are preserved; this script never patches source data.
"""
import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd
import yfinance as yf

from marketpulse.quality.validate import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('quality_id')
    args = parser.parse_args()
    root = Path.cwd()
    source = root / 'reports' / args.quality_id / 'issues.csv'
    issues = pd.read_csv(source)
    gaps = issues.loc[issues.rule.isin(['missing_session', 'unusable_session']),
                      ['symbol', 'session_date']].drop_duplicates()
    universe = {i['symbol']: i for i in json.loads((root / 'config/universe.json').read_text())}
    recovery_id = str(uuid4())
    folder = root / 'data/raw/gap_rechecks' / recovery_id
    folder.mkdir(parents=True)
    rows = []
    for symbol, group in gaps.groupby('symbol', sort=False):
        ticker = yf.Ticker(universe[symbol]['provider_symbol'])
        for day in group.session_date:
            date = pd.Timestamp(day).date()
            entry = {'symbol': symbol, 'session_date': day,
                     'start': str(date - timedelta(days=2)), 'end': str(date + timedelta(days=3)),
                     'observed_at': datetime.now(UTC).isoformat()}
            try:
                data = ticker.history(start=entry['start'], end=entry['end'], interval='1d',
                                      auto_adjust=False, back_adjust=False, repair=False,
                                      actions=True, keepna=True, rounding=False,
                                      timeout=10)
                path = folder / f'{symbol}_{day}.parquet'
                data.to_parquet(path)
                entry.update(file=path.name, sha256=sha(path))
                matches = data.loc[data.index.strftime('%Y-%m-%d') == day]
                entry['status'] = 'candidate_found' if len(matches) == 1 else 'still_missing'
                if len(matches) == 1:
                    values = matches[['Open', 'High', 'Low', 'Close', 'Adj Close']].iloc[0]
                    if values.isna().any() or (values <= 0).any():
                        entry['status'] = 'still_invalid'
            except Exception as exc:  # noqa: BLE001 -- persist each failed independent provider request
                entry.update(status='request_failed', error_type=type(exc).__name__)
            rows.append(entry)
            (folder / f'{symbol}_{day}.json').write_text(json.dumps(entry, indent=2))
        print(f'{symbol}: {len(group)} gaps rechecked', flush=True)
    result = {'recovery_id': recovery_id, 'quality_id': args.quality_id,
              'request_options': {'interval': '1d', 'auto_adjust': False,
                                  'back_adjust': False, 'repair': False, 'actions': True,
                                  'keepna': True, 'rounding': False, 'timeout': 10},
              'issue_sha256': sha(source), 'provider': 'yahoo_research',
              'yfinance_version': yf.__version__, 'requests': rows}
    (folder / 'manifest.json').write_text(json.dumps(result, indent=2))
    print(folder)
    print(pd.Series([r['status'] for r in rows]).value_counts().to_string())


if __name__ == '__main__':
    main()
