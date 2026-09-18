"""Create a local PostgreSQL custom-format backup without command-line credentials."""
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from marketpulse.cli import connection
from marketpulse.quality.validate import sha

root = Path.cwd()
load_dotenv(root / '.env')
binary = shutil.which('pg_dump') or 'C:/Program Files/PostgreSQL/18/bin/pg_dump.exe'
if not Path(binary).exists():
    raise SystemExit('Install PostgreSQL client tools first')
environment = os.environ.copy()
with connection() as conn:
    params = conn.info.get_parameters()
    for key, variable in [('host', 'PGHOST'), ('port', 'PGPORT'), ('dbname', 'PGDATABASE'),
                          ('user', 'PGUSER'), ('password', 'PGPASSWORD'), ('sslmode', 'PGSSLMODE')]:
        if key in params:
            environment[variable] = params[key]
folder = root / 'backups'
folder.mkdir(exist_ok=True)
target = folder / (datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '.dump')
subprocess.run([binary, '--format=custom', '--no-owner', '--no-privileges', '--file', str(target)],
               env=environment, check=True, capture_output=True)
restore = str(Path(binary).with_name('pg_restore.exe' if os.name == 'nt' else 'pg_restore'))
inventory = subprocess.run([restore, '--list', str(target)], check=True, capture_output=True, text=True)
assert 'TABLE DATA' in inventory.stdout
receipt = {'status': 'archive_verified', 'file': str(target.relative_to(root)),
           'sha256': sha(target), 'bytes': target.stat().st_size,
           'note': 'Archive inventory verified; restore into a separate database before disaster recovery use'}
(folder / 'latest.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
