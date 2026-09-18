"""Verify output checksums, row conservation, and accepted-price invariants."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from marketpulse.quality.validate import PRICES, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    result = json.loads(args.manifest.read_text())
    root = Path.cwd()
    if sha(root / result['source_manifest']) != result['source_manifest_sha256']:
        raise ValueError('Source manifest changed')
    total = 0
    for output in result['outputs']:
        path = root / output['path']
        if sha(path) != output['sha256']:
            raise ValueError('Output checksum changed')
        frame = pd.read_parquet(path)
        if len(frame) != output['rows']:
            raise ValueError('Output row count changed')
        if output.get('kind') == 'aligned':
            if frame.session_date.duplicated().any() or not frame.session_date.is_monotonic_increasing:
                raise ValueError('Bad aligned session order')
            for horizon in [1, 5]:
                expected = frame.feature_eligible.copy()
                for offset in range(1, horizon + 1):
                    expected &= frame.feature_eligible.shift(-offset, fill_value=False)
                if not expected.equals(frame[f'target_{horizon}d_eligible']):
                    raise ValueError('Horizon mask crosses a gap')
            if frame.loc[frame.gap, PRICES].notna().any().any():
                raise ValueError('A missing session was filled')
        elif 'processed' in path.parts:
            prices = frame[PRICES].to_numpy()
            if not np.isfinite(prices).all() or not (prices > 0).all():
                raise ValueError('Invalid retained price')
            if frame.session_date.duplicated().any():
                raise ValueError('Duplicate retained date')
            if not frame.session_date.is_monotonic_increasing:
                raise ValueError('Unsorted retained dates')
            total += len(frame)
    for row in result['instruments']:
        if row['raw'] != row['clean'] + row['quarantined']:
            raise ValueError('Rows lost')
    print(f'Verified {total} retained rows; all input rows accounted for; checksums intact.')


if __name__ == '__main__':
    main()
