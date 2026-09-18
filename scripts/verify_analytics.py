"""Verify exported report hashes, gap handling and independent risk calculations."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from marketpulse.quality.validate import sha

root = Path.cwd()
folder = root / 'reports/stage6' / json.loads(
    (root / 'reports/stage6/latest.json').read_text())['run_id']
manifest = json.loads((folder / 'manifest.json').read_text())
for name, checksum in manifest['outputs'].items():
    assert sha(folder / name) == checksum, name
prices = pd.read_csv(folder / 'prices.csv', index_col=0)
returns = pd.read_csv(folder / 'returns.csv', index_col=0)
metrics = pd.read_csv(folder / 'metrics.csv').set_index('symbol')
correlation = pd.read_csv(folder / 'correlation.csv', index_col=0)
np.testing.assert_allclose(correlation, correlation.T, equal_nan=True)
annual = manifest['config']['annual_sessions']
rf = (1 + manifest['config']['risk_free_annual']) ** (1 / annual) - 1
for symbol in prices:
    p = prices[symbol].to_numpy()
    expected = np.r_[np.nan, p[1:] / p[:-1] - 1]
    np.testing.assert_allclose(returns[symbol], expected, equal_nan=True, atol=1e-14)
    valid = expected[np.isfinite(expected)]
    row = metrics.loc[symbol]
    np.testing.assert_allclose(row.annualized_volatility, np.std(valid, ddof=1) * np.sqrt(annual))
    np.testing.assert_allclose(row.sharpe,
                               np.mean(valid - rf) / np.std(valid - rf, ddof=1) * np.sqrt(annual))
    np.testing.assert_allclose(row.sortino, np.mean(valid - rf) * np.sqrt(annual) /
                               np.sqrt(np.mean(np.minimum(valid - rf, 0) ** 2)))
    assert row.daily_return_observations == len(valid)
np.testing.assert_allclose(metrics.loc['NIFTY50', 'beta_vs_nifty'], 1)
result = {'status': 'passed', 'instruments': len(prices.columns),
          'session_dates': len(prices), 'output_hashes_verified': len(manifest['outputs']),
          'checks': ['adjacent-session returns', 'volatility', 'Sharpe', 'Sortino',
                     'observation counts', 'correlation symmetry', 'benchmark beta']}
(folder / 'verification.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
