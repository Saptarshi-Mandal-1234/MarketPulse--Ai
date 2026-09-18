"""Run a read-only published snapshot and database integrity check."""
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
result = subprocess.run([sys.executable, str(root / 'scripts/verify_release.py')],
                        cwd=root, capture_output=True, text=True, timeout=120, check=False)
status = {'checked_at': datetime.now(UTC).isoformat(),
          'snapshot_and_database': 'passed' if result.returncode == 0 else 'failed'}
print('MarketPulse AI | Project health')
print('Snapshot and database integrity: ' + status['snapshot_and_database'])
if result.returncode == 0:
    pointer = json.loads((root / 'data/dashboard/current.json').read_text())
    manifest = json.loads((Path(pointer['path']) / 'manifest.json').read_text())
    print('Published session: ' + manifest['expected_session'])
    print('Instruments without current indicators: ' + str(manifest['stale_instruments']))
    print('A successful integrity check does not mean every indicator is current.')
else:
    print('Run scripts/verify_release.py for detailed diagnostics. No data was changed.')
folder = root / 'reports/health'
folder.mkdir(parents=True, exist_ok=True)
(folder / 'latest.json').write_text(json.dumps(status, indent=2))
raise SystemExit(result.returncode)
