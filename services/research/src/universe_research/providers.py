"""Web search providers (ADR-0015).

Two providers, both talking through a client the caller built from Core's egress gate, so every request is
gated (offline / kill switch) and logged:

- `HttpSearchProvider` — the default. Posts to a keyless HTML search endpoint (DuckDuckGo Lite) and parses the
  results with the standard-library HTML parser. No API key, no extra runtime, every byte through the gate.
- `SearxngProvider` — talks to a self-hosted SearXNG container (loopback) and reads its JSON. Better, more
  neutral results; opt-in, and the container is managed by the supervisor (a protected-core proposal).

We deliberately do not use the `ddgs` library: it makes its own HTTP requests (via `primp`), which would bypass
the egress gate — the one hard rule here. A gated httpx client keeps search inside the gate.
"""

from collections.abc import Awaitable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qs, urlparse

import httpx  # type-only: clients are built by the egress gate and passed in (tests/protected/test_invariants)

DDG_LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchResult":
        return cls(title=data.get("title", ""), url=data.get("url", ""), snippet=data.get("snippet", ""))


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 8) -> Awaitable[list[SearchResult]]: ...


def _clean_url(href: str) -> str:
    """DuckDuckGo Lite wraps results in a redirect (`/l/?uddg=<real url>`); unwrap it to the real target."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


class _DdgLiteParser(HTMLParser):
    """Collects result links (`a.result-link`) and snippet cells (`td.result-snippet`) in document order."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.snippets: list[str] = []
        self._link_href: str | None = None
        self._link_text: list[str] = []
        self._snippet_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        classes = d.get("class", "").split()
        if tag == "a" and "result-link" in classes:
            self._link_href = d.get("href", "")
            self._link_text = []
        elif tag == "td" and "result-snippet" in classes:
            self._snippet_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link_href is not None:
            self.links.append((self._link_href, "".join(self._link_text).strip()))
            self._link_href = None
        elif tag == "td" and self._snippet_text is not None:
            self.snippets.append("".join(self._snippet_text).strip())
            self._snippet_text = None

    def handle_data(self, data: str) -> None:
        if self._link_href is not None:
            self._link_text.append(data)
        elif self._snippet_text is not None:
            self._snippet_text.append(data)


def parse_ddg_lite(html: str) -> list[SearchResult]:
    parser = _DdgLiteParser()
    parser.feed(html)
    results: list[SearchResult] = []
    for i, (href, title) in enumerate(parser.links):
        url = _clean_url(href)
        if not url or not title:
            continue
        snippet = parser.snippets[i] if i < len(parser.snippets) else ""
        results.append(SearchResult(title=title, url=url, snippet=snippet))
    return results


@dataclass
class HttpSearchProvider:
    """Default provider: a keyless HTML search endpoint, fetched through the egress gate."""

    client: httpx.AsyncClient
    endpoint: str = DDG_LITE_ENDPOINT
    name: str = "duckduckgo"

    async def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        response = await self.client.post(self.endpoint, data={"q": query})
        response.raise_for_status()
        return parse_ddg_lite(response.text)[:limit]


@dataclass
class SearxngProvider:
    """Self-hosted SearXNG (loopback container), read as JSON. Opt-in; the supervisor runs the container."""

    client: httpx.AsyncClient  # a loopback client whose base_url is the SearXNG container
    name: str = "searxng"

    async def search(self, query: str, *, limit: int = 8) -> list[SearchResult]:
        response = await self.client.get("/search", params={"q": query, "format": "json"})
        response.raise_for_status()
        data = response.json()
        results = []
        for r in data.get("results", [])[:limit]:
            url = r.get("url", "")
            title = r.get("title", "")
            if url and title:
                results.append(SearchResult(title=title, url=url, snippet=r.get("content", "")))
        return results
