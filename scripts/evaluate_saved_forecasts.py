"""Audit previously published forecasts against validated, completed outcomes."""
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from marketpulse.cli import connection
from marketpulse.models.train import labels
from marketpulse.quality.validate import sha

root = Path(__file__).resolve().parents[1]
now = datetime.now(UTC)
out = root / 'reports/validation' / (now.strftime('%Y-%m-%dT%H%M%SZ') + '-credibility')
out.mkdir(parents=True)
checks = {}
for name in ['verify_release', 'verify_database', 'verify_analytics', 'verify_models', 'verify_features']:
    result = subprocess.run([sys.executable, str(root / 'scripts' / (name + '.py'))],
                            cwd=root, capture_output=True, text=True, timeout=180, check=False)
    checks[name] = {'passed': result.returncode == 0, 'output': result.stdout, 'error': result.stderr}
if not all(c['passed'] for c in checks.values()):
    (out / 'checks.json').write_text(json.dumps(checks, indent=2))
    raise SystemExit('Integrity check failed; scoring stopped. See ' + str(out))
q = json.loads((root / 'data/processed' / json.loads((root / 'data/processed/latest.json').read_text())['quality_id'] / 'manifest.json').read_text())
frames = []
for entry in q['outputs']:
    if entry.get('kind') == 'aligned':
        path = root / entry['path']
        assert sha(path) == entry['sha256']
        frames.append(labels(pd.read_parquet(path).sort_values('session_date')))
actual = pd.concat(frames, ignore_index=True)
actual['session_date'] = actual.session_date.astype(str)
load_dotenv(root / '.env')
rows, excluded = [], {}
with connection() as conn:
    for path in (root / 'data/dashboard').glob('*/manifest.json'):
        m = json.loads(path.read_text())
        fp = path.parent / 'Forecasts.csv'
        if not fp.exists() or 'model_run_id' not in m:
            continue
        issued = pd.Timestamp(m['created_at'])
        model = json.loads((root / 'reports/stage7' / m['model_run_id'] / 'manifest.json').read_text())
        assert pd.Timestamp(model['created_at']) <= issued
        assert sha(fp) == m['outputs']['Forecasts.csv']
        db = conn.execute('SELECT manifest FROM marketpulse.dashboard_snapshots WHERE snapshot_id=%s', (m['snapshot_id'],)).fetchone()
        if db is None or db[0] != m:
            excluded['unverified_snapshot'] = excluded.get('unverified_snapshot', 0) + 1
            continue
        for r in pd.read_csv(fp).itertuples():
            if pd.isna(r.value) or str(r.status).startswith('Skipped'):
                continue
            # Strictly before the target day's opening; never retrospective same-day issues.
            if issued >= pd.Timestamp(r.target_date, tz='Asia/Kolkata'):
                continue
            if pd.Timestamp(r.target_date + ' 16:00', tz='Asia/Kolkata') > now:
                continue
            horizon = 5 if r.target.endswith('5d') else 1
            a = actual[(actual.symbol == r.symbol) & (actual.session_date == r.as_of_date)]
            if a.empty or pd.isna(a.iloc[0][r.target]) or str(a.iloc[0][f'target_date_{horizon}d'].date()) != r.target_date:
                excluded['unavailable_outcome_before_dedup'] = excluded.get('unavailable_outcome_before_dedup', 0) + 1
                continue
            rows.append({'snapshot_id': m['snapshot_id'], 'issued_at': issued.isoformat(),
                         'symbol': r.symbol, 'as_of_date': r.as_of_date, 'target_date': r.target_date,
                         'target': r.target, 'prediction': float(r.value),
                         'actual': float(a.iloc[0][r.target]), 'model': r.model})
f = pd.DataFrame(rows)
if not f.empty:
    f = f.sort_values('issued_at').drop_duplicates(['symbol', 'as_of_date', 'target_date', 'target'])
f.to_csv(out / 'scored_predictions.csv', index=False)
metrics = {}
if not f.empty:
    for (target, day), g in f.groupby(['target', 'target_date']):
        item = {'n': len(g), 'models': g.model.unique().tolist()}
        if target == 'direction_1d':
            item.update(accuracy=float(((g.prediction >= .5) == g.actual).mean()),
                        brier=float(((g.prediction - g.actual) ** 2).mean()),
                        half_probability_brier=.25, always_up_accuracy=float(g.actual.mean()))
        else:
            item.update(mae=float(abs(g.prediction - g.actual).mean()),
                        zero_return_mae=float(abs(g.actual).mean()))
        metrics[f'{target} / {day}'] = item
pointer = json.loads((root / 'data/dashboard/current.json').read_text())
m = json.loads((Path(pointer['path']) / 'manifest.json').read_text())
report = {'checked_at': now.isoformat(), 'published_session': m['expected_session'],
          'checks': checks, 'metrics': metrics, 'excluded': excluded,
          'limitations': ['Selected forecasts are baselines; no ML advantage established.',
                          'Only a few correlated market sessions; not proof of reliability or profitability.',
                          'Historical training source is not point-in-time certified.',
                          'Outcomes use the current validated adjusted-price snapshot and require every intervening session eligible.',
                          'Repeated exports are deduplicated using the earliest pre-target issue.',
                          'No forecast was retrained or regenerated for this evaluation.']}
(out / 'report.json').write_text(json.dumps(report, indent=2))
lines = ['# MarketPulse prediction credibility check', '',
         'Published data through ' + m['expected_session'] + '. All five integrity and calculation checks passed.', '',
         '| Target and outcome date | Samples | Accuracy | Brier | Return MAE | Comparator |',
         '|---|---:|---:|---:|---:|---|']
for key, v in metrics.items():
    if 'accuracy' in v:
        lines.append(f"| {key} | {v['n']} | {v['accuracy']:.1%} | {v['brier']:.4f} | - | Always-up: {v['always_up_accuracy']:.1%}; 50/50 Brier: 0.2500 |")
    else:
        lines.append(f"| {key} | {v['n']} | - | - | {v['mae'] * 100:.3f} percentage points | Zero return: {v['zero_return_mae'] * 100:.3f} percentage points |")
lines += ['', '## Interpretation', 'The pipeline and analytics are internally consistent. Predictive advantage is not demonstrated. Five-day outcomes are not scored until eligible validated prices exist.', '']
lines += ['- ' + s for s in report['limitations']]
(out / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps({'report': str(out / 'REPORT.md'), 'metrics': metrics}, indent=2))
