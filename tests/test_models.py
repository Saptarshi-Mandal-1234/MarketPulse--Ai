import numpy as np
import pandas as pd
import pytest

from marketpulse.models.train import estimator, labels, masks, splits


def sample():
    return pd.DataFrame({'symbol': ['X'] * 12,
                         'session_date': pd.bdate_range('2020-01-01', periods=12),
                         'adj_close': [100., 100., 110., 120., 130., 140., 150., 160., 170., 180., 190., 200.],
                         'feature_eligible': True})


def test_labels_use_exact_sessions_and_preserve_unknowns():
    frame = sample()
    result = labels(frame)
    assert result.direction_1d.iloc[0] == 0
    assert result.future_return_5d.iloc[0] == pytest.approx(.4)
    assert result.future_return_5d.tail(5).isna().all()
    assert pd.isna(result.direction_1d.iloc[-1])
    frame.loc[3, 'feature_eligible'] = False
    result = labels(frame)
    assert result.future_return_5d.iloc[:4].isna().all()
    assert pd.isna(result.future_return_1d.iloc[2])
    assert result.future_return_1d.iloc[4] == pytest.approx(140 / 130 - 1)


def test_purge_and_evaluation_outcomes_do_not_cross_boundaries():
    frame = labels(sample())
    frame['core_ready'] = True
    start, end = frame.session_date.iloc[7], frame.session_date.iloc[10]
    train, test = masks(frame, 'future_return_1d', start, end)
    assert train.sum() == 2
    assert (frame.loc[train, 'target_date_5d'] < start).all()
    assert (frame.loc[test, 'target_date_1d'] < end).all()
    assert not (train & test).any()


def test_preprocessing_is_training_only():
    config = {'seed': 42}
    pipeline = estimator('linear', False, config)
    pipeline.fit(pd.DataFrame({'x': [1., 3., np.nan]}), [0., 1., 0.])
    assert pipeline.steps[0][1].statistics_[0] == 2
    pipeline.predict(pd.DataFrame({'x': [1000000., np.nan]}))
    assert pipeline.steps[0][1].statistics_[0] == 2


def test_splits_keep_last_year_separate():
    dates = pd.bdate_range('2015-01-01', '2026-09-09')
    folds, holdout = splits(dates, {'initial_train_years': 3,
                                  'holdout_months': 12, 'validation_months': 3})
    assert holdout == pd.Timestamp('2025-09-09')
    assert folds[0][0] == pd.Timestamp('2018-01-01')
    assert folds[-1][1] == holdout
    assert all(a < b <= holdout for a, b in folds)


def test_labels_reject_unsorted_sessions():
    with pytest.raises(ValueError):
        labels(sample().iloc[::-1])
