# Security

Do not report credentials in a public issue. If a secret is accidentally committed,
rotate it immediately and remove it from Git history. PostgreSQL credentials belong only
in the ignored `.env` file.

The project downloads public market data and does not execute trades. Review dependency
and provider changes before adopting them in an automated environment.
