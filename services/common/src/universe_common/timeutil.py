"""Timestamps are ISO-8601 UTC strings with millisecond precision."""

from datetime import UTC, datetime


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
