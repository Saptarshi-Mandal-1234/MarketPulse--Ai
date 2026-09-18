import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketpulse.pipeline import expected_session, freshness
from marketpulse.signals.risk import assess, technical

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config/risk.json').read_text())
REFERENCE = json.loads((ROOT / 'config/nse_sessions_operational.json').read_text())


def test_expected_session_holiday_and_cutoff():
    assert expected_session(datetime.fromisoformat('2026-09-15T10:00:00+05:30'), REFERENCE) == '2026-09-11'
    assert expected_session(datetime.fromisoformat('2026-09-15T15:59:00+05:30'), REFERENCE) == '2026-09-11'
    assert expected_session(datetime.fromisoformat('2026-09-15T16:00:00+05:30'), REFERENCE) == '2026-09-15'
    assert expected_session(datetime.fromisoformat('2026-09-14T20:00:00+05:30'), REFERENCE) == '2026-09-11'


def test_future_calendar_fails_closed():
    with pytest.raises(ValueError):
        expected_session(datetime.fromisoformat('2027-01-02T20:00:00+05:30'), REFERENCE)


def test_special_session_cutoff():
    assert expected_session(datetime.fromisoformat('2026-11-08T18:15:00+05:30'), REFERENCE) == '2026-11-06'
    assert expected_session(datetime.fromisoformat('2026-11-08T21:30:00+05:30'), REFERENCE) == '2026-11-08'


def test_freshness_rejects_incomplete_universe():
    q = {'instruments': [{'latest_usable': '2026-09-15'}, {'latest_usable': None}]}
    assert not freshness(q, '2026-09-15')


def test_signal_rules_and_missing_volume():
    row = {'ema_12': 110, 'ema_26': 100, 'macd': 2, 'macd_signal': 1,
           'return_20d': .1, 'volatility_20': .4, 'relative_volume_20': np.nan, 'rsi_14': 55}
    result = technical(row, CONFIG)
    assert result['signal'] == 'Bullish'
    assert result['risk_band'] == 'High Risk'
    assert result['abnormal_volume'] is None
    row.update(ema_12=90, macd=0, return_20d=-.1, relative_volume_20=3)
    assert technical(row, CONFIG)['signal'] == 'Bearish'
    assert technical(row, CONFIG)['abnormal_volume']


def test_anomaly_fit_excludes_evaluated_row_and_gap_zscore():
    rng = np.random.default_rng(42)
    frame = pd.DataFrame({'symbol': 'X', 'session_date': pd.bdate_range('2020-01-01', periods=160).strftime('%Y-%m-%d'),
                          'core_ready': True, 'input_valid': True, 'return_1d': rng.normal(0, .01, 160),
                          'volatility_20': .2, 'rsi_14': 50., 'relative_volume_20': 1.,
                          'ema_12': 110., 'ema_26': 100., 'macd': 1., 'macd_signal': .5,
                          'return_20d': .1})
    result = assess(frame, CONFIG)
    assert result['training_end'] < result['session_date']
    assert result['training_rows'] == 159
    frame.loc[150, 'input_valid'] = False
    frame.loc[150, 'core_ready'] = False
    assert assess(frame, CONFIG)['return_z'] is None


def test_provider_failure_keeps_published_dashboard(tmp_path, monkeypatch):
    from marketpulse import pipeline
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/nse_sessions_operational.json').write_text(json.dumps(REFERENCE))
    pointer = tmp_path / 'data/dashboard/current.json'
    pointer.parent.mkdir(parents=True)
    pointer.write_text('{"snapshot_id":"last-good"}')
    before = pointer.read_bytes()
    class FakeConnection:
        def execute(self, *args):
            return self
        def fetchone(self):
            return (True,)
    @contextmanager
    def connect():
        yield FakeConnection()
    def failure(*args, **kwargs):
        raise ConnectionError('simulated provider outage')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline, 'connection', connect)
    monkeypatch.setattr(pipeline, 'migrate', lambda *args: None)
    monkeypatch.setattr(pipeline, 'download', failure)
    monkeypatch.setattr(pipeline, 'expected_session', lambda *args: '2026-09-15')
    monkeypatch.setattr('sys.argv', ['pipeline', '--daily', '--force'])
    with pytest.raises(SystemExit):
        pipeline.main()
    assert pointer.read_bytes() == before
    status = json.loads((tmp_path / 'reports/pipeline/latest.json').read_text())
    assert status['status'] == 'failed'
    assert status['current_stage'] == 'download'
    assert status['stages'] == []
