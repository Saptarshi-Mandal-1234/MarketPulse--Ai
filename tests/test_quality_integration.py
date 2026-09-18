import json
from pathlib import Path

import pandas as pd

from marketpulse.quality.validate import run, sha

ROOT = Path(__file__).resolve().parents[1]


def test_full_validation_lineage_and_gap_policy(tmp_path):
    config = tmp_path / 'config'
    config.mkdir()
    for name in ['quality.json', 'nse_sessions_reference.json']:
        (config / name).write_text((ROOT / 'config' / name).read_text())
    item = {'symbol': 'TEST', 'kind': 'equity', 'observed_at': '2020-01-10T18:00:00Z',
            'status': 'success', 'file': 'TEST.parquet', 'rows': 2}
    (config / 'universe.json').write_text(json.dumps([item]))
    raw_dir = tmp_path / 'data/raw/test'
    raw_dir.mkdir(parents=True)
    data = pd.DataFrame({'Open': [10., 10.], 'High': [11., 11.], 'Low': [9., 9.],
                         'Close': [10., 10.], 'Adj Close': [10., 10.], 'Volume': [1, 1]},
                        index=pd.to_datetime(['2020-01-02', '2020-01-06']))
    path = raw_dir / 'TEST.parquet'
    data.to_parquet(path)
    item['sha256'] = sha(path)
    source = raw_dir / 'manifest.json'
    source.write_text(json.dumps({'status': 'success', 'run_id': 'test', 'provider': 'test',
                                 'instruments': [item], 'request': {
                                     'start_inclusive': '2020-01-02',
                                     'end_exclusive': '2020-01-07'}}))
    result = run(tmp_path, source)
    assert result['stage3_complete']
    assert not result['feature_stage_ready']  # No eligible five-session window.
    assert result['instruments'][0]['excluded_sessions'] == 1
    aligned = pd.read_parquet(tmp_path / 'data/processed' / result['quality_id'] /
                              'aligned/TEST.parquet')
    assert aligned.loc[1, 'gap']
    assert not aligned.target_1d_eligible.any()
    assert sha(path) == item['sha256']
    for output in result['outputs']:
        assert sha(tmp_path / output['path']) == output['sha256']
    pointer = json.loads((tmp_path / 'data/processed/latest.json').read_text())
    assert pointer['quality_id'] == result['quality_id']
