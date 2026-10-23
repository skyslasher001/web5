"""Natural-language filters in a query (SPEC §6): types ("photos", "the song"), dates ("last summer",
"yesterday", "in March 2025", "Tuesday afternoon") and projects ("ember wolf contracts").

Rule-based and fast (no LLM), so it fits the fast path. Matched words are removed from the text query
and returned as chips the UI shows and lets you delete.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from universe_vault.filetypes import ItemType
from universe_vault.schemas import FilterChip, ParsedQuery

TYPE_WORDS: dict[str, tuple[ItemType, ...]] = {
    "photo": ("photo", "screenshot"),
    "picture": ("photo", "screenshot"),
    "pic": ("photo", "screenshot"),
    "image": ("photo", "screenshot"),
    "screenshot": ("screenshot",),
    "song": ("song", "audio"),
    "music": ("song", "audio"),
    "track": ("song", "audio"),
    "audio": ("audio", "song", "voice_memo"),
    "recording": ("audio", "voice_memo"),
    "voice memo": ("voice_memo",),
    "memo": ("voice_memo",),
    "video": ("video",),
    "movie": ("video",),
    "clip": ("video",),
    "pdf": ("pdf",),
    "document": ("document", "pdf"),
    "doc": ("document", "pdf"),
    "spreadsheet": ("spreadsheet",),
    "sheet": ("spreadsheet",),
    "note": ("note",),
    "idea": ("idea",),
    "code": ("code_file", "code_repo"),
    "script": ("code_file",),
    "link": ("link",),
    "bookmark": ("link",),
}
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name} | {
    name.lower(): i for i, name in enumerate(calendar.month_abbr) if name
}
WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
SEASONS = {"spring": (3, 6), "summer": (6, 9), "fall": (9, 12), "autumn": (9, 12), "winter": (12, 3)}
PARTS_OF_DAY = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 22), "night": (22, 29)}
STOPWORDS = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "from", "with", "by", "and", "or", "my", "me", "i",
    "is", "are", "was", "were", "that", "this", "these", "those", "about", "all", "any", "some", "find", "show",
    "open", "get", "pull", "up", "search", "look", "where", "what", "which", "please", "it", "its",
}  # fmt: skip


@dataclass
class Project:
    id: str
    name: str
    slug: str


@dataclass
class _State:
    text: str
    types: list[ItemType] = field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
    project_ids: list[str] = field(default_factory=list)
    chips: list[FilterChip] = field(default_factory=list)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _local(day: date, hour: int = 0) -> datetime:
    """Midnight (or `hour`) on `day` in this PC's time zone; hours beyond 23 roll into the next day."""
    return datetime(day.year, day.month, day.day).astimezone() + timedelta(hours=hour)


def _month_range(year: int, month: int) -> tuple[datetime, datetime]:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return _local(start), _local(end)


def _cut(state: _State, match: re.Match[str]) -> None:
    state.text = (state.text[: match.start()] + " " + state.text[match.end() :]).strip()


def _set_dates(state: _State, start: datetime, end: datetime, label: str) -> None:
    state.date_from, state.date_to = start, end
    state.chips.append(FilterChip(kind="date", label=label, value=f"{_iso(start)}..{_iso(end)}"))


_WEEKDAY_RE = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def _dates(state: _State, today: date) -> None:
    """Find the first date expression, remove it from the text and set the range."""

    def g(match: re.Match[str], index: int) -> str:
        return (match.group(index) or "").lower().strip()

    def relative(m: re.Match[str]) -> tuple[datetime, datetime]:
        word, unit = g(m, 1), g(m, 2)
        if unit == "week":
            monday = today - timedelta(days=today.weekday())
            start = monday - timedelta(days=7) if word == "last" else monday
            return _local(start), _local(start + timedelta(days=7))
        if unit == "month":
            year, month = today.year, today.month
            if word == "last":
                year, month = (year - 1, 12) if month == 1 else (year, month - 1)
            return _month_range(year, month)
        year = today.year - (word == "last")
        return _local(date(year, 1, 1)), _local(date(year + 1, 1, 1))

    def last_n(m: re.Match[str]) -> tuple[datetime, datetime]:
        days = int(g(m, 2)) * {"day": 1, "week": 7, "month": 30, "year": 365}[g(m, 3)]
        return _local(today - timedelta(days=days - 1)), _local(today + timedelta(days=1))

    def season(m: re.Match[str]) -> tuple[datetime, datetime]:
        word, name = g(m, 1), g(m, 2)
        start_m, end_m = SEASONS[name]
        if name == "winter":  # Dec–Feb; "last winter" is the most recent one that has started
            year = today.year if today.month == 12 else today.year - 1
            if word == "last" and today.month in (12, 1, 2):
                year -= 1
            return _local(date(year, 12, 1)), _local(date(year + 1, 3, 1))
        year = today.year
        if word == "last" and today.month < end_m:
            year -= 1  # "last summer" means the most recent summer that has ended
        return _local(date(year, start_m, 1)), _local(date(year, end_m, 1))

    def month(m: re.Match[str]) -> tuple[datetime, datetime]:
        number = MONTHS[g(m, 1)]
        year = int(g(m, 2)) if g(m, 2) else (today.year if number <= today.month else today.year - 1)
        return _month_range(year, number)

    def weekday(m: re.Match[str]) -> tuple[datetime, datetime]:
        back = (today.weekday() - WEEKDAYS[g(m, 2)]) % 7
        if back == 0 and g(m, 1) == "last":
            back = 7
        day = today - timedelta(days=back)
        if g(m, 3):
            start_h, end_h = PARTS_OF_DAY[g(m, 3)]
            return _local(day, start_h), _local(day, end_h)
        return _local(day), _local(day + timedelta(days=1))

    def year(m: re.Match[str]) -> tuple[datetime, datetime]:
        value = int(g(m, 1))
        return _local(date(value, 1, 1)), _local(date(value + 1, 1, 1))

    patterns: list[tuple[str, Any]] = [
        (r"\btoday\b", lambda m: (_local(today), _local(today + timedelta(days=1)))),
        (r"\byesterday\b", lambda m: (_local(today - timedelta(days=1)), _local(today))),
        (r"\b(this|last)\s+(week|month|year)\b", relative),
        (r"\b(last|past)\s+(\d{1,3})\s+(day|week|month|year)s?\b", last_n),
        (r"\b(last|this)\s+(spring|summer|fall|autumn|winter)\b", season),
        (rf"\b(?:on\s+)?(last\s+)?({_WEEKDAY_RE})(?:\s+(morning|afternoon|evening|night))?\b", weekday),
        # Months and bare years only count with a preposition or a year ("may" and "2025" are often just words).
        (rf"\b(?:in|during|from|since)\s+({_MONTH_RE})\b(?:\s+((?:19|20)\d{{2}}))?", month),
        (rf"\b({_MONTH_RE})\s+((?:19|20)\d{{2}})\b", month),
        (r"\b(?:in|during|from|since)\s+((?:19|20)\d{2})\b", year),
    ]
    for pattern, resolve in patterns:
        match = re.search(pattern, state.text, re.IGNORECASE)
        if match is None:
            continue
        try:
            start, end = resolve(match)
        except (KeyError, ValueError):
            continue
        _cut(state, match)
        _set_dates(state, start, end, match.group(0).strip())
        return


def _types(state: _State) -> None:
    for phrase in sorted(TYPE_WORDS, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(phrase)}(?:e?s)?\b", re.IGNORECASE)
        match = pattern.search(state.text)
        if match is None:
            continue
        for item_type in TYPE_WORDS[phrase]:
            if item_type not in state.types:
                state.types.append(item_type)
        state.chips.append(FilterChip(kind="type", label=match.group(0), value=",".join(TYPE_WORDS[phrase])))
        _cut(state, match)


def _projects(state: _State, projects: list[Project]) -> None:
    for project in sorted(projects, key=lambda p: len(p.name), reverse=True):
        words = project.name.lower().split()
        names = {project.name.lower(), project.slug.replace("-", " ")}
        if len(words) >= 2:
            names.add(" ".join(words[:2]))
            pattern_names = sorted(names, key=len, reverse=True)
            regex = rf"\b(?:project\s+)?({'|'.join(re.escape(n) for n in pattern_names)})\b"
        else:
            # A one-word project name only counts when it's clearly meant as a project ("in devmind").
            regex = rf"\b(?:in|from|for|project)\s+({re.escape(project.name.lower())})\b"
        match = re.search(regex, state.text, re.IGNORECASE)
        if match is None:
            continue
        state.project_ids.append(project.id)
        state.chips.append(FilterChip(kind="project", label=project.name, value=project.id))
        _cut(state, match)


def parse(query: str, projects: list[Project] | None = None, *, today: date | None = None) -> ParsedQuery:
    state = _State(text=" ".join(query.split()))
    _projects(state, projects or [])
    _dates(state, today or datetime.now().date())
    _types(state)
    text = " ".join(state.text.split())
    return ParsedQuery(
        text=text,
        types=state.types,
        date_from=_iso(state.date_from) if state.date_from else None,
        date_to=_iso(state.date_to) if state.date_to else None,
        project_ids=state.project_ids,
        chips=state.chips,
    )


def terms(text: str) -> list[str]:
    """Words worth matching: no stopwords, no punctuation."""
    return [w for w in re.findall(r"\w+", text.lower()) if w not in STOPWORDS]
