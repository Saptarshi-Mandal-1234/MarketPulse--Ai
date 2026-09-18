import numpy as np
import pandas as pd
import pytest

from marketpulse.analytics.report import analyze
from marketpulse.db.load import records

CONFIG = {'benchmark': 'NIFTY50', 'annual_sessions': 252, 'risk_free_annual': 0.,
          'minimum_return_observations': 3, 'rolling_sessions': 3}


def test_known_beta_and_pair_counts():
    returns = np.array([0.01, -.02, .03, -.01, .02, -.03])
    prices = pd.DataFrame({'NIFTY50': 100 * np.cumprod(np.r_[1, 1 + returns]),
                          'TEST': 100 * np.cumprod(np.r_[1, 1 + 2 * returns])},
                         index=pd.bdate_range('2020-01-01', periods=7))
    result = analyze(prices, CONFIG)
    stats = result['metrics'].set_index('symbol')
    assert stats.loc['TEST', 'beta_vs_nifty'] == pytest.approx(2)
    assert result['correlation'].loc['TEST', 'NIFTY50'] == pytest.approx(1)
    assert result['pair_counts'].loc['TEST', 'NIFTY50'] == 6


def test_gap_does_not_create_return_or_short_rolling_window():
    prices = pd.DataFrame({'NIFTY50': [100., 101, 102, 103, 104, 105],
                          'TEST': [100., 101, np.nan, 200, 201, 202]},
                         index=pd.bdate_range('2020-01-01', periods=6))
    result = analyze(prices, CONFIG)
    assert result['returns']['TEST'].iloc[2:4].isna().all()
    assert result['rolling_volatility']['TEST'].isna().all()
    assert result['metrics'].set_index('symbol').loc['TEST', 'endpoint_return'] == 1.02


def test_observed_drawdown_and_constant_price_ratios():
    prices = pd.DataFrame({'NIFTY50': [100., 100, 100, 100], 'TEST': [100., 120, 90, 100]},
                         index=pd.bdate_range('2020-01-01', periods=4))
    stats = analyze(prices, CONFIG)['metrics'].set_index('symbol')
    assert stats.loc['TEST', 'observed_max_drawdown'] == -.25
    assert pd.isna(stats.loc['NIFTY50', 'sharpe'])
    assert pd.isna(stats.loc['TEST', 'beta_vs_nifty'])


def test_serialization_nulls_and_timestamp():
    frame = pd.DataFrame({'missing': [np.nan], 'volume': pd.Series([pd.NA], dtype='Int64'),
                          'time': [pd.Timestamp('2020-01-01', tz='UTC')]})
    assert records(frame) == [{'missing': None, 'volume': None, 'time': '2020-01-01T00:00:00.000Z'}]
