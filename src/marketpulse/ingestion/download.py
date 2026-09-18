"""Archive provider frames without cleaning, imputation, or database price writes."""
import argparse
import hashlib
import json
import platform
import time
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


def utc_now():
    return datetime.now(UTC).isoformat()


def fetch(symbol, start, end):
    return yf.download(
        symbol, start=start, end=end, interval='1d', auto_adjust=False,
        back_adjust=False, actions=True, repair=False, keepna=True,
        threads=False, progress=False, rounding=False, ignore_tz=True,
        multi_level_index=False, timeout=30,
    )


def inspect_frame(frame, start, end):
    if frame is None or frame.empty:
        raise ValueError('Empty provider response')
    if isinstance(frame.columns, pd.MultiIndex):
        raise TypeError('Unexpected multi-level columns')
    required = {'Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume'}
    if not required.issubset(frame.columns):
        raise ValueError('Missing required provider columns')
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError('Expected date index')
    dates = frame.index.date
    if min(dates) < date.fromisoformat(start) or max(dates) >= date.fromisoformat(end):
        raise ValueError('Provider returned dates outside requested range')
    return {
        'rows': len(frame), 'first_session': str(min(dates)), 'last_session': str(max(dates)),
        'duplicate_dates': int(frame.index.duplicated().sum()),
        'nulls': {str(k): int(v) for k, v in frame.isna().sum().items()},
        'columns': list(frame.columns),
    }


def download(root, start, end, symbols=None, fetcher=fetch, sleeper=time.sleep,
             allow_completed_today=False):
    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError('Start must be earlier than exclusive end')
    local = datetime.now(ZoneInfo('Asia/Kolkata'))
    ceiling = local.date() + timedelta(days=int(allow_completed_today and local.hour >= 16))
    if date.fromisoformat(end) > ceiling:
        raise ValueError('End must be today or earlier; incomplete current-day bars are excluded')
    universe = json.loads((root / 'config/universe.json').read_text())
    if symbols:
        unknown = set(symbols) - {row['symbol'] for row in universe}
        if unknown:
            raise ValueError('Unknown symbols: ' + ', '.join(sorted(unknown)))
        universe = [row for row in universe if row['symbol'] in symbols]
    run_id = str(uuid4())
    run_dir = root / 'data/raw/yahoo_research' / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        'run_id': run_id, 'provider': 'yahoo_research', 'started_at': utc_now(),
        'status': 'running', 'contract_version': '1.0',
        'versions': {'python': platform.python_version(), 'pandas': pd.__version__,
                     'yfinance': yf.__version__},
        'request': {'start_inclusive': start, 'end_exclusive': end, 'interval': '1d',
                    'auto_adjust': False, 'back_adjust': False, 'repair': False,
                    'actions': True, 'keepna': True, 'rounding': False,
                    'ignore_tz': True, 'multi_level_index': False, 'timeout': 30},
        'representation': 'Unmodified yfinance DataFrame serialized to Parquet; not HTTP bytes',
        'instruments': [],
    }
    (run_dir / 'request.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    for instrument in universe:
        symbol = instrument['symbol']
        result = {**instrument, 'status': 'failed', 'attempts': []}
        for attempt in range(1, 4):
            entry = {'attempt': attempt, 'started_at': utc_now()}
            try:
                frame = fetcher(instrument['provider_symbol'], start, end)
                # Preserve returned frames before inspecting, including malformed/empty responses.
                if frame is not None:
                    path = run_dir / f'{symbol}.attempt-{attempt}.parquet'
                    frame.to_parquet(path, index=True)
                    entry.update(file=path.name,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                summary = inspect_frame(frame, start, end)
                entry['status'] = 'success'
                result.update(summary, status='success', file=entry['file'],
                              sha256=entry['sha256'], observed_at=utc_now())
            except Exception as exc:  # noqa: BLE001 -- isolate provider failures per instrument
                # Provider/library exception messages may include request/session details.
                entry.update(status='failed', error_type=type(exc).__name__)
            entry['finished_at'] = utc_now()
            result['attempts'].append(entry)
            if result['status'] == 'success':
                break
            if attempt < 3:
                sleeper(2 ** attempt)
        manifest['instruments'].append(result)
        # Per-instrument receipt is written once for recovery if a later symbol is interrupted.
        (run_dir / f'{symbol}.receipt.json').write_text(
            json.dumps(result, indent=2), encoding='utf-8')
        print(f"{symbol}: {result['status']} ({result.get('rows', 0)} rows)", flush=True)
        sleeper(1)
    manifest['finished_at'] = utc_now()
    manifest['status'] = ('success' if all(r['status'] == 'success'
                                          for r in manifest['instruments']) else 'partial_failure')
    (run_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    report_dir = root / 'reports' / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    lines = ['# Historical download report', '', f"Status: {manifest['status']}",
             f'Run: {run_id}', f'Request: {start} inclusive to {end} exclusive', '',
             '| Instrument | Status | Rows | First session | Last session |',
             '|---|---|---:|---|---|']
    for row in manifest['instruments']:
        lines.append(f"| {row['symbol']} | {row['status']} | {row.get('rows', 0)} | "
                     f"{row.get('first_session', '')} | {row.get('last_session', '')} |")
    lines += ['', 'These are provider snapshots. Exchange-calendar completeness, corporate actions,',
              'invalid prices and stale data require Stage 3 validation. No prices were imputed.',
              'Each rerun creates a separate archive; prior runs are not overwritten.']
    (report_dir / 'download.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Report: {report_dir / "download.md"}', flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--start')
    parser.add_argument('--end', help='Exclusive YYYY-MM-DD; defaults to today in India')
    parser.add_argument('--symbols', nargs='+', help='Internal symbols, e.g. NIFTY50 RELIANCE')
    args = parser.parse_args()
    root = args.root.resolve()
    config = tomllib.loads((root / 'config/project.toml').read_text())
    start = args.start or config['history_start']
    end = args.end or datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
    try:
        result = download(root, start, end, args.symbols)
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Download could not start/finish ({type(exc).__name__}). Check inputs/disk.\n')
    raise SystemExit(0 if result['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
