"""Purged, date-grouped historical model experiments; never live trading signals."""
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from marketpulse.db.load import read_artifacts
from marketpulse.quality.validate import sha

TARGETS = {'direction_1d': 1, 'future_return_1d': 1, 'future_return_5d': 5}


def labels(frame):
    """Input must retain every session, including explicit missing-price rows."""
    if frame.symbol.nunique() != 1 or frame.session_date.duplicated().any():
        raise ValueError('One symbol with unique sessions required')
    dates = pd.to_datetime(frame.session_date)
    if not dates.is_monotonic_increasing:
        raise ValueError('Unsorted sessions')
    result = frame[['symbol', 'session_date']].copy()
    valid = frame.feature_eligible.fillna(False).astype(bool)
    for horizon in [1, 5]:
        eligible = valid.copy()
        for offset in range(1, horizon + 1):
            eligible &= valid.shift(-offset, fill_value=False)
        result[f'future_return_{horizon}d'] = (
            frame.adj_close.shift(-horizon) / frame.adj_close - 1).where(eligible)
        result[f'target_date_{horizon}d'] = dates.shift(-horizon)
    result['direction_1d'] = (result.future_return_1d > 0).astype(float).where(
        result.future_return_1d.notna())
    return result


def splits(dates, config):
    dates = pd.DatetimeIndex(sorted(pd.unique(dates)))
    holdout = dates[-1] - pd.DateOffset(months=config['holdout_months'])
    start = dates[0] + pd.DateOffset(years=config['initial_train_years'])
    folds = []
    while start < holdout:
        end = min(start + pd.DateOffset(months=config['validation_months']), holdout)
        folds.append((start, end))
        start = end
    if not folds:
        raise ValueError('Insufficient history for configured validation')
    return folds, holdout


def masks(frame, target, start, end):
    # Universal five-session purge, even for the one-session targets.
    ready = frame.core_ready & frame[target].notna()
    train = ready & (frame.session_date < start) & (frame.target_date_5d < start)
    test = ready & (frame.session_date >= start) & (frame.session_date < end)
    # Do not let validation selection see outcomes in the final holdout.
    test &= frame[f'target_date_{TARGETS[target]}d'] < end
    return train, test


def estimator(name, classification, config):
    seed = config['seed']
    if name == 'baseline':
        model = DummyClassifier(strategy='prior') if classification else DummyRegressor(
            strategy='constant', constant=0)
    elif name == 'linear':
        model = LogisticRegression(C=.1, max_iter=2000, random_state=seed) if classification else Ridge(alpha=10)
    elif name == 'random_forest':
        cls = RandomForestClassifier if classification else RandomForestRegressor
        model = cls(n_estimators=config['trees'], max_depth=config['max_depth'],
                    min_samples_leaf=30, max_features=.7, n_jobs=2, random_state=seed)
    elif name == 'xgboost':
        cls = xgboost.XGBClassifier if classification else xgboost.XGBRegressor
        model = cls(n_estimators=config['xgb_trees'], max_depth=config['xgb_depth'],
                    learning_rate=config['learning_rate'], tree_method='hist',
                    n_jobs=2, random_state=seed, subsample=1, colsample_bytree=1)
    else:
        raise ValueError(name)
    return make_pipeline(SimpleImputer(strategy='median', add_indicator=True,
                                      keep_empty_features=True), StandardScaler(), model)


def metrics(y, pred, classification):
    if classification:
        return {'balanced_accuracy': float(balanced_accuracy_score(y, pred >= .5)),
                'roc_auc': float(roc_auc_score(y, pred)) if len(np.unique(y)) == 2 else None,
                'brier': float(brier_score_loss(y, pred)),
                'log_loss': float(log_loss(y, pred, labels=[0, 1]))}
    return {'mae': float(mean_absolute_error(y, pred)),
            'rmse': float(np.sqrt(mean_squared_error(y, pred)))}


def main():
    root = Path.cwd()
    config = json.loads((root / 'config/models.json').read_text())
    features, quality, _, _, _, _ = read_artifacts(root)
    frames, targets = [], []
    for entry in quality['outputs']:
        if entry.get('kind') == 'aligned':
            targets.append(labels(pd.read_parquet(root / entry['path'])))
    for entry in features['outputs']:
        frames.append(pd.read_parquet(root / entry['path']))
    target_frame = pd.concat(targets, ignore_index=True)
    frame = pd.concat(frames, ignore_index=True).merge(
        target_frame, on=['symbol', 'session_date'], validate='one_to_one')
    frame.session_date = pd.to_datetime(frame.session_date)
    frame = frame.sort_values(['session_date', 'symbol']).reset_index(drop=True)
    columns = features['predictor_columns']
    # Fixed universe identity is metadata known before validation; no fitted encoding.
    identity = pd.get_dummies(frame.symbol, prefix='instrument', dtype=float)
    x = pd.concat([frame[columns], identity], axis=1).astype(float)
    assert not np.isinf(x.to_numpy()).any()
    folds, holdout = splits(frame.session_date, config)
    run_id = str(uuid4())
    folder = root / 'reports/stage7' / run_id
    artifacts = root / 'artifacts/models' / run_id
    folder.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    target_frame.to_parquet(artifacts / 'targets.parquet', index=False)
    results, predictions, audit, selected, calibration = [], [], [], {}, []
    names = ['baseline', 'linear', 'random_forest', 'xgboost']
    for target in TARGETS:
        classification = target == 'direction_1d'
        score = 'brier' if classification else 'mae'
        for number, (start, end) in enumerate(folds):
            train, test = masks(frame, target, start, end)
            if train.sum() < 100 or test.sum() == 0:
                raise ValueError('Insufficient observations in fold')
            assert frame.loc[train, 'target_date_5d'].max() < start
            audit.append({'target': target, 'fold': number, 'start': str(start.date()),
                          'end_exclusive': str(end.date()), 'train_rows': int(train.sum()),
                          'test_rows': int(test.sum()),
                          'latest_training_outcome': str(frame.loc[train, 'target_date_5d'].max().date())})
            for name in names:
                model = estimator(name, classification, config)
                model.fit(x.loc[train], frame.loc[train, target])
                pred = model.predict_proba(x.loc[test])[:, 1] if classification else model.predict(x.loc[test])
                results.append({'target': target, 'model': name, 'split': 'validation',
                                'fold': number, 'rows': int(test.sum()),
                                **metrics(frame.loc[test, target], pred, classification)})
            print(f'{target}: validation {number + 1}/{len(folds)}', flush=True)
        table = pd.DataFrame(results)
        candidates = table[(table.target == target) & (table.split == 'validation')]
        # Equal fold weights; selection rule fixed before opening final holdout.
        winner = candidates.groupby('model')[score].mean().idxmin()
        selected[target] = {'model': winner, 'selection_metric': score,
                            'mean_validation_score': float(candidates.groupby('model')[score].mean()[winner])}
        end = frame.session_date.max() + pd.Timedelta(days=1)
        train, test = masks(frame, target, holdout, end)
        audit.append({'target': target, 'fold': 'holdout', 'start': str(holdout.date()),
                      'end_exclusive': str(end.date()), 'train_rows': int(train.sum()),
                      'test_rows': int(test.sum()),
                      'latest_training_outcome': str(frame.loc[train, 'target_date_5d'].max().date())})
        for name in dict.fromkeys([winner, 'baseline']):
            model = estimator(name, classification, config)
            model.fit(x.loc[train], frame.loc[train, target])
            pred = model.predict_proba(x.loc[test])[:, 1] if classification else model.predict(x.loc[test])
            results.append({'target': target, 'model': name, 'split': 'holdout', 'fold': -1,
                            'rows': int(test.sum()), **metrics(frame.loc[test, target], pred, classification)})
            output = frame.loc[test, ['symbol', 'session_date', f'target_date_{TARGETS[target]}d']].copy()
            output['actual'] = frame.loc[test, target]
            output['prediction'] = pred
            output['target'] = target
            output['model'] = name
            predictions.append(output)
            if classification:
                for lo in np.arange(0, 1, .1):
                    group = output[(output.prediction >= lo) & (output.prediction <= lo + .1
                                   if lo > .89 else output.prediction < lo + .1)]
                    calibration.append({'model': name, 'lower': lo, 'rows': len(group),
                                        'mean_probability': group.prediction.mean(),
                                        'observed_positive_rate': group.actual.mean()})
            if name == winner:
                joblib.dump({'pipeline': model, 'predictors': list(x.columns),
                             'target': target, 'dataset_id': features['dataset_sha256'],
                             'research_only': True, 'holdout_start': str(holdout)},
                            artifacts / f'{target}.joblib')
        pd.DataFrame(results).to_csv(folder / 'metrics.csv', index=False)
    pd.concat(predictions, ignore_index=True).to_csv(folder / 'holdout_predictions.csv', index=False)
    pd.DataFrame(audit).to_csv(folder / 'split_audit.csv', index=False)
    pd.DataFrame(calibration).to_csv(folder / 'calibration.csv', index=False)
    manifest = {'run_id': run_id, 'status': 'complete', 'created_at': datetime.now(UTC).isoformat(),
                'dataset_id': features['dataset_sha256'], 'config': config,
                'point_in_time_certified': False, 'research_only': True,
                'holdout_start': str(holdout.date()), 'folds': len(folds), 'selected': selected,
                'versions': {'sklearn': sklearn.__version__, 'xgboost': xgboost.__version__,
                             'pandas': pd.__version__, 'numpy': np.__version__},
                'implementation_sha256': sha(Path(__file__)),
                'feature_manifest_sha256': sha(root / 'data/features' / features['run_id'] / 'manifest.json'),
                'predictors': list(x.columns)}
    report = ['# Stage 7 — historical prediction experiments', '',
              f'{len(folds)} expanding quarterly validation folds; final holdout begins {holdout.date()}.',
              'Models are pooled across the 11 instruments, with instrument identity included.',
              'Selection uses mean validation Brier loss for direction and MAE for returns.',
              'Only the selected candidate and baseline are evaluated on the final holdout.', '',
              '## Final holdout results', '']
    for r in results:
        if r['split'] == 'holdout':
            values = {k: round(v, 6) if isinstance(v, float) else v for k, v in r.items()
                      if k not in ['split', 'fold']}
            report.append('- ' + json.dumps(values))
    report += ['', '## Interpretation', '',
               'This is retrospective research using a revised historical snapshot. Archive timestamps',
               'are not backdated: these results are not point-in-time tradable predictions.',
               'Gaps and warm-up rows are excluded, never filled. Training preprocessing is fitted',
               'inside each fold. All training outcomes end before evaluation starts.',
               'The five-session target requires all six consecutive prices. Final unknown labels',
               'remain null. Return errors are fractions: 0.01 means one percentage point.',
               'The baseline predicts the training class frequency (majority at threshold 0.5)',
               'or zero return. Brier and calibration tables assess raw probability quality;',
               'no post-holdout calibration or tuning is performed.',
               'Saved models are fitted only before the holdout, for reproducibility, not live use.',
               'Correlated stocks and overlapping five-day outcomes mean rows are not independent.',
               'No transaction costs, execution simulation or profitability claims are included.',
               'See docs/STAGE_7.md for rerun and model-loading instructions.']
    (folder / 'MODEL_REPORT.md').write_text('\n'.join(report), encoding='utf-8')
    manifest['outputs'] = {str(p.relative_to(root)): sha(p) for parent in [folder, artifacts]
                           for p in parent.iterdir()}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (root / 'reports/stage7/latest.json').write_text(json.dumps({'run_id': run_id}))
    print(folder, flush=True)


if __name__ == '__main__':
    main()
