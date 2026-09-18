"""Explainable technical state and past-only anomaly reference for the latest valid session."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from psycopg.types.json import Jsonb
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline

from marketpulse.cli import connection, migrate
from marketpulse.db.load import read_artifacts, records
from marketpulse.quality.validate import sha


def technical(row, config):
    pairs = [('ema_12', 'ema_26'), ('macd', 'macd_signal')]
    votes = [float(np.sign(row[a] - row[b])) for a, b in pairs
             if pd.notna(row.get(a)) and pd.notna(row.get(b))]
    if pd.notna(row.get('return_20d')):
        votes.append(float(np.sign(row['return_20d'])))
    score = float(np.mean(votes)) if len(votes) >= 2 else None
    trend = ('Unavailable' if score is None else 'Bullish' if score >= .5 else
             'Bearish' if score <= -.5 else 'Neutral')
    vol = row.get('volatility_20')
    risk = ('Unavailable' if pd.isna(vol) else 'High Risk' if vol >= config['high_volatility']
            else 'Low' if vol < config['low_volatility'] else 'Moderate')
    volume = row.get('relative_volume_20')
    return {'technical_score': score, 'signal': trend, 'risk_band': risk,
            'annualized_volatility': vol, 'rsi_14': row.get('rsi_14'),
            'relative_volume': volume,
            'abnormal_volume': None if pd.isna(volume) else bool(volume >= config['abnormal_volume_multiple'])}


def assess(frame, config):
    ready = frame.loc[frame.core_ready].sort_values('session_date')
    if ready.empty:
        raise ValueError('No core-ready session for instrument')
    latest = ready.iloc[-1]
    history = ready.loc[ready.session_date < latest.session_date].tail(config['isolation_training_rows'])
    result = {'symbol': latest.symbol, 'session_date': str(latest.session_date),
              'source_last_session': str(frame.session_date.max()),
              'latest_input_missing': bool(latest.session_date != frame.session_date.max()),
              **technical(latest, config)}
    selected = ['return_1d', 'volatility_20', 'rsi_14']
    if history.relative_volume_20.notna().any():
        selected.append('relative_volume_20')
    result.update(isolation_score=None, isolation_anomaly=None, training_rows=len(history),
                  training_end=None if history.empty else str(history.session_date.max()))
    if len(history) >= config['isolation_minimum_rows']:
        detector = make_pipeline(SimpleImputer(strategy='median'), IsolationForest(
            n_estimators=100, contamination=config['isolation_contamination'],
            random_state=config['seed'], n_jobs=2))
        detector.fit(history[selected])
        score = float(detector.decision_function(ready.iloc[[-1]][selected])[0])
        result.update(isolation_score=score, isolation_anomaly=bool(score < 0))
    # Return surprise uses only the current contiguous segment, excluding the evaluated return.
    position = frame.index[frame.session_date == latest.session_date][0]
    segment = frame.loc[:position]
    gaps = segment.index[~segment.input_valid]
    if len(gaps):
        segment = segment.loc[gaps[-1] + 1:]
    previous = segment.iloc[:-1].tail(60).return_1d
    std = previous.std(ddof=1)
    z = ((latest.return_1d - previous.mean()) / std
         if previous.notna().sum() >= 40 and std > 0 else None)
    result['return_z'] = z
    result['statistical_anomaly'] = None if z is None else bool(abs(z) >= config['return_z_threshold'])
    result['attention'] = bool(result['risk_band'] == 'High Risk' or result['abnormal_volume']
                               or result['isolation_anomaly'] or result['statistical_anomaly'])
    return result


def main():
    root = Path.cwd()
    features, _, _, _, _, _ = read_artifacts(root)
    config = json.loads((root / 'config/risk.json').read_text())
    identity = {'dataset_id': features['dataset_sha256'], 'config': config,
                'implementation_sha256': sha(Path(__file__))}
    run_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    rows = [assess(pd.read_parquet(root / entry['path']), config) for entry in features['outputs']]
    frame = pd.DataFrame(rows)
    folder = root / 'reports/stage8' / run_id
    folder.mkdir(parents=True, exist_ok=True)
    frame.to_csv(folder / 'risk.csv', index=False)
    manifest = {**identity, 'run_id': run_id, 'created_at': datetime.now(UTC).isoformat(),
                'risk_sha256': sha(folder / 'risk.csv'), 'research_only': True,
                'status': 'complete', 'instruments': len(rows)}
    load_dotenv(root / '.env')
    with connection() as conn:
        migrate(conn, root)
        active = conn.execute('SELECT dataset_id FROM marketpulse.active_dataset').fetchone()
        if not active or active[0] != features['dataset_sha256']:
            raise ValueError('Load current features into PostgreSQL first')
        conn.execute('INSERT INTO marketpulse.risk_runs VALUES (%s,%s,%s,%s,%s) '
                     'ON CONFLICT(risk_run_id) DO NOTHING',
                     (run_id, features['dataset_sha256'], manifest['created_at'], Jsonb(config), Jsonb(manifest)))
        for row in records(frame):
            conn.execute('INSERT INTO marketpulse.risk_observations VALUES (%s,%s,%s,%s) '
                         'ON CONFLICT(risk_run_id,symbol) DO NOTHING',
                         (run_id, row['symbol'], row['session_date'], Jsonb(row)))
        actual = {s: p for s, p in conn.execute(
            'SELECT symbol,details FROM marketpulse.risk_observations WHERE risk_run_id=%s', (run_id,))}
        if actual != {r['symbol']: r for r in records(frame)}:
            raise ValueError('Risk reconciliation mismatch')
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (root / 'reports/stage8/latest.json').write_text(json.dumps({'run_id': run_id}))
    print(f'Risk assessment verified for {len(rows)} instruments: {folder}')


if __name__ == '__main__':
    main()
