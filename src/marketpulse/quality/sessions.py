"""Versioned NSE cash-market daily-session calendar and gap-safe input masks."""
import json
from pathlib import Path

import pandas as pd

REFERENCE = Path(__file__).resolve().parents[3] / 'config/nse_sessions_reference.json'


def make_calendar(start, end, reference=None):
    ref = reference or json.loads(REFERENCE.read_text())
    if start < ref['coverage_start'] or end > ref['coverage_end_exclusive'] or start >= end:
        raise ValueError('Requested period is outside reviewed calendar coverage')
    rows = []
    for day in pd.date_range(start, end, inclusive='left'):
        key = str(day.date())
        annual = ref['years'][str(day.year)]
        opened = day.dayofweek < 5 and key not in annual['closed_dates']
        source = annual.get('accessed_copy', annual['source'])
        kind = 'regular' if opened else 'closed'
        if key == annual['muhurat_date']:
            opened, kind = True, 'muhurat'
        if key in ref['extra_open']:
            opened, source = True, ref['extra_open'][key]
            if kind != 'muhurat':
                kind = 'special' if day.dayofweek > 4 else 'regular'
        if key in ref['extra_closed']:
            opened, source, kind = False, ref['extra_closed'][key], 'closed'
        rows.append({'session_date': key, 'expected_open': bool(opened),
                     'session_kind': kind, 'source': source,
                     'calendar_version': ref['version']})
    return pd.DataFrame(rows)


def align_sessions(clean, cal, symbol):
    """Keep absent sessions as null rows; never shift over them when defining horizons."""
    dates = cal.loc[cal.expected_open, 'session_date']
    aligned = clean.set_index('session_date').reindex(dates).reset_index()
    aligned['symbol'] = symbol
    aligned['price_valid'] = aligned.price_valid.fillna(False).astype(bool)
    aligned['gap'] = ~aligned.price_valid
    aligned['feature_eligible'] = aligned.price_valid & aligned.adj_close.notna()
    aligned['volume_feature_eligible'] = (aligned.feature_eligible &
                                          aligned.volume.notna() & (aligned.volume > 0))
    aligned['gap_disposition'] = aligned.gap.map({True: 'excluded_no_imputation', False: ''})
    # A missing bar breaks all rolling feature windows across that boundary.
    aligned['segment_id'] = (~aligned.feature_eligible).cumsum()
    for horizon in [1, 5]:
        eligible = aligned.feature_eligible.copy()
        for offset in range(1, horizon + 1):
            eligible &= aligned.feature_eligible.shift(-offset, fill_value=False)
        aligned[f'target_{horizon}d_eligible'] = eligible
    return aligned
