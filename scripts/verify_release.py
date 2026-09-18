"""Verify the published dashboard snapshot and its PostgreSQL provenance."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from marketpulse.cli import connection
from marketpulse.quality.validate import sha

root = Path.cwd()
pointer = json.loads((root / 'data/dashboard/current.json').read_text())
folder = Path(pointer['path'])
assert sha(folder / 'manifest.json') == pointer['manifest_sha256']
manifest = json.loads((folder / 'manifest.json').read_text())
tables = {}
for name, checksum in manifest['outputs'].items():
    assert sha(folder / name) == checksum
    tables[name] = pd.read_csv(folder / name)
assert len(tables['Market.csv']) == 11
assert tables['Symbols.csv'].symbol.nunique() == 11
forecasts = tables['Forecasts.csv']
assert len(forecasts) == 33
assert forecasts.loc[forecasts.status.str.startswith('Skipped'), 'value'].isna().all()
assert np.isfinite(forecasts.value.dropna()).all()
direction = forecasts.loc[forecasts.target == 'direction_1d', 'value'].dropna()
assert direction.between(0, 1).all()
assert not tables['History.csv'].duplicated(['symbol', 'session_date']).any()
load_dotenv(root / '.env')
with connection() as conn:
    stored = conn.execute('SELECT manifest FROM marketpulse.dashboard_snapshots WHERE snapshot_id=%s',
                          (manifest['snapshot_id'],)).fetchone()[0]
    assert stored == manifest
    forecasts_count = conn.execute('SELECT count(*) FROM marketpulse.research_forecasts WHERE run_id=%s',
                                    (manifest['snapshot_id'],)).fetchone()[0]
    assert forecasts_count == 33
result = {'status': 'passed', 'snapshot_id': manifest['snapshot_id'],
          'dataset_id': manifest['dataset_id'], 'tables_verified': len(tables),
          'history_rows': len(tables['History.csv']), 'forecasts_verified': forecasts_count,
          'current_indicator_instruments': 11 - manifest['stale_instruments'],
          'expected_session': manifest['expected_session']}
(root / 'reports/release').mkdir(exist_ok=True)
(root / 'reports/release/verification.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
