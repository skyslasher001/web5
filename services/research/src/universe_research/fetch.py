"""Fetch a web page through a gated client and extract its main text (ADR-0015).

The client is built by Core's egress gate and passed in, so the download is offline/kill gated and logged.
Redirects are followed here, one hop at a time, so every hop is checked: only http(s), and never a loopback,
private or link-local address (a public page must not be able to point the researcher at your router or a
local service). Downloads are capped in size and time. trafilatura turns the HTML into clean main-content
text off the event loop — it only parses bytes we already downloaded, it never fetches anything itself.
"""

import asyncio
import html as _html
import ipaddress
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx  # type-only (tests/protected/test_invariants): the client is created by the egress gate
import trafilatura

# Linear: no lazy `.*?` over the whole page (many unclosed <title> tags made that quadratic).
_TITLE_RE = re.compile(r"<title[^>]*>([^<]*)</title>", re.IGNORECASE)
_TITLE_SCAN = 65_536
_WS_RE = re.compile(r"\s+")

MAX_BYTES = 3_000_000
DEADLINE_S = 45.0  # the whole fetch, redirects included (httpx's timeout is per read)
MAX_REDIRECTS = 5
_TEXT_TYPES = ("text/", "application/xhtml+xml", "application/xml")


class FetchRefused(ValueError):
    """The URL (or a redirect) points somewhere the researcher may not go, or isn't a readable page."""


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str
    status: int
    fetched_at: float
    truncated: bool = False


def page_title(html: str, fallback: str) -> str:
    match = _TITLE_RE.search(html, 0, _TITLE_SCAN)
    if match:
        title = _html.unescape(_WS_RE.sub(" ", match.group(1)).strip())[:300]
        if title:
            return title
    return fallback


def extract(html: str, url: str) -> tuple[str, str]:
    """(title, clean main text). Empty text when there's nothing readable (e.g. a non-HTML page)."""
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_recall=True)
    return page_title(html, url), (text or "").strip()


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def check_target(url: str, *, allow_private: bool = False) -> None:
    """Refuse non-http(s) URLs and hosts that resolve to loopback, private, link-local or reserved addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchRefused(f"only http(s) pages can be read, not {url[:80]!r}")
    if allow_private:
        return
    host = parts.hostname
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, parts.port or 443)
        except OSError as exc:
            raise FetchRefused(f"can't resolve {host}") from exc
        addresses = [str(info[4][0]) for info in infos]
    if not addresses or not all(_public(a) for a in addresses):
        raise FetchRefused(f"{host} is a local or private address; the researcher only reads public pages")


async def fetch_page(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_chars: int = 20_000,
    allow_private: bool = False,
    max_bytes: int = MAX_BYTES,
    deadline_s: float = DEADLINE_S,
    now: Callable[[], float] = time.time,
) -> FetchedPage:
    current = url
    async with asyncio.timeout(deadline_s):
        for _hop in range(MAX_REDIRECTS + 1):
            await check_target(current, allow_private=allow_private)
            async with client.stream("GET", current, follow_redirects=False) as response:
                if response.is_redirect and "location" in response.headers:
                    current = str(response.url.join(response.headers["location"]))
                    continue
                response.raise_for_status()
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(_TEXT_TYPES):
                    raise FetchRefused(f"{current[:80]} is {ctype}, not a readable page")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) >= max_bytes:
                        del body[max_bytes:]
                        break
                html = body.decode(response.encoding or "utf-8", errors="replace")
                final_url, status = str(response.url), response.status_code
                break
        else:
            raise FetchRefused(f"more than {MAX_REDIRECTS} redirects from {url[:80]}")
    title, text = await asyncio.to_thread(extract, html, final_url)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return FetchedPage(
        url=final_url,
        title=title,
        text=text or "(no readable text was extracted from this page)",
        status=status,
        fetched_at=now(),
        truncated=truncated,
    )
