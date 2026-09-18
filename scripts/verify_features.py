"""Verify feature artifacts and test prefix invariance on actual source data."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from marketpulse.features.technical import compute_features
from marketpulse.quality.validate import sha


def main():
    root = Path.cwd()
    pointer = json.loads((root / 'data/features/latest.json').read_text())
    path = root / 'data/features' / pointer['run_id'] / 'manifest.json'
    if sha(path) != pointer['manifest_sha256']:
        raise ValueError('Feature manifest changed')
    result = json.loads(path.read_text())
    quality_path = root / 'data/processed' / result['quality_id'] / 'manifest.json'
    if sha(quality_path) != result['identity']['source_manifest_sha256']:
        raise ValueError('Source manifest changed')
    quality = json.loads(quality_path.read_text())
    kinds = {r['symbol']: r['kind'] for r in json.loads((root / 'config/universe.json').read_text())}
    names = result['predictor_columns']
    rows = ready = 0
    for item in result['outputs']:
        if sha(root / item['path']) != item['sha256']:
            raise ValueError('Feature output changed')
        frame = pd.read_parquet(root / item['path'])
        values = frame[names]
        if np.isinf(values.to_numpy()).any() or not values.loc[~frame.input_valid].isna().all().all():
            raise ValueError('Invalid numeric feature or gap filled')
        if not frame.rsi_14.dropna().between(0, 100).all() or (frame.atr_14.dropna() < 0).any():
            raise ValueError('Indicator range violation')
        if frame.session_date.duplicated().any() or len(frame) != item['rows']:
            raise ValueError('Output dates/count mismatch')
        source = next(o for o in quality['outputs']
                      if o.get('kind') == 'aligned' and Path(o['path']).stem == item['symbol'])
        source_path = root / source['path']
        if sha(source_path) != source['sha256']:
            raise ValueError('Aligned data changed')
        raw = pd.read_parquet(source_path)
        prefix = raw.iloc[:len(raw) // 2]
        rebuilt, _ = compute_features(prefix, result['config'], kinds[item['symbol']])
        pd.testing.assert_frame_equal(frame.loc[prefix.index, names], rebuilt[names])
        rows += len(frame)
        ready += int(frame.core_ready.sum())
    report = {'feature_run_id': result['run_id'], 'rows': rows, 'core_ready': ready,
              'instruments': len(result['outputs']), 'features': len(names),
              'checks': 'hashes, gap nulls, numeric bounds, row counts, actual-data prefix invariance',
              'status': 'passed'}
    (root / 'reports' / result['run_id'] / 'verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
