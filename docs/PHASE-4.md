# Phase 4: Universe interface

Status: **delivered 2026-10-14; review fixes, smooth zoom and the agent roster added the same day. Waiting for your review.**

Phase 4 turns the Phase 1 starfield into the universe of your own data. Every item is drawn as what it is (a note is a star, a photo a planet, a song a pulsar, a repository a space station), in your galaxies, by meaning, along time, or as a graph of links. You fly around it, open anything in a viewer that unfolds over it, and search lights up the answers and flies you there. Design decisions are in [ADR-0012](adr/0012-phase-4-universe-renderer.md).

**Done when** (SPEC §25): *"a 50k-item seed dataset hits the FPS budget and search flies the camera to results."* `tests/e2e/universe.spec.ts` seeds 50,000 items and drives the real app:

- **Search flies the camera to results: passes.** A search for one item's unique number, then Enter, plans a 1200 ms flight (the SPEC's maximum) and ends 16 units from the item at System zoom, with the breadcrumb updated. A broad search forms a numbered constellation and frames it.
- **FPS budget: measured, not yet proven on recommended hardware.** The budget is 60 FPS at 50k in 3D on recommended hardware, and 30 FPS at 10k in Lite on minimum hardware. Both assume real graphics hardware. This build machine has no GPU, so it renders in software (SwiftShader), roughly a hundred times slower. The test asserts both budgets whenever a GPU renders, and prints the software numbers otherwise. **Run `pnpm bench:universe` on your PC:** it seeds 50k items, measures every preset and layout, and prints PASS or FAIL against the budget. That's the number that counts.

| Measured here (Linux, 4 cores, SwiftShader, 1280×900) | Result |
| --- | --- |
| Seeding 50,000 items (`scripts/seed_universe.py`) | 34–44 s |
| App open → 50k items loaded and laid out | 17–22 s (the first page shows within a second) |
| `GET /universe/items`, all 50k (5 pages) / `GET /universe/links` (14k) | 0.72 s / 0.20 s |
| Project layout / Graph layout at 50k (Web Worker) | 48 ms / 11 s |
| Semantic layout at 50k (worker process, numpy) | 13.6 s, then cached |
| Hybrid search at 50k | 0.36 s |
| Camera flight to an item | planned 1200 ms, done in 1206–1328 ms (frames are 250 ms apart in software) |
| 3D High, 50k, layout animating | ~4 FPS (software) |
| 3D Balanced, 50k, Project / Time / Graph animating | 30 / 9 / 9 FPS (software) |
| Lite, 50k, zooming with the mouse wheel | 20 FPS to under 1 FPS, varying by run (software) |
| 2D list scrolling with the universe behind it (Phase 2 test) | 60 FPS |

## What you can do now

**Fly around your data**
- **Celestial mapping** (SPEC §7):

  | Item | Shown as |
  | --- | --- |
  | Note | Star |
  | Idea | Nebula → protostar → star, as it matures |
  | Song, audio | Pulsar |
  | Photo | Planet, with the photo as its surface up close |
  | Document, file | Moon or asteroid |
  | Code | Space station |
  | Link | Satellite |
  | Fresh inbox capture | Comet waiting at the edge |
  | Galaxy (project) | Spiral, sized by item count and brightened by recent activity |

  Brightness and size follow how recently and how often you open things, so forgotten items dim. Colour always comes with a shape.
- **Four layouts**, keys `1`–`4`, with animated transitions:
  - **Project:** items in their galaxies.
  - **Semantic:** related things cluster by meaning, even across projects (needs an embedding model).
  - **Time:** a spiral by date, with a time-travel slider that replays your universe growing.
  - **Graph:** force-directed on links between items.
- **Zoom levels:**
  - **Universe:** distant galaxies are sprites.
  - **Galaxy:** select one to fly in.
  - **System:** click an item; the camera flies to it and its links appear as filaments.
  - **Item:** double-click, or **View** in the panel, opens its viewer.

  `Esc` steps back a level, `H` flies home to the Core, and the minimap flies wherever you click.
- **Smooth, scalable zoom** (added after review):
  - Scrolling zooms on a log scale toward whatever is under the cursor, gliding to a stop, from the whole universe down to a single star.
  - Stars fade in and out instead of popping.
  - Zooming into a galaxy is enough to be "in" it: the breadcrumb follows.
  - `+` and `−` keys and a zoom slider in the navigator.
  - Lite mode zooms the same way.
- **Agents fly**: each agent is a probe with its own shape, colour and trail, flying to the item or galaxy its current tool works on. With the kill switch engaged, they all park at the Core.
- **Links**: notes link with `[[Title]]` (Obsidian style). A link to a note that doesn't exist yet connects once it does. You can link any two items by hand. Suggested links show dashed (auto-suggestions arrive in Phase 9).

**Find things**
- **Search in the universe** keeps you in the universe. The results light up, the rest dims, the first nine get numbers, and the camera frames them. **Enter** flies to the best match; **↓** opens the list.
- **Filter chips** under the search bar: types (everything else hides), the selected galaxy, and Date (the Time layout).

**Open things** (glass viewers over the dimmed universe)
- **Notes:** Markdown editor with live preview, backlinks, links and "Link to…". **Ctrl+S** saves a new version. If the note changed elsewhere meanwhile, the save is refused and you're asked to reload; nothing is overwritten.
- **Photos:** EXIF details and similar photos.
- **PDFs:** paged viewer.
- **Code:** syntax highlighting.
- **Audio:** waveform and player.
- **Video:** player.
- **Documents:** the extracted text.

Every viewer has **Ask Core about this**.
- **Galaxy dashboards** (double-click a galaxy, or **Dashboard** in the panel) show:
  - goals and tasks as a checklist;
  - status;
  - a 12-month timeline;
  - items by type and recent items;
  - agent reports (what agents linked here, with their traces).

**Make it fit your machine** (System → Display)
- **Quality: Auto, Ultra, High, Balanced, or Lite (a 2D graph).**
  - Auto picks from your graphics card: a discrete GPU gets High, integrated graphics Balanced, software rendering Lite.
  - If frames keep dropping, Auto steps down a preset and tells you.
  - Ultra and High add bloom.
- **Text size** and **high contrast**.

**Agents panel → Roster** (added after review, [ADR-0013](adr/0013-agents-you-add.md))
- Every agent with a short synopsis (edit it with the pencil) and its stats: tasks, success rate, average steps, tokens, last active.
- **Add an agent:**
  - give it a name, a one-line purpose, a synopsis and instructions;
  - pick read or read-and-write access, a model and its tools.

  Every tool call still goes through your permission rules and approvals. Your agents live in your data folder, never in the app's files, and Core can delegate to them right away.
- **Turn agents off and on:** Core and Critic always stay on.
- **Remove agents you added:** their files are kept aside, not deleted.

**HUD**
- **Bottom left:** navigator (minimap, breadcrumb, zoom level, layouts, time slider) under the activity ribbon.
- **Top right:** a CPU and memory chip.
- **Approvals:** `Ctrl+.` jumps to the approvals.
- **Screen readers:** told what's selected, the layout, and how many results.

## Setup

From [PHASE-3.md](PHASE-3.md#setup), then:

1. `uv sync` and `pnpm install`. New:
   - UI: sigma, graphology, marked, DOMPurify, pdf.js, highlight.js, d3-force-3d.
   - Python: nothing (numpy was already there).
2. `pnpm build` (needed before `pnpm start`, the end-to-end tests and the benchmark).
3. **Semantic layout:** needs an embedding model (`ollama pull nomic-embed-text`, as in Phase 2). It's computed in the background the first time you press `2`.
4. **Benchmark on your machine:** `pnpm bench:universe` (about 3 minutes). It prints FPS for each preset and layout, the camera-flight time, and PASS/FAIL against SPEC §24.

## Demo script (≈5 minutes)

1. **50k items:** `uv run python scripts/seed_universe.py C:\Temp\universe50k`. Then set `UNIVERSE_VAULT_DIR=C:\Temp\universe50k` and run `pnpm dev`. (Use a scratch folder: the script refuses a vault that already has items.)
2. **Universe zoom:** twelve galaxies on a ring around the Core, sized by item count. Comets wait at the edge, and loose items form a halo. Drag to orbit, scroll to zoom.
3. **Galaxy zoom:** click *Ember Wolf Acquisitions*. The camera flies in (≤ 1.2 s) and its spiral arms resolve into stars, planets, pulsars and stations. Hover anything for its name and kind.
4. **System and Item zoom:** click an item. The ring marks it, its filaments appear, and the breadcrumb reads *Universe › Ember Wolf › …*. Double-click it: the note viewer opens. Edit, `Ctrl+S` (version 2), `Esc`, `Esc`, `H`.
5. **Search:** type `water` and the results light up with numbers 1–9. Type a five-digit number from any title (e.g. `01234`) and press **Enter**: the camera flies to that one item.
6. **Layouts:** press `3` (Time) and drag the slider back, or press ▶ to watch the universe grow. Press `4` (Graph) for linked items with filaments, and `2` (Semantic; the seed has no embeddings unless you pass `--embedder`).
7. **Dashboard:** double-click a galaxy. Add a goal, tick it, and look at the timeline and the agent reports.
8. **Agents:** ask Core *"Find my notes about water"*. The Librarian's probe flies to each note it reads.
9. **Quality:** System → Display → Lite. The same universe as a 2D graph, where search, selection and dashboards still work.
10. **Benchmark:** `pnpm bench:universe`.

## Tests

| Suite | Count | New in Phase 4 |
| --- | --- | --- |
| pytest (`uv run pytest`) | 213: 212 passed, 1 Windows-only skip | scene data paging and incremental updates, wikilinks resolving late, backlinks, manual links, note editing with versions and conflicts, the Semantic layout job, similar items, galaxy goals, the 50k seed generator, vector streaming, the semantic layout's clustering, probe targets |
| Vitest (`pnpm exec vitest run`) | 89 | layouts (Project, Time, Graph, Semantic merge, 50k timing), scene data, celestial mapping, pick colours, nearest items, flights, constellations, quality detection, zoom levels |
| Playwright Electron (`pnpm test:e2e`) | 20 | the 50k done-when: streaming, FPS measurements, search flying the camera, layouts, the note viewer (including hostile HTML in a note), dashboards, and no network traffic |

Everything listed passed here: `ruff`, `ruff format`, `pyright`, `eslint`, `prettier`, `tsc`, the generated-types check and `pnpm build`. The e2e suite ran under `xvfb-run`.

### Bugs found and fixed while building Phase 4

Each has a regression test.

- **Vector search depended on LanceDB adding the `_distance` column implicitly.** That behaviour is deprecated and would have broken search on a LanceDB upgrade.
- **Opening an item, or adding it to a galaxy, didn't mark it changed,** so the universe's incremental refresh missed it.
- **The seed generator silently dropped galaxies.** A missing colour token was swallowed by `INSERT OR IGNORE`.
- **Following a `[[link]]` from one note to another in the viewer kept the first note's unsaved draft.**
- **Search vs. Enter:** a search refresh after pressing Enter re-framed all results, undoing the flight to the one you picked.
- **Lite mode sorted 50k nodes by z-index on every frame,** about 2 s a frame in software rendering. It no longer sorts.

### Review round (2026-10-14): 29 findings, all fixed

Three reviewers went through the Phase 4 code before your approval: backend, 3D scene, and HUD/viewers. Each fix has a regression test that fails on the old code.

- **Notes and your data**
  - **Data loss:** saving a note could overwrite an edit made outside the app (in Obsidian, say) that the watcher hadn't recorded yet. Now that edit is kept as its own version and the save is refused, with a reload.
  - **Simultaneous saves:** two saves from the same version could both "win", or fail with an error. Saves are now serialized and the version number is taken inside the write.
  - **Unsaved edits lost:** opening another item, a backlink or a dashboard, or pressing `Z`, threw away unsaved note edits. Shortcuts no longer act behind an open viewer, and letters typed on a dropdown no longer trigger shortcuts.
  - **Typing during a save** was overwritten, and a second `Ctrl+S` conflicted with the first. Reopened notes could show stale text.
- **Links**
  - A `[[link]]` vanished for good when its target was trashed or deleted. Now it waits for the target again and finds a new note with that name.
  - `[[slug-style]]` links never resolved.
  - Notes from before Phase 4 never had their links read. A one-time background job (migration 0005) reads them.
- **PDFs and songs** didn't load in the packaged app: the security policy blocks the blob reads pdf.js and the waveform used. They now read the bytes directly, and each PDF frees its worker thread on close.
- **Universe refresh**
  - The incremental refresh could miss changes: a worker committing just after a refresh read, a multi-page refresh, events arriving during a refresh, items deleted outright.
- **3D scene**
  - While a layout recomputed (seconds for Graph), clicks, hovers and search highlights could land on the wrong item.
  - Layout requests piled up during an import.
  - A selected galaxy yanked the camera back every few seconds.
  - A selected item wasn't flown to again after a layout switch.
  - An emptied vault left the old universe on screen.
  - Interrupted transitions jumped.
- **Search**
  - A single search result was re-selected on every refresh.
  - `Enter` could fly to the previous search's best match.
  - The time filter stayed on after leaving the Time layout.
- **Leaks and safety:** photo textures, bloom passes and probe trails leaked GPU memory. Wikilinks inside code blocks rendered as links and their labels weren't escaped (DOMPurify still sanitized everything). One bad embedding (an infinite value) stopped the Semantic layout from ever updating.

## Known limitations

- **The FPS budget isn't proven on recommended hardware yet.** This machine has no GPU (see the table above). Please run `pnpm bench:universe` on your PC and send me the output. If a number misses its budget, I'll profile on that data. The most likely levers are the size-based level of detail and the Balanced preset.
- **Lite is slow in software rendering at 50k** (20 FPS to under 1 FPS while zooming here). It's meant for weak GPUs, where it hasn't been measured.
- **The Semantic layout is an approximation:** PCA plus k-means, not UMAP (ADR-0012). It clusters by meaning but keeps less local structure. It needs an embedding model and is recomputed in the background when the vault grows by more than 5 %.
- **Photo planets** only show photos that have thumbnails. Seed photos have none, so they stay points.
- **Viewers:**
  - PDF highlights and Q&A inside the viewer: "Ask Core" covers questions for now.
  - Synced transcripts arrive with Voice (Phase 7).
  - Songs show BPM and key only if the file's tags have them; pulsars pulse at a fixed rate.
  - Some PDF image formats (JBIG2, JPEG 2000) need WebAssembly, which the app's security policy doesn't allow, so those images don't render.
  - The note editor is a plain text area (no slash commands or inline AI actions yet).
- **2D views:** Grid and List exist (Phase 2). Table, Timeline, Kanban and Map are not built yet; Map comes with the creative studios (Phase 10).
- **Tag filter chip:** search with `#tag` in the query instead.
- **No network/offline pill yet:** nothing goes online until Research (Phase 6).
- **GPU picking on Windows (unconfirmed):** small points might be harder to hover on some graphics drivers (ANGLE drops points whose centre is off the 1-pixel pick view). Worth a look when you run the benchmark.
- **Not yet run on Windows** (CI still ends in `startup_failure` before any job runs).

## The neural universe

Your idea of the universe as a brain is thought through in [VISION-neural-universe.md](VISION-neural-universe.md):
- how to map it so it holds up (links as synapses that strengthen with use, galaxies as synaptic hubs, agents as firing neurons);
- what to add, phase by phase;
- the full voice receive chain for Phase 7.

It ends with three decisions for you.

## What's next: Phase 5 (Forge + Sentinel v1)

SPEC §25: error triage, failing-test reproduction, patching in worktrees, verification gating, Critic/Sentinel review, approval cards, apply and rollback, the post-apply health watch, protected-core enforcement, and the System Vitals panel. Most of it lives in protected core, so expect a larger proposal for you to apply.

Useful from you now:
- review Phase 4;
- run `pnpm bench:universe` on your PC and send me the output;
- try the demo on your own vault.
