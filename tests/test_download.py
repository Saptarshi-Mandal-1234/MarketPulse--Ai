import hashlib
import json

import pandas as pd
import pytest

from marketpulse.ingestion.download import download, inspect_frame


def frame():
    return pd.DataFrame({'Open': [100., 101.], 'High': [102., 103.],
                         'Low': [99., 100.], 'Close': [101., 102.],
                         'Adj Close': [50.5, 51.], 'Volume': [10, 20]},
                        index=pd.to_datetime(['2020-01-02', '2020-01-03']))


def setup_root(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/universe.json').write_text(json.dumps([
        {'symbol': 'TEST', 'provider_symbol': 'TEST.NS', 'kind': 'equity'}]))
    return tmp_path


def test_snapshot_preserves_values_and_reruns(tmp_path):
    root = setup_root(tmp_path)
    original = frame()
    for _ in range(2):
        result = download(root, '2020-01-01', '2020-01-04',
                          fetcher=lambda *a: original, sleeper=lambda _: None)
        row = result['instruments'][0]
        path = root / 'data/raw/yahoo_research' / result['run_id'] / row['file']
        pd.testing.assert_frame_equal(pd.read_parquet(path), original)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
        assert result['status'] == 'success'
    assert len(list((root / 'data/raw/yahoo_research').iterdir())) == 2


def test_retries_and_failure_receipts(tmp_path):
    root = setup_root(tmp_path)
    result = download(root, '2020-01-01', '2020-01-04',
                      fetcher=lambda *a: pd.DataFrame(), sleeper=lambda _: None)
    assert result['status'] == 'partial_failure'
    assert len(result['instruments'][0]['attempts']) == 3


def test_transient_failure_recovers(tmp_path):
    root = setup_root(tmp_path)
    responses = iter([None, frame()])
    result = download(root, '2020-01-01', '2020-01-04',
                      fetcher=lambda *a: next(responses), sleeper=lambda _: None)
    assert result['status'] == 'success'
    assert len(result['instruments'][0]['attempts']) == 2


def test_date_bounds_and_schema():
    with pytest.raises(ValueError):
        inspect_frame(frame(), '2020-01-01', '2020-01-03')
    with pytest.raises(ValueError):
        inspect_frame(frame().drop(columns='Adj Close'), '2020-01-01', '2020-01-04')


def test_unknown_symbol_rejected_before_archiving(tmp_path):
    root = setup_root(tmp_path)
    with pytest.raises(ValueError):
        download(root, '2020-01-01', '2020-01-04', symbols=['MISSING'])
    assert not (root / 'data').exists()
