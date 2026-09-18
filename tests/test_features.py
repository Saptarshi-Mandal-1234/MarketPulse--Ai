import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketpulse.features.technical import compute_features, wilder

CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'config/features.json').read_text())


def fixture(n=300, flat=False):
    price = np.full(n, 100.) if flat else np.arange(n, dtype=float) + 100
    return pd.DataFrame({'symbol': 'TEST', 'session_date': pd.bdate_range('2020-01-01', periods=n)
                         .strftime('%Y-%m-%d'), 'open': price, 'close': price,
                         'high': price + 2, 'low': price - 2, 'adj_close': price,
                         'volume': 100., 'feature_eligible': True,
                         'volume_feature_eligible': True,
                         'observed_at': pd.Timestamp('2026-09-10', tz='UTC'),
                         'target_1d_eligible': True})


def test_known_values_and_warmup():
    out, _ = compute_features(fixture(), CONFIG, 'equity')
    assert out.loc[4, 'sma_5'] == 102
    assert out.loc[3, 'sma_5'] != out.loc[3, 'sma_5']
    assert out.loc[1, 'return_1d'] == pytest.approx(.01)
    assert out.loc[14, 'rsi_14'] == 100
    assert out.loc[13, 'atr_14'] == 4
    assert out.loc[251, 'high_252'] == 353
    assert out.loc[250, 'high_252'] != out.loc[250, 'high_252']
    assert out.loc[20, 'relative_volume_20'] == 1


def test_wilder_arithmetic_seed_and_recurrence():
    result = wilder(pd.Series([np.nan, 1., 2., 3., 7.]), 3)
    assert result.iloc[3] == 2
    assert result.iloc[4] == pytest.approx(11 / 3)


def test_future_changes_cannot_change_past_features():
    original = fixture()
    before, names = compute_features(original, CONFIG, 'equity')
    changed = original.copy()
    changed.loc[200:, ['open', 'close', 'high', 'low', 'adj_close', 'volume']] *= 7
    changed.loc[200:, 'feature_eligible'] = False
    changed['target_1d_eligible'] = False
    after, _ = compute_features(changed, CONFIG, 'equity')
    pd.testing.assert_frame_equal(before.loc[:199], after.loc[:199])
    assert 'target_1d_eligible' not in after
    prefix, _ = compute_features(original.iloc[:200], CONFIG, 'equity')
    pd.testing.assert_frame_equal(before.loc[:199, names], prefix[names])


def test_gap_resets_recursive_and_rolling_indicators():
    data = fixture()
    data.loc[150, 'feature_eligible'] = False
    out, names = compute_features(data, CONFIG, 'equity')
    assert out.loc[150, names].isna().all()
    assert pd.isna(out.loc[151, 'return_1d'])
    assert pd.isna(out.loc[154, 'sma_5'])
    assert not pd.isna(out.loc[155, 'sma_5'])
    tail, _ = compute_features(data.iloc[151:], CONFIG, 'equity')
    pd.testing.assert_frame_equal(out.loc[151:, names], tail[names])


def test_constant_series_has_no_infinities():
    out, names = compute_features(fixture(flat=True), CONFIG, 'equity')
    assert out.loc[14, 'rsi_14'] == 50
    assert out.loc[30, 'bollinger_width'] == 0
    assert pd.isna(out.loc[30, 'bollinger_percent_b'])
    assert not np.isinf(out[names].to_numpy()).any()


def test_adjusted_high_low_and_index_volume():
    data = fixture(flat=True)
    data['adj_close'] = 50.
    out, _ = compute_features(data, CONFIG, 'index')
    assert out.loc[13, 'atr_14'] == 2
    assert out.loc[251, 'high_252'] == 51
    assert out[['volume_change_1d', 'volume_sma_20', 'relative_volume_20']].isna().all().all()


def test_missing_volume_breaks_full_volume_window():
    data = fixture()
    data.loc[100, 'volume_feature_eligible'] = False
    out, _ = compute_features(data, CONFIG, 'equity')
    assert out.loc[100:119, 'volume_sma_20'].isna().all()
    assert not pd.isna(out.loc[120, 'volume_sma_20'])
    assert pd.isna(out.loc[101, 'volume_change_1d'])


def test_observed_availability_is_never_backdated():
    out, _ = compute_features(fixture(), CONFIG, 'equity')
    assert (out.available_at == pd.Timestamp('2026-09-10', tz='UTC')).all()


def test_rejects_duplicate_dates():
    data = fixture()
    data.loc[1, 'session_date'] = data.loc[0, 'session_date']
    with pytest.raises(ValueError, match='unique'):
        compute_features(data, CONFIG, 'equity')
