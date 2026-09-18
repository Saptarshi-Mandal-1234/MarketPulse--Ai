"""Descriptive, gap-aware analytics read from a consistent PostgreSQL snapshot."""
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from marketpulse.cli import connection
from marketpulse.quality.validate import sha


def ratio(numerator, denominator):
    return float(numerator / denominator) if denominator > 0 and np.isfinite(denominator) else None


def analyze(prices, config):
    if prices.index.duplicated().any() or not prices.index.is_monotonic_increasing:
        raise ValueError('Sorted unique session dates required')
    complete = prices.dropna()
    if len(complete) < 2:
        raise ValueError('Need two common price dates')
    # Common endpoints make normalized performance comparable across the basket.
    window = prices.loc[complete.index[0]:complete.index[-1]]
    returns = window.pct_change(fill_method=None)
    benchmark = config['benchmark']
    annual = config['annual_sessions']
    rf = (1 + config['risk_free_annual']) ** (1 / annual) - 1
    stats = []
    for symbol in window:
        p = window[symbol]
        r = returns[symbol].dropna()
        excess = r - rf
        paired = pd.concat([returns[symbol], returns[benchmark]], axis=1).dropna()
        elapsed = (window.index[-1] - window.index[0]).days / 365.25
        endpoint = p.iloc[-1] / p.iloc[0] - 1
        downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2))
        sufficient = len(r) >= config['minimum_return_observations']
        beta = (ratio(paired.iloc[:, 0].cov(paired.iloc[:, 1]), paired.iloc[:, 1].var())
                if len(paired) >= config['minimum_return_observations'] else None)
        stats.append({'symbol': symbol, 'first_session': str(window.index[0].date()),
                      'last_session': str(window.index[-1].date()),
                      'usable_price_rows': int(p.notna().sum()), 'missing_prices': int(p.isna().sum()),
                      'daily_return_observations': len(r), 'benchmark_pairs': len(paired),
                      'endpoint_return': float(endpoint),
                      'endpoint_cagr': float((1 + endpoint) ** (1 / elapsed) - 1) if elapsed > 0 else None,
                      'annualized_volatility': float(r.std(ddof=1) * np.sqrt(annual)) if sufficient else None,
                      'sharpe': ratio(excess.mean() * np.sqrt(annual), excess.std(ddof=1)) if sufficient else None,
                      'sortino': ratio(excess.mean() * np.sqrt(annual), downside) if sufficient else None,
                      'observed_max_drawdown': float((p / p.cummax() - 1).min()),
                      'beta_vs_nifty': beta,
                      'endpoint_excess_vs_nifty': float(endpoint -
                          (window[benchmark].iloc[-1] / window[benchmark].iloc[0] - 1))})
    metrics = pd.DataFrame(stats)
    normalized = window / window.iloc[0] * 100
    drawdowns = window / window.cummax() - 1
    correlation = returns.corr(min_periods=config['minimum_return_observations'])
    valid = returns.notna().astype(int)
    pair_counts = valid.T.dot(valid)
    n = config['rolling_sessions']
    volatility = returns.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(annual)
    rolling_beta = pd.DataFrame(index=returns.index)
    for symbol in returns:
        common_benchmark = returns[benchmark].where(returns[symbol].notna())
        variance = common_benchmark.rolling(n, min_periods=n).var()
        rolling_beta[symbol] = (returns[symbol].rolling(n, min_periods=n)
                                .cov(common_benchmark) / variance.where(variance > 0))
    return {'metrics': metrics, 'prices': window, 'returns': returns,
            'normalized': normalized, 'drawdowns': drawdowns, 'correlation': correlation,
            'pair_counts': pair_counts, 'rolling_volatility': volatility, 'rolling_beta': rolling_beta}


def charts(tables, folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    plt.rcParams.update({'figure.dpi': 130, 'font.size': 10})
    for key, title, ylabel in [('normalized', 'Observed adjusted-price growth — common start = 100', 'Index level'),
                               ('drawdowns', 'Drawdowns from observed peaks', 'Drawdown'),
                               ('rolling_volatility', '60-session annualized volatility', 'Volatility')]:
        fig, ax = plt.subplots(figsize=(12, 6), layout='constrained')
        for i, symbol in enumerate(tables[key]):
            ax.plot(tables[key].index, tables[key][symbol], label=symbol,
                    color=plt.get_cmap('tab20')(i),
                    linewidth=2.4 if symbol == 'NIFTY50' else .9)
        ax.set(title=title, ylabel=ylabel)
        ax.grid(alpha=.2)
        ax.legend(loc='upper left', ncol=3, fontsize=8)
        fig.savefig(folder / f'{key}.png')
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 8), layout='constrained')
    matrix = tables['correlation']
    im = ax.imshow(matrix, cmap='RdBu_r', vmin=-1, vmax=1)
    ax.set_xticks(range(len(matrix)), matrix.columns, rotation=55, ha='right')
    ax.set_yticks(range(len(matrix)), matrix.index)
    for i in range(len(matrix)):
        for j in range(len(matrix)):
            ax.text(j, i, f'{matrix.iloc[i,j]:.2f}', ha='center', va='center', fontsize=8,
                    color='white' if abs(matrix.iloc[i,j]) > .6 else 'black')
    ax.set_title('Daily-return correlation — available same-session pairs')
    fig.colorbar(im, ax=ax)
    fig.savefig(folder / 'correlation.png')
    plt.close(fig)


def main():
    root = Path.cwd()
    config = json.loads((root / 'config/analytics.json').read_text())
    load_dotenv(root / '.env')
    with connection() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        row = conn.execute('SELECT dataset_id FROM marketpulse.active_dataset').fetchone()
        if not row:
            raise ValueError('Run Stage 5 first')
        dataset = row[0]
        rows = conn.execute('''SELECT symbol,session_date,payload FROM marketpulse.validated_sessions
            WHERE dataset_id=%s ORDER BY session_date,symbol''', (dataset,)).fetchall()
        sectors = dict(conn.execute('SELECT symbol,sector FROM marketpulse.stocks').fetchall())
    observations = [{'symbol': s, 'date': pd.Timestamp(d),
                     'price': p.get('adj_close') if p.get('feature_eligible') else None}
                    for s, d, p in rows]
    prices = pd.DataFrame(observations).pivot(index='date', columns='symbol', values='price')
    tables = analyze(prices, config)
    tables['metrics']['sector'] = tables['metrics'].symbol.map(sectors)
    equities = tables['metrics'][tables['metrics'].symbol != config['benchmark']]
    tables['sector_summary'] = equities.groupby('sector').agg(
        stocks=('symbol', 'count'), mean_constituent_return=('endpoint_return', 'mean'),
        mean_constituent_volatility=('annualized_volatility', 'mean'),
        mean_constituent_beta=('beta_vs_nifty', 'mean'))
    run_id = str(uuid4())
    folder = root / 'reports/stage6' / run_id
    folder.mkdir(parents=True)
    for key, table in tables.items():
        table.to_csv(folder / f'{key}.csv', index=key != 'metrics')
    charts(tables, folder)
    manifest = {'run_id': run_id, 'dataset_id': dataset, 'created_at': datetime.now(UTC).isoformat(),
                'config': config, 'status': 'complete', 'database_source': True,
                'instruments': len(prices.columns), 'source_session_rows': len(rows)}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    lines = ['# Stage 6 — exploratory and risk analytics', '',
             'Computed from the verified PostgreSQL snapshot; all percentages below are descriptive.',
             f"Common range: {tables['metrics'].first_session.iloc[0]} to {tables['metrics'].last_session.iloc[0]}.",
             '', '| Instrument | Endpoint return | CAGR | Annual vol. | Observed max drawdown | Beta | Sharpe |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for r in tables['metrics'].to_dict('records'):
        def fmt(v, percent=False):
            return '—' if v is None or pd.isna(v) else (f'{v:.1%}' if percent else f'{v:.2f}')
        lines.append('| ' + r['symbol'] + ' | ' + ' | '.join([
            fmt(r['endpoint_return'], True), fmt(r['endpoint_cagr'], True),
            fmt(r['annualized_volatility'], True), fmt(r['observed_max_drawdown'], True),
            fmt(r['beta_vs_nifty']), fmt(r['sharpe'])]) + ' |')
    lines += ['', '## Method and limits', '',
              '- Returns are computed only across consecutive available exchange sessions; no filling.',
              '- Endpoint returns/CAGR use common observed endpoints; interim gaps remain visible.',
              '- Sharpe and Sortino use an explicit 0% annual risk-free assumption, not a current rate.',
              '- Volatility and ratios use 252 sessions/year. Beta/correlation use available paired returns.',
              '- Drawdowns use observed peaks: missing prices may conceal a worse drawdown.',
              '- Stocks use provider adjusted close; NIFTY50 is a price index, not its total-return index.',
              '  Dividend-adjusted equity excess returns therefore are not like-for-like total-return alpha.',
              '- Sector numbers are unweighted means of the selected constituents, not sector indexes.',
              '- This fixed surviving large-cap basket and revised data do not support investable backtest claims.',
              '', '## Charts', '']
    for key in ['normalized', 'drawdowns', 'rolling_volatility', 'correlation']:
        lines += [f'![{key}]({(folder / (key + ".png")).resolve().as_posix()})', '']
    (folder / 'ANALYTICS_REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    manifest['implementation_sha256'] = sha(Path(__file__))
    manifest['outputs'] = {p.name: sha(p) for p in sorted(folder.iterdir())
                           if p.name != 'manifest.json'}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (root / 'reports/stage6/latest.json').write_text(json.dumps({'run_id': run_id}))
    print(folder)


if __name__ == '__main__':
    main()
