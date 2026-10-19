# Proposal: Phase 7 protected core — microphone consent

Status: **waiting for your approval.** Nothing in it is applied yet.

Patch: [`phase-7-consent.patch`](phase-7-consent.patch). Design: [ADR-0016](../adr/0016-phase-7-voice.md) §6.

## Why this needs you

Voice itself is built and committed: speech-to-text, the voices, the wake phrase, the modes, barge-in, voice
navigation, memos and transcription. What decides **whether the microphone may open** is protected core
(AGENTS.md: consent and the kill switch live in `apps/desktop/src/main/protected/` and
`services/core/.../protected/`), so it arrives as this patch.

Until it's applied:
- **The mic can't open.** Chromium's permission handler refuses every media request, as it has since Phase 1.
- **Voice still speaks**: you can turn voice on, hear agents in their own voices, and test the voices.
- The orb, the Voice panel and the Activity ribbon say what's missing.

## What it adds

| Where | What |
| --- | --- |
| `apps/desktop/src/main/protected/consent.ts` | **The consent state.** The mic is off at every launch. Turning it on happens only after you confirm a **native dialog** (once per launch), which no renderer code can click, and never while the kill switch is engaged (also re-checked after the dialog closes). Turning it off is instant, from anywhere. `mediaAllowed` is the only rule Chromium gets: **audio only**, for **our main window**, from **our own origin** (`app://universe`, or the dev server in `pnpm dev`), **while consent is on**. Camera, screen and everything else stay refused (Phase 8). |
| `apps/desktop/src/main/index.ts` | **Wiring.** The permission request and check handlers use `mediaAllowed`. The bridge's `getConsent` / `setMicConsent` go to the consent state (only the main window may ask to turn it on). A reload, a crash or safe mode starts with the mic off. The **tray** gets "Microphone on: turn it off" and its tooltip says when the mic is on, an indicator the page can't hide. Every change is reported to Core (below). |
| `apps/desktop/src/main/protected/killswitch.ts` + `index.ts` | **The kill switch stops the mic first.** Engaging revokes consent before anything else, then reloads the page if the mic was on: Chromium keeps an open stream running after a permission is revoked, and the reload ends it. (Core also stops the voice process on `killswitch.engaged`; that part is already on the branch.) |
| `services/core/.../protected/consent_api.py` + `app.py` | **The consent record.** `POST /api/v1/consent` (session token) records each change in the audit log (`consent.changed`, with where it came from: hud, voice, tray, kill switch, window) and publishes the `consent.changed` event; `GET /api/v1/consent` reads it back. Core never grants capture from it: a wrong report could only mislabel the log, never open a mic. |
| `packages/shared-types/*` | Regenerated for the two endpoints (`pnpm gen:types`). |
| `apps/desktop/.../protected/consent.test.ts`, `tests/protected/test_consent_api.py` | 15 consent tests (off at launch, the dialog, declining, once per launch, refused under the kill switch even if it engages while the dialog is open, revoke, a failing audit call never blocks turning off, and the permission rule's refusals: camera, audio+video, another window, a foreign page, a garbled origin, another permission) and 3 Core record tests. |

## How it was tested

In a scratch worktree at the branch head with this patch applied:
- the full Electron e2e suite (`app.spec.ts` + `safe-mode.spec.ts`), with Chromium's fake microphone
  (`--use-fake-device-for-media-stream`). The Phase 7 test declines the native dialog (the mic stays off),
  confirms it (the mic opens, the indicator shows, the audit records `on, via hud`), and the kill-switch test then
  checks the mic was revoked (`off, via killswitch`) and the indicator is gone;
- the desktop Vitest suite, eslint, prettier and the type check;
- the full Python suite, ruff and pyright.

Results are in [What was run](#what-was-run) below.

## To apply it

```sh
git apply docs/proposals/phase-7-consent.patch
uv run pytest tests/protected
pnpm exec vitest run apps/desktop
git add -A && git commit -m "Apply the Phase 7 protected-core patch (microphone consent)"
```

Then turn the mic on from the orb's mic button: the native dialog asks once per launch.

## What to look at closely

- `mediaAllowed` in `consent.ts`: the whole rule Chromium gets.
- `MicConsent.request`: the dialog text in `index.ts`, once per launch, the kill-switch re-check.
- The kill switch's `stopCapture`: revoke, then reload the page if the mic was on.

## What was run

2026-10-19, in a scratch worktree at the branch head with the patch applied:

- **Electron e2e** (`app.spec.ts` + `safe-mode.spec.ts`): 15 passed, 1 skipped (the second half of the Phase 5
  done-when, which needs the Phase 5 patch).
- **Desktop Vitest:** 43 of 43 (15 of them the new consent tests). eslint, prettier and the type check clean.
- **Python:** `tests/protected` 25 of 25 (3 new). The full suite: 314 passed, 8 skipped, 1 failed. The failure was a
  race in an existing backup test, unrelated to this patch (it read the events while restic was still restoring).
  It's fixed on the branch, and that file then passed 4 of 4 with the patch applied. ruff and pyright clean.
