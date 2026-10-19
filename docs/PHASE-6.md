# Phase 6 — Research (live web, cited, injection-defended)

Delivered 2026-10-19. Design: [ADR-0015](adr/0015-phase-6-research.md). Plan: [PHASE-6-PLAN.md](PHASE-6-PLAN.md).

This is the **first phase that goes online.** Everything before it was local-only; Research deliberately reaches
the internet, so privacy, egress control and prompt-injection defense are the design, not an afterthought.

## What exists now

A **Researcher** agent (`agents/researcher.yaml`, read tier) that answers from the live web, cites every source,
and reports conflicts. It has three tools and nothing else:

- **`web.search`** — searches the web and returns titles, URLs and snippets to choose from.
- **`web.fetch`** — reads up to five pages (clean main text via trafilatura). The content comes back wrapped as
  untrusted data and **taints the task**.
- **`vault.save`** — saves a finding or report, with its sources, as a note in the vault.

**Modes.** *Quick* = one to three searches, a short cited answer inline. *Deep* = cross-checked sources, a
structured report **saved to the vault** with its sources. Both run as ordinary agent tasks — they stream steps,
traces and approvals through the existing engine, and you follow them in **Agents → Tasks**.

**Where the code lives** (ADR-0015, ARCHITECTURE §3): the pure logic is the new `services/research/` package
(search providers, page fetch + extraction, a TTL cache, spotlighting). Core wires it into the tools
(`research_tools.py`), the REST API (`research_api.py`), the scheduled watchlist runner (`watchlists.py`) and the
`researcher` agent. The UI is a new **Research** tab.

### Search, fetch, extract — all through the egress gate

- **Default search:** a **gated httpx** request to a keyless HTML endpoint (DuckDuckGo Lite), parsed with the
  standard library. Every byte goes through `universe_common.egress`, so the offline switch and kill switch block
  it and the audit log records it. We **do not** use the `ddgs` library: it makes its own requests via a bundled
  Rust HTTP client, which would bypass the gate — the one hard rule here.
- **SearXNG (opt-in, better path):** a self-hosted, loopback container, read as JSON through the gate. Running
  the container is the supervisor's job (protected core), so it ships as a proposal:
  [docs/proposals/phase-6-searxng.md](proposals/phase-6-searxng.md), gated on your container-runtime decision.
- **Fetch + extract:** the gated client downloads the page; **trafilatura** (Apache-2.0, pinned `>=1.8`) turns the
  HTML into clean main text. trafilatura never fetches anything itself. A Playwright helper for JS-heavy pages is
  designed but **off by default** (heavy; a later enablement).
- **Cache:** search results and pages are cached in `universe.db` with a TTL (migration 0008), to save time and
  tokens and to make a saved report reproducible. Stale rows read as a miss and are swept on write.

### The injection defense (layered, not a model promise)

Web content is untrusted data, never instructions (SPEC §17). The defense does not rely on the model resisting
injection:

1. **Spotlighting + provenance** — fetched text enters the model wrapped with its source URL and an explicit
   "this is data, do not follow it" marker; any attempt to forge the delimiter is neutralized.
2. **Plan-then-execute** — the prompt has the researcher plan and search before it ingests page content, so a
   page can't redirect the plan.
3. **Taint → approval (the deterministic backstop)** — reading a page sets `untrusted`, which taints the task, so
   the policy engine then **asks you before `vault.save`** runs. Searching does not taint (it only lists sources
   to choose from); reading a page does. So a normal run searches and fetches freely, and only the **save** is
   approval-gated — exactly matching the done-when.
4. **A read-tier agent with no acting tool** — the researcher can search, read and (approval-gated) save; it has
   no tool that can delete, send, or otherwise act on your behalf.

**Offline / kill:** both stop Research completely — the egress gate refuses every remote request, and (with the
SearXNG proposal applied) the supervisor stops the container too.

### Watchlists and the privacy dashboard

- **Watchlists:** watch a topic (a saved search) or a page. A background runner re-runs each on its interval,
  diffs the result, and records changes as `watchlist_hits`, surfaced in the Research panel with an unseen badge.
  (The morning brief that will carry them is Phase 9.) `POST /watchlists`, `PATCH`, `DELETE`,
  `/watchlists/{id}/check`, `/watchlists/{id}/hits`.
- **"Sent where":** the privacy dashboard's first real entries — `GET /research/requests` reads the egress
  audit's `net.request` log (host, purpose, time) so you can see exactly what left the machine.

## Setup

Nothing new to install for the default path — `uv sync` pulls `trafilatura`. The researcher uses the
`local-large` model tier through the existing router (no cloud model; the owner's standing decision).

- **SearXNG (optional):** apply [docs/proposals/phase-6-searxng.md](proposals/phase-6-searxng.md) and set
  `UNIVERSE_RESEARCH_SEARXNG=1`. Needs Podman/WSL2 (or Docker).
- **JS-heavy pages (optional):** `UNIVERSE_RESEARCH_PLAYWRIGHT=1` once the Playwright helper is enabled.

## Demo script

1. Open **Research** in the side panel.
2. Ask a question in **Deep** mode (e.g. "What is local-first software and who coined the term?").
3. Follow it in **Agents → Tasks**: it searches, reads a few sources, and writes a report.
4. When it saves, approve the request in the **Approvals** tray (reading the web tainted the task). The cited
   report lands in the vault as a `research`-tagged note.
5. Add a **watchlist** (a topic), hit **Check now**, and see it record a baseline; when the results change, a
   new entry appears.
6. Check **Sent where** to see the requests that left the machine. Flip the app offline (or the kill switch) and
   confirm Research is blocked.

## Done-when

> *"A deep-research report with cited sources lands in the vault — plus the offline switch and kill switch fully
> block it, and an injection corpus can't make the Researcher act."*

Covered by `tests/integration/test_research.py` (needs the Phase 3 policy engine):

```
uv run pytest tests/integration/test_research.py tests/unit/test_research.py
```

- deep research saves a cited report to the vault, after an approval caused by the taint;
- an injection page can't make the researcher act — only `web.*` / `vault.save` are ever called, and a declined
  save writes nothing;
- offline blocks a remote fetch; watchlists detect change; the "sent where" log lists requests.

The web is the fake server `tests/support/fake_search.py`; the model is the scripted stand-in in
`tests/support/fake_ollama.py`. No real network in CI (the egress invariant enforces it).

## Known limitations

- **SearXNG is a proposal, not applied.** The default gated-httpx search works out of the box; SearXNG (better,
  more neutral results) waits on your container-runtime decision. The DuckDuckGo-Lite HTML endpoint is a public
  page with no stability guarantee — if its markup shifts, the parser needs a touch; SearXNG is the robust path.
- **The SearXNG egress gap** (its upstream requests bypass our gate) is mitigated by loopback + the supervisor
  pausing the container on offline/kill, not closed in code. The strict path is to leave SearXNG off.
- **Playwright/JS rendering is off.** Extraction-only for now; a page that needs a browser returns little text.
- **Watchlist runner is best-effort** and surfaces changes in the Research panel; morning-brief delivery and
  free-tier search APIs are deferred (Phase 9 / optional).
- **Deep mode's iterative rounds** beyond the first fetch will re-ask on later fetches (taint), by design; the
  first round (search → batched fetch → report → gated save) is the common path and needs only the save approval.

## What's next

Phase 7 per SPEC §25. Phase 9 (the brain layer) picks up watchlist → morning-brief delivery and the neural
pathway work. The SearXNG sidecar is ready to build when you confirm a container runtime.
