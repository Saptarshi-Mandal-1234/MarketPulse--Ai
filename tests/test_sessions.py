import pandas as pd
import pytest

from marketpulse.quality.sessions import align_sessions, make_calendar


@pytest.mark.parametrize('day', ['2015-02-28', '2016-10-30', '2019-10-27',
                                '2020-02-01', '2020-11-14', '2023-11-12',
                                '2024-01-20', '2024-03-02', '2024-05-18',
                                '2025-02-01', '2026-02-01'])
def test_special_openings(day):
    end = str((pd.Timestamp(day) + pd.Timedelta(days=1)).date())
    assert make_calendar(day, end).expected_open.iloc[0]


@pytest.mark.parametrize('day', ['2019-04-29', '2019-10-21', '2023-06-29',
                                '2024-01-22', '2024-05-20', '2024-11-20', '2026-01-15'])
def test_extra_closures(day):
    end = str((pd.Timestamp(day) + pd.Timedelta(days=1)).date())
    assert not make_calendar(day, end).expected_open.iloc[0]


def test_corrected_annual_dates():
    assert make_calendar('2015-10-23', '2015-10-24').expected_open.iloc[0]
    assert make_calendar('2023-06-28', '2023-06-29').expected_open.iloc[0]


def test_unreviewed_future_fails_closed():
    with pytest.raises(ValueError, match='coverage'):
        make_calendar('2026-09-01', '2027-01-01')


def test_masks_do_not_skip_missing_session_or_unknown_future():
    cal = make_calendar('2020-01-01', '2020-01-15')
    dates = cal.loc[cal.expected_open, 'session_date'].tolist()
    clean = pd.DataFrame({'session_date': dates, 'price_valid': True,
                          'adj_close': 100., 'volume': 10, 'close': 100.})
    clean = clean.drop(index=2)
    aligned = align_sessions(clean, cal, 'TEST')
    assert aligned.loc[2, 'gap']
    assert pd.isna(aligned.loc[2, 'close'])
    assert not aligned.loc[1, 'target_1d_eligible']
    assert not aligned.loc[0, 'target_5d_eligible']
    assert not aligned.iloc[-1].target_1d_eligible
    assert aligned.loc[1, 'segment_id'] != aligned.loc[3, 'segment_id']
