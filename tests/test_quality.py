import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketpulse.quality.validate import calendar, run, validate_frame

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/quality.json').read_text())
ITEM = {'symbol': 'TEST', 'kind': 'equity', 'sha256': 'a' * 64,
        'observed_at': '2026-09-10T00:00:00Z'}
MANIFEST = {'provider': 'yahoo_research', 'run_id': 'test',
            'request': {'start_inclusive': '2020-01-01', 'end_exclusive': '2020-01-10'}}


def bars():
    return pd.DataFrame({'Open': [100., 100., 100.], 'High': [110., 110., 110.],
                         'Low': [90., 90., 90.], 'Close': [105., 105., 105.],
                         'Adj Close': [105., 105., 105.], 'Volume': [100, 100, 100]},
                        index=pd.to_datetime(['2020-01-02', '2020-01-03', '2020-01-06']))


def check(frame):
    cal = calendar('2020-01-01', '2020-01-10', CONFIG)
    return validate_frame(frame, ITEM, MANIFEST, CONFIG, cal)


def test_bad_prices_quarantined_without_mutating_source():
    data = bars()
    data.iloc[1, data.columns.get_loc('Close')] = np.nan
    original = data.copy(deep=True)
    clean, quarantine, issues = check(data)
    assert len(clean) == 2 and len(quarantine) == 1
    assert '2020-01-03' not in set(clean.session_date)
    assert any(i['rule'] == 'unusable_session' for i in issues)
    pd.testing.assert_frame_equal(original, data)


def test_duplicates_quarantine_all_copies():
    clean, quarantine, _ = check(pd.concat([bars(), bars().iloc[[0]]]))
    assert len(clean) == 2 and len(quarantine) == 2
    assert set(quarantine.reasons) == {'duplicate_date'}


@pytest.mark.parametrize(('col', 'value'), [('High', 80), ('Open', np.inf),
                                          ('Low', -1), ('Volume', 1.5), ('Volume', -2)])
def test_invalid_values(col, value):
    data = bars().astype(float)
    data.loc[data.index[0], col] = value
    clean, quarantine, _ = check(data)
    assert len(clean) == 2 and len(quarantine) == 1


def test_zero_volume_and_missing_adjustment_are_warnings():
    data = bars()
    data.loc[data.index[0], 'Volume'] = 0
    data.loc[data.index[1], 'Adj Close'] = np.nan
    clean, quarantine, issues = check(data)
    assert len(clean) == 3 and quarantine.empty
    assert {'zero_volume', 'missing_adjusted_close'} <= {i['rule'] for i in issues}


def test_missing_column_is_not_silently_accepted():
    clean, quarantine, _ = check(bars().drop(columns='Volume'))
    assert clean.empty and len(quarantine) == 3


def test_calendar_special_session_and_confirmed_holiday():
    cal = calendar('2024-03-01', '2024-03-05', CONFIG).set_index('session_date')
    assert cal.loc['2024-03-02', 'expected_open']
    cal = calendar('2026-01-14', '2026-01-17', CONFIG).set_index('session_date')
    assert not cal.loc['2026-01-15', 'expected_open']


def test_hash_failure_writes_no_outputs(tmp_path):
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/quality.json').write_text(json.dumps(CONFIG))
    (tmp_path / 'config/universe.json').write_text(json.dumps([ITEM]))
    (tmp_path / 'config/nse_sessions_reference.json').write_text(
        (ROOT / 'config/nse_sessions_reference.json').read_text())
    data = tmp_path / 'raw'
    data.mkdir()
    bars().to_parquet(data / 'test.parquet')
    manifest = {**MANIFEST, 'status': 'success',
                'instruments': [{**ITEM, 'file': 'test.parquet'}]}
    path = data / 'manifest.json'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='checksum'):
        run(tmp_path, path)
    assert not (tmp_path / 'data').exists()
