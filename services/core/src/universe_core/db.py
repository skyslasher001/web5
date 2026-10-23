"""The three SQLite files in <vault>/.universe/ (ADR-0003), migrated at startup."""

import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from universe_common.sqlite import connect, migrate_up


def migrations_dir(name: str) -> Path:
    return Path(str(resources.files("universe_core").joinpath("migrations", name)))


@dataclass
class Databases:
    universe: sqlite3.Connection
    events: sqlite3.Connection
    audit: sqlite3.Connection
    directory: Path

    @classmethod
    def open(cls, directory: Path) -> "Databases":
        directory.mkdir(parents=True, exist_ok=True)
        dbs = cls(
            universe=connect(directory / "universe.db"),
            events=connect(directory / "events.db"),
            audit=connect(directory / "audit.db"),
            directory=directory,
        )
        for name in ("universe", "events", "audit"):
            migrate_up(getattr(dbs, name), migrations_dir(name), snapshot_dir=directory / "backups" / "migrations")
        return dbs

    def sizes(self) -> dict[str, int]:
        out = {}
        for name in ("universe", "events", "audit"):
            total = 0
            for suffix in ("", "-wal"):
                path = self.directory / f"{name}.db{suffix}"
                if path.exists():
                    total += path.stat().st_size
            out[name] = total
        return out

    def close(self) -> None:
        for conn in (self.universe, self.events, self.audit):
            conn.close()
