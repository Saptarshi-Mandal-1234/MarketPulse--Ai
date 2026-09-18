"""Atomic, repeatable loading and value verification of Stage 3/4 artifacts."""
import json
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from marketpulse.cli import connection, migrate
from marketpulse.quality.validate import sha


def records(frame):
    # pandas emits JSON null for NaN/NA/NaT; no nonstandard NaN tokens enter JSONB.
    return json.loads(frame.to_json(orient='records', date_format='iso', double_precision=15))


def read_artifacts(root):
    pointer = json.loads((root / 'data/features/latest.json').read_text())
    fp = root / 'data/features' / pointer['run_id'] / 'manifest.json'
    if sha(fp) != pointer['manifest_sha256']:
        raise ValueError('Feature manifest checksum mismatch')
    features = json.loads(fp.read_text())
    qp = root / 'data/processed' / features['quality_id'] / 'manifest.json'
    if sha(qp) != features['identity']['source_manifest_sha256']:
        raise ValueError('Quality manifest checksum mismatch')
    quality = json.loads(qp.read_text())
    if not quality.get('stage3_complete') or features['status'] != 'complete':
        raise ValueError('Stage 3/4 is incomplete')
    for manifest in [quality, features]:
        for entry in manifest['outputs']:
            path = (root / entry['path']).resolve()
            if not path.is_relative_to(root.resolve()) or sha(path) != entry['sha256']:
                raise ValueError('Artifact path/checksum mismatch')
    raw_path = root / quality['source_manifest']
    if sha(raw_path) != quality['source_manifest_sha256']:
        raise ValueError('Raw manifest checksum mismatch')
    raw = json.loads(raw_path.read_text())
    for entry in raw['instruments']:
        if sha(raw_path.parent / entry['file']) != entry['sha256']:
            raise ValueError('Raw archive checksum mismatch')
    calendar = pd.read_csv(root / 'reports' / features['quality_id'] / 'calendar.csv')
    issues = pd.read_csv(root / 'reports' / features['quality_id'] / 'issues.csv')
    return features, quality, raw, raw_path, calendar, issues


def load(root, conn):
    features, quality, raw, raw_path, calendar, issues = read_artifacts(root)
    dataset = features['dataset_sha256']
    aligned = [o for o in quality['outputs'] if o.get('kind') == 'aligned']
    prices = [o for o in quality['outputs'] if 'data\\processed' in o['path'].replace('/', '\\')
              and o.get('kind') != 'aligned']
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(731906)')
        exists = conn.execute('SELECT 1 FROM marketpulse.dataset_loads WHERE dataset_id=%s',
                              (dataset,)).fetchone()
        active = conn.execute('SELECT dataset_id FROM marketpulse.active_dataset').fetchone()
        if exists and (not active or active[0] != dataset):
            raise ValueError('Historical dataset reactivation requires rebuilding the canonical cache')
        if not exists:
            conn.execute('INSERT INTO marketpulse.dataset_loads VALUES (%s,%s,%s,%s,now())',
                         (dataset, features['quality_id'], features['run_id'],
                          Jsonb({'features': features, 'quality': quality,
                                 'calendar_sha256': sha(root / 'reports' / features['quality_id'] /
                                                        'calendar.csv'),
                                 'issues_sha256': sha(root / 'reports' / features['quality_id'] /
                                                      'issues.csv')})))
            conn.execute('''INSERT INTO marketpulse.ingestion_runs
                (run_id,provider,started_at,finished_at,status,raw_path,raw_sha256)
                VALUES (%s,%s,%s,%s,'success',%s,%s) ON CONFLICT(run_id) DO NOTHING''',
                         (raw['run_id'], raw['provider'], raw['started_at'], raw['finished_at'],
                          str(raw_path.relative_to(root)), sha(raw_path)))
            with conn.cursor() as cursor:
                cursor.executemany('INSERT INTO marketpulse.session_calendars VALUES (%s,%s,%s,%s,%s)',
                                   [(dataset, r['session_date'], r['expected_open'], r['session_kind'],
                                     r['source']) for r in records(calendar)])
                cursor.executemany('INSERT INTO marketpulse.dataset_quality_issues VALUES (%s,%s,%s)',
                                   [(dataset, i, Jsonb(r)) for i, r in enumerate(records(issues))])
                for entry in aligned:
                    rows = records(pd.read_parquet(root / entry['path']))
                    cursor.executemany('INSERT INTO marketpulse.validated_sessions VALUES (%s,%s,%s,%s)',
                                       [(dataset, r['symbol'], r['session_date'], Jsonb(r)) for r in rows])
                for entry in prices:
                    frame = pd.read_parquet(root / entry['path'])
                    # Canonical cache reflects exactly this provider/window. Immutable sessions
                    # retain previous snapshots for reproducible historical analysis.
                    cursor.execute('''DELETE FROM marketpulse.daily_prices WHERE symbol=%s AND
                        provider=%s AND session_date >= %s AND session_date < %s''',
                                   (frame.symbol.iloc[0], raw['provider'],
                                    raw['request']['start_inclusive'], raw['request']['end_exclusive']))
                    columns = ['symbol', 'session_date', 'open', 'high', 'low', 'close', 'adj_close',
                               'volume', 'provider', 'adjustment', 'observed_at', 'run_id']
                    cursor.executemany('''INSERT INTO marketpulse.daily_prices
                        (symbol,session_date,open,high,low,close,adj_close,volume,provider,
                         adjustment,observed_at,run_id) VALUES
                        (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                                       [tuple(r[c] for c in columns) for r in records(frame)])
                for entry in features['outputs']:
                    frame = pd.read_parquet(root / entry['path'])
                    rows = records(frame.loc[frame.input_valid])
                    cursor.executemany('''INSERT INTO marketpulse.technical_indicators
                        (symbol,session_date,feature_version,dataset_sha256,available_at,values)
                        VALUES (%s,%s,%s,%s,%s,%s)''',
                                       [(r['symbol'], r['session_date'], features['feature_version'],
                                         dataset, r['available_at'],
                                         Jsonb({c: r[c] for c in features['predictor_columns']}))
                                        for r in rows])
        # Verify all immutable session and feature payloads, not just row counts.
        expected_sessions = {}
        for entry in aligned:
            for r in records(pd.read_parquet(root / entry['path'])):
                expected_sessions[(r['symbol'], r['session_date'])] = r
        actual_sessions = {(s, str(d)): p for s, d, p in conn.execute(
            'SELECT symbol,session_date,payload FROM marketpulse.validated_sessions WHERE dataset_id=%s',
            (dataset,)).fetchall()}
        if actual_sessions != expected_sessions:
            raise ValueError('Database session reconciliation failed')
        expected_features = {}
        for entry in features['outputs']:
            frame = pd.read_parquet(root / entry['path'])
            for r in records(frame.loc[frame.input_valid]):
                expected_features[(r['symbol'], r['session_date'])] = {
                    c: r[c] for c in features['predictor_columns']}
        actual_features = {(s, str(d)): p for s, d, p in conn.execute('''SELECT symbol,session_date,
            values FROM marketpulse.technical_indicators WHERE dataset_sha256=%s''', (dataset,))}
        if expected_features != actual_features:
            raise ValueError('Database feature reconciliation failed')
        conn.execute('''INSERT INTO marketpulse.active_dataset VALUES (true,%s)
            ON CONFLICT(singleton) DO UPDATE SET dataset_id=EXCLUDED.dataset_id''', (dataset,))
    return {'dataset_id': dataset, 'new_load': not bool(exists),
            'sessions': len(actual_sessions), 'feature_rows': len(actual_features),
            'price_rows': sum(o['rows'] for o in prices), 'issues': len(issues),
            'calendar_dates': len(calendar), 'verification': 'all snapshot and feature values match'}


def main():
    root = Path.cwd()
    load_dotenv(root / '.env')
    with connection() as conn:
        migrate(conn, root)
        result = load(root, conn)
        repeated = load(root, conn)
        if repeated['new_load']:
            raise ValueError('Repeat load was not idempotent')
    result['idempotent_rerun_verified'] = True
    report = root / 'reports/stage5'
    report.mkdir(parents=True, exist_ok=True)
    (report / 'database_load.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
