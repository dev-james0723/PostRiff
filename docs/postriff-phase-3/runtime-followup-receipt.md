# Phase 3 runtime follow-up

Scope: continue the first real writing-route qualification prerequisite under the existing local-only authorization. **Local runtime repairs and package validation passed. No real provider request, cloud deployment, hosted pairing acceptance or Phase 4 work occurred.**

## Changed

- `AuthorizedWorker` now rejects expired prepared jobs before calling the adapter, checks membership and session again on completion, and records an interrupted/revoked outcome without accepting a draft when access changes during a call. It retains reported usage after revocation while returning no draft or usage to the revoked caller. Deleted workspaces are never recreated.
- Invalid artifacts finalize as interrupted with no writing allowance charge. Replay still cannot start a second provider call. Managed trial reservations apply only to managed writing.
- Claude now returns the same artifact/usage envelope as managed writing and can receive a protected host credential through construction. Synthetic process → durable worker → review → independent edit → save → restart passes. This does not qualify the real Claude CLI/API.
- Managed malformed/truncated responses retain reported usage and cannot become accepted candidates. The shared request builder is also used by the review script, so the review includes the exact request body.
- Added a local preparation script and a separate fictional workspace. It never reads provider credentials or sends HTTP. Review output is created exclusively to avoid silently replacing a reviewed payload.

## Validation

- `.phase3-build-venv/bin/python -m unittest discover -s tests -p 'test_postriff*.py'`: **134 passed**, including 31 Phase 3 tests. Counts include the current integrated tree; six new Phase 3 tests were added here. [Log](evidence/runtime-followup-python.log).
- Shared frontend production build, bundled sidecar and macOS Electron packaging passed. [Build log](evidence/runtime-followup-package.log).
- Existing packaged desktop acceptance harness ran outside the development cwd against the rebuilt app: candidate/edit, offline pending text, restart, encrypted vault persistence, revocation, sandbox/IPC assertions, desktop/mobile viewport checks, no page errors and no orphan sidecar passed. Pairing confirmation was injected by the synthetic harness. [Evidence](evidence/runtime-followup-desktop/desktop-acceptance.json). Mobile screenshot inspected.
- Review hashes match the actual adapter request builder; local access token excluded from review; private workspace directory 0700 and access file 0600 checked. ZIP integrity passed. [Audit](evidence/runtime-followup-audit.json).
- [Scoped diff](evidence/runtime-followup-source.patch), with pre-edit files retained under `evidence/runtime-followup-before/`. Git history remains `validation_unavailable`: this installed tree has no Git metadata.
- No frontend or database-schema edits; previous frontend tests/typecheck and local PostgreSQL evidence remain historical checks for those unchanged boundaries, not new hosted acceptance.

## Current package

The app at `desktop/artifacts/PostRiff-darwin-arm64/PostRiff.app` was rebuilt. The original ZIP is preserved; the new delivery is [runtime follow-up ZIP](../../desktop/artifacts/PostRiff-0.3.0-macos-arm64-runtime-followup.zip).

SHA-256: `bab75bcf933eee00accfb7acd7fb35f38db473ae581e4ac24c176b14ece0cf94`.

Still a local macOS arm64 development package without Developer ID/notarization. Windows, physical sleep/wake and real model execution remain unvalidated. The external worker is intentionally not enabled by the desktop fixture launcher.

## Prepared real-run review and remaining input

Use [the prepared request review](managed-writing-prepared-review.json); it supersedes the earlier ephemeral `managed-writing-request-review.json`. Its manifest is retained in the private `.phase3-qualification/fictional.sqlite3` workspace; `local-access.json` there contains only its local fixture access token and must not be exported or pasted into chat.

- Request hash: `d2f0746bed8dd1a651436d25422cb5a0d87d094c508bba5f5c31b68d4700ecae`.
- Proposed one DeepInfra request, English LinkedIn and Traditional Chinese Instagram variants from three fictional garden facts; 2,048 output tokens, 45-second HTTP timeout, no tools/retry/fallback, proposed US$0.05 maximum.
- Account and protected API-key location have been requested but are not supplied. No provider credential was inspected or used.
- Candidate model remains `meta-llama/Llama-3.3-70B-Instruct`; public page retrieval failed and official-domain search found no confirming price. Availability and price remain **unverified**. The [official structured-output documentation](https://docs.deepinfra.com/chat/structured-outputs) confirms API JSON modes generally, not this model/account's availability.
- Before execution, identify the account/key location, verify model availability/current price, then obtain the exact account/payload/cost authorization required by the Phase 3 prompt. If the 15-minute prepared job expires, prepare a fresh job from unchanged canonical state and verify the same manifest/request hashes; do not extend an expired job or reuse a started job. A model/payload change requires a new review.

Full Phase 3 remains incomplete: real route conformance, hosted desktop identity/transport mounting, genuine two-device sync, native integration qualification and inherited Phase 2 live dependencies are still pending. This follow-up does not change those status claims.
