"""Phase 4 demo and benchmark data: a synthetic universe of 50,000 items in an EMPTY vault (ADR-0012).

    uv run python scripts/seed_universe.py C:\\Temp\\universe50k --count 50000
    set UNIVERSE_VAULT_DIR=C:\\Temp\\universe50k   (then pnpm dev)

Running 50k files through the real pipeline would take hours, so this writes rows straight into the vault's
database: items with small Markdown files under `seed/`, searchable text, galaxies, links between items, and
(with --embedder) vectors so the Semantic layout has something to arrange. It refuses a vault that already
has items: it's for a scratch folder, never your real vault.
"""

import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for tests.support

from tests.support.seed import TOPICS
from universe_common.ids import uuid7
from universe_common.sqlite import transaction
from universe_core.db import Databases
from universe_core.seed import ensure_seed_galaxies
from universe_vault.layout import Vault, slugify

# Roughly what a real vault holds, so every celestial kind shows up.
MIX = {
    "note": 0.32, "idea": 0.05, "photo": 0.18, "screenshot": 0.03, "song": 0.05, "audio": 0.02,
    "voice_memo": 0.02, "video": 0.02, "document": 0.08, "pdf": 0.06, "spreadsheet": 0.02,
    "code_file": 0.07, "code_repo": 0.005, "link": 0.055, "file": 0.02,
}  # fmt: skip
EXTRA_GALAXIES = [
    "Garden redesign", "Home studio", "Kyoto trip", "Reading list", "Side hustle ideas", "Fitness log",
    "Family photos", "Taxes 2026",
]  # fmt: skip
WORDS = [
    "harbor", "lantern", "quartz", "meadow", "ember", "signal", "orbit", "velvet", "cinder", "atlas", "pixel",
    "summit", "drift", "echo", "maple", "nova", "prism", "tide", "relay", "copper", "willow", "beacon", "cobalt",
    "fable", "glacier", "haven", "ivory", "jasper", "kestrel", "lumen",
]  # fmt: skip
PIPELINE_STAGES = ("metadata", "extract", "embed", "sidecar")
HUES = ["rose", "green", "blue", "amber", "violet", "cyan", "slate"]  # the galaxy colours (design tokens)


class _QuietBus:
    """The seed galaxies' "created" events have nobody to go to here."""

    def publish(self, *_args: object, **_kwargs: object) -> None:
        return None


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def generate(
    vault_dir: Path, count: int, *, seed: int = 7, embedder: str | None = None, dim: int = 768
) -> dict[str, float]:
    rng = random.Random(seed)  # noqa: S311 (reproducible demo data, not security)
    vault = Vault(vault_dir)
    vault.ensure()
    dbs = Databases.open(vault.index)
    conn = dbs.universe
    try:
        if conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]:
            raise SystemExit(f"{vault_dir} already has items: seed only an empty, scratch vault")
        started = time.monotonic()
        ensure_seed_galaxies(conn, _QuietBus())  # type: ignore[arg-type]
        now = datetime.now(UTC)
        with transaction(conn):
            for n, name in enumerate(EXTRA_GALAXIES):
                if conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slugify(name),)).fetchone():
                    continue
                conn.execute(
                    "INSERT INTO projects (id, name, slug, description, color_token, layout_seed,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (uuid7(), name, slugify(name), "Synthetic galaxy (seed data)", HUES[n % len(HUES)], 10 + n,
                     _iso(now), _iso(now)),
                )  # fmt: skip
        galaxies = [r["id"] for r in conn.execute("SELECT id FROM projects ORDER BY layout_seed")]
        # Galaxy sizes follow a long tail, like real projects: a few big ones, many small.
        weights = [1 / (k + 1) ** 0.9 for k in range(len(galaxies))]
        source = uuid7()
        conn.execute(
            "INSERT INTO sources (id, kind, importer, extra, created_at) VALUES (?, 'importer', 'seed_universe', ?, ?)",
            (source, json.dumps({"synthetic": True}), _iso(now)),
        )
        types = list(MIX)
        type_weights = [MIX[t] for t in types]
        items, memberships, chunk_rows, topics_of = [], [], [], []
        for n in range(count):
            item_id = uuid7()
            item_type = rng.choices(types, type_weights)[0]
            topic, sentence, _probe = TOPICS[rng.randrange(len(TOPICS))]
            title = f"{rng.choice(WORDS).title()} {topic} {n:05d}"
            age_days = rng.random() ** 2 * 900  # more recent items than old ones
            created = now - timedelta(days=age_days, seconds=rng.randrange(86400))
            roll = rng.random()
            galaxy = rng.choices(galaxies, weights)[0] if roll < 0.85 else None
            inbox = galaxy is None and roll > 0.95  # ~5 %: fresh captures waiting for triage (comets)
            if inbox:
                created = now - timedelta(hours=rng.random() * 72)
            opened = created + timedelta(days=rng.random() * age_days) if rng.random() < 0.35 else None
            rel = f"seed/{created:%Y}/{item_id}.md"
            body = f"# {title}\n\n{sentence} {' '.join(rng.sample(WORDS, 6))}.\n"
            path = vault.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8", newline="\n")
            stage = rng.choice(["nebula", "protostar", "star"]) if item_type == "idea" else None
            items.append(
                (
                    item_id, item_type, title, slugify(title), "inbox" if inbox or galaxy is None else "active",
                    stage, rel, "text/markdown", len(body), f"seed-{item_id}", _iso(created),
                    json.dumps({"synthetic": True}), rng.random() < 0.01, rng.randrange(12) if opened else 0,
                    _iso(opened) if opened else None, source, _iso(created), _iso(created),
                )
            )  # fmt: skip
            if galaxy:
                memberships.append((item_id, galaxy, "seed", _iso(created)))
            chunk_rows.append((item_id, f"{title}\n{sentence}"))
            topics_of.append(topic)
        with transaction(conn):
            conn.executemany(
                "INSERT INTO items (id, type, title, slug, status, idea_stage, path, mime, size_bytes, content_hash,"
                " captured_at, metadata, pinned, open_count, last_opened_at, source_id, created_at, updated_at,"
                " pipeline_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'done')",
                items,
            )
            conn.executemany(
                "INSERT INTO item_projects (item_id, project_id, added_by, added_at) VALUES (?, ?, ?, ?)", memberships
            )
            conn.executemany("INSERT INTO chunks (item_id, ord, kind, text) VALUES (?, 0, 'text', ?)", chunk_rows)
            conn.executemany(
                "INSERT INTO items_fts (item_id, title, tags, meta) VALUES (?, ?, '', '')",
                [(i[0], i[2]) for i in items],
            )
            conn.executemany("INSERT INTO items_trigram (item_id, title) VALUES (?, ?)", [(i[0], i[2]) for i in items])
            stamp = _iso(now)
            model = embedder.split("@", 1)[0] if embedder else None
            digest = embedder.split("@", 1)[1] if embedder and "@" in embedder else None
            for stage in PIPELINE_STAGES:
                status = "done" if stage != "embed" or embedder else "skipped"
                conn.executemany(
                    "INSERT INTO item_stages (item_id, stage, status, model, model_version, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            i[0],
                            stage,
                            status,
                            model if stage == "embed" else None,
                            digest if stage == "embed" else None,
                            stamp,
                        )
                        for i in items
                    ],
                )
            # Links: mostly between items of the same galaxy, like notes that cite each other.
            by_galaxy: dict[str, list[str]] = {}
            for item_id, galaxy, *_rest in memberships:
                by_galaxy.setdefault(galaxy, []).append(item_id)
            link_rows = set()
            for members in by_galaxy.values():
                for _ in range(len(members) // 3):
                    a, b = rng.sample(members, 2) if len(members) > 1 else (members[0], members[0])
                    if a != b:
                        link_rows.add((a, b))
            conn.executemany(
                "INSERT OR IGNORE INTO links (id, from_id, to_id, kind, state, strength, created_by, created_at)"
                " VALUES (?, ?, ?, 'manual', ?, ?, 'seed', ?)",
                [
                    (uuid7(), a, b, "suggested" if rng.random() < 0.2 else "confirmed", round(rng.random(), 2), stamp)
                    for a, b in sorted(link_rows)
                ],
            )
        if embedder:
            _write_vectors(vault, embedder, dim, [i[0] for i in items], [i[1] for i in items], topics_of, rng)
        return {"items": count, "links": len(link_rows), "seconds": round(time.monotonic() - started, 1)}
    finally:
        dbs.close()


def _write_vectors(
    vault: Vault, embedder: str, dim: int, ids: list[str], types: list[str], topics: list[str], rng: random.Random
) -> None:
    """One vector per item: its topic's direction plus noise, so the Semantic layout clusters by topic."""
    import numpy as np

    from universe_vault.vectors import VectorRow, VectorStore, table_name

    name, _, digest = embedder.partition("@")
    gen = np.random.default_rng(rng.randrange(2**32))
    centres = {t: gen.standard_normal(dim) for t, _s, _p in TOPICS}
    store = VectorStore(vault.vectors)
    table = table_name(name, digest)
    now = _iso(datetime.now(UTC))
    rows = []
    for n, (item_id, item_type, topic) in enumerate(zip(ids, types, topics, strict=True)):
        v = centres[topic] + 0.6 * gen.standard_normal(dim)
        v = v / (np.linalg.norm(v) or 1.0)
        rows.append(VectorRow(n + 1, item_id, item_type, now, [float(x) for x in v]))
    store.add_many(table, rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("vault", help="an empty folder to use as a scratch vault")
    parser.add_argument("--count", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--embedder", help="write vectors for this embedding model, as name@digest (see System → Search models)"
    )
    parser.add_argument("--dim", type=int, default=768, help="vector size of that model (nomic-embed-text: 768)")
    args = parser.parse_args()
    result = generate(Path(args.vault).resolve(), args.count, seed=args.seed, embedder=args.embedder, dim=args.dim)
    print(f"Seeded {result['items']:,} items and {result['links']:,} links in {result['seconds']} s")
    print(f"Next: set UNIVERSE_VAULT_DIR={Path(args.vault).resolve()} and start UNIVERSE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
