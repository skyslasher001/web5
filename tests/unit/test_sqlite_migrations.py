import sqlite3
from pathlib import Path

import pytest

from universe_common.sqlite import (
    MigrationError,
    applied_versions,
    connect,
    load_migrations,
    migrate_down,
    migrate_up,
    transaction,
)
from universe_core.db import migrations_dir


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')").fetchall()
    return {r["name"] for r in rows if not r["name"].startswith("sqlite_")}


@pytest.mark.parametrize("name", ["universe", "events", "audit"])
def test_every_migration_round_trips(tmp_path: Path, name: str) -> None:
    conn = connect(tmp_path / f"{name}.db")
    migrations = load_migrations(migrations_dir(name))
    assert migrate_up(conn, migrations_dir(name)) == [m.version for m in migrations]
    after_up = _tables(conn)
    assert after_up - {"schema_migrations"}
    assert migrate_down(conn, migrations_dir(name), 0) == [m.version for m in reversed(migrations)]
    assert _tables(conn) == {"schema_migrations"}
    migrate_up(conn, migrations_dir(name))
    assert _tables(conn) == after_up


def test_edited_migration_is_detected(tmp_path: Path) -> None:
    mig = tmp_path / "mig"
    mig.mkdir()
    (mig / "0001_one.up.sql").write_text("CREATE TABLE a (x INTEGER);")
    (mig / "0001_one.down.sql").write_text("DROP TABLE a;")
    conn = connect(tmp_path / "x.db")
    migrate_up(conn, mig)
    (mig / "0001_one.up.sql").write_text("CREATE TABLE a (x INTEGER, y INTEGER);")
    with pytest.raises(MigrationError, match="edited"):
        migrate_up(conn, mig)


def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    mig = tmp_path / "mig"
    mig.mkdir()
    (mig / "0001_bad.up.sql").write_text("CREATE TABLE a (x INTEGER);\nTHIS IS NOT SQL;")
    (mig / "0001_bad.down.sql").write_text("DROP TABLE a;")
    conn = connect(tmp_path / "x.db")
    with pytest.raises(sqlite3.OperationalError):
        migrate_up(conn, mig)
    assert "a" not in _tables(conn)
    assert applied_versions(conn) == {}


def test_migrations_must_be_contiguous_and_paired(tmp_path: Path) -> None:
    mig = tmp_path / "mig"
    mig.mkdir()
    (mig / "0002_two.up.sql").write_text("SELECT 1;")
    (mig / "0002_two.down.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="contiguous"):
        load_migrations(mig)
    (mig / "0001_one.up.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError, match="both"):
        load_migrations(mig)


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_sqlite_has_fts5_and_wal(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.execute("CREATE VIRTUAL TABLE f USING fts5(body)")
    conn.execute("INSERT INTO f VALUES ('the sunset at the lake')")
    assert conn.execute("SELECT COUNT(*) FROM f WHERE f MATCH 'lake'").fetchone()[0] == 1
