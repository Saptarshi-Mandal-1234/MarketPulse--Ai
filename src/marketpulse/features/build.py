"""Build versioned feature artifacts from a checksum-verified Stage 3 handoff."""
import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from marketpulse.features.technical import compute_features
from marketpulse.quality.validate import sha


def build(root):
    pointer = json.loads((root / 'data/processed/latest.json').read_text())
    source_path = root / 'data/processed' / pointer['quality_id'] / 'manifest.json'
    if sha(source_path) != pointer['manifest_sha256']:
        raise ValueError('Stage 3 manifest checksum mismatch')
    source = json.loads(source_path.read_text())
    if not source.get('stage3_complete') or not source.get('feature_stage_ready'):
        raise ValueError('Stage 3 handoff is not ready')
    config_path = root / 'config/features.json'
    config = json.loads(config_path.read_text())
    universe = json.loads((root / 'config/universe.json').read_text())
    inputs = [o for o in source['outputs'] if o.get('kind') == 'aligned']
    if {Path(o['path']).stem for o in inputs} != {i['symbol'] for i in universe}:
        raise ValueError('Aligned universe mismatch')
    for item in inputs:
        path = (root / item['path']).resolve()
        if not path.is_relative_to(source_path.parent.resolve()) or sha(path) != item['sha256']:
            raise ValueError('Aligned source path/checksum mismatch')
    run_id = str(uuid4())
    out = root / 'data/features' / run_id
    reports = root / 'reports' / run_id
    out.mkdir(parents=True, exist_ok=False)
    reports.mkdir(parents=True, exist_ok=False)
    identity = {'source_manifest_sha256': sha(source_path), 'config_sha256': sha(config_path),
                'universe_sha256': sha(root / 'config/universe.json'),
                'implementation_sha256': sha(Path(__file__).with_name('technical.py')),
                'builder_sha256': sha(Path(__file__)), 'pandas_version': pd.__version__,
                'numpy_version': np.__version__}
    dataset_sha = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    summaries, files, coverage = [], [], []
    for item in universe:
        entry = next(o for o in inputs if Path(o['path']).stem == item['symbol'])
        frame = pd.read_parquet(root / entry['path'])
        if len(frame) != entry['rows'] or set(frame.symbol) != {item['symbol']}:
            raise ValueError('Aligned row count/symbol mismatch')
        features, names = compute_features(frame, config, item['kind'])
        features['feature_version'] = config['version']
        features['dataset_sha256'] = dataset_sha
        path = out / f"{item['symbol']}.parquet"
        features.to_parquet(path, index=False)
        files.append({'symbol': item['symbol'], 'path': str(path.relative_to(root)),
                      'sha256': sha(path), 'rows': len(features)})
        summaries.append({'symbol': item['symbol'], 'rows': len(features),
                          'input_valid': int(features.input_valid.sum()),
                          'core_ready': int(features.core_ready.sum()),
                          'latest_core_session': features.loc[features.core_ready, 'session_date'].max()})
        for name in names:
            coverage.append({'symbol': item['symbol'], 'feature': name,
                             'non_null': int(features[name].notna().sum()),
                             'null': int(features[name].isna().sum())})
        print(f"{item['symbol']}: {features.core_ready.sum()} core-ready sessions", flush=True)
    pd.DataFrame(coverage).to_csv(reports / 'coverage.csv', index=False)
    result = {'run_id': run_id, 'created_at': datetime.now(UTC).isoformat(),
              'status': 'complete', 'feature_version': config['version'],
              'dataset_sha256': dataset_sha, 'identity': identity,
              'quality_id': pointer['quality_id'], 'predictor_columns': names,
              'metadata_columns': [c for c in features.columns if c not in names],
              'config': config, 'instruments': summaries, 'outputs': files,
              'point_in_time_certified': False, 'model_ready': False}
    (out / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    lines = ['# Stage 4 feature report', '', f'{len(names)} numeric features; {len(universe)} instruments.',
             'Rolling history resets after every excluded price session. Warm-up values remain null.',
             '', '| Instrument | Session rows | Valid price rows | Core-ready rows | Latest core |',
             '|---|---:|---:|---:|---|']
    for s in summaries:
        lines.append(f"| {s['symbol']} | {s['rows']} | {s['input_valid']} | {s['core_ready']} | "
                     f"{s['latest_core_session']} |")
    lines += ['', 'Core-ready means the configured seven core features exist, not every feature.',
              'Long-window and volume coverage is detailed in coverage.csv.',
              'Predictors exclude target labels and future-dependent target eligibility flags.',
              'Historical adjusted snapshots are not point-in-time vintages. available_at reflects',
              'actual archive observation times, not a fictitious historical daily cutoff.',
              'No models were trained and no database writes were made.']
    (reports / 'features.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    temporary = root / 'data/features/latest.tmp'
    temporary.write_text(json.dumps({'run_id': run_id, 'manifest_sha256': sha(out / 'manifest.json')}))
    temporary.replace(root / 'data/features/latest.json')
    print(f'Report: {reports / "features.md"}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    build(args.root.resolve())


if __name__ == '__main__':
    main()
