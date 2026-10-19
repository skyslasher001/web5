"""Fetch a web page through a gated client and extract its main text (ADR-0015).

The client is built by Core's egress gate and passed in, so the download is offline/kill gated and logged;
redirects run back through the same hook. trafilatura turns the HTML into clean main-content text — it only
parses bytes we already downloaded, it never fetches anything itself.
"""

import html as _html
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx  # type-only (tests/protected/test_invariants): the client is created by the egress gate
import trafilatura

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str
    status: int
    fetched_at: float
    truncated: bool = False


def page_title(html: str, fallback: str) -> str:
    match = _TITLE_RE.search(html)
    if match:
        title = _html.unescape(_WS_RE.sub(" ", match.group(1)).strip())[:300]
        if title:
            return title
    return fallback


def extract(html: str, url: str) -> tuple[str, str]:
    """(title, clean main text). Empty text when there's nothing readable (e.g. a non-HTML page)."""
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_recall=True)
    return page_title(html, url), (text or "").strip()


async def fetch_page(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_chars: int = 20_000,
    now: Callable[[], float] = time.time,
) -> FetchedPage:
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    final_url = str(response.url)
    title, text = extract(response.text, final_url)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return FetchedPage(
        url=final_url,
        title=title,
        text=text or "(no readable text was extracted from this page)",
        status=response.status_code,
        fetched_at=now(),
        truncated=truncated,
    )
