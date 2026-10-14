# 0012 — Phase 4 universe: scene data, layouts, renderer, Lite mode and viewers

- Status: Accepted
- Date: 2026-10-13
- Flags: architecture, performance

## Context

Phase 4 (SPEC §25) turns the Phase 1 starfield into the real universe: every item drawn by type (SPEC §7 celestial mapping), four layouts with animated transitions, zoom levels with level of detail, the complete HUD, item viewers, agent probes, constellation results, quality presets and a 2D Lite mode. Done when a 50k-item seed dataset hits the FPS budget (60 FPS at 50k on recommended hardware, 30 FPS at 10k in Lite) and search flies the camera to results.

## Decision

1. **Scene data.** `GET /universe/items` returns items as columns (ids, types, titles, primary galaxy, dates, open counts, status, idea stage), paged at 10k rows, with `since` for incremental updates after `item.*` events. The renderer keeps them in typed arrays, never one JS object per item.
2. **Links.** A `links` table (migration 0004): from, to, kind (`wikilink`, `manual`, `agent`), state (`confirmed`, `suggested`), strength. Notes' `[[Title]]` links are resolved when a note is indexed, which also gives note backlinks. You can link and unlink items by hand. Auto-suggested links remain Phase 9.
3. **Layouts.**
   - Project, Time and Graph are computed in a Web Worker in the UI from the scene data: deterministic (seeded by item id), cheap, and recomputed when the data changes. Graph runs `d3-force-3d` on the linked subgraph plus galaxy hubs; unlinked items rest in a dim outer shell.
   - **Semantic is computed in the vault worker process** and cached per embedding model (`layout_cache`). Each item's vector is the mean of its chunk vectors. The steps: PCA to 32 dimensions with numpy, k-means into √(n/2) clusters, cluster centres placed in 3D by PCA, then items around their centre. **Δ ARCHITECTURE §2.1** planned `umap-learn`. It needs numba, llvmlite, scikit-learn and pynndescent (≈200 MB) and takes minutes at 50k. This approach takes seconds, adds no dependency and still clusters by meaning, but keeps less of the local structure than UMAP. While the layout is computing (or without an embedding model), Semantic shows the Project layout and says so.
4. **Renderer.**
   - **All items are one `THREE.Points` draw call** with a custom shader. Each point draws its type's shape procedurally (star, ringed planet, pulsing pulsar, moon, station, satellite, nebula), so colour is always paired with a shape. Point size grows with importance (opens, recency), and forgotten items are dimmer.
   - Two position buffers (from → to) and one uniform animate layout changes on the GPU, with no per-frame CPU work.
   - Galaxies are sprites, sized by item count and brightened by recent activity.
   - **Level of detail** follows camera distance:
     - at Universe zoom, galaxy sprites and their labels;
     - at Galaxy zoom, items plus labels for the nearest few;
     - at System zoom, an item and its linked neighbours, with filaments and photo planets (sphere meshes with the thumbnail as surface, the nearest 24 only);
     - at Item zoom, the viewer opens.
   - **GPU picking:** on hover or click, the points are rendered once into a 1×1 render target with ids encoded as colours.
   - Camera flights last 600–1200 ms scaled by distance, ease-in-out-cubic; with reduced motion they are instant jumps. Controls are three's `OrbitControls`, which ships with three.
   - Filaments are line segments; suggested links are dashed. Inbox items without a galaxy, captured in the last 7 days, are comets at the edge. Agent probes fly to the item or galaxy their current step names (`agent.step` now carries a `target`); with the kill switch engaged they park at the Core.
   - **Constellation results:** a search in the universe view dims everything else, numbers the results 1…N, joins them with faint lines and flies the camera to frame them. A single strong result is flown to and selected.
5. **Quality presets** Ultra / High / Balanced / Lite.
   - Ultra and High add bloom (`UnrealBloomPass` from three's examples) and a higher pixel ratio, more labels and more near meshes. Balanced has no bloom and a 1× pixel ratio.
   - The first preset is picked from hardware detection (a discrete GPU → High, an integrated GPU → Balanced, no WebGL → Lite). The live frame budget then steps it down, never silently.
   - **Lite is a 2D WebGL graph**: `sigma` 3.0.3 with `graphology` 0.26.0. It uses the same positions flattened to 2D, the same colours and the same HUD.
6. **Item viewers** open as a glass card over the dimmed universe at Item zoom.
   - Notes: a Markdown editor with live preview (`marked` 18.0.14, sanitized by `DOMPurify` 3.4.16) and backlinks. Saving writes a new version.
   - PDFs: `pdfjs-dist` 6.3.289, plus "Ask Core about this".
   - Code: `highlight.js` 11.12.0, plus open in your editor.
   - Photos: with EXIF and similar photos (vector neighbours).
   - Audio and video: the native players, with a waveform drawn from Web Audio.
   - Links, and project dashboards: goals, status, items by type, recent items, and agent reports from the audit log.
7. **50k seed.** `scripts/seed_universe.py` writes synthetic items, galaxies, links and vectors straight into an empty vault's database. Running them through the pipeline would take hours. It refuses a vault that already has items.

Checked for this decision (2026-10-13), all permissive, each pinned to the newest release at least two weeks old (newer ones were days old):
- MIT: sigma 3.0.3 (4.0.0 is from 2026-10-08), graphology 0.26.0, marked 18.0.14, d3-force-3d 3.0.6.
- MPL-2.0 OR Apache-2.0: DOMPurify 3.4.16.
- Apache-2.0: pdfjs-dist 6.3.289.
- BSD-3-Clause: highlight.js 11.12.0.

## Consequences

- One draw call for every item keeps 50k items cheap. The cost moves into the shader and the picking pass, which is a second, tiny draw.
- The semantic layout is an approximation. If it clusters badly on real embeddings, `umap-learn` can replace step 3 behind the same endpoint.
- **Flag (performance):** CI renders in software (SwiftShader), so the FPS budget is measured there and reported as measured. The recommended-hardware number has to be measured on your PC.
- Measured in software rendering at 50k (PHASE-4.md): 3D Balanced ≈30 FPS in the Project layout, 3D High ≈4 FPS, Graph layout 11 s, Semantic layout 13.6 s. Software rendering therefore maps to Lite under Auto.
- sigma's z-index sorting is off in Lite: sorting 50k nodes cost about 2 s per frame in software.
- New UI weight: pdf.js is the largest piece. It and highlight.js load only when a viewer needs them.

## Alternatives considered

- **InstancedMesh per type:** real geometry per item, but eight draw calls and much more vertex work at 50k. Real meshes are used only for the nearest photo planets.
- **umap-learn on the backend:** truer local structure, ≈200 MB of native dependencies and minutes per layout (see 3).
- **force-graph / three-forcegraph for Graph and Lite:** couples layout with rendering. sigma keeps rendering separate and is built for large 2D graphs.
- **CodeMirror for the note editor:** better editing and more weight. A textarea with live preview covers the SPEC's editor until slash commands and inline AI actions need more.
