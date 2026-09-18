"""Repository-local setup commands. No market data is downloaded."""
import argparse
import hashlib
import json
import os
import sys
import tomllib
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def connection():
    if os.getenv("DATABASE_URL"):
        return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
    if not os.getenv("PGPASSWORD"):
        raise ValueError("Set PGPASSWORD or DATABASE_URL privately in .env first.")
    return psycopg.connect(connect_timeout=5)


def migrate(conn, root):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(731905)")
        conn.execute("CREATE SCHEMA IF NOT EXISTS marketpulse")
        conn.execute("""CREATE TABLE IF NOT EXISTS marketpulse.schema_migrations
                     (name text PRIMARY KEY, sha256 text NOT NULL,
                      applied_at timestamptz NOT NULL DEFAULT now())""")
        for path in sorted((root / "sql").glob("[0-9]*.sql")):
            body = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(body.encode()).hexdigest()
            row = conn.execute("SELECT sha256 FROM marketpulse.schema_migrations WHERE name=%s",
                               (path.name,)).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError("Applied migration changed: " + path.name)
                continue
            conn.execute(body)
            conn.execute("INSERT INTO marketpulse.schema_migrations(name,sha256) VALUES (%s,%s)",
                         (path.name, digest))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["doctor", "db-check", "db-init"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    load_dotenv(root / ".env", override=False)
    try:
        config = tomllib.loads((root / "config/project.toml").read_text())
        universe = json.loads((root / "config/universe.json").read_text())
        if len(universe) != 11 or len({x["symbol"] for x in universe}) != 11:
            raise ValueError("Expected eleven unique instruments")
        if args.command == "doctor":
            print(f"OK: Python {sys.version.split()[0]}; {len(universe)} instruments; "
                  f"contract {config['contract_version']}")
            configured = bool(os.getenv("DATABASE_URL") or os.getenv("PGPASSWORD"))
            print("Database: " + ("configured, run db-check" if configured else
                                  "pending: configure .env and start PostgreSQL"))
            return
        with connection() as conn:
            if args.command == "db-init":
                migrate(conn, root)
            print("OK: PostgreSQL " + conn.execute("SHOW server_version").fetchone()[0])
    except (OSError, ValueError, psycopg.Error):
        # Do not print connection strings or exception text that could contain secrets.
        print("Setup failed. Check repository root, config, PostgreSQL service and private .env.",
              file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
