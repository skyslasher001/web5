"""Research (Phase 6, ADR-0015): web search, page fetch + clean extraction, a TTL cache and spotlighting.

Pure logic only — no Core or database-of-Core imports. Clients are built by Core's egress gate and passed in,
so every outbound request is gated (offline / kill switch) and logged. Core wires these into the `web.search`,
`web.fetch` and `vault.save` tools of the `researcher` agent.
"""

from universe_research.cache import DEFAULT_TTL_S, ResearchCache
from universe_research.fetch import FetchedPage, extract, fetch_page, page_title
from universe_research.providers import (
    DDG_LITE_ENDPOINT,
    HttpSearchProvider,
    SearchProvider,
    SearchResult,
    SearxngProvider,
    parse_ddg_lite,
)
from universe_research.spotlight import SENTINEL, spotlight

__all__ = [
    "DDG_LITE_ENDPOINT",
    "DEFAULT_TTL_S",
    "SENTINEL",
    "FetchedPage",
    "HttpSearchProvider",
    "ResearchCache",
    "SearchProvider",
    "SearchResult",
    "SearxngProvider",
    "extract",
    "fetch_page",
    "page_title",
    "parse_ddg_lite",
    "spotlight",
]
