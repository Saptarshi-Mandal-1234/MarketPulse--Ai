"""Interactive local bootstrap: administrator password is never saved or printed."""
import getpass
import secrets
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

from marketpulse.cli import migrate

ROOT = Path(__file__).resolve().parents[1]


def main():
    env_path = ROOT / '.env'
    current = dotenv_values(env_path)
    if current.get('DATABASE_URL') or current.get('PGPASSWORD'):
        print('Connection settings already exist. Use db-check and db-init from the README.')
        return
    admin_password = getpass.getpass('PostgreSQL installation password (typing is hidden): ')
    with psycopg.connect(host='localhost', port=5432, dbname='postgres', user='postgres',
                         password=admin_password, connect_timeout=5, autocommit=True) as admin:
        role_exists = admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='marketpulse'"
        ).fetchone()
        database_exists = admin.execute(
            "SELECT 1 FROM pg_database WHERE datname='marketpulse'"
        ).fetchone()
        if role_exists or database_exists:
            print('A marketpulse role or database already exists. Nothing was changed.')
            print('Tell Codex this message so the existing setup can be connected safely.')
            return
        password = secrets.token_urlsafe(32)
        # Save the generated application credential before creating resources, so it
        # remains recoverable if database creation fails. Never save the admin password.
        env_path.write_text(
            'PGHOST=localhost\nPGPORT=5432\nPGDATABASE=marketpulse\n'
            'PGUSER=marketpulse\nPGPASSWORD=' + password + '\n'
            'PGSSLMODE=prefer\nDATABASE_URL=\n', encoding='utf-8'
        )
        admin.execute(sql.SQL('CREATE ROLE marketpulse LOGIN PASSWORD {}').format(
            sql.Literal(password)))
        admin.execute('CREATE DATABASE marketpulse OWNER marketpulse')
    del admin_password
    with psycopg.connect(host='localhost', port=5432, dbname='marketpulse',
                         user='marketpulse', password=password, connect_timeout=5) as conn:
        migrate(conn, ROOT)
        migrate(conn, ROOT)
        count = conn.execute('SELECT count(*) FROM marketpulse.stocks').fetchone()[0]
        if count != 11:
            raise ValueError('Unexpected instrument count')
    print('SUCCESS: database connected, migrations verified twice, 11 instruments seeded.')
    print('The application password is stored only in the local ignored .env file.')


if __name__ == '__main__':
    try:
        main()
    except (psycopg.Error, OSError, ValueError):
        print('Setup did not finish. Check the password and PostgreSQL service.')
        print('Tell Codex this message. Do not share any passwords or the .env contents.')
        raise SystemExit(1)
