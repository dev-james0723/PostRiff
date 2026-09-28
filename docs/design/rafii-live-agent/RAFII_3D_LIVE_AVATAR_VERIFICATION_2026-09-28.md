# Rafii 3D Live Avatar Verification — 2026-09-28

## Scope verified
This evidence covers the browser-facing Rafii 3D Voice Mode implementation described by:
- `docs/design/rafii-live-agent/RAFII_3D_LIVE_AVATAR_ENGINEERING_SPEC_2026-09-28.md`
- `docs/superpowers/plans/2026-09-28-rafii-3d-live-voice-avatar.md`

No paid provider was contacted during the browser verification. The repository's local `RAFII_AGENT_HARNESS=1` GPT-Live stand-in and disposable PostgreSQL database were used.

## Asset
- Canonical asset: `web/public/raffi/raffi-live-v1.glb`
- Reproducible builder: `scripts/raffi_3d_build.py`
- Final asset contract run before Task 1 commit: PASS
- Observed generated size in the fresh Task 1 run: 553,332 bytes, well under the 5 MiB ceiling
- Required named nodes: present
- Mouth morph targets `Open`, `Wide`, `Round`, `Smile`: present

## Browser and interaction evidence
Chromium and WebKit were both exercised against the same local development build and QA voice harness.

### Chromium
- Desktop viewport: 1440×900
- Mobile viewport: 390×844, Playwright mobile emulation
- Result: 57/57 checks passed
- Active Voice Mode rendered exactly one local 3D canvas
- `raffi-live-v1.glb` returned HTTP 200
- No 3D-related failed network request or console/page runtime error was observed
- Real synthetic outgoing voice level drove `speaking` mode and a non-zero mouth value
- `Stop talking` changed the avatar to `interrupted` and mouth value 0
- Axe reported zero serious/critical issues in the exercised Voice Mode panel
- Mobile controls remained on-screen and no horizontal overflow was observed
- Reduced-motion mobile run reported continuous character motion `off`
- Forced GLB request failure degraded to the static Rafii image while the live call and all voice controls remained usable

### WebKit
- Desktop viewport: 1440×900
- Mobile viewport: 390×844, Playwright mobile emulation
- Result: 57/57 checks passed
- The same 3D readiness, HTTP 200 asset load, speaking mouth motion, immediate interruption, reduced-motion, layout, and forced-fallback checks passed

Physical iPhone verification was not available in this automated run; mobile results above are emulated. WebKit provides the Safari-class engine check required by the spec.

## Evidence files
Chromium:
- `docs/design/rafii-live-agent/evidence/rafii-3d/chromium/rafii-live-agent-browser.json`
- `docs/design/rafii-live-agent/evidence/rafii-3d/chromium/voice-desktop-2-call-live.png`
- `docs/design/rafii-live-agent/evidence/rafii-3d/chromium/voice-desktop-5-stop-talking.png`
- `docs/design/rafii-live-agent/evidence/rafii-3d/chromium/voice-phone-2-call-live.png`

WebKit:
- `docs/design/rafii-live-agent/evidence/rafii-3d/webkit/rafii-live-agent-browser.json`
- `docs/design/rafii-live-agent/evidence/rafii-3d/webkit/voice-desktop-2-call-live.png`
- `docs/design/rafii-live-agent/evidence/rafii-3d/webkit/voice-desktop-5-stop-talking.png`
- `docs/design/rafii-live-agent/evidence/rafii-3d/webkit/voice-phone-2-call-live.png`

## Environment note
The first attempted local QA harness used an older shared Python virtual environment and returned `ModuleNotFoundError` from `/agent/status`. This did not exercise the 3D feature. A clean Python 3.12 worktree-local `.venv` was then created from the repository's current `requirements-dev.txt`, after which both browser suites passed. The worktree-local virtual environment is ignored and is not part of the release.

## Release status at this document's creation
Implementation and local browser verification are complete. Final repository-wide checks, whole-branch review, reconciliation with the latest `origin/consumer-saas`, release, deployment, and production verification are separate gates and must be recorded after they actually occur.
