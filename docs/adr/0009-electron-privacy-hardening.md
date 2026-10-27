# 0009 — Electron privacy hardening: no outbound traffic from Chromium

- Status: Accepted (2026-10-12)
- Date: 2026-10-12
- Flags: privacy

## Context

SPEC §3.1 and §17: data never leaves the machine unless enabled, and no telemetry leaves the machine. During Phase 1 the Chromium net log showed Electron downloading a Hunspell spellcheck dictionary from `redirector.gvt1.com` at startup, even with `webPreferences.spellcheck: false`. Chromium also has background subsystems (component updater, field trials) that can make requests.

## Decision

- Electron main appends `--disable-background-networking` and `--disable-component-update` before the app is ready.
- On `session-created` (before any download can start), the spellchecker is disabled, its languages are cleared, and its dictionary download URL is pointed at an unroutable loopback port.
- Every renderer permission request is denied except `clipboard-sanitized-write` (copy buttons) until the consent system lands (Phases 7–8).
- **Regression test:** the Electron e2e run records a Chromium net log (`--log-net-log`), and the last test fails if any request went to a non-loopback host.

## Consequences

- No spellcheck in text inputs. A local, user-installed dictionary can be added later without any network access.
- Any future dependency or Chromium upgrade that starts calling home fails CI instead of shipping silently.

## Alternatives considered

- **Firewall rules only** (Phase 12 option): enforce at the OS level, but they don't explain *what* tried to connect. The net-log test catches it in development.
