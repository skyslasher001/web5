"""The audit log must be append-only and tamper-evident (SPEC §17). Guards protected core."""

import sqlite3
from pathlib import Path

import pytest

from universe_common.sqlite import connect, migrate_up
from universe_core.db import migrations_dir
from universe_core.protected.audit import GENESIS, AuditWriter


@pytest.fixture
def audit(tmp_path: Path) -> AuditWriter:
    conn = connect(tmp_path / "audit.db")
    migrate_up(conn, migrations_dir("audit"))
    return AuditWriter(conn)


def test_chain_verifies(audit: AuditWriter) -> None:
    for i in range(5):
        audit.append(actor="user", action="setting.changed", target_type="setting", target_id=f"k{i}")
    result = audit.verify()
    assert result.ok and result.count == 5


def test_rows_cannot_be_updated_or_deleted(audit: AuditWriter) -> None:
    audit.append(actor="user", action="setting.changed")
    conn = audit._conn
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET actor = 'agent:forge'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log")


def test_a_forged_row_breaks_verification(audit: AuditWriter) -> None:
    audit.append(actor="user", action="setting.changed")
    audit._conn.execute(
        "INSERT INTO audit_log (seq, ts, actor, action, details, outcome, prev_hash, hash)"
        " VALUES (2, '2026-01-01T00:00:00Z', 'agent:forge', 'permission.changed', '{}', 'ok', ?, ?)",
        (GENESIS, "f" * 64),
    )
    result = audit.verify()
    assert not result.ok and result.first_bad_seq == 2


def test_listing_returns_newest_first(audit: AuditWriter) -> None:
    audit.append(actor="user", action="a.one")
    audit.append(actor="user", action="a.two")
    assert [e.action for e in audit.list()] == ["a.two", "a.one"]
    assert [e.action for e in audit.list(action="a.one")] == ["a.one"]
