"""Generates a folder of mixed files for the Phase 2 "done when" (500 files, find any of them in < 1 s).

Every file carries a unique marker word (in its name and, where the format has text, in its content) and
one topic sentence. The marker proves keyword recall per file; the topics give meaning search something
to find with words that never appear in the files (e.g. "dog" finds the files about puppies).
"""

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from tests.support import files

# topic, a sentence written into files, and a query that shares meaning but no words with it.
# The concept pairs are ones tests/support/fake_ollama.py embeds close together.
TOPICS: list[tuple[str, str, str]] = [
    ("pets", "My puppy chased the kitten through the garden all afternoon.", "dog"),
    ("vehicles", "The sedan needs new tyres before the long truck convoy.", "automobile"),
    ("evenings", "We watched the twilight fade over the hills at dusk.", "sunset"),
    ("water", "The river meets the ocean just past the old pond.", "lake"),
    ("bills", "Paid the invoice and filed the receipt with the payment notes.", "bill"),
    ("music", "The chorus of that melody has been stuck in my head.", "tune"),  # "song" is a type filter
    ("deals", "Both sides signed the contract and the deal closed.", "agreement"),
    ("money", "The budget leaves little room once pricing and cost go up.", "finance"),
    ("health", "Booked the clinic so the doctor can review the medicine.", "health"),
]

FILLER = [
    "Notes from the weekly sync",
    "Follow up next Tuesday",
    "Draft attached for review",
    "Remember to back this up",
    "Ideas collected over the weekend",
    "Loose ends to tie up.",
]

WORDS = [
    "amber",
    "birch",
    "cedar",
    "delta",
    "ember",
    "falcon",
    "garnet",
    "harbor",
    "indigo",
    "juniper",
    "kestrel",
    "lumen",
    "meadow",
    "nectar",
    "onyx",
    "pebble",
    "quartz",
    "raven",
    "saffron",
    "tundra",
    "umber",
    "velvet",
    "willow",
    "xenon",
    "yarrow",
    "zephyr",
]

# kind → share of the mix (rounded; the remainder goes to notes)
MIX: dict[str, float] = {
    "md": 0.22,
    "txt": 0.12,
    "pdf": 0.12,
    "docx": 0.08,
    "xlsx": 0.06,
    "pptx": 0.04,
    "csv": 0.06,
    "py": 0.06,
    "jpg": 0.12,
    "png": 0.04,
    "wav": 0.08,
}


@dataclass
class SeedFile:
    path: str
    kind: str
    marker: str
    topic: str
    meaning_query: str
    marker_in_content: bool


def _kinds(count: int) -> list[str]:
    kinds: list[str] = []
    for kind, share in MIX.items():
        kinds += [kind] * round(count * share)
    kinds = kinds[:count]
    kinds += ["md"] * (count - len(kinds))
    return kinds


def _write(path: Path, kind: str, marker: str, sentence: str, filler: str, rng: random.Random) -> bool:
    """Writes one file. Returns whether the marker is inside the content (not only in the name)."""
    body = f"{marker}. {sentence} {filler}."
    match kind:
        case "md":
            path.write_text(f"# {marker.title()} notes\n\n{sentence}\n\n- {filler}\n- ref {marker}\n", encoding="utf-8")
        case "txt":
            path.write_text(body + "\n", encoding="utf-8")
        case "pdf":
            files.write_pdf(path, [f"Report {marker}", sentence, filler])
        case "docx":
            files.write_docx(path, f"Memo {marker}", [sentence, filler])
        case "xlsx":
            files.write_xlsx(path, {"Sheet1": [["ref", "note", "amount"], [marker, sentence, rng.randint(5, 900)]]})
        case "pptx":
            files.write_pptx(path, [(f"Deck {marker}", sentence), ("Next steps", filler)])
        case "csv":
            path.write_text(f"ref,note\n{marker},{sentence}\n", encoding="utf-8")
        case "py":
            path.write_text(f'"""{sentence}"""\n\n\ndef {marker}() -> str:\n    return "{filler}"\n', encoding="utf-8")
        case "jpg":
            files.write_photo(
                path,
                color=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)),
                taken=f"20{rng.randint(15, 25)}:{rng.randint(1, 12):02d}:{rng.randint(1, 28):02d} 12:00:00",
                size=(320, 240),
            )
            return False
        case "png":
            files.write_text_image(path, f"Scan {marker}")
        case "wav":
            files.write_wav(path, title=f"{marker} take", artist="Seed Band", album=sentence[:40], seconds=0.2)
        case _:
            raise ValueError(kind)
    return True


def generate(dest: Path, count: int = 500, *, seed: int = 7) -> list[SeedFile]:
    """Writes `count` mixed files into `dest` (created; must be empty) and describes each one."""
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise FileExistsError(f"{dest} is not empty")
    rng = random.Random(seed)  # noqa: S311 (reproducible test data, not security)
    kinds = _kinds(count)
    rng.shuffle(kinds)
    out: list[SeedFile] = []
    for i, kind in enumerate(kinds):
        marker = f"{WORDS[i % len(WORDS)]}{i:04d}"
        topic, sentence, meaning_query = TOPICS[i % len(TOPICS)]
        folder = dest / topic
        folder.mkdir(exist_ok=True)
        path = folder / f"{marker}-{topic}.{kind}"
        in_content = _write(path, kind, marker, sentence, rng.choice(FILLER), rng)
        out.append(SeedFile(str(path.relative_to(dest)), kind, marker, topic, meaning_query, in_content))
    return out


def write_manifest(seeded: list[SeedFile], path: Path) -> None:
    path.write_text(json.dumps([asdict(f) for f in seeded], indent=1), encoding="utf-8")
