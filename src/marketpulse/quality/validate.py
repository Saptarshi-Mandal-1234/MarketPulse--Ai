"""Conservative, reproducible validation of immutable provider archives."""
import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import holidays
import numpy as np
import pandas as pd

from marketpulse.quality.sessions import align_sessions, make_calendar

RENAME = {'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close',
          'Adj Close': 'adj_close', 'Volume': 'volume', 'Dividends': 'dividends',
          'Stock Splits': 'stock_splits'}
PRICES = ['open', 'high', 'low', 'close']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calendar(start, end, config):
    return make_calendar(start, end, config.get('_reference'))


def validate_frame(raw, instrument, manifest, config, cal):
    issues = []
    symbol = instrument['symbol']
    extra = sorted(set(raw.columns) - set(RENAME))
    if extra:
        issues.append({'symbol': symbol, 'source_row': None, 'session_date': None,
                       'rule': 'unexpected_columns', 'severity': 'warning',
                       'detail': ', '.join(map(str, extra))})
    if not raw.index.is_monotonic_increasing:
        issues.append({'symbol': symbol, 'source_row': None, 'session_date': None,
                       'rule': 'unsorted_dates', 'severity': 'info',
                       'detail': 'Output sorted; original source-row positions preserved'})
    frame = raw.rename(columns=RENAME).copy().reset_index(drop=True)
    frame.insert(0, 'source_row', np.arange(len(frame)))
    dates = pd.to_datetime(raw.index, errors='coerce')
    if isinstance(dates, pd.DatetimeIndex) and dates.tz is not None:
        dates = dates.tz_convert('Asia/Kolkata').tz_localize(None)
    frame['session_date'] = pd.Series(dates).dt.strftime('%Y-%m-%d').values
    bad = pd.Series(False, index=frame.index)

    def flag(mask, rule, severity='error', detail=''):
        mask = pd.Series(mask, index=frame.index).fillna(False)
        if severity == 'error':
            bad.loc[mask] = True
        for idx in frame.index[mask]:
            issues.append({'symbol': symbol, 'source_row': int(idx),
                           'session_date': frame.at[idx, 'session_date'],
                           'rule': rule, 'severity': severity, 'detail': detail})

    flag(frame.session_date.isna(), 'invalid_date')
    if isinstance(dates, pd.DatetimeIndex):
        flag(pd.Series(dates != dates.normalize()).values, 'non_daily_timestamp')
    flag(frame.session_date.duplicated(keep=False) & frame.session_date.notna(),
         'duplicate_date', detail='All copies quarantined; no arbitrary winner')
    req = manifest['request']
    flag((frame.session_date < req['start_inclusive']) |
         (frame.session_date >= req['end_exclusive']), 'date_out_of_range')
    for col in PRICES + ['adj_close', 'volume', 'dividends', 'stock_splits']:
        if col not in frame:
            frame[col] = np.nan
            if col in PRICES + ['adj_close', 'volume']:
                flag(pd.Series(True, index=frame.index), 'missing_column', detail=col)
        original = frame[col].copy()
        frame[col] = pd.to_numeric(frame[col], errors='coerce')
        flag(original.notna() & frame[col].isna(), 'invalid_numeric', detail=col)
    for col in PRICES:
        flag(~np.isfinite(frame[col]) | (frame[col] <= 0), 'invalid_price', detail=col)
    flag(frame.adj_close.notna() & (~np.isfinite(frame.adj_close) | (frame.adj_close <= 0)),
         'invalid_adjusted_close')
    flag(frame.adj_close.isna(), 'missing_adjusted_close', 'warning', 'Not label-ready')
    flag((frame.high < frame[PRICES].max(axis=1)) |
         (frame.low > frame[PRICES].min(axis=1)), 'invalid_ohlc_order')
    flag(frame.volume.notna() & (~np.isfinite(frame.volume) | (frame.volume < 0) |
                                (frame.volume >= 2 ** 63) |
                                (frame.volume % 1 != 0)), 'invalid_volume')
    if instrument['kind'] == 'equity':
        flag(frame.volume.isna(), 'missing_volume', 'warning')
        flag(frame.volume == 0, 'zero_volume', 'warning')
    flag((frame.dividends > 0) | (frame.stock_splits > 0), 'corporate_action', 'info',
         'Source event retained; verify before modelling')
    for col in ['dividends', 'stock_splits']:
        flag(frame[col].notna() & (~np.isfinite(frame[col]) | (frame[col] < 0)),
             'invalid_corporate_action', detail=col)
    opens = set(cal.loc[cal.expected_open, 'session_date'])
    closed = set(cal.loc[~cal.expected_open, 'session_date'])
    flag(frame.session_date.isin(closed), 'verified_closed_session',
         detail='Not a session in the bounded NSE circular reference')

    frame['symbol'] = symbol
    frame['provider'] = manifest['provider']
    frame['run_id'] = manifest['run_id']
    frame['observed_at'] = pd.Timestamp(instrument['observed_at'])
    frame['adjustment'] = 'raw_ohlc_with_adj_close'
    frame['source_sha256'] = instrument['sha256']
    clean = frame.loc[~bad].sort_values('session_date').copy()
    clean['price_valid'] = True
    clean['label_price_available'] = clean.adj_close.notna()
    clean['calendar_review_required'] = clean.session_date.isin(closed)
    clean['volume'] = clean.volume.astype('Int64')
    # Warning calculations compare available observations, not claimed consecutive sessions.
    returns = clean.adj_close.pct_change(fill_method=None).abs()
    volume_baseline = clean.volume.shift(1).rolling(
        config['volume_window'], min_periods=config['volume_min_periods']).median()
    for idx in clean.index[returns > config['absolute_return_warning']]:
        flag(frame.index == idx, 'large_observed_return', 'warning',
             'Between available bars; may span missing sessions')
    if instrument['kind'] == 'equity':
        for idx in clean.index[(volume_baseline > 0) &
                               (clean.volume > volume_baseline * config['volume_median_multiple'])]:
            flag(frame.index == idx, 'volume_spike', 'warning', 'Versus trailing median')
    present = set(frame.session_date.dropna())
    usable = set(clean.session_date.dropna())
    if opens and (not usable or max(usable) < max(opens)):
        issues.append({'symbol': symbol, 'source_row': None, 'session_date': max(opens),
                       'rule': 'stale_latest_bar', 'severity': 'warning',
                       'detail': 'No valid bar for latest expected session in requested range'})
    for day in sorted(opens - usable):
        issues.append({'symbol': symbol, 'source_row': None, 'session_date': day,
                       'rule': 'unusable_session' if day in present else 'missing_session',
                       'severity': 'warning', 'detail': 'Expected session; excluded, never filled'})
    quarantine = frame.loc[bad].copy()
    reasons = {}
    for item in issues:
        if item['severity'] == 'error' and item['source_row'] is not None:
            reasons.setdefault(item['source_row'], set()).add(item['rule'])
    quarantine['reasons'] = [','.join(sorted(reasons[i])) for i in quarantine.index]
    return clean, quarantine, issues


def run(root, source_manifest, config_path=None):
    manifest = json.loads(source_manifest.read_text())
    if manifest['status'] != 'success':
        raise ValueError('Only complete successful source runs are accepted')
    universe = json.loads((root / 'config/universe.json').read_text())
    if (len(manifest['instruments']) != len(universe) or
            {i['symbol'] for i in manifest['instruments']} != {i['symbol'] for i in universe}):
        raise ValueError('Validation requires a full-universe source run')
    config_path = config_path or root / 'config/quality.json'
    config = json.loads(config_path.read_text())
    reference_path = root / config['calendar_reference']
    reference = json.loads(reference_path.read_text())
    # Coverage errors are detected before any output folders are created.
    cal = make_calendar(manifest['request']['start_inclusive'],
                        manifest['request']['end_exclusive'], reference)
    # Validate every checksum before generating outputs.
    for row in manifest['instruments']:
        path = (source_manifest.parent / row['file']).resolve()
        if path.parent != source_manifest.parent.resolve() or sha(path) != row['sha256']:
            raise ValueError('Source path or checksum mismatch')
    quality_id = str(uuid4())
    out = root / 'data/processed' / quality_id
    quarantine_dir = root / 'data/quarantine' / quality_id
    report_dir = root / 'reports' / quality_id
    for directory in [out, quarantine_dir, report_dir]:
        directory.mkdir(parents=True, exist_ok=False)
    cal.to_csv(report_dir / 'calendar.csv', index=False)
    aligned_dir = out / 'aligned'
    aligned_dir.mkdir()
    summaries, all_issues, outputs = [], [], []
    for item in manifest['instruments']:
        raw = pd.read_parquet(source_manifest.parent / item['file'])
        if len(raw) != item['rows']:
            raise ValueError('Source manifest row count mismatch')
        clean, quarantine, issues = validate_frame(raw, item, manifest, config, cal)
        aligned = align_sessions(clean, cal, item['symbol'])
        for issue in issues:
            if issue['severity'] == 'error':
                issue['disposition'] = 'quarantined'
            elif issue['rule'] in ['missing_session', 'unusable_session', 'stale_latest_bar']:
                issue['disposition'] = 'excluded_with_explicit_session_mask'
            elif issue['rule'] in ['missing_adjusted_close', 'missing_volume', 'zero_volume']:
                issue['disposition'] = 'retained_price_only; eligibility_masks_apply'
            else:
                issue['disposition'] = 'retained_source_observation; no_automatic_repair'
        for folder, table in [(out, clean), (quarantine_dir, quarantine)]:
            path = folder / f"{item['symbol']}.parquet"
            table.to_parquet(path, index=False)
            outputs.append({'path': str(path.relative_to(root)), 'sha256': sha(path),
                            'rows': len(table)})
        path = aligned_dir / f"{item['symbol']}.parquet"
        aligned.to_parquet(path, index=False)
        outputs.append({'path': str(path.relative_to(root)), 'sha256': sha(path),
                        'rows': len(aligned), 'kind': 'aligned'})
        gaps = aligned.loc[aligned.gap, ['symbol', 'session_date', 'gap_disposition']]
        gaps.to_csv(report_dir / f"{item['symbol']}_gaps.csv", index=False)
        summary = {'symbol': item['symbol'], 'raw': len(raw), 'clean': len(clean),
                   'source_dtypes': {str(k): str(v) for k, v in raw.dtypes.items()},
                   'quarantined': len(quarantine),
                   'missing_sessions': sum(i['rule'] == 'missing_session' for i in issues),
                   'excluded_sessions': int(aligned.gap.sum()),
                   'eligible_1d': int(aligned.target_1d_eligible.sum()),
                   'eligible_5d': int(aligned.target_5d_eligible.sum()),
                   'latest_usable': None if clean.empty else clean.session_date.max()}
        summaries.append(summary)
        all_issues.extend(issues)
        print(f"{item['symbol']}: {len(clean)} retained, {len(quarantine)} quarantined", flush=True)
    issue_frame = pd.DataFrame(all_issues, columns=[
        'symbol', 'source_row', 'session_date', 'rule', 'severity', 'detail', 'disposition'])
    issue_frame.to_csv(report_dir / 'issues.csv', index=False)
    result = {'quality_id': quality_id, 'created_at': datetime.now(UTC).isoformat(),
              'source_manifest': str(source_manifest.relative_to(root)),
              'source_manifest_sha256': sha(source_manifest), 'config': config,
              'config_sha256': sha(config_path), 'validator_sha256': sha(Path(__file__)),
              'calendar_reference_sha256': sha(reference_path),
              'session_code_sha256': sha(Path(__file__).with_name('sessions.py')),
              'holidays_version': holidays.__version__, 'pandas_version': pd.__version__,
              'status': 'validated_with_exclusions', 'stage3_complete': True,
              'feature_stage_ready': all(s['eligible_5d'] > 0 for s in summaries),
              'model_ready': False,
              'model_ready_reason': 'Features, targets, and walk-forward validation belong to later stages',
              'gap_policy': 'Use aligned data, restart windows at segment_id changes, honor horizon masks',
              'calendar_status': config['calendar_status'], 'instruments': summaries,
              'issue_counts': issue_frame.rule.value_counts().to_dict(), 'outputs': outputs}
    (out / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    lines = ['# Stage 3 data-quality report', '', 'Status: VALIDATED WITH EXCLUSIONS.',
             '', 'Valid bars are retained; invalid rows are quarantined. No prices are filled.',
             'Bounded NSE circular calendar and per-session eligibility masks are included.',
             '', '| Symbol | Raw | Retained | Quarantined | Missing sessions* | Latest usable |',
             '|---|---:|---:|---:|---:|---|']
    for s in summaries:
        lines.append(f"| {s['symbol']} | {s['raw']} | {s['clean']} | {s['quarantined']} | "
                     f"{s['missing_sessions']} | {s['latest_usable']} |")
    lines += ['', '*Missing rows and unusable rows are represented as null sessions in aligned/.',
              'Ready for feature engineering using masks; not a complete or model-ready time series.',
              'Every issue has a recorded disposition in issues.csv.', '', 'Issue counts:']
    lines += [f'- {k}: {v}' for k, v in result['issue_counts'].items()]
    lines += ['', 'Next: Stage 4 feature engineering using aligned/ and segment/horizon masks.',
              'Source gaps remain excluded. Never shift across gaps or impute prices.',
              'Daily reports are generated on each run; no unattended schedule is enabled.']
    (report_dir / 'quality.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    # Publish a pointer only after all artifacts have been written successfully.
    pointer = root / 'data/processed/latest.json'
    temporary = pointer.with_suffix('.tmp')
    temporary.write_text(json.dumps({'quality_id': quality_id,
                                    'manifest_sha256': sha(out / 'manifest.json')}))
    temporary.replace(pointer)
    print(f'Report: {report_dir / "quality.md"}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.manifest:
        source = args.manifest.resolve()
    else:
        sources = list((root / 'data/raw/yahoo_research').glob('*/manifest.json'))
        expected = {i['symbol'] for i in json.loads((root / 'config/universe.json').read_text())}
        sources = [s for s in sources if json.loads(s.read_text())['status'] == 'success'
                   and {i['symbol'] for i in json.loads(s.read_text())['instruments']} == expected]
        if not sources:
            parser.error('No completed downloads found')
        source = max(sources, key=lambda s: json.loads(s.read_text())['finished_at'])
    run(root, source)


if __name__ == '__main__':
    main()
