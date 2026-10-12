"""SQLite helpers: WAL connections, explicit transactions, versioned up/down SQL migrations."""

import hashlib
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")


def connect(path: Path | str, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a connection in autocommit mode; use `transaction()` for atomic work."""
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, autocommit=True, check_same_thread=False)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, autocommit=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up_sql: str
    down_sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.up_sql.encode("utf-8")).hexdigest()


class MigrationError(RuntimeError):
    pass


def load_migrations(directory: Path) -> list[Migration]:
    found: dict[int, dict[str, str]] = {}
    names: dict[int, str] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_RE.match(path.name)
        if not match:
            raise MigrationError(f"bad migration filename: {path.name}")
        version, name, kind = int(match[1]), match[2], match[3]
        if names.setdefault(version, name) != name:
            raise MigrationError(f"migration {version:04d} has two names")
        found.setdefault(version, {})[kind] = path.read_text(encoding="utf-8")
    migrations = []
    for version in sorted(found):
        parts = found[version]
        if "up" not in parts or "down" not in parts:
            raise MigrationError(f"migration {version:04d} needs both .up.sql and .down.sql")
        migrations.append(Migration(version, names[version], parts["up"], parts["down"]))
    expected = list(range(1, len(migrations) + 1))
    if [m.version for m in migrations] != expected:
        raise MigrationError(f"migration versions must be contiguous from 0001, got {[m.version for m in migrations]}")
    return migrations


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )


def applied_versions(conn: sqlite3.Connection) -> dict[int, str]:
    _ensure_table(conn)
    return {row["version"]: row["checksum"] for row in conn.execute("SELECT version, checksum FROM schema_migrations")}


def _run_script(conn: sqlite3.Connection, sql: str) -> None:
    # The script runs inside one explicit transaction; executescript does not auto-commit
    # in autocommit mode, so a failure rolls everything back.
    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def migrate_up(conn: sqlite3.Connection, directory: Path, target: int | None = None) -> list[int]:
    """Apply pending migrations up to `target` (default: latest). Returns the versions applied."""
    migrations = load_migrations(directory)
    applied = applied_versions(conn)
    for m in migrations:
        if m.version in applied and applied[m.version] != m.checksum:
            raise MigrationError(f"migration {m.version:04d}_{m.name} was edited after it was applied")
    done = []
    for m in migrations:
        if m.version in applied or (target is not None and m.version > target):
            continue
        # Values come from a validated filename (int, [a-z0-9_]) and a hex digest, never from input.
        record = (
            "INSERT INTO schema_migrations (version, name, checksum) "  # noqa: S608
            f"VALUES ({m.version}, '{m.name}', '{m.checksum}');"
        )
        _run_script(conn, m.up_sql + "\n" + record)
        done.append(m.version)
    return done


def migrate_down(conn: sqlite3.Connection, directory: Path, target: int) -> list[int]:
    """Revert applied migrations above `target`, newest first. Returns the versions reverted."""
    migrations = {m.version: m for m in load_migrations(directory)}
    applied = sorted(applied_versions(conn), reverse=True)
    done = []
    for version in applied:
        if version <= target:
            break
        m = migrations[version]
        _run_script(conn, m.down_sql + f"\nDELETE FROM schema_migrations WHERE version = {version};")
        done.append(version)
    return done
