"""Publish a coherent dashboard snapshot, forecasts and plain-language daily report."""
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import joblib
import pandas as pd
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from marketpulse.cli import connection
from marketpulse.db.load import read_artifacts, records
from marketpulse.pipeline import expected_session
from marketpulse.quality.sessions import make_calendar
from marketpulse.quality.validate import sha


def latest(root, stage):
    folder = root / 'reports' / stage
    return folder / json.loads((folder / 'latest.json').read_text())['run_id']


def export(root):
    feature, quality, _, _, _, _ = read_artifacts(root)
    risk_dir, analytics_dir, model_dir = [latest(root, s) for s in ['stage8', 'stage6', 'stage7']]
    risk_manifest = json.loads((risk_dir / 'manifest.json').read_text())
    analysis_manifest = json.loads((analytics_dir / 'manifest.json').read_text())
    model_manifest = json.loads((model_dir / 'manifest.json').read_text())
    dataset = feature['dataset_sha256']
    if risk_manifest['dataset_id'] != dataset or analysis_manifest['dataset_id'] != dataset:
        raise ValueError('Mixed source datasets cannot be published')
    if sha(risk_dir / 'risk.csv') != risk_manifest['risk_sha256']:
        raise ValueError('Risk checksum mismatch')
    for parent, manifest in [(analytics_dir, analysis_manifest), (root, model_manifest)]:
        for name, checksum in manifest['outputs'].items():
            if sha(parent / name) != checksum:
                raise ValueError('Dashboard source checksum mismatch')
    frame = pd.concat([pd.read_parquet(root / e['path']) for e in feature['outputs']], ignore_index=True)
    prices = pd.concat([pd.read_parquet(root / e['path']) for e in quality['outputs']
                        if e.get('kind') == 'aligned'], ignore_index=True)
    history = frame.merge(prices[['symbol', 'session_date', 'adj_close', 'volume']],
                          on=['symbol', 'session_date'], validate='one_to_one')
    risk = pd.read_csv(risk_dir / 'risk.csv')
    market = risk.merge(history[['symbol', 'session_date', 'adj_close', 'return_1d']],
                        on=['symbol', 'session_date'], validate='one_to_one')
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo('Asia/Kolkata')).date()
    market['calendar_age_days'] = (pd.Timestamp(today) - pd.to_datetime(market.session_date)).dt.days
    market['data_status'] = market.latest_input_missing.map({True: 'No current risk reading', False: 'Current indicators'})
    universe = pd.DataFrame(json.loads((root / 'config/universe.json').read_text()))
    market = market.merge(universe[['symbol', 'sector']], on='symbol', validate='one_to_one')
    scores = pd.read_csv(model_dir / 'metrics.csv')
    score_summary = scores.groupby(['target', 'model', 'split'], as_index=False).agg(
        balanced_accuracy=('balanced_accuracy', 'mean'), roc_auc=('roc_auc', 'mean'),
        brier=('brier', 'mean'), mae=('mae', 'mean'), rmse=('rmse', 'mean'))
    score_summary['selection'] = score_summary.apply(lambda r: 'Selected' if
        model_manifest['selected'][r.target]['model'] == r.model else 'Candidate', axis=1)
    score_summary['evidence'] = 'Baseline won validation; no demonstrated model advantage'
    run_id = str(uuid4())
    folder = root / 'data/dashboard' / run_id
    folder.mkdir(parents=True)
    config_path = root / 'config/nse_sessions_operational.json'
    reference = json.loads((config_path if config_path.exists() else root /
                            'config/nse_sessions_reference.json').read_text())
    calendar = make_calendar(reference['coverage_start'], reference['coverage_end_exclusive'], reference)
    expected = expected_session(now, reference)
    market['latest_input_missing'] = market.session_date < expected
    market['data_status'] = market.latest_input_missing.map({True: 'No current risk reading', False: 'Current indicators'})
    sessions = list(calendar.loc[calendar.expected_open, 'session_date'])
    forecasts = []
    for target, selection in model_manifest['selected'].items():
        bundle_path = root / 'artifacts/models' / model_manifest['run_id'] / f'{target}.joblib'
        bundle = joblib.load(bundle_path)
        tail = frame.loc[frame.core_ready].sort_values('session_date').groupby('symbol').tail(1)
        x = pd.concat([tail[feature['predictor_columns']],
                       pd.get_dummies(tail.symbol, prefix='instrument', dtype=float)], axis=1)
        x = x.reindex(columns=bundle['predictors'], fill_value=0)
        available = pd.to_datetime(tail.available_at, utc=True) <= now
        values = (bundle['pipeline'].predict_proba(x)[:, 1] if target == 'direction_1d'
                  else bundle['pipeline'].predict(x))
        horizon = 5 if target.endswith('5d') else 1
        for (idx, row), value in zip(tail.iterrows(), values, strict=True):
            position = sessions.index(row.session_date) + horizon
            target_date = sessions[position] if position < len(sessions) else None
            stale = row.session_date < expected
            valid = bool(available.loc[idx] and not stale and target_date and target_date > str(today))
            status = ('Research baseline only' if valid else 'Skipped: stale input or non-future target date'
                      if stale or target_date and target_date <= str(today) else 'Skipped: calendar/availability')
            forecasts.append({'symbol': row.symbol, 'as_of_date': row.session_date,
                              'target': target, 'target_date': target_date,
                              'value': float(value) if valid else None,
                              'status': status, 'model': selection['model']})
    forecast_frame = pd.DataFrame(forecasts)
    equities = market.loc[(market.symbol != 'NIFTY50') & ~market.latest_input_missing]
    counts = equities.signal.value_counts()
    summary = (f"Session {expected}, {len(equities)} stocks with current indicators: "
               f"{int(counts.get('Bullish', 0))} stocks have bullish "
               f"technical readings, {int(counts.get('Bearish', 0))} bearish and "
               f"{int(counts.get('Neutral', 0))} neutral. "
               f"{int(equities.abnormal_volume.fillna(False).sum())} show abnormal volume; "
               f"{int((equities.risk_band == 'High Risk').sum())} exceed the configured volatility threshold.")
    insights = pd.DataFrame([
        {'topic': 'Market summary', 'insight': summary},
        {'topic': 'Data freshness', 'insight': f"Generated {now.isoformat()}; latest source grid ends "
         f"{frame.session_date.max()}. {int(market.latest_input_missing.sum())} instruments lack current "
         'core-ready indicators and are excluded from the signal counts.'},
        {'topic': 'Model evidence', 'insight': 'Simple baselines won all three targets. No ML trading edge established.'},
        {'topic': 'Interpretation', 'insight': 'Technical labels describe observed conditions; anomaly flags require review.'}])
    tables = {'Market': market, 'History': history[['symbol', 'session_date', 'adj_close', 'volume',
               'sma_20', 'ema_12', 'ema_26', 'rsi_14', 'macd', 'macd_signal', 'volatility_20', 'return_1d']],
              'Performance': pd.read_csv(analytics_dir / 'metrics.csv'),
              'Models': score_summary, 'Forecasts': forecast_frame,
              'Anomalies': risk, 'Insights': insights, 'Symbols': universe[['symbol', 'name', 'sector']]}
    schema = {}
    for name, table in tables.items():
        table.to_csv(folder / f'{name}.csv', index=False)
        schema[name] = {c: 'boolean' if pd.api.types.is_bool_dtype(table[c]) else
                        'double' if pd.api.types.is_numeric_dtype(table[c]) else 'string' for c in table}
    manifest = {'snapshot_id': run_id, 'dataset_id': dataset, 'created_at': now.isoformat(),
                'model_run_id': model_manifest['run_id'], 'risk_run_id': risk_manifest['run_id'],
                'stale_instruments': int(market.latest_input_missing.sum()),
                'expected_session': expected, 'schema': schema,
                'outputs': {p.name: sha(p) for p in folder.glob('*.csv')}}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    report = root / 'reports/daily' / run_id
    report.mkdir(parents=True)
    (report / 'DAILY_REPORT.md').write_text('# MarketPulse daily insights\n\n' +
        '\n\n'.join(f"**{r.topic}**\n\n{r.insight}" for r in insights.itertuples()), encoding='utf-8')
    load_dotenv(root / '.env')
    with connection() as conn:
        conn.execute('INSERT INTO marketpulse.dashboard_snapshots VALUES (%s,%s,%s,%s)',
                     (run_id, dataset, now, Jsonb(manifest)))
        for row in records(forecast_frame):
            conn.execute('INSERT INTO marketpulse.research_forecasts VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (run_id, row['symbol'], row['as_of_date'], row['target'], row['target_date'],
                          model_manifest['run_id'], row['value'], row['status'], Jsonb(row)))
    temporary = root / 'data/dashboard/current.tmp'
    temporary.write_text(json.dumps({'snapshot_id': run_id, 'path': folder.resolve().as_posix(),
                                     'manifest_sha256': sha(folder / 'manifest.json')}))
    temporary.replace(root / 'data/dashboard/current.json')
    print(f'Dashboard snapshot published: {run_id}')
    return manifest


if __name__ == '__main__':
    export(Path.cwd())
