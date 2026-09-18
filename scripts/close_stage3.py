"""Create a closeout audit after matching every exclusion to recorded provider rechecks."""
import argparse
import json
from pathlib import Path

import pandas as pd

from marketpulse.quality.validate import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('quality_id')
    parser.add_argument('recovery_id')
    args = parser.parse_args()
    root = Path.cwd()
    processed = root / 'data/processed' / args.quality_id
    result = json.loads((processed / 'manifest.json').read_text())
    recovery_dir = root / 'data/raw/gap_rechecks' / args.recovery_id
    recovery = json.loads((recovery_dir / 'manifest.json').read_text())
    reviewed = json.loads((root / 'data/processed' / recovery['quality_id'] /
                          'manifest.json').read_text())
    if reviewed['source_manifest_sha256'] != result['source_manifest_sha256']:
        raise ValueError('Rechecks belong to a different source snapshot')
    old_issues = root / 'reports' / recovery['quality_id'] / 'issues.csv'
    if sha(old_issues) != recovery['issue_sha256']:
        raise ValueError('Original gap inventory changed')
    requested = set()
    outcomes = {}
    for request in recovery['requests']:
        key = (request['symbol'], request['session_date'])
        if key in requested:
            raise ValueError('Duplicate recheck record')
        requested.add(key)
        if request['status'] not in ['still_missing', 'still_invalid']:
            raise ValueError('Unreviewed recovery candidate or request failure')
        path = (recovery_dir / request['file']).resolve()
        if path.parent != recovery_dir.resolve() or sha(path) != request['sha256']:
            raise ValueError('Recheck source checksum mismatch')
        outcomes[request['status']] = outcomes.get(request['status'], 0) + 1
    excluded = set()
    for path in (processed / 'aligned').glob('*.parquet'):
        frame = pd.read_parquet(path)
        excluded.update(zip(frame.loc[frame.gap, 'symbol'],
                            frame.loc[frame.gap, 'session_date'], strict=True))
    if requested != excluded:
        raise ValueError('Not every final exclusion has matching recovery evidence')
    issues = pd.read_csv(root / 'reports' / args.quality_id / 'issues.csv')
    if issues.disposition.isna().any():
        raise ValueError('An issue has no disposition')
    source_manifest = root / result['source_manifest']
    source = json.loads(source_manifest.read_text())
    for instrument in source['instruments']:
        if sha(source_manifest.parent / instrument['file']) != instrument['sha256']:
            raise ValueError('Source snapshot changed')
    for output in result['outputs']:
        if sha(root / output['path']) != output['sha256']:
            raise ValueError('Validated output changed')
    totals = {field: sum(row[field] for row in result['instruments'])
              for field in ['raw', 'clean', 'quarantined', 'excluded_sessions',
                            'eligible_1d', 'eligible_5d']}
    audit = {'stage': 3, 'status': 'complete_with_documented_exclusions',
             'quality_id': args.quality_id, 'quality_manifest_sha256': sha(processed / 'manifest.json'),
             'recheck_manifest': str((recovery_dir / 'manifest.json').relative_to(root)),
             'recheck_manifest_sha256': sha(recovery_dir / 'manifest.json'),
             'recheck_outcomes': outcomes, 'totals': totals,
             'feature_stage_ready': result['feature_stage_ready'],
             'latest_usable_session': min(row['latest_usable'] for row in result['instruments'])}
    report = root / 'reports' / args.quality_id
    (report / 'completion.json').write_text(json.dumps(audit, indent=2))
    text = f'''# Stage 3 completed

Result: validated with documented exclusions; ready for Stage 4 feature engineering.

- {totals['raw']:,} original rows: {totals['clean']:,} retained and {totals['quarantined']} quarantined.
- {totals['excluded_sessions']} missing/unusable instrument-sessions explicitly represented as gaps.
- All {len(requested)} gaps rechecked using narrow Yahoo requests: {outcomes}.
- No replacement bars were available; no prices were invented or forward-filled.
- Latest usable close across all instruments: {audit['latest_usable_session']}.
- {totals['eligible_1d']:,} one-session and {totals['eligible_5d']:,} five-session price windows eligible
  before later feature warm-up, training splits and model checks.

The checked-in calendar covers 2015-01-01 through 2026-09-09. It reconciles NSE cash-market
annual circulars, Muhurat sessions and researched amendments. Extension beyond this period
fails closed until the reference is reviewed. Source URLs and accessed mirror copies are
recorded in config/nse_sessions_reference.json; local archive PDF downloads timed out.

Use data/processed/{args.quality_id}/aligned/ for Stage 4. Restart rolling windows when
segment_id changes and honor feature/volume/horizon eligibility flags. Plain retained-bar
files omit gaps and must not be used with an unqualified shift or rolling operation.

Every issue in issues.csv has a disposition. Corporate events, unusual returns and volume
spikes remain source observations; they are not automatically corrected. This is a research
data-quality handoff, not a claim that historical data is error-free or point-in-time investable.
No unreviewed prices were loaded into PostgreSQL. No background automation was enabled.

Completion evidence: completion.json; all checksums and gap-recheck coverage verified.
Source/download gaps are resolved operationally by exclusion, not by recovering unavailable prices.
'''
    (report / 'STAGE_3_COMPLETE.md').write_text(text, encoding='utf-8')
    print(json.dumps(audit, indent=2))


if __name__ == '__main__':
    main()
