"""Seed galaxies (SPEC §28): created on first boot, idempotent by slug."""

import sqlite3

from universe_common.ids import uuid7
from universe_common.timeutil import utcnow
from universe_core.events import EventBus

SEED_GALAXIES = [
    ("ember-wolf-acquisitions", "Ember Wolf Acquisitions", "Vacant land wholesaling business.", "amber", 1),
    (
        "devmind",
        "DevMind",
        "Offline AI developer IDE on the same Electron/FastAPI/React stack.",
        "violet",
        2,
    ),
    ("algo-trading-bot", "Algo trading bot", "Python trading bot for perpetual futures.", "green", 3),
    ("universe", "UNIVERSE", "This app's own source code, so Forge can see and repair it.", "cyan", 4),
]


def ensure_seed_galaxies(conn: sqlite3.Connection, bus: EventBus) -> list[str]:
    """Insert missing seed projects. Returns the slugs created."""
    created = []
    for slug, name, description, color, seed in SEED_GALAXIES:
        if conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
            continue
        now = utcnow()
        project_id = uuid7()
        conn.execute(
            "INSERT INTO projects (id, name, slug, description, color_token, layout_seed, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (project_id, name, slug, description, color, seed, now, now),
        )
        bus.publish(
            "project.created",
            {"project_id": project_id, "name": name, "slug": slug, "seed": True},
            subject_type="project",
            subject_id=project_id,
        )
        created.append(slug)
    return created
