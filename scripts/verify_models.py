"""Reconcile saved models with exported holdout predictions and scores."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from marketpulse.models.train import metrics
from marketpulse.quality.validate import sha

root = Path.cwd()
run_id = json.loads((root / 'reports/stage7/latest.json').read_text())['run_id']
folder = root / 'reports/stage7' / run_id
manifest = json.loads((folder / 'manifest.json').read_text())
for name, checksum in manifest['outputs'].items():
    assert sha(root / name) == checksum, name
audit = pd.read_csv(folder / 'split_audit.csv')
assert (pd.to_datetime(audit.latest_training_outcome) < pd.to_datetime(audit.start)).all()
prediction = pd.read_csv(folder / 'holdout_predictions.csv')
assert not prediction.duplicated(['target', 'model', 'symbol', 'session_date']).any()
assert np.isfinite(prediction[['prediction', 'actual']].to_numpy()).all()
assert (pd.to_datetime(prediction.session_date) >= pd.Timestamp(manifest['holdout_start'])).all()
scores = pd.read_csv(folder / 'metrics.csv')
per_symbol = []
for (target, model), group in prediction.groupby(['target', 'model']):
    row = scores[(scores.target == target) & (scores.model == model) & (scores.split == 'holdout')].iloc[0]
    computed = metrics(group.actual, group.prediction, target == 'direction_1d')
    for name, value in computed.items():
        if value is not None:
            np.testing.assert_allclose(row[name], value, atol=1e-12)
    for symbol, part in group.groupby('symbol'):
        per_symbol.append({'target': target, 'model': model, 'symbol': symbol, 'rows': len(part),
                           **metrics(part.actual, part.prediction, target == 'direction_1d')})
# Retrieve the feature version bound into the completed experiment, not a future latest pointer.
paths = list((root / 'data/features').glob('*/manifest.json'))
feature_path = next(p for p in paths if sha(p) == manifest['feature_manifest_sha256'])
features = json.loads(feature_path.read_text())
frames = []
for entry in features['outputs']:
    assert sha(root / entry['path']) == entry['sha256']
    frames.append(pd.read_parquet(root / entry['path']))
frame = pd.concat(frames, ignore_index=True)
frame.session_date = pd.to_datetime(frame.session_date).dt.strftime('%Y-%m-%d')
identity = pd.get_dummies(frame.symbol, prefix='instrument', dtype=float)
x = pd.concat([frame[features['predictor_columns']], identity], axis=1)
x.index = pd.MultiIndex.from_frame(frame[['symbol', 'session_date']])
for target, choice in manifest['selected'].items():
    bundle = joblib.load(root / 'artifacts/models' / run_id / f'{target}.joblib')
    group = prediction[(prediction.target == target) & (prediction.model == choice['model'])]
    values = x.loc[pd.MultiIndex.from_frame(group[['symbol', 'session_date']]), bundle['predictors']]
    pipeline = bundle['pipeline']
    actual = pipeline.predict_proba(values)[:, 1] if target == 'direction_1d' else pipeline.predict(values)
    np.testing.assert_allclose(actual, group.prediction, rtol=1e-7, atol=1e-12)
pd.DataFrame(per_symbol).to_csv(folder / 'per_symbol_metrics.csv', index=False)
result = {'status': 'passed', 'output_hashes_verified': len(manifest['outputs']),
          'purged_splits_verified': len(audit), 'holdout_predictions_verified': len(prediction),
          'saved_models_reproduced': len(manifest['selected']),
          'per_symbol_scores': len(per_symbol)}
(folder / 'verification.json').write_text(json.dumps(result, indent=2))
lines = ['# Stage 7 results', '',
         'Completed historical experiments for NIFTY50 and ten stocks.',
         (f"Validation: {manifest['folds']} expanding quarterly folds. Final holdout starts "
          f"{manifest['holdout_start']}."), '',
         'Models were selected before evaluating the holdout. Smaller Brier and return errors are better.',
         '', '| Target | Selected model | Mean validation loss | Holdout loss | Baseline holdout loss |',
         '|---|---|---:|---:|---:|']
for target, choice in manifest['selected'].items():
    name = choice['selection_metric']
    held = scores[(scores.target == target) & (scores.split == 'holdout')].set_index('model')
    lines.append(f"| {target} | {choice['model']} | {choice['mean_validation_score']:.6f} | "
                 f"{held.loc[choice['model'], name]:.6f} | {held.loc['baseline', name]:.6f} |")
lines += ['', 'Direction loss is Brier score; return loss is MAE in return fractions.',
          'An MAE of 0.01 is one percentage point of return error. A selected baseline means',
          'the tested trained candidates did not improve the predefined validation criterion.',
          '', '## Direction details', '',
          '| Model | Balanced accuracy | ROC-AUC | Brier | Log loss |',
          '|---|---:|---:|---:|---:|']
for r in scores[(scores.target == 'direction_1d') & (scores.split == 'holdout')].itertuples():
    lines.append(f'| {r.model} | {r.balanced_accuracy:.2%} | {r.roc_auc:.4f} | '
                 f'{r.brier:.4f} | {r.log_loss:.4f} |')
lines += ['', '## Candidate comparison on validation only', '',
          '| Target | Candidate | Mean validation loss |', '|---|---|---:|']
for target, choice in manifest['selected'].items():
    means = scores[(scores.target == target) & (scores.split == 'validation')].groupby(
        'model')[choice['selection_metric']].mean()
    for name, value in means.items():
        lines.append(f'| {target} | {name} | {value:.6f} |')
lines += ['', '## Files and checks', '',
          '- metrics.csv: all validation folds and final holdout scores.',
          '- per_symbol_metrics.csv: final scores and sample counts for each instrument.',
          '- calibration.csv: predicted probability versus observed frequency.',
          '- holdout_predictions.csv: dated, reproducible historical predictions and outcomes.',
          '- split_audit.csv and verification.json: purging and saved-model reproduction checks.',
          '', 'All three saved models reproduce the exported predictions. The full test suite has 61 tests.',
          '', '## Limits', '',
          'These are revised-snapshot research results, not point-in-time trading performance.',
          'No claim of a reliable trading edge follows from small score differences.',
          'Missing sessions remain excluded; correlated instruments and overlapping outcomes',
          'reduce the effective independent sample size. No live signals were generated.']
(folder / 'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')
print(json.dumps(result, indent=2))
