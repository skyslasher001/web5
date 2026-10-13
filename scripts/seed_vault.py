"""Phase 2 demo helper: make 500 mixed files to drop into UNIVERSE, then time finding every one of them.

    uv run python scripts/seed_vault.py generate C:\\Temp\\seed500          # writes the files + a manifest
    (drag the folder onto the UNIVERSE window and wait for "Indexing" to finish)
    uv run python scripts/seed_vault.py bench C:\\Temp\\seed500-manifest.json --key uk_...

`bench` uses a local API key with the search scope (Vault panel → Local API) and talks to Core on
loopback only. It never touches the vault itself.
"""

import argparse
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for tests.support

from tests.support.seed import generate, write_manifest

DEFAULT_CORE = "http://127.0.0.1:47821"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def cmd_generate(args: argparse.Namespace) -> int:
    dest = Path(args.folder).resolve()
    seeded = generate(dest, args.count, seed=args.seed)
    manifest = dest.with_name(f"{dest.name}-manifest.json")
    write_manifest(seeded, manifest)
    kinds: dict[str, int] = {}
    for f in seeded:
        kinds[f.kind] = kinds.get(f.kind, 0) + 1
    print(f"Wrote {len(seeded)} files to {dest}")
    print("  " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    print(f"Manifest: {manifest}")
    print("Next: drag the folder onto the UNIVERSE window, wait for indexing, then run `bench`.")
    return 0


def _search(core: str, key: str, q: str) -> tuple[list[str], float, float]:
    url = f"{core}/api/v1/search?{urllib.parse.urlencode({'q': q, 'limit': 20})}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})  # noqa: S310 (loopback only)
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        body = json.load(response)
    wall_ms = (time.perf_counter() - started) * 1000
    return [h["item"]["path"] for h in body["hits"]], float(body["took_ms"]), wall_ms


def _p(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def cmd_bench(args: argparse.Namespace) -> int:
    if urllib.parse.urlparse(args.core).hostname not in LOOPBACK:
        print("Refusing: bench only talks to Core on this machine (loopback).", file=sys.stderr)
        return 2
    seeded = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    missed: list[str] = []
    walls: list[float] = []
    for f in seeded:
        paths, _took, wall = _search(args.core, args.key, f["marker"])
        walls.append(wall)
        if not paths or not any(f["marker"] in Path(p).name for p in paths[:1]):
            missed.append(f["path"])
    meaning: list[float] = []
    for query in sorted({f["meaning_query"] for f in seeded}):
        _paths, _took, wall = _search(args.core, args.key, query)
        meaning.append(wall)
    found = len(seeded) - len(missed)
    print(f"Keyword: found {found}/{len(seeded)} at rank 1")
    print(f"  latency ms: median {statistics.median(walls):.0f} · p95 {_p(walls, 95):.0f} · max {max(walls):.0f}")
    print(f"Meaning queries ({len(meaning)}): median {statistics.median(meaning):.0f} ms · max {max(meaning):.0f} ms")
    for path in missed[:10]:
        print(f"  missed: {path}")
    ok = not missed and max(walls + meaning) < 1000
    print("PASS: every file found in under a second" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="write mixed files into an empty folder")
    gen.add_argument("folder")
    gen.add_argument("--count", type=int, default=500)
    gen.add_argument("--seed", type=int, default=7)
    gen.set_defaults(run=cmd_generate)
    bench = sub.add_parser("bench", help="find every generated file through Core's search API")
    bench.add_argument("manifest")
    bench.add_argument("--key", required=True, help="a local API key with the search scope")
    bench.add_argument("--core", default=DEFAULT_CORE)
    bench.set_defaults(run=cmd_bench)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
