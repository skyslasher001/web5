"""File types, safe vault paths, natural-language filters, text extraction and chunking."""

from datetime import date
from pathlib import Path

import pytest
from universe_vault.extract import CHUNK_MAX, ExtractionError, Section, chunk_sections, extract_text
from universe_vault.filetypes import detect_type
from universe_vault.layout import Vault, VaultPathError, safe_filename, slugify
from universe_vault.query import Project, parse

from tests.support import files

TODAY = date(2026, 10, 13)  # a Tuesday
PROJECTS = [
    Project("p-ember", "Ember Wolf Acquisitions", "ember-wolf-acquisitions"),
    Project("p-devmind", "DevMind", "devmind"),
]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("notes.md", "note"),
        ("IMG_2041.JPG", "photo"),
        ("Screenshot 2026-10-12 at 9.41.png", "screenshot"),
        ("deal.pdf", "pdf"),
        ("budget.xlsx", "spreadsheet"),
        ("take3.wav", "audio"),
        ("clip.mov", "video"),
        ("main.py", "code_file"),
        ("Dockerfile", "code_file"),
        ("letter.docx", "document"),
        ("archive.zip", "file"),
        ("site.url", "link"),
    ],
)
def test_item_types_come_from_the_file_name(name: str, expected: str) -> None:
    assert detect_type(name) == expected


def test_file_names_are_made_safe_for_windows() -> None:
    assert safe_filename('a<b>:c"d|e?f*.txt') == "a_b__c_d_e_f_.txt"
    assert safe_filename("CON.txt") == "_CON.txt"
    assert safe_filename("trailing. ") == "trailing"
    assert len(safe_filename("x" * 400 + ".pdf")) <= 150
    assert slugify("Parcel 4471 — seller call!") == "parcel-4471-seller-call"


def test_vault_paths_cannot_escape_the_vault(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    vault.ensure()
    assert vault.abs("notes/2026/10/a.md") == (tmp_path / "vault" / "notes/2026/10/a.md").resolve()
    for bad in ("../outside.txt", "notes/../../outside.txt"):
        with pytest.raises(VaultPathError):
            vault.abs(bad)


def test_free_path_never_overwrites(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    (tmp_path / "a.txt").write_text("1")
    assert vault.free_path(tmp_path, "a.txt").name == "a (2).txt"
    assert vault.free_path(tmp_path, "b.txt").name == "b.txt"


# ---------- natural-language filters ----------


def test_type_words_become_filters_and_leave_the_text() -> None:
    parsed = parse("photos of the lake", today=TODAY)
    assert parsed.types == ["photo", "screenshot"]
    assert parsed.text == "of the lake"
    assert [c.kind for c in parsed.chips] == ["type"]


def test_relative_dates() -> None:
    parsed = parse("invoices from last week", today=TODAY)
    assert parsed.date_from is not None and parsed.date_to is not None
    assert parsed.date_from[:10] in ("2026-10-04", "2026-10-05")  # Monday 5th, local midnight in UTC
    assert parsed.text == "invoices from"
    summer = parse("songs last summer", today=TODAY)
    assert summer.date_from is not None and summer.date_from[:7] in ("2026-05", "2026-06")
    assert summer.date_to is not None and summer.date_to[:7] in ("2026-08", "2026-09")
    assert summer.types == ["song", "audio"]


def test_weekday_with_part_of_day() -> None:
    parsed = parse("what did I look at last tuesday afternoon", today=TODAY)
    assert parsed.date_from is not None and parsed.date_to is not None
    assert "2026-10-06" in (parsed.date_from[:10], parsed.date_to[:10])  # a week ago, not today


def test_ambiguous_month_words_and_bare_years_stay_text() -> None:
    assert parse("notes I may need", today=TODAY).date_from is None
    assert parse("budget 2025", today=TODAY).date_from is None
    assert parse("budget 2025", today=TODAY).text == "budget 2025"
    in_year = parse("budget in 2025", today=TODAY)
    assert in_year.date_from is not None and in_year.date_from[:4] in ("2024", "2025")
    march = parse("photos from march 2025", today=TODAY)
    assert march.date_from is not None and march.date_to is not None
    assert "2025-03" in (march.date_from[:7], march.date_to[:7])


def test_projects_by_name() -> None:
    parsed = parse("ember wolf contracts", PROJECTS, today=TODAY)
    assert parsed.project_ids == ["p-ember"] and parsed.text == "contracts"
    assert parse("fix the devmind build", PROJECTS, today=TODAY).project_ids == []  # one word: needs "in"
    assert parse("bugs in devmind", PROJECTS, today=TODAY).project_ids == ["p-devmind"]


# ---------- extraction ----------


def test_every_document_format_yields_text(tmp_path: Path) -> None:
    files.write_pdf(tmp_path / "a.pdf", ["Parcel 4471 purchase agreement", "Lake house details"], title="Deal")
    files.write_docx(tmp_path / "b.docx", "Pricing tiers", ["Tier one costs nine dollars."])
    files.write_xlsx(tmp_path / "c.xlsx", {"Budget": [["Item", "Cost"], ["Survey", 450]]})
    files.write_pptx(tmp_path / "d.pptx", [("Roadmap", "Ship the vault in Q4")])
    (tmp_path / "e.md").write_text("---\ntitle: Seller call\n---\nOwner wants out by November.\n")
    (tmp_path / "f.html").write_text("<title>T</title><style>x{}</style><p>Hello <b>web</b></p><script>no()</script>")
    (tmp_path / "g.csv").write_text("name,city\nSam,Austin\n")
    (tmp_path / "h.json").write_text('{"owner": "Sam", "parcel": 4471}')

    def text(name: str) -> str:
        return "\n".join(s.text for s in extract_text(tmp_path / name).sections)

    pdf = extract_text(tmp_path / "a.pdf")
    assert [s.page for s in pdf.sections] == [1, 2] and "Lake house" in pdf.sections[1].text
    assert pdf.extra is not None and pdf.extra["pdf_title"] == "Deal"
    assert "nine dollars" in text("b.docx")
    assert "Survey | 450" in text("c.xlsx")
    assert "Ship the vault" in text("d.pptx")
    assert text("e.md") == "Owner wants out by November."  # frontmatter is metadata, not body
    assert text("f.html") == "Hello web"  # no script or style
    assert "Sam | Austin" in text("g.csv")
    assert "parcel: 4471" in text("h.json")


def test_binary_files_are_refused(tmp_path: Path) -> None:
    (tmp_path / "blob.dat").write_bytes(bytes(range(256)) * 20)
    with pytest.raises(ExtractionError):
        extract_text(tmp_path / "blob.dat")


def test_chunks_respect_size_and_pages() -> None:
    long_paragraph = "word " * 1200
    chunks = chunk_sections([Section("Intro paragraph.\n\n" + long_paragraph, page=1), Section("Page two.", page=2)])
    assert all(len(c.text) <= CHUNK_MAX for c in chunks)
    assert chunks[-1].page == 2 and chunks[-1].text == "Page two."
    assert {c.page for c in chunks[:-1]} == {1}
