# UNIVERSE

A local-first Windows desktop app that works as a digital brain. Every project, note, idea, song, file, photo, link and conversation lives in one navigable 3D universe, run by a team of local AI agents. ("UNIVERSE" is a working name.)

## Status

**Phase 0: Blueprint, delivered and awaiting approval.** No application code yet. Phase 1 (Foundation) starts after approval.

| Document | What's in it |
| --- | --- |
| [SPEC.md](SPEC.md) | Requirements: the master build prompt |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture, tech decisions, repo tree, data model, API/events, UI concept, Forge safety design |
| [docs/PHASE-0.md](docs/PHASE-0.md) | Phase 0 delivery note: hardware info needed, open questions, what Phase 1 delivers |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [AGENTS.md](AGENTS.md) | Rules for AI coding assistants and Forge |

Hardware report (run on the target Windows PC):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hardware-report.ps1
```

## Legacy

`src/`, `index.html` and the Vite/Tailwind configs at the root are a pre-existing [Bolt](https://bolt.new/~/sb1-pwkbjj78) landing page that has nothing to do with UNIVERSE. They're slated for replacement in Phase 1 (see Question 1 in [docs/PHASE-0.md](docs/PHASE-0.md)).
