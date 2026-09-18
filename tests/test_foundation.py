import json
import tomllib
from pathlib import Path

from pglast import parse_sql

ROOT = Path(__file__).resolve().parents[1]


def test_universe_and_seed_agree():
    universe = json.loads((ROOT / "config/universe.json").read_text())
    assert len(universe) == 11
    assert sum(row["kind"] == "equity" for row in universe) == 10
    assert len({row["provider_symbol"] for row in universe}) == 11
    seed = (ROOT / "sql/002_seed_universe.sql").read_text()
    for row in universe:
        assert "'" + row["symbol"] + "'" in seed


def test_postgresql_syntax():
    for path in (ROOT / "sql").glob("*.sql"):
        assert parse_sql(path.read_text())


def test_targets_config():
    config = tomllib.loads((ROOT / "config/project.toml").read_text())
    assert config["horizons_sessions"] == [1, 5]
    assert config["timezone"] == "Asia/Kolkata"
