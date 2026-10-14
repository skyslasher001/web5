# UNIVERSE — Master Build Prompt v2

Oct 12, 2026

## How to use this prompt

Give sections 1–29 to your AI builder as one prompt. With Claude Code: export this doc as Markdown, save it as SPEC.md in the repo root, and say "Read SPEC.md and deliver Phase 0."

- "UNIVERSE" and the wake word "Hey Universe" are placeholders. Rename them anywhere.
- v2 keeps everything from v1 and adds: the full futuristic Universe interface, Universal Recall (anything pulled up instantly by voice or search), Forge (the self-repair and self-upgrade agent), Sentinel, a brain layer, reliability and backups, a performance governor, and a 13-phase build plan.
- Every line below is a requirement for the builder. Edit freely before you hand it over.

## 1. Mission

You are building UNIVERSE: a local-first Windows desktop app that works as my digital brain. Every project, note, idea, song, file, photo, link, and conversation lives in one navigable, interactive universe.

A team of AI agents runs it. They organize, research, create, see my screen when I allow it, talk with me by voice, fix their own bugs, and upgrade the system over time. Anything I have ever put in must be pullable on a whim, by voice or by typing, in under a second.

Design target: a premium sci-fi command center that stays neat, fast, and calm. Beautiful and useful in equal measure. Never cluttered.

## 2. Your role

You are a senior principal engineer, product architect, and UI/UX designer building this with me. I am a technically hands-on solo builder.

- Be direct. No fluff. Ship working code.
- Push back when I am wrong, with reasons and a better option.
- Hold the design bar of a premium product, not a hobby project.

## 3. Non-negotiables

1. **Local-first.** Runs on my Windows PC. Fully functional offline except live web research and optional cloud models. Data never leaves the machine unless I explicitly enable it.
2. **Open source.** Prefer MIT, Apache-2.0, BSD, ISC. Flag any GPL, AGPL, or non-commercial license before adopting it. This covers code, model weights, and voice models. Offer an alternative with every flag.
3. **Cost-effective.** Default cost is $0 per query. Local models first. Paid APIs are opt-in, behind hard monthly caps, with a visible usage meter.
4. **Consent.** Mic, screen, and camera are OFF by default. Each has its own toggle, an always-visible indicator while active, and a global kill switch. Nothing captured is stored unless I say so.
5. **My data stays readable.** The vault is plain files in open formats, usable without the app. Full export anytime. Deletion is real: originals, embeddings, caches, and thumbnails.
6. **Modular.** Every capability (LLM, embedder, reranker, STT, TTS, wake word, VLM, OCR, search, agent, tool, view) is a swappable plugin behind a clean interface.
7. **Self-healing, never self-destroying.** The system repairs and upgrades itself only through tested, reversible, approved changes. It can never lock me out, delete my data, or weaken its own safety rules.
8. **Fast and smooth.** The performance budgets in section 24 are requirements.
9. **Real output.** Every phase ends with runnable code, tests, and setup steps. No pseudo-code. No stubs presented as finished.

## 4. System architecture

The app is a set of small cooperating processes. A tiny supervisor keeps them alive, so one crash never takes down the whole universe.

```
┌───────────────────── ELECTRON SHELL ─────────────────────┐
│ Renderer: React · 3D Universe · HUD · Panels · 2D views  │
│ Main: global hotkeys · tray · screen capture · windows   │
└────────────────────────────┬─────────────────────────────┘
                             │ REST + WebSocket (127.0.0.1 + auth token)
┌────────────────────────────▼─── SUPERVISOR / WATCHDOG ───┐
│ CORE (FastAPI): Orchestrator · Agents · Memory · Vault   │
│ Search · Event Bus · Audit Log · Budget · Permissions    │
├──────────────┬──────────────┬──────────────┬─────────────┤
│ Job Queue    │ Model        │ Voice        │ Vision      │
│ + Workers    │ Runtime      │ STT / TTS /  │ Capture +   │
│ (ingestion)  │ (LLM, embed) │ wake word    │ VLM + OCR   │
├──────────────┴──────────────┴──────────────┴─────────────┤
│ SQLite (metadata, FTS5, events, jobs) · LanceDB (vectors)│
│ Vault files · Git (app source) · Encrypted backups       │
└──────────────────────────────────────────────────────────┘
   Optional sidecars: SearXNG · code sandbox · capped cloud LLM
```

**Processes**

- **Electron main:** windows, tray, global hotkeys, screen-capture permission, OS integration. Launches the supervisor.
- **Renderer:** the React UI (Universe, HUD, panels, 2D views).
- **Supervisor:** a tiny, rarely changed process. Starts and monitors every service, restarts crashes, holds the last-known-good version, and boots safe mode.
- **Core (Python FastAPI):** API, WebSockets, orchestrator, agents, memory, vault services, permissions, budget, audit log.
- **Workers:** ingestion, embedding, transcription, captioning. Background priority only.
- **Model services:** Ollama and/or llama.cpp (OpenAI-compatible API) for LLM and VLM; separate STT and TTS services.
- **Optional sidecars:** SearXNG, code sandbox, capped cloud LLM.

**Communication**

- REST for commands. WebSocket for streaming tokens, events, and job progress.
- Internal event bus (pub/sub). Everything emits events: item.created, agent.started, job.progress, error.raised, approval.requested. The UI, agents, audit log, and Forge all subscribe.
- Events are persisted to SQLite so the timeline can replay history.
- Local API (POST /capture, GET /search) so my other tools and scripts can push items in and query the vault.

## 5. The Vault (stores everything)

The vault holds every kind of thing I make or save, keeps the originals untouched, and processes each item so it can be found by meaning.

**What goes in:** notes, ideas, songs, audio, voice memos, photos, videos, docs, PDFs, spreadsheets, code and repos, links and bookmarks, screenshots, chat transcripts, and whole project folders.

**How it gets in:** drag-drop anywhere in the UI, watched folders, global quick capture, clipboard, the local API, and importers (section 21).

**Storage**

- Original files on disk in a transparent structure: `Vault/<type>/<yyyy>/<mm>/…`. The vault lives outside the repo at a path I choose.
- Notes are Markdown with YAML frontmatter, Obsidian-compatible, so I can open the vault in Obsidian with the app closed.
- Non-text items get a sidecar JSON with their metadata.
- SQLite in WAL mode: metadata, FTS5 full-text index, links, tags, events, jobs.
- LanceDB (or Chroma): text and image embeddings. Every embedding records the model name and version that produced it.
- Content hashing for dedupe. Originals are never modified; every edit creates a version.
- An item can belong to several projects. Membership lives in metadata, not folder location.

**Minimum data model:** Item, Version, Link (typed, weighted, created by me or an agent, with confidence), Project, Tag, Collection, Agent, Memory, Conversation, Message, Job, Event, Capture, Source (provenance).

**Processing pipeline** (queued, prioritized, resumable, runs when the PC is idle):

1. Hash and dedupe
2. Metadata extraction (EXIF, ID3, file properties)
3. Text extraction (MIT/BSD libraries; flag PyMuPDF as AGPL)
4. OCR for images and scans
5. Transcription for audio and video, with timestamps (faster-whisper or equivalent)
6. Image captioning and image embeddings (CLIP/SigLIP class)
7. Text embeddings
8. Summary
9. Auto-tags
10. Entity extraction: people, places, organizations, dates
11. Link suggestions to related items and projects
12. Placement in the universe

Every item shows its pipeline status. Failures retry with backoff and get reported to Forge. When an embedder or captioner is upgraded, old items are re-processed in the background without blocking anything.

**Lifecycle:** Inbox → Triaged → Active → Archived. Ideas also have growth stages (section 7).

**Knowledge graph:** items link to each other and to projects. Links I confirm are solid; links an agent suggests stay marked as suggestions until I confirm them.

## 6. Universal Recall (pull up anything on a whim)

This is the heart of the app: any item, from anywhere, in one command, in under a second.

**Entry points**

- Global hotkey (default Ctrl+Space, configurable) opens a floating command bar over any app, even when UNIVERSE is minimized.
- Wake word plus voice: "Hey Universe, pull up…"
- The search bar, always visible in the HUD.
- Tray icon for quick capture and quick search.

**Retrieval engine**

- Hybrid ranking: BM25 keyword (FTS5) + vector similarity (text and image) + a local reranker.
- Boosts: recency, how often I open it, pinned, current project, graph proximity to what I'm working on.
- Natural-language filters parsed from the query: dates ("last summer", "Tuesday afternoon"), types ("the song", "photos"), projects, people, places.
- Cross-modal: text finds photos ("the sunset at the lake"), "the error from yesterday" finds the screenshot. Stretch goal: humming finds a song.
- Filters in the UI by type, project, date, tag, and agent.

**Two-speed routing**

- **Fast path:** navigation and commands ("open X", "show my songs", "go to Ember Wolf", "play it") resolve through a lightweight intent parser plus search. No LLM call. Target under 300 ms.
- **Smart path:** questions that need reasoning ("what were my best ideas for the pricing tool?") go to Core with retrieved context and stream an answer that cites the items it used.

**Results**

- High-confidence match: the camera flies to it and it opens immediately.
- Several matches: results form a temporary constellation in front of the camera. I select by keyboard, click, or voice ("the second one").
- Follow-up commands on any result: open, play, pin, link these, move to project, send to Builder, summarize, compare.

**Everything is a command.** Every action in the app is also in the command palette: create note, start research, toggle mic, switch layout, run an agent, open settings, kill switch.

**Context recall:** "What was I working on?" and "What did I look at Tuesday?" answer from the activity timeline (section 10).

## 7. The Universe interface

The main view is a living universe of my own data: sleek, futuristic, and neat. Every visual element maps to something real, so the beauty is also the navigation.

**Design language**

- **Theme:** deep space. Near-black base (around #05070D) with subtle nebula gradients and a slow parallax starfield.
- **Panels:** frosted glass (backdrop blur, 1px hairline borders, low-opacity fills), rounded corners, soft glow on focus only.
- **Color:** one primary accent (electric cyan), one secondary (violet), and a fixed semantic color per item type. No more than about 8 hues on screen. Color is always paired with an icon or shape, never used alone.
- **Typography:** Space Grotesk or Inter for UI, JetBrains Mono for data and code. All OFL-licensed.
- **Spacing:** 8px grid, generous negative space, strict alignment. Neat beats busy.
- **Motion:** purposeful only. UI transitions 150–250 ms. Camera flights 600–1200 ms, eased. Spring physics on panels. Reduced-motion mode.
- **Sound:** optional subtle UI sounds and ambient hum. Off by default, with volume control.
- **Design tokens:** one source file. Every component uses tokens, never hardcoded values.

**Celestial mapping**

| Thing | Shown as | Behavior |
| --- | --- | --- |
| Me / home | The Core (central star) | Pulses with system activity; home position for the camera |
| Project | Galaxy | Size = item count; brightness = recent activity |
| Note | Star | Brighter when recently opened |
| Idea | Nebula → protostar → star | Visibly matures as I develop it; promoting it births a new galaxy (project) |
| Song | Pulsar | Pulses to its BPM while playing |
| Photo | Planet | Photo appears as its surface on approach |
| Document / file | Moon or asteroid | Orbits the item or project it belongs to |
| Code repo | Space station | Shows build/test health as a status light |
| Link / bookmark | Satellite | |
| Connection | Light filament | Brightness = strength; dashed = suggested, unconfirmed |
| Agent | Luminous probe | Own color and trail; flies to whatever it is working on, along the links between items |
| Signal | Light pulse along a filament | Travels a link when I or an agent move between linked items (added 2026-10-14) |
| Inbox capture | Comet | Arrives from the edge, waits for triage |
| Forgotten item | Dim star | Flares briefly when resurfaced |

**Layouts** (switchable, with animated transitions)

- **Project:** items grouped in their galaxies.
- **Semantic:** positions from embeddings (UMAP or similar), so related things cluster by meaning even across projects.
- **Time:** a spiral or timeline by creation date, with a time-travel slider that replays the universe growing.
- **Graph:** force-directed on links.

**Zoom levels:** Universe → Galaxy → System (an item and its neighbors) → Item (opens its viewer). Labels appear only up close. Distant galaxies render as sprites.

**HUD layout**

- **Top center:** search and command bar, always reachable, with filter chips (type, project, date, tag).
- **Bottom center:** voice orb with distinct animated states for idle, listening (live waveform), thinking, and speaking.
- **Chat panel:** slides out from the orb. Talk to Core or any agent; history is searchable and saved to the vault.
- **Left dock:** agent roster with live status (idle, working, waiting for approval). Click an agent to chat with it or see its task.
- **Right panel:** context for the selected item: preview, AI summary, metadata, links, versions, actions.
- **Top right:** status cluster. Mic, screen, and camera indicators that are impossible to miss when active, plus network/offline state, budget meter, and system vitals.
- **Bottom left:** minimap and breadcrumb (Universe › Ember Wolf › Note).
- **Activity ribbon:** a collapsible live feed of agent actions.
- **Approvals tray:** pending confirmations (tool calls, Forge patches) with one-click review.
- **Zen mode:** hides the whole HUD for pure exploration.

**Item viewers** (glass cards that unfold from the object)

- **Notes:** Markdown editor with live preview, backlinks, slash commands, inline AI actions.
- **Songs:** player with waveform, time-synced lyrics editor, key/BPM/chords, stems, versions and takes.
- **Photos:** viewer, EXIF, map location, captions, similar photos.
- **Docs and PDFs:** viewer with highlights and Q&A.
- **Code:** syntax-highlighted viewer, open in my IDE.
- **Video:** player with synced transcript.
- **Projects:** dashboard with goals, tasks, status, timeline, linked items, and agent reports.

**2D views** of the same data, always one click away: Grid, List, Table, Timeline, Kanban, Map (photos with GPS). Real work never requires 3D.

**Rendering performance**

- three.js InstancedMesh, level of detail, frustum culling, GPU picking.
- Layouts computed off the main thread (web worker or backend) and cached.
- Progressive streaming of items; texture atlases for thumbnails.
- Bloom and post-processing behind quality settings.
- Quality presets: Ultra, High, Balanced, Lite. Lite is a 2D WebGL graph.
- Auto-pick the preset from hardware detection, then adjust from live FPS.

**Accessibility:** full keyboard navigation, screen-reader labels on all panels, reduced motion, adjustable text size, high-contrast option.

## 8. Agent swarm

Fourteen specialist agents, defined in config files, coordinated by one orchestrator. I can add, edit, clone, or disable any agent from the UI without touching code.

**Framework**

- **Core** receives my requests, plans, delegates to specialists, runs independent subtasks in parallel, merges results, and routes important outputs through Critic.
- Agents are YAML files, hot-reloaded on change.
- Each agent defines: name, purpose, system prompt, allowed tools, permission tier, model tier, memory scopes (per-agent and shared), voice, color and icon, triggers (manual, schedule, event), budget limits, and max steps.
- One standard tool interface: every tool has a schema, permission tier, and timeout. MCP client support so any MCP server plugs in as tools.
- **Task board:** every task has an owner agent, status, progress, logs, and cost.
- **Guardrails:** step limits, timeouts, loop detection, per-task token budgets, retries with backoff.
- **Human-in-the-loop:** approval points configurable per agent and per tool.
- **Skill library:** agents save reusable procedures (with my approval), versioned and testable. This is the system's procedural memory.
- Agent-to-agent messages travel over the event bus and are visible in the activity ribbon.

**Agent definition example**

```yaml
id: librarian
name: Librarian
purpose: Organize, tag, link, dedupe, and retrieve anything in the vault.
model: local-fast          # tier name, resolved by the model router
escalate_to: local-large
voice: calm-neutral        # resolved to an installed TTS voice
color: "#7FD4FF"
tools: [vault.search, vault.read, vault.tag, vault.link, vault.move]
permission_tier: write
memory: [shared, librarian]
triggers:
  - event: item.processed
  - schedule: "0 3 * * *"   # nightly tidy
limits: {max_steps: 20, max_tokens: 40000, timeout_s: 300}
requires_approval: [vault.move, vault.delete]
```

**Roster**

| Agent | Job | Permission tier |
| --- | --- | --- |
| Core | Orchestrator and my main point of contact. Plans, delegates, merges. | write (via delegation) |
| Navigator | Executes UI and voice commands instantly: fly to, open, filter, play, switch views. | read |
| Librarian | Organizes, tags, links, dedupes, and retrieves vault items. | write |
| Scribe | Captures notes and ideas; turns rambling voice into structure; meeting notes. | write |
| Researcher | Live web research with citations, cross-checks, watchlists. | read + network |
| Composer | Songs: lyrics, structure, rhymes, chords, melody ideas, audio analysis. | write |
| Curator | Photos and media: captions, albums, dedupe, best-of picks. | write |
| Builder | Code, scripts, project scaffolding, automations. Sandboxed execution. | write + sandbox |
| Strategist | Projects, goals, tasks, plans, status reports, next actions. | write |
| Observer | Screen vision when I allow it; explains what's on screen; reads errors. | read (consent-gated) |
| Chronicler | Timeline, daily and weekly briefs, memory consolidation, resurfacing. | write |
| Critic | Reviews other agents' output for accuracy, logic, sources, and quality. | read |
| Forge | Fixes bugs and errors; upgrades the system (section 9). | system (gated) |
| Sentinel | Security, privacy, health, backups, and budget watchdog. Independent reviewer of Forge. | read + system-observe |

## 9. Forge: self-repair and self-upgrade

Forge keeps UNIVERSE healthy and makes it better over time. It finds and fixes bugs fast, upgrades dependencies, models, prompts, and features, and never breaks the system or weakens its safety rules.

**Prerequisites** (built from Phase 1 so Forge has what it needs)

- App source lives in a local Git repo. UNIVERSE shows its own codebase as a galaxy.
- Structured error capture everywhere: backend exceptions, frontend errors, worker failures, crashes. Each with stack trace, context, and repro data.
- Test suite, lint, type checks, agent evals, and perf benchmarks all runnable headlessly.
- Supervisor with last-known-good version and safe mode.

**Repair loop**

1. **Detect:** errors, crashes, failed jobs, failing tests, perf regressions, my bug reports ("Forge, the photo viewer froze"), Observer screenshots of error dialogs.
2. **Triage:** dedupe, group, rank by severity and frequency.
3. **Reproduce:** write a failing test first.
4. **Diagnose:** read logs, code, and recent changes. State the root cause in plain English.
5. **Patch:** in an isolated git worktree or branch. Minimal diff.
6. **Verify:** full tests, lint, types, evals, and perf benchmarks in the sandbox. The new test must pass; nothing else may regress.
7. **Review:** Critic reviews code quality. Sentinel reviews safety, permission, and privacy impact. Forge cannot approve its own work.
8. **Propose:** a card in the approvals tray: what broke, root cause, diff, test results, risk level (low/medium/high), rollback plan.
9. **Apply:** on my approval: backup snapshot → merge → restart the affected service → health check.
10. **Watch:** monitor for a set window. On regression, auto-roll back to last-known-good and report what happened.

**Upgrade loop**

- **Dependencies:** scan for security advisories and new versions (pip-audit, npm audit), test upgrades on a branch, propose.
- **Models:** periodically check Hugging Face for newer open models per role (LLM, embedder, reranker, STT, TTS, VLM, OCR) that fit my hardware and license rules. Benchmark candidates locally on the eval set for quality, speed, and VRAM. Propose a swap with the numbers. Re-embedding runs as a background job.
- **Prompts and agents:** A/B test prompt changes on golden tasks. Propose only measured improvements.
- **Performance:** profile slow paths, propose optimizations with before/after numbers.
- **Features:** notice repeated manual work ("you renamed 40 photos by hand this week") and propose a tool, skill, or automation. I approve before anything gets built.
- **Self-documentation:** maintain the changelog, ARCHITECTURE.md, and an ADR for every change.

**Hard limits**

- **Protected core:** Forge never modifies the permission system, consent controls, kill switch, audit log, budget caps, Sentinel, supervisor, update/rollback mechanism, or its own limits. For these, Forge writes a proposal with a diff and explanation; I apply it myself.
- Never deletes or rewrites vault data. Schema migrations require a verified backup and my approval.
- Never disables, skips, or weakens a test to make it pass.
- Every change needs my approval by default. An optional auto-apply toggle (off by default) can cover narrow low-risk categories I choose, such as patch-level dependency bumps that pass every check, always with auto-rollback.
- Proposals are batched and rate-limited (e.g. 5 per day max) so Forge never spams me.
- Every Forge action goes in the audit log. One-click rollback to any prior version from the UI.

**Safe mode:** if the app fails to start twice in a row, the supervisor boots last-known-good with agents disabled, shows what failed, and lets Forge and me fix it from there.

## 10. Brain layer (what makes it feel like a mind)

The brain layer turns storage into memory: it remembers, connects, forgets gracefully, and brings the right thing back at the right time.

**Memory types**

- **Working:** the current conversation and task context.
- **Episodic:** what happened, when. Conversations, captures, activity, decisions.
- **Semantic:** facts about me, my projects, my people, my preferences. Kept in a "Self" profile I can view and edit.
- **Procedural:** skills and workflows the agents have learned.
- Scopes: per-agent and shared. Every memory is viewable, editable, and deletable, and carries its provenance (source and date).

**Consolidation ("dreaming")** — a nightly idle job run by Chronicler:

- Summarize the day.
- Merge duplicate memories; strengthen or weaken links based on use.
- Decay stale, low-value memories. Never delete originals.
- Propose Self-profile updates for my approval.
- Detect contradictions ("you said X in March, Y today") and ask me which is right.

**Auto-linking:** suggest connections across projects, shown as dashed filaments until I confirm.

**Neural pathways** (added 2026-10-14, owner-approved; see docs/VISION-neural-universe.md): links are synapses.

- A link fires when I move from one item to a linked one, open one right after the other, or an agent uses both in one task. Firings are recorded from Phase 4 on, so there is history to learn from.
- Each firing strengthens the link; strength decays with a half-life (about 30 days). Filament width and brightness show it, so the paths I actually think along get brighter.
- Items that keep firing together without a link get a dashed suggested filament.
- Weak links fade but are never deleted.

**Resurfacing:** periodically bring back forgotten ideas and notes that relate to what I'm doing now.

**Briefs:** a morning brief (active projects, deadlines, new findings from watchlists, resurfaced ideas, system health), on screen or spoken. Plus a weekly review.

**Timeline and time travel:** every event is logged. I can scrub the universe through time and ask "what was I doing last Tuesday afternoon?"

**Idea incubator:** ideas grow nebula → protostar → star, and get promoted into a project galaxy when ready. Strategist helps develop them.

**Projects:** goals, milestones, tasks, and status. Agents write status reports; next actions show up in the brief.

**Optional screen recall** (OFF by default): periodic screenshot + OCR history so I can "find that thing I saw".

- App and site exclusion list; password managers, banking, and private windows excluded automatically.
- Retention limit (e.g. 7–30 days), encrypted at rest.
- Pause hotkey and a one-click purge.

## 11. Voice

I can run the whole app by voice, and every agent can talk back in its own voice.

- **Speech-to-text:** local faster-whisper (or the current best open equivalent), streaming, with voice activity detection (Silero-class).
- **Modes:** push-to-talk (hotkey), wake word (openWakeWord-class, custom word, default "Hey Universe"), and a continuous conversation mode that times out.
- **Text-to-speech:** local (Kokoro, Piper, or the current best open option). Each agent has its own voice. Check every voice model's license individually.
- **Barge-in:** I can interrupt while it's speaking. Needs echo cancellation (WebRTC AEC) or a headset mode.
- **Latency target:** end of my speech → first spoken audio in under 1.5 s on recommended hardware.
- **Voice drives everything Navigator can do:** "Take me to Ember Wolf", "Play the song I made in March", "Show photos from the lake", "Read me my brief", "Forge, what broke?"
- Spoken answers stay short; full detail goes on screen.
- Dictation into any editor. Voice memos are transcribed into the vault automatically.
- Mic indicator always visible while the mic is live.

## 12. Vision (screen)

Observer sees my screen only when I allow it, and only for as long as I allow it.

- Capture only when toggled on or when I say "look at this". Choose full screen, one window, or a drawn region. Multi-monitor aware.
- Local vision-language model for understanding, with OCR fallback (PaddleOCR or Tesseract class).
- "I can see your screen" indicator while active; auto-off after a configurable timeout.
- **Watch mode** (opt-in, time-limited, one window): Observer watches for errors, explains them, and hands off to Builder or Forge.
- Captures are not stored unless I say "save this"; then the capture becomes a vault item.
- Exclusion list. Never capture password fields or password managers.
- Camera: off by default, separate toggle, same rules as the screen.

## 13. Live web research

Researcher answers from the live web, cites every source, and reports conflicts instead of guessing.

- Self-hosted SearXNG (AGPL, run unmodified as a separate service) plus free-tier search APIs as fallbacks.
- Page fetch with clean extraction (trafilatura or readability). Headless browser (Playwright) for JavaScript-heavy pages.
- Every web-based answer cites its sources with links.
- **Quick mode:** 1–3 searches for a fast answer.
- **Deep mode:** multi-step searches, cross-checked sources, a structured report saved to the vault.
- Cache pages and results with a TTL to save time and tokens.
- **Watchlists:** monitor topics or pages for changes; summaries land in the morning brief.
- Save any finding or page to the vault in one command, with a snapshot of the page.
- All web content is untrusted data (section 17).
- Every outbound request is logged.

## 14. Creative studios

Each kind of creative work gets real tools, not just storage.

**Songs (Composer)**

- Lyrics editor with rhyme and syllable help, song-structure templates, versions and takes.
- Audio analysis: BPM and key (librosa class), stem separation (Demucs class), hum or sing → MIDI (basic-pitch class).
- Voice memo → song idea pipeline: transcribe, extract melody, tag, link to related songs.
- Music generation models are optional. Most open music models are non-commercial; flag the license per model.

**Photos (Curator)**

- Auto captions, tags, albums, and best-of picks.
- Perceptual-hash dedupe; EXIF and GPS map view.
- Face clustering opt-in, local only. Flag model licenses.

**Ideas and projects (Scribe + Strategist):** as in section 10.

**Code (Builder):** repos as galaxies, sandboxed execution, scaffolding, open in my IDE.

## 15. Cost engine and model management

Default cost is $0. Cloud is opt-in, capped, and metered.

- **Model router:** small fast local model by default; escalate to a larger local model for hard tasks; cloud only if I enable it per agent, under a cap.
- **Providers** behind one OpenAI-compatible interface: Ollama, llama.cpp server, optional cloud.
- **Caps:** hard monthly cap plus per-agent caps. Stop at the cap. Warnings at 50%, 80%, 100%. Usage meter in the HUD. Cost logged per task.
- **Token savings:** context trimming, retrieval instead of dumping whole files, summaries, prompt caching, semantic response cache, embedding cache, web cache. Streaming everywhere.
- **Hardware detection on first run:** GPU, VRAM, RAM, CPU, disk. Recommend a model loadout that fits.
- **Hardware tiers:** define loadouts for CPU-only, ≤8 GB VRAM, 12–16 GB, and 24 GB+.
- **Model Manager UI:** installed models, download from Hugging Face with progress, quantization choice, VRAM usage, benchmark results, and model assignment per role.
- Check current best open models on Hugging Face at build time. Do NOT hardcode from memory.

## 16. Performance and resource governor

Voice and the UI always win; background work waits its turn.

- **Priority classes:** Realtime (voice, active chat, UI) > Interactive (search, vision, Navigator) > Background (ingestion, embeddings, consolidation, Forge tests).
- **GPU/VRAM manager:** keep the hot model resident, load and unload others on demand. Background work never starves voice.
- **Yield:** pause background work when a fullscreen app or game is running, on battery, or above CPU/GPU thresholds. Resume when idle.
- **Idle scheduler** for heavy jobs: consolidation, re-embedding, Forge benchmarks.
- Lazy-load models and services. The shell is usable before models are warm.
- SQLite WAL with proper indexes. Pagination and virtualized lists everywhere.

## 17. Security, privacy, and safety

The system can read my files, see my screen, and browse the web, so every power is gated, logged, and revocable.

- **Permission tiers** for tools: read-only, write, system. Destructive or system actions always require my confirmation, unless I set a narrow auto-approve rule.
- **Global kill switch:** hotkey + tray + HUD. Instantly stops all agents, mic, screen, camera, and network jobs.
- **Audit log:** every tool call, agent action, file change, network request, and approval. Append-only, viewable, searchable.
- **Prompt-injection defense:** content from web pages, files, emails, and screenshots is untrusted data, never instructions. Tool calls that come from untrusted content need my confirmation. Agents can never raise their own permissions.
- **Sandbox:** code runs in an isolated container or sandbox, no network by default, limited filesystem.
- **Localhost hardening:** backend binds to 127.0.0.1 only, per-session auth token between UI and backend, origin checks, DNS-rebinding protection so web pages can't reach the local API.
- **Secrets** in the OS credential store (Windows Credential Manager via keyring). Never in plaintext config or logs.
- **Encryption at rest** option for the vault database and sensitive items. App lock with PIN or Windows Hello.
- **Offline switch:** blocks all outbound traffic with one toggle.
- No telemetry leaves the machine.
- **Privacy dashboard:** what's stored, what's been captured, and what was sent where.

## 18. Reliability

A crash, a bad update, or a dead drive never costs me my universe.

- **Supervisor/watchdog** restarts crashed services, keeps last-known-good, boots safe mode.
- **Backups:** automated, encrypted, versioned (restic class). Targets: external drive or NAS, optional cloud bucket. Daily incremental by default. Snapshots are mandatory before any upgrade or migration. Sentinel test-restores periodically. One-click restore.
- **Crash safety:** autosave, transactional writes, resumable jobs.
- **Updates:** signed app releases. Forge changes go through git. Full version history and one-click rollback.
- **Migrations:** versioned and reversible.

## 19. Observability

I can see exactly what the system is doing and how healthy it is, at any moment.

- Structured JSON logs per service, rotated.
- **Metrics:** latency per endpoint and agent, FPS, queue depth, CPU/GPU/RAM/VRAM, tokens and cost, error rates.
- **System Vitals panel** (the Core's heartbeat): service health, loaded models, job queue, recent errors, Forge status, backup status.
- **Agent traces:** a step-by-step view of any task (prompts, tool calls, results, cost) for debugging.

## 20. Testing and quality

The test suite is what makes Forge safe, so it is built from day one.

- **Backend:** pytest. **Frontend:** Vitest. **End-to-end:** Playwright.
- **Agent evals:** a golden-task suite per agent with scoring. Runs before any prompt or model change.
- **Perf benchmarks:** search latency, voice latency, FPS at 10k and 50k items.
- **Pre-commit:** format, lint, type check (ruff, mypy or pyright, eslint, tsc).
- Every bug fix ships with a regression test.
- Seed-data generator to stress-test the universe at scale.

## 21. Integrations and imports

Everything I already have should flow in without manual copying.

- **Importers:** folders, Downloads, phone photo sync folders, Google Drive, Obsidian vaults, Notion and Evernote exports, browser bookmarks, existing music libraries.
- **MCP client:** any MCP server (calendar, email, GitHub, and more) plugs in as a tool.
- **Open externally:** "open in my IDE", "show in Explorer", "open with default app".
- **Local API:** my other tools and scripts can push items in and query the vault (section 4).

## 22. Default stack

Challenge any choice if you have a better option, and justify it in one line. Verify current versions and licenses online at build time.

| Layer | Default | License |
| --- | --- | --- |
| Desktop shell | Electron (Tauri if clearly better) | MIT |
| Frontend | React + TypeScript + Vite | MIT |
| 3D universe | three.js, react-three-fiber, drei, postprocessing | MIT / Zlib |
| 2D lite graph | sigma.js or force-graph | MIT |
| UI kit | Radix primitives, Tailwind, Motion (Framer Motion), cmdk | MIT |
| UI state and data | Zustand, TanStack Query | MIT |
| Backend | Python, FastAPI, WebSockets, Pydantic | MIT |
| Python env and packaging | uv | MIT / Apache-2.0 |
| Agent loop | Lightweight custom loop or PydanticAI | MIT |
| LLM and VLM runtime | Ollama and/or llama.cpp (OpenAI-compatible) | MIT |
| Embeddings and reranker | Current best open models from Hugging Face | verify per model |
| Database | SQLite + FTS5 | Public domain |
| Vectors | LanceDB (or Chroma) | Apache-2.0 |
| Job queue | SQLite-backed (e.g. huey); no Redis | MIT |
| File watching | watchdog | Apache-2.0 |
| Speech-to-text | faster-whisper + Silero VAD | MIT |
| Wake word | openWakeWord | Apache-2.0 code; pretrained models are non-commercial, so train a custom wake word |
| Text-to-speech | Kokoro (preferred) or Piper | Apache-2.0 / verify Piper fork (newer fork is GPL-3.0) |
| OCR | PaddleOCR or Tesseract | Apache-2.0 |
| Document extraction | docling, pypdf, pdfplumber | MIT / BSD (avoid PyMuPDF, AGPL, unless I approve) |
| Semantic layout | umap-learn | BSD-3 |
| Audio analysis | librosa, Demucs, basic-pitch | ISC / MIT / Apache-2.0 |
| Images | Pillow, imagehash | HPND / BSD |
| Map view | Leaflet | BSD-2 |
| Web search and fetch | SearXNG, trafilatura, Playwright | AGPL (separate service) / Apache-2.0 / Apache-2.0 |
| Secrets | keyring (Windows Credential Manager) | MIT |
| Backups | restic | BSD-2 |
| Testing | pytest, Vitest, Playwright | MIT / MIT / Apache-2.0 |
| Installer and updates | electron-builder, electron-updater | MIT |

## 23. Repo structure

One monorepo with a one-command dev start. The vault lives outside the repo at a path I choose (e.g. `D:\UniverseVault\`).

```
universe/
├─ apps/
│  ├─ desktop/           # Electron main + preload
│  └─ ui/                # React renderer: universe, HUD, panels, 2D views
├─ services/
│  ├─ core/              # FastAPI: API, orchestrator, event bus, memory, permissions
│  ├─ agents/            # agent runtime, tools, MCP client
│  ├─ vault/             # storage, ingestion pipeline, search
│  ├─ voice/             # STT, TTS, wake word
│  ├─ vision/            # capture, VLM, OCR
│  ├─ research/          # search, fetch, extract, cache
│  └─ supervisor/        # watchdog, safe mode, last-known-good
├─ agents/               # agent YAML definitions + prompts
├─ skills/               # approved learned skills
├─ plugins/              # swappable providers (models, voices, search)
├─ packages/
│  ├─ design-tokens/     # one source of truth for the look
│  └─ shared-types/      # API schemas shared by UI and backend
├─ evals/                # golden tasks per agent
├─ tests/                # unit, integration, e2e, perf
├─ docs/                 # ARCHITECTURE.md, ADRs, user and agent guides
├─ scripts/              # dev, build, seed data, benchmarks
├─ AGENTS.md             # rules for AI coding assistants and Forge
├─ CLAUDE.md
├─ .env.example
└─ README.md
```

## 24. Performance budgets

Treat these as requirements. If one is not achievable on my hardware, tell me with measured numbers and propose the closest target.

| Metric | Recommended hardware | Minimum hardware / Lite |
| --- | --- | --- |
| App shell usable after launch | < 3 s | < 6 s |
| Command bar opens (global hotkey) | < 150 ms | < 300 ms |
| Keyword search results | < 100 ms | < 200 ms |
| Hybrid semantic search results | < 400 ms | < 1 s |
| Fast-path command ("open X") after transcript | < 300 ms | < 600 ms |
| Voice: end of speech → first spoken audio | < 1.5 s | < 3 s |
| Chat: first streamed token | < 1 s | < 2.5 s |
| Universe rendering | 60 FPS at 50k items | 30 FPS at 10k items (2D Lite) |
| Camera flight to an item | ≤ 1.2 s | Instant jump |
| Idle RAM, no models loaded | < 1 GB | < 1 GB |
| Ingestion impact on UI | None; background only | None; background only |

## 25. Build phases

Thirteen phases. Finish and verify each before starting the next. Logging, tests, git, and the supervisor start in Phase 1 because Forge depends on them.

0. **Blueprint** — architecture doc, final tech decisions, repo tree, data model, API and event outline, UI concept, Forge safety design, hardware questions.
   - Done when: I approve it.
1. **Foundation** — monorepo; Electron shell built on the design tokens with the base HUD frame; FastAPI with WebSocket streaming chat to a local model via Ollama; SQLite; Core agent; event bus; structured logging and error capture; supervisor with safe mode; test harness and pre-commit; git; hardware detection with model recommendations; one-command dev start.
   - Done when: I launch the app, chat with streaming replies, kill the backend and watch it auto-restart, and all tests pass.
2. **Vault + Recall** — storage layout, ingestion pipeline and job queue, all core media types, hybrid search, global-hotkey command bar, quick capture, watched folders, 2D grid/list views, automated backups.
   - Done when: I drop in 500 mixed files and find any of them by keyword or meaning in under a second.
3. **Agent engine** — YAML registry, Core orchestrator, first agents (Navigator, Librarian, Scribe, Critic), tool system with permission tiers and approvals tray, MCP client, memory system, audit log, model router with budget caps, kill switch.
   - Done when: "find my notes about X, summarize them, and link them to project Y" works end to end with a full audit trail.
4. **Universe interface** — 3D universe on real data, celestial mapping, four layouts, zoom levels with LOD, complete HUD, item viewers, agent probes, constellation results, quality presets, Lite mode.
   - Done when: a 50k-item seed dataset hits the FPS budget and search flies the camera to results.
5. **Forge + Sentinel v1** — error triage, failing-test repro, patching in worktrees, verification gating, Critic/Sentinel review, approval cards, apply and rollback, post-apply health watch, protected-core enforcement, System Vitals panel.
   - Done when: I inject a deliberate bug, Forge finds it and proposes a tested fix, I approve, it applies, and one-click rollback works.
6. **Research** — SearXNG, fetch and extract, citations, cache, quick and deep modes, watchlists, save to vault, injection defenses.
   - Done when: a deep-research report with cited sources lands in the vault.
7. **Voice** — STT, TTS, wake word, push-to-talk, continuous mode, barge-in, per-agent voices, full voice navigation.
   - Done when: I can run the app for 10 minutes by voice alone.
8. **Vision** — consented capture (screen, window, region), VLM + OCR, "look at this", watch mode, save capture, exclusions, camera toggle.
   - Done when: "look at this error" returns a correct explanation and a handoff to Forge or Builder.
9. **Brain layer** — memory UI, nightly consolidation, auto-linking, neural pathways (links that strengthen with use), resurfacing, morning brief, time travel, idea incubator, project dashboards, optional screen recall.
   - Done when: the morning brief is generated from my real data and the time slider replays history.
10. **Creative studios** — Composer audio tools, lyrics editor, hum-to-MIDI, Curator photo tools, map view, dedupe.
    - Done when: a hummed voice memo becomes a tagged song idea with MIDI attached.
11. **Forge v2: self-upgrade** — dependency upgrades, Hugging Face model scouting with local benchmarks and swaps, prompt A/B evals, performance proposals, workflow-to-skill proposals, changelog and ADRs.
    - Done when: Forge proposes and benchmarks one real model upgrade with numbers.
12. **Ship** — Windows installer, first-run wizard (hardware, models, vault path, privacy choices, voices, wake word, imports), encryption at rest and app lock, signed updates, full performance and accessibility pass, docs.
    - Done when: a clean Windows install reaches a working universe through one wizard.

## 26. How you work

1. One phase at a time. Finish and verify before moving on.
2. Each phase delivers: runnable code, setup steps, tests, a demo script I can follow, known limitations, and what's next.
3. Keep the repo clean: monorepo, README, .env.example, one-command dev start. Keep AGENTS.md and CLAUDE.md current so any AI assistant, and Forge, can work on the code.
4. Simple over clever. No premature abstractions beyond the plugin interfaces.
5. Record decisions as ADRs. If a decision materially changes cost, privacy, security, or architecture, flag it in 1–2 lines, pick the best default, and keep moving.
6. Verify current versions, models, and licenses online at build time. Do not rely on memory.
7. Ask at most 5 questions per phase, only where the answer changes the build.
8. When something fails, show the real error and fix it. Never paper over failures with mocks.

## 27. Your first response

Deliver Phase 0 only, then stop and wait for my go-ahead on Phase 1:

1. Architecture diagram in text
2. Final tech decisions, each with a one-line justification and license note
3. Repo folder tree
4. Data model: tables and key fields
5. API and event outline
6. Universe UI concept, with a text wireframe of the main screen and HUD
7. Forge safety design summary
8. The exact hardware info you need from me
9. Your questions (5 max)

## 28. Seed galaxies (my existing projects)

Create these galaxies first; I'll import their files during Phase 2.

- **Ember Wolf Acquisitions** — my vacant land wholesaling business.
- **DevMind** — my offline AI developer IDE, on the same Electron/FastAPI/React stack. Reuse its components where it makes sense, and let Builder and Forge open code in it.
- **Algo trading bot** — Python, perpetual futures.
- **UNIVERSE itself** — its own source code, so Forge can see and repair it.

## 29. Future parking lot (not in scope until I say so)

- Phone companion app for capture and search over LAN or a private VPN (Tailscale class)
- Screen actions (clicking and typing for me), off by default, per-action confirmation
- VR/AR view of the universe
- Encrypted multi-device sync
- Deep email and calendar integration
- Local fine-tuning of a personal model on my vault (LoRA)
- Shareable galaxies: export a project as a package someone else can open
