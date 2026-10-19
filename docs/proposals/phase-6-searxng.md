# Proposal: Phase 6 SearXNG sidecar — a private metasearch container, gated by the supervisor

Status: **proposed, and gated on your container-runtime decision.** Nothing is applied. Research already works
without this (the default search path is a gated httpx request to a keyless HTML endpoint); SearXNG is the
better, more neutral, opt-in path.

Design: [ADR-0015](../adr/0015-phase-6-research.md). Open questions: [PHASE-6-PLAN.md](../PHASE-6-PLAN.md) §"Decisions needed".

## Why this needs you

Two reasons it isn't just applied like the rest of Phase 6:

1. **It touches the protected core.** Running and stopping a container is the supervisor's job
   (`services/supervisor/**`, protected, standard-library only). A Forge-style change there must arrive as a
   patch you apply, after review.
2. **It needs a container runtime that may not exist yet.** SearXNG runs as a Podman (or Docker) container on
   WSL2. Until you confirm that's installed (open question #1), there's nothing to test the container lifecycle
   against — in CI there is no container runtime at all. So this is a reviewed **design + code sketch**, and the
   final patch is produced and scratch-worktree-tested the moment you confirm the runtime.

Core already has everything on its side: `SearxngProvider` (talks to the container over loopback as JSON through
the egress gate), the `research_searxng_enabled` / `research_searxng_url` settings (off by default; the URL must
be loopback), and the provider selection in `research_tools.py`. Turning the flag on with no container running
simply fails the search and falls back — so this patch is what makes the flag useful.

## The egress gap, and how this closes it

SearXNG makes its **own** upstream requests to search engines. Those do **not** pass through our egress gate, so
the gate's offline switch and kill switch can't see them. Three mitigations, applied together (ADR-0015):

- **Loopback only.** The container binds `127.0.0.1` and is reachable only from this machine; Core talks to it
  through the gate like any loopback service.
- **The supervisor pauses the container on offline / kill.** When offline mode or the kill switch is engaged,
  the supervisor stops (or pauses) the SearXNG container, so it cannot reach out while you believe the app is
  sealed. It restarts it when you clear both.
- **ddgs-free gated default.** When you want strict, provable gating, leave SearXNG off: the default provider is
  a gated httpx request, every byte of which the gate sees and logs.

## What the patch adds (protected core)

| Where | What |
| --- | --- |
| `services/supervisor/.../searxng.py` (new) | A managed sidecar: detect the runtime (`podman`, else `docker`), `run`/`stop`/`pause`/`unpause` an unmodified `searxng/searxng` image published on `127.0.0.1:<port>`, with a generated secret and a minimal settings volume. Standard library only (`subprocess`, like the existing process management). |
| `services/supervisor/.../supervisor.py` | Start the sidecar on demand when `research_searxng_enabled`; a health check (loopback GET) with backoff; include it in the services the System panel shows. |
| the supervisor's offline / kill handling | On engage → `stop`/`pause` the container; on release → start it again. This is the decisive mitigation for the egress gap. |
| `services/supervisor/.../config.py` | `UNIVERSE_RESEARCH_SEARXNG`, `UNIVERSE_RESEARCH_SEARXNG_PORT`, and the image tag, mirrored from Core's settings. |
| `tests/protected/test_searxng.py` (new) | The lifecycle decision logic (which runtime, the run/stop/pause commands, the offline→stop and release→start transitions) tested without a real container by faking the `subprocess` runner; a skipped integration test that runs the real container when a runtime is present. |

No AGPL code enters our tree: SearXNG runs **unmodified** as a separate service, talked to over HTTP
(ADR-0008 §isolated services).

## To decide

1. **Runtime:** is Podman + WSL2 (or Docker) installed? If yes, I produce and scratch-test the patch above. If
   not, Research stays on the gated-httpx default and this waits.
2. **Pause vs stop** on offline/kill: *pause* is faster to resume but keeps the container resident; *stop* frees
   it fully. Recommended: **stop** on the kill switch (hard seal), **pause** on plain offline mode.
3. **Engines** to enable in SearXNG's settings (privacy vs coverage) — a settings-volume detail, easy to change.

## What to look at (when the patch exists)

- The offline/kill → container transition: that nothing can reach the network through SearXNG while the app is
  sealed.
- That the image is pinned and run unmodified, bound to loopback, with no volume exposing your data.
