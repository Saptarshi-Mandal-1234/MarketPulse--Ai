"""Causal technical indicators on contiguous, validated exchange sessions."""
import numpy as np
import pandas as pd


def divide(a, b):
    return a / b.where(b != 0)


def wilder(series, period):
    """Arithmetic seed after period finite observations, then Wilder recurrence."""
    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    seed = []
    previous = np.nan
    for i, value in enumerate(values):
        if not np.isfinite(value):
            seed, previous = [], np.nan
        elif np.isnan(previous):
            seed.append(value)
            if len(seed) == period:
                previous = float(np.mean(seed))
                result[i] = previous
        else:
            previous = (previous * (period - 1) + value) / period
            result[i] = previous
    return pd.Series(result, index=series.index)


def segment_features(frame, config, kind):
    close = frame.adj_close.astype(float)
    factor = close / frame.close.astype(float)
    high = frame.high.astype(float) * factor
    low = frame.low.astype(float) * factor
    out = pd.DataFrame(index=frame.index)
    for period in config['return_periods']:
        out[f'return_{period}d'] = close / close.shift(period) - 1
    out['log_return_1d'] = np.log(close / close.shift(1))
    for period in config['sma_periods']:
        out[f'sma_{period}'] = close.rolling(period, min_periods=period).mean()
        out[f'distance_sma_{period}'] = divide(close, out[f'sma_{period}']) - 1
    for period in config['ema_periods']:
        out[f'ema_{period}'] = close.ewm(span=period, adjust=False, min_periods=period).mean()
    rsi_period = config['rsi_period']
    change = close.diff()
    gain = wilder(change.clip(lower=0), rsi_period)
    loss = wilder((-change).clip(lower=0), rsi_period)
    rsi = 100 - 100 / (1 + divide(gain, loss))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100)
    rsi = rsi.mask((loss == 0) & (gain == 0), 50)
    out[f'rsi_{rsi_period}'] = rsi
    fast, slow, signal = config['macd']
    out['macd'] = (close.ewm(span=fast, adjust=False, min_periods=fast).mean() -
                   close.ewm(span=slow, adjust=False, min_periods=slow).mean())
    out['macd_signal'] = out.macd.ewm(span=signal, adjust=False, min_periods=signal).mean()
    out['macd_histogram'] = out.macd - out.macd_signal
    period = config['bollinger_period']
    middle = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std(ddof=0)
    out['bollinger_middle'] = middle
    out['bollinger_upper'] = middle + config['bollinger_sigma'] * std
    out['bollinger_lower'] = middle - config['bollinger_sigma'] * std
    out['bollinger_width'] = divide(out.bollinger_upper - out.bollinger_lower, middle)
    out['bollinger_percent_b'] = divide(close - out.bollinger_lower,
                                       out.bollinger_upper - out.bollinger_lower)
    previous = close.shift(1)
    true_range = pd.concat([high - low, (high - previous).abs(),
                            (low - previous).abs()], axis=1).max(axis=1)
    # First TR in each contiguous segment is its adjusted high-low.
    out[f'atr_{config["atr_period"]}'] = wilder(true_range, config['atr_period'])
    out['atr_fraction'] = divide(out[f'atr_{config["atr_period"]}'], close)
    out['momentum_10'] = close - close.shift(10)
    out['roc_10'] = close / close.shift(10) - 1
    for period in config['volatility_periods']:
        out[f'volatility_{period}'] = (out.log_return_1d.rolling(period, min_periods=period)
                                     .std(ddof=1) * np.sqrt(config['annual_sessions']))
    period = config['range_period']
    highest = high.rolling(period, min_periods=period).max()
    lowest = low.rolling(period, min_periods=period).min()
    out['high_252'] = highest
    out['low_252'] = lowest
    out['distance_high_252'] = divide(close, highest) - 1
    out['distance_low_252'] = divide(close, lowest) - 1
    volume = frame.volume.astype(float).where(frame.volume_feature_eligible.fillna(False))
    if kind == 'index':
        volume[:] = np.nan  # Index-provider volume is not equity share volume.
    period = config['volume_period']
    out['volume_change_1d'] = divide(volume, volume.shift(1)) - 1
    out['volume_sma_20'] = volume.rolling(period, min_periods=period).mean()
    baseline = volume.shift(1).rolling(period, min_periods=period).mean()
    out['relative_volume_20'] = divide(volume, baseline)
    return out.replace([np.inf, -np.inf], np.nan)


def compute_features(frame, config, kind):
    if frame.session_date.duplicated().any() or not frame.session_date.is_monotonic_increasing:
        raise ValueError('Input must have sorted unique exchange sessions')
    if frame.symbol.nunique() != 1:
        raise ValueError('One instrument per input is required')
    # Derive boundaries again; do not trust arbitrary caller-supplied segment ids.
    valid = frame.feature_eligible.fillna(False).astype(bool)
    numeric = frame[['open', 'high', 'low', 'close', 'adj_close']].astype(float)
    if not (np.isfinite(numeric.loc[valid]).all().all() and (numeric.loc[valid] > 0).all().all()):
        raise ValueError('Eligible prices must be finite and positive')
    groups = (~valid).cumsum()
    template = segment_features(frame.iloc[:0], config, kind)
    output = pd.DataFrame(np.nan, index=frame.index, columns=template.columns)
    ages = pd.Series(0, index=frame.index, dtype='int64')
    for _, part in frame.loc[valid].groupby(groups[valid], sort=False):
        output.loc[part.index] = segment_features(part, config, kind)
        ages.loc[part.index] = np.arange(1, len(part) + 1)
    # Input target masks use future availability and MUST NOT enter predictors.
    metadata = frame[['symbol', 'session_date']].copy()
    metadata['segment_age'] = ages
    metadata['input_valid'] = valid
    metadata['core_ready'] = valid & output[config['core_features']].notna().all(axis=1)
    # Conservative archive availability: never backdate historical observations.
    observed = pd.to_datetime(frame.observed_at, utc=True)
    if observed.loc[valid].isna().any():
        raise ValueError('Eligible rows need source observation timestamps')
    metadata['available_at'] = observed.ffill().cummax().where(valid)
    return pd.concat([metadata, output], axis=1), list(output.columns)
