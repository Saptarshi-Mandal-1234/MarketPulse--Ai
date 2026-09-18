"""Verify a completed download's file hashes and readable row counts offline."""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    total = 0
    for row in manifest['instruments']:
        for attempt in row['attempts']:
            if 'file' in attempt:
                path = args.manifest.parent / attempt['file']
                if hashlib.sha256(path.read_bytes()).hexdigest() != attempt['sha256']:
                    raise ValueError('Checksum mismatch: ' + path.name)
        if row['status'] == 'success':
            data = pd.read_parquet(args.manifest.parent / row['file'])
            if len(data) != row['rows']:
                raise ValueError('Row count mismatch: ' + row['symbol'])
            total += len(data)
    print(f"Verified {len(manifest['instruments'])} instrument receipts; {total} rows.")


if __name__ == '__main__':
    main()
