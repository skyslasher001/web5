# 0015 — Phase 6: Research (live web, cited, injection-defended)

- Status: Proposed
- Date: 2026-10-14
- Flags: privacy, security, architecture, cost

## Context

SPEC §13 and §25 Phase 6: a Researcher answers from the live web, cites every source, reports conflicts, caches
results, watches topics, and saves findings to the vault. **Done when:** *"a deep-research report with cited
sources lands in the vault."*

This is the **first phase that goes online**. Every prior phase was local-only; Research deliberately reaches
the internet. So privacy, egress control and prompt-injection defense are the crux of the design, not an
afterthought. It builds on things that already exist:

- the **egress gate** (`universe_common.egress`): the only place HTTP clients are made; it enforces the offline
  switch and kill switch, allows loopback, and logs every outbound request through the audit callback;
- the **taint** system (Phase 3, ADR-0011): once untrusted content enters a task's context, `tainted = true`
  and every side-effecting or network tool call then needs the owner's approval;
- the **scheduler** (croniter in Core) for watchlists;
- **vault save + versions + snapshots** (Phase 2) for "save a finding";
- **supervisor sidecar management** (containers started on demand with backoff);
- the designed **offline state** ("status pill plus Researcher greyed out") and the **privacy dashboard**
  ("what was sent where", SPEC §17).

This ADR is **Proposed**: it records the intended design so the work is planned and the owner can decide the
open questions ([PHASE-6-PLAN.md](../PHASE-6-PLAN.md)). It is not Accepted until Phase 6 starts — and Phase 6
starts only after Phase 5 is approved (one phase at a time, SPEC §25).

## Decision

**Where the code lives.** Research logic lives in `services/research/` but runs **inside Core** (like Vision),
reached by a `researcher.yaml` agent. Only **SearXNG** is a separate process (a sidecar container). This mirrors
the "Vision runs in Core, not its own process" precedent (ADR-0001): a fourth process that only forwards bytes
earns nothing.

**Search — two tiers, both gated.**
- **SearXNG** as a **loopback-only sidecar container** (AGPL-3.0, run *unmodified*, talked to over HTTP), the
  supervisor starts it on demand. No AGPL code enters our tree.
- **`ddgs`** (MIT, 9.16.0) as the fallback when no container runtime is present, through our egress client. It
  also covers the common case where the owner hasn't installed Podman/WSL2 yet, so Research works out of the box.
- Free-tier search APIs stay an optional later addition, not a launch dependency.

**Fetch and extract.**
- Our **gated httpx client** fetches result pages (`local_only=False`, audited).
- **trafilatura** (Apache-2.0, 2.3.1) does clean extraction. (It relicensed from GPLv3 to Apache-2.0 at v1.8.0,
  so we pin `>=1.8` — the current 2.3.1 is fine; `readability-lxml` stays a noted fallback.)
- **Playwright** (Apache-2.0, 1.64.0) headless Chromium renders JavaScript-heavy pages, behind a flag and as a
  separate helper — it's heavy (a browser binary) and off unless a page needs it.

**Every outbound request goes through the egress gate and is logged** (SPEC §13). The offline switch and kill
switch must stop Research completely — including the SearXNG container (see the gap below).

**The SearXNG egress gap (security decision).** SearXNG makes its *own* upstream engine requests, which do **not**
pass through our egress gate. Three mitigations, applied together: (a) SearXNG binds to loopback only; (b) the
supervisor **pauses/stops the SearXNG container** when offline mode or the kill switch is engaged, so it can't
reach out while the owner thinks the app is offline; (c) the **`ddgs` path is fully gated** and is the default
when strict gating is wanted — the container is an opt-in the owner turns on for better, more neutral results.
This is flagged for the owner in the plan.

**Injection defense — layered, model-independent at the backstop.** Web content is untrusted data, never
instructions (SPEC §17). The design does not rely on the model resisting injection:
1. **Spotlighting + provenance:** fetched content enters the context wrapped with its source URL and explicit
   "untrusted data, not instructions" delimiters.
2. **Plan-then-execute:** the Researcher plans its searches before ingesting page content, so page text can't
   redirect the plan (the 2026 literature's recommended paradigm for web agents).
3. **Taint → approval (the backstop):** fetching web content taints the task, so any later write (save to the
   vault) or further network call needs the owner's approval. This is human-in-the-loop, not a model promise —
   and the 2026 research consensus is that deterministic/out-of-band controls plus a human backstop are needed
   because adaptive attacks defeat model-only defenses.
4. **No tool calls from page text, read-tier agent:** the Researcher runs at the read permission tier; it has no
   tool that can act on the owner's behalf beyond searching, fetching and (approval-gated) saving.

**Modes.** *Quick* = 1–3 searches, an inline answer with citations. *Deep* = multi-step searches, cross-checked
sources, a structured report **saved to the vault** with page snapshots. Both stream progress like an agent task.

**Cache.** Search results and extracted pages are cached with a TTL (a table in `universe.db` via a migration;
page snapshots in the vault cache dir), to save time and tokens and to make a report reproducible.

**Watchlists.** A scheduled Core job re-queries/re-fetches a topic or page and diffs it; change summaries are
stored. Surfacing them in the **morning brief** is Phase 9 (the brief doesn't exist yet), so until then they
appear in the Research panel.

**API** (matches ARCHITECTURE §5): `POST /research {q, mode}` (streams), `/watchlists` CRUD.

**Model.** Synthesis uses the `local-large` tier through the existing router. No cloud model (the owner's
standing decision; the slot stays off).

## Consequences

- **Privacy (flag):** the first capability that sends anything off the machine. The privacy dashboard's first
  real "sent where" entries are research queries. The offline switch and kill switch gate it, container included.
- **Security (flag):** untrusted web content enters the system. The taint→approval backstop and spotlighting are
  the defense; verification that an injection corpus can't make the Researcher act becomes a required test.
- **Container runtime (flag):** Podman/WSL2 may not be installed. The `ddgs` fallback keeps Research working
  without it; SearXNG is the better, owner-enabled path. No hard dependency on a container at launch.
- **Install size:** Playwright pulls a Chromium build. Kept behind the JS-page flag so the common path stays light.
- **Licenses:** all permissive (trafilatura/Playwright Apache-2.0, ddgs MIT) except SearXNG (AGPL-3.0), which is
  isolated as an unmodified separate service — no copyleft reaches our code (ADR-0008 policy satisfied).
- **Deferred:** watchlist → morning-brief rendering (Phase 9); free-tier API fallbacks (optional); research-grade
  policy engines (CaMeL/FIDES-style) — we rely on taint + approval + spotlighting, which is the deployable backstop.

## Alternatives considered

- **readability-lxml as the primary extractor:** trafilatura is more robust and now Apache-2.0; readability stays
  a fallback note.
- **A cloud search API (Tavily/Bing/Serp) as the primary:** rejected — breaks local-first and $0-by-default, and
  sends every query to a third party. SearXNG + ddgs keep it private and free.
- **Playwright for every fetch:** rejected — too heavy. trafilatura first; Playwright only when a page needs JS.
- **A standalone research microservice process:** rejected — the logic runs in Core; only SearXNG is a sidecar,
  consistent with Vision-in-Core (ADR-0001).
- **Trusting the model to ignore injected instructions:** rejected on the 2026 evidence; the human-in-the-loop
  taint backstop stands in front regardless of model behaviour.
