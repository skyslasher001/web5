# Ideas: a smoother, well-running, more intelligent universe

A ranked backlog of ideas toward the owner's two standing goals — the universe should feel **smooth and calm**
(SPEC §16, §24) and behave like a **brain** (SPEC §10, [VISION-neural-universe.md](VISION-neural-universe.md)).
This is a proposal to pick from, not a plan of record. Each idea maps to a phase, with effort, risk and flags,
and whether it is safe to pull forward **now** without disturbing the delivered-and-review-pending phases.

**Recommendation up front:** keep one-phase-at-a-time. Phase 6 (Research) is next after Phase 5 is approved; the
big intelligence ideas belong to **Phase 9 (brain layer)** — that phase exists for exactly this. Pulling one or
two small items forward is fine (the owner already did this with signal pulses and smooth zoom in Phase 4); doing
a whole phase early is not. A short **safe-now** subset is marked, and I'll build whichever of those you green-light.

Already built (so these aren't proposed): smooth mode + automatic quality step-down on dropped frames, the
Web-Worker layout, smooth cursor-directed zoom, LRU texture eviction, batched query refresh (Phase 4); the
governor that pauses background work (Phase 2); link-firing recording (`link_activity`), signal pulses and probes
flying the link paths (Phase 4); System Vitals (Phase 5).

## Smoothness — responsiveness and calm

| # | Idea | Why it helps | Phase | Effort | Risk | Safe now? |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | **Interaction-aware governor.** When the owner is actively navigating or typing, the renderer signals "busy" and the governor yields background jobs (ingest, embeds, layout recompute) harder, then resumes on idle. | Kills the main cause of stutter: heavy background work during interaction. | 9 / polish | M | M (touches governor + renderer) | after a pick |
| S2 | **Viewer prefetch.** On hover/select, prefetch the item's viewer payload and nearest neighbours. | Opening an item feels instant. | 4 polish | S | L (additive prefetch) | ✅ candidate |
| S3 | **More off-main-thread.** Move scene-data transforms and search-result ranking into the existing worker. | Fewer frame hitches on big result sets. | 4 polish | M | M | after a pick |
| S4 | **Parallel warm start.** Warm the embedding model and the first items page concurrently at launch. | Shorter cold start; the search bar goes live sooner. | polish | S | L–M | ✅ candidate |
| S5 | **Perf HUD overlay** (toggle): live FPS, frame time, draw calls, job queue. | Directly serves "well running" and the pending `pnpm bench:universe` tuning on the owner's GPU. | polish | S | L (additive, off by default) | ✅ recommend first |
| S6 | **Continuous adaptive LOD.** Drive the visible star/detail budget from measured frame time instead of discrete presets only. | Steadier frame rate across scenes without manual preset changes. | 4 polish | M | M (renderer hot path) | after a pick |

## Intelligence — brain-like behaviour

Most of these are the parked items in [VISION-neural-universe.md](VISION-neural-universe.md) §2, which the owner
already slotted to Phase 9. Listed so they're not forgotten and so a specific one can be pulled forward on request.

| # | Idea | Why it helps | Phase | Effort | Risk | Safe now? |
| --- | --- | --- | --- | --- | --- | --- |
| I1 | **Spreading activation** (VISION #4). Select/search spreads activation 1–2 hops along strong links; related items prime (faint glow) and get a small ranking boost. | "Brings back the thing next to the thing you asked for" — the core neural recall feel. Uses `link_activity`, already recorded. | 9 | M | M | Phase 9 |
| I2 | **Cluster zoom level** (VISION #5). Universe → Galaxy → **Cluster** → System → Item, clusters named by the local model. | The smooth zoom always has something meaningful at every distance. | 9 (or 4-polish without names) | M–L | M | Phase 9 |
| I3 | **Dream replay** (VISION #6). The morning brief replays yesterday's strongest new pathways at high speed. | Memory consolidation you can watch. Needs the brief (Phase 9). | 9 | M | L | Phase 9 |
| I4 | **Visible working memory** (VISION #7). The current task's context as a small lit constellation you can add to or clear. | Makes the agents' "mind" legible and steerable. | 9 | M | M | Phase 9 |
| I5 | **System state as body signals** (VISION #8). Energy (budget/load), pain (errors → fly to Forge), immune response (Sentinel). | Turns the already-measured Vitals into felt, living signals. Partly in Vitals now. | 5 → 9 | S–M | L | small viz could be pulled forward |
| I6 | **Pathway strengthen + decay now.** Start computing decayed link strength from `link_activity` (data is already collected) so Phase 9 opens with real history. | Phase 9's Hebbian links work better with months of history. | 9 (data now) | S | L (a background compute job) | Phase 9 (data already accruing) |
| I7 | **Co-activation auto-links** (VISION #1 extended). Two items that keep firing together without a link get a dashed "suggested" filament. | Auto-linking learned from behaviour, not just embeddings. | 9 | M | M | Phase 9 |
| I8 | **Vector memory recall.** Agent memory is keyword-only (FTS5) today; add semantic recall. | Agents remember by meaning, not just words — "highly intelligent". | 9 | M | M | Phase 9 |
| I9 | **Adaptive routing + effort.** Core picks model tier and reasoning effort by task complexity (large tier for synthesis, fast tier for trivial). | More capability where it matters, less cost/latency where it doesn't. | 11 (heuristics could come earlier) | M | M | after a pick |

## How I'd proceed

1. **Phase 5 first:** the readiness audit is running; its confirmed findings get fixed before anything here.
2. **Phase 6 next**, after you approve Phase 5 ([PHASE-6-PLAN.md](PHASE-6-PLAN.md)).
3. **Phase 9** absorbs the intelligence ideas (I1–I8) — that's the brain layer's whole purpose.
4. **Safe-now subset** you can green-light without disturbing the review-pending phases: **S5 (perf HUD)** first —
   it's additive, off by default, and helps the GPU bench you still owe us — then **S2 (viewer prefetch)** and
   **S4 (warm start)**. Each would ship with tests and stay behind the existing quality/settings where relevant.
   Say which you want and I'll build them; otherwise they wait their phase.
