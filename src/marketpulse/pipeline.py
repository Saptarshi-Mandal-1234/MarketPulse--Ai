"""Laptop daily workflow with a process lock, stage logs and last-good dashboard publication."""
import argparse
import contextlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from marketpulse.cli import connection, migrate
from marketpulse.features.build import build
from marketpulse.ingestion.download import download
from marketpulse.quality.sessions import make_calendar
from marketpulse.quality.validate import run as validate


def expected_session(now, reference):
    local = now.astimezone(ZoneInfo('Asia/Kolkata'))
    today = local.date()
    cal = make_calendar(str(today - timedelta(days=14)), str(today + timedelta(days=1)), reference)
    # Normal bars are eligible 30 minutes after the 15:30 close; special-session bars after 21:30.
    row = cal.iloc[-1]
    cutoff = (21, 30) if row.session_kind in ['muhurat', 'special'] else (16, 0)
    dates = cal.loc[cal.expected_open, 'session_date']
    if (local.hour, local.minute) < cutoff:
        dates = dates[dates < str(today)]
    if dates.empty:
        raise ValueError('No eligible session within calendar window')
    return dates.iloc[-1]


def freshness(quality, expected):
    return all(r['latest_usable'] is not None and r['latest_usable'] >= expected
               for r in quality['instruments'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daily', action='store_true', help='Fetch a fresh full adjusted-price snapshot')
    parser.add_argument('--replay', action='store_true', help='Rebuild from the existing verified raw archive')
    parser.add_argument('--force', action='store_true', help='Recheck a session already published')
    args = parser.parse_args()
    if args.daily == args.replay:
        parser.error('Choose exactly one of --daily or --replay')
    root = Path.cwd()
    load_dotenv(root / '.env')
    run_id = str(uuid4())
    folder = root / 'reports/pipeline' / run_id
    folder.mkdir(parents=True)
    state = {'run_id': run_id, 'mode': 'daily' if args.daily else 'replay',
             'started_at': datetime.now(UTC).isoformat(), 'status': 'running', 'stages': []}
    def persist():
        (folder / 'status.json').write_text(json.dumps(state, indent=2))
        temporary = root / 'reports/pipeline/latest.tmp'
        temporary.write_text(json.dumps(state, indent=2))
        temporary.replace(root / 'reports/pipeline/latest.json')
    def stage(name, action):
        state['current_stage'] = name
        persist()
        print(f'{name}...', flush=True)
        with ((folder / f'{name}.log').open('w', encoding='utf-8') as log,
              contextlib.redirect_stdout(log), contextlib.redirect_stderr(log)):
            result = action(log)
        state['stages'].append({'name': name, 'finished_at': datetime.now(UTC).isoformat()})
        persist()
        return result
    def command(module):
        def execute(log):
            subprocess.run([sys.executable, '-m', module], cwd=root, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=1800)
        return execute
    persist()
    try:
        with connection() as conn:
            conn.autocommit = True
            if not conn.execute('SELECT pg_try_advisory_lock(731910)').fetchone()[0]:
                state['status'] = 'skipped_already_running'
                return
            migrate(conn, root)
            ref = json.loads((root / 'config/nse_sessions_operational.json').read_text())
            expected = expected_session(datetime.now(UTC), ref)
            state['expected_session'] = expected
            current_path = root / 'data/dashboard/current.json'
            if args.daily and current_path.exists() and not args.force:
                current = json.loads(current_path.read_text())
                manifest = json.loads((Path(current['path']) / 'manifest.json').read_text())
                if manifest.get('expected_session') == expected and manifest['stale_instruments'] == 0:
                    state['status'] = 'skipped_already_current'
                    return
            if args.daily:
                end = str(datetime.fromisoformat(expected).date() + timedelta(days=1))
                raw = stage('download', lambda log: download(root, '2015-01-01', end, None,
                                                            allow_completed_today=True))
                if raw['status'] != 'success':
                    raise ValueError('Provider did not return a complete universe')
                source = root / 'data/raw/yahoo_research' / raw['run_id'] / 'manifest.json'
            else:
                current = json.loads((root / 'data/processed/latest.json').read_text())
                quality = json.loads((root / 'data/processed' / current['quality_id'] / 'manifest.json').read_text())
                source = root / quality['source_manifest']
            quality = stage('validation', lambda log: validate(root, source, root / 'config/quality-operational.json'))
            if args.daily and not freshness(quality, expected):
                state['reason'] = 'Latest expected session missing; previous dashboard preserved'
                raise ValueError('Stale provider snapshot')
            stage('features', lambda log: build(root))
            stage('database', command('marketpulse.db.load'))
            stage('analytics', command('marketpulse.analytics.report'))
            stage('risk', command('marketpulse.signals.risk'))
            stage('forecasts_dashboard_insights', command('marketpulse.reporting.export'))
            state['status'] = 'success' if args.daily else 'success_replay'
    except Exception as exc:  # noqa: BLE001 -- preserve run status for every stage failure
        state.update(status='failed', error_type=type(exc).__name__)
        print(f"Pipeline stopped at {state.get('current_stage', 'startup')}. See {folder / 'status.json'}")
    finally:
        state['finished_at'] = datetime.now(UTC).isoformat()
        persist()
        try:
            with connection() as conn:
                conn.execute('INSERT INTO marketpulse.pipeline_runs VALUES (%s,%s,%s,%s,%s,%s)',
                             (run_id, state['started_at'], state['finished_at'], state['mode'],
                              state['status'], Jsonb(state)))
        except Exception as exc:  # noqa: BLE001 -- local log survives database failure
            state['database_log_error'] = type(exc).__name__
            persist()
    if state['status'] == 'failed':
        raise SystemExit(1)
    print(f"Pipeline {state['status']}: {run_id}")


if __name__ == '__main__':
    main()
