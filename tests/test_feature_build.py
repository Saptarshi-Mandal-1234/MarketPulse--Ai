import json
from pathlib import Path

import pandas as pd
import pytest

from marketpulse.features.build import build
from marketpulse.quality.validate import sha

ROOT = Path(__file__).resolve().parents[1]


def setup_input(root):
    config = root / 'config'
    config.mkdir()
    (config / 'features.json').write_text((ROOT / 'config/features.json').read_text())
    (config / 'universe.json').write_text(json.dumps([{'symbol': 'TEST', 'kind': 'equity'}]))
    folder = root / 'data/processed/test/aligned'
    folder.mkdir(parents=True)
    path = folder / 'TEST.parquet'
    frame = pd.DataFrame({'symbol': 'TEST', 'session_date': pd.bdate_range('2020-01-01', periods=100)
                          .strftime('%Y-%m-%d'), 'open': 100., 'close': 100.,
                          'adj_close': 100., 'high': 101., 'low': 99., 'volume': 100.,
                          'feature_eligible': True, 'volume_feature_eligible': True,
                          'observed_at': pd.Timestamp('2026-09-10', tz='UTC')})
    frame.to_parquet(path, index=False)
    manifest = folder.parent / 'manifest.json'
    manifest.write_text(json.dumps({'stage3_complete': True, 'feature_stage_ready': True,
                                    'outputs': [{'kind': 'aligned', 'rows': 100,
                                                 'path': str(path.relative_to(root)),
                                                 'sha256': sha(path)}]}))
    (root / 'data/processed/latest.json').write_text(json.dumps({
        'quality_id': 'test', 'manifest_sha256': sha(manifest)}))
    return path


def test_build_outputs_and_preserves_input(tmp_path):
    path = setup_input(tmp_path)
    digest = sha(path)
    result = build(tmp_path)
    assert len(result['predictor_columns']) == 39
    assert result['instruments'][0]['core_ready'] == 67
    assert sha(path) == digest
    for item in result['outputs']:
        assert sha(tmp_path / item['path']) == item['sha256']
    assert (tmp_path / 'data/features/latest.json').exists()


def test_tampered_input_rejected_before_output(tmp_path):
    path = setup_input(tmp_path)
    path.write_bytes(b'altered')
    with pytest.raises(ValueError, match='checksum'):
        build(tmp_path)
    assert not (tmp_path / 'data/features').exists()
