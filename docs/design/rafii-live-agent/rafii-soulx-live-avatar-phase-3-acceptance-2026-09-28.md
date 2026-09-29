# Rafii SoulX Live Avatar — Phase 3 acceptance attempt (2026-09-28)

## Gate decision

**FAIL / release held.** Real CUDA inference, real GPT Live lip sync, interruption, five-minute stability, and visual quality were **NOT RUN**. Do not merge, deploy, or enable the avatar on the strength of the local regression suite. The feature stays default off. This is an access/credential blocker, not evidence that the SoulX model or animation failed.

## Starting state and scope

- Worktree: `/Users/ouxianxing/.codex/worktrees/rafii-soulx-avatar/James-Au-Studio`.
- Starting and final feature implementation tip: `9aeaccab221438a29c8db4f23325bd30ea1e9f45` on `codex/rafii-soulx-avatar-20260928`; Phase 1 `394c2d4`, Phase 2 `69734ca`. No implementation code changed in this attempt; only this acceptance report changed.
- Remote `origin` default/canonical release branch at audit time: `consumer-saas`, `ee688397dd39d9cf3df6c99f22c488fa355b54ee`. It was not modified.
- Read-only production inspection found deployment `dpl_28Qi5dkEdjiSk41K5jJs599eZLSU` in `READY` state on `postriff-phase2-private.vercel.app`, sourced from `consumer-saas` at exactly `ee688397dd39d9cf3df6c99f22c488fa355b54ee`. This matches the audited canonical branch tip. It predates this acceptance attempt and does not contain the SoulX feature.
- Reference: `web/public/raffi/avatar-256.png`, SHA-256 `6ac56752cb008d6dc27640cc53567fd724a4cd9068123289e8705683b88d792f`. SoulX source checkout was at `9bc03de06bb0de82cd6bc477804512ae06144bf2`.
- Pinned model revisions in `scripts/setup_rafii_soulx_lite.sh`: SoulX Lite `59119b6c681230c3eeee157e224ae1941746711e`, wav2vec2 `22aad52d435eb6dbaf354bdad9b0da84ce7d6156`. Neither model was downloaded in this attempt; weights and checksums were not observed.
- GPT Live model configured by the existing Rafii backend: `gpt-live-1`. No Live session was opened.
- `web/.env.example` sets `AVATAR_MODE=disabled`; the config route also hard-disables the worker in production. No flag was enabled in this attempt.

## Paid-resource and credential preflight

- The user explicitly authorized RunPod's GitHub OAuth request for read-only email/profile access, and sign-in completed. The [RunPod Billing screen](https://console.runpod.io/user/billing) showed a **$0.00 balance**, **no payment methods**, and, when a custom **$3** credit amount was entered, the validation message **“The minimum transaction is $10.”** Auto-Pay remained disabled. No card was entered or saved, no charge was submitted, and no pod was provisioned. A $10 required top-up exceeds the approved $3 incremental-spend cap, so the paid path stopped at this gate.
- No `RUNPOD_API_KEY`, `RUNPOD_API_TOKEN`, or `OPENAI_API_KEY` was injected into this task's shell. The existing local Rafii `.env.local` has no `OPENAI_API_KEY` entry. Vercel's **development** environment did not inject one through `vercel env run`; its **production** secret is protected from CLI injection (`37 Secret values cannot be pulled`), and no value was revealed or copied. No delegated billing path was created.
- RunPod access is now verified, but its $10 minimum funding requirement exceeds the hard cap and no authorized usable local Live credential was available. The approved real acceptance run could not start. No GPU deployment was attempted.
- **Actual incremental direct spend: USD $0.00.** RunPod pods created: 0. GPU runtime: 0. GPT Live usage: 0 minutes. Resource termination: not applicable; no paid resource was started. No tunnel was opened.
- Current public list rates, **not incurred**: [RunPod Secure Cloud RTX 4090 $0.74/hour and container disk $0.10/GB/month](https://www.runpod.io/pricing); [OpenAI `gpt-live-1` $0.05/minute, with backend/tool charges separate](https://platform.openai.com/pricing). A two-hour pod and 20 Live minutes would be about $2.49 before account fees/tax or any separate backend calls; the approved $3.00 hard cap still governs an eventual attempt. Account-specific charges must be checked before provisioning.

## Local environment and regression evidence

Host: Apple M3 Pro, macOS arm64; **not** a CUDA host. Node `v24.15.0`, npm lockfile install, Playwright `1.62.1`, Python `3.14.5` from the existing project virtual environment. At preflight the filesystem had about 35–325 MiB free. Disposable npm `_npx` and `_cacache` cache entries were removed after confirming no active process used them; this freed roughly 5 GiB. No source or user data was deleted. `npm ci --no-audit --no-fund` installed the lockfile dependencies in this worktree.

| Check | Final result | Reproducer / evidence |
| --- | --- | --- |
| Avatar and voice Node tests | **PASS**, 25/25 | `cd web && node --test tests/rafii-soulx-avatar.test.cjs tests/voice-opening.test.cjs tests/voice-consent.test.cjs tests/voice-transcript.test.cjs` |
| Fake-engine worker protocol | **PASS**, 5/5 | `/Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python -m unittest tests.test_rafii_soulx_worker_protocol -v` |
| Chromium and WebKit audio worklet | **PASS**, both | `cd web && node tests/rafii-soulx-audio-worklet-browser.cjs`; original speaker path remained active in each browser |
| Chromium and WebKit voice opening | **PASS**, six scenarios | `cd web && node tests/voice-opening-browser.cjs` |
| Chromium and WebKit HTTP/WebSocket worker | **PASS**, both with fake inference | `cd web && PYTHONPATH=/tmp/rafii-soulx-ws RAFII_TEST_PYTHON=/Users/ouxianxing/Documents/James-Au-Studio/.venv/bin/python node tests/rafii-soulx-worker-browser.cjs`; both received two frames and a cancellation acknowledgement |
| Typecheck | **PASS** | `cd web && PATH=/opt/homebrew/opt/node@24/bin:$PATH npm run typecheck` |
| Lint | **PASS**, 0 warnings/errors across 859 files | `cd web && npm run lint` |
| Full production build | **PASS** | `cd web && PATH=/opt/homebrew/opt/node@24/bin:$PATH NEXT_TELEMETRY_DISABLED=1 npm run build`; compiled, TypeScript passed, and all 105 static pages generated. The previous `ENOSPC` validation gap is resolved for this tree. |

First local runs failed for environment reasons: the shared `node_modules` directory lacked `gsap`/`@gsap/react`, so an isolated lockfile install was made in this worktree; the default Python lacked FastAPI, so the existing project virtual environment was used. That virtual environment lacked a WebSocket backend, causing the first browser worker test to reconnect until timeout. `wsproto==1.2.0` was installed only into a temporary test target and the affected browser scenario then passed in both engines. The pinned GPU setup already installs `uvicorn[standard]`; no source change was justified by these local environment issues. These passes use **fake inference** and do not satisfy the real Phase 3 gate.

## Real-run scenario and metric matrix

| Required evidence | Result |
| --- | --- |
| CUDA device/driver/VRAM, torch CUDA, Python/torch versions, SoulX worker health/inference device, exact downloaded weights | **NOT RUN / unmeasured**; no pod or weights |
| A normal user → GPT Live → Rafii audio → real SoulX frame | **NOT RUN** |
| At least ten turns and no old-state replay | **NOT RUN** |
| Five barge-ins, three rapid interruptions, stale-frame rejection with real inference | **NOT RUN** |
| Worker outage, retry/recovery, authoritative voice/audio/tools/text independence | **NOT RUN with real GPT Live**; only synthetic protocol checks passed |
| Session rollover and no cross-session frames/audio/state | **NOT RUN with real GPT Live**; unit coverage passed |
| Continuous five-minute real interaction | **NOT RUN** |
| Neutral, speaking, mouth open/closed, head movement, interruption, return to rest | **NOT RUN**; no real frames for visual judgement |
| GPT audio start, dispatch, first frame/motion, stop/reconnect latency; FPS, dropped frames, GPU/CPU/VRAM/network | **Unmeasured**; no numbers inferred from synthetic tests |

No real-run recording, image sequence, timing JSON, GPU log, or visual acceptance artifact exists. The Phase 2 sampler `web/tests/rafii-soulx-live-acceptance.cjs` remains available for the real session after access is established.

## Smallest next action and release condition

Under the present **USD $3.00** cap, this RunPod account cannot be funded: its minimum credit purchase is $10 and its balance is $0.00. A human must arrange sufficient pre-existing credit without violating the incremental-spend cap, or explicitly revise the budget in a later instruction. Separately, make an already-authorized `OPENAI_API_KEY` available to the Rafii acceptance runtime through a secure process injection; do not paste its value into a chat or file. Only after both blockers are resolved, recheck prices and availability, run the pinned setup on exactly one Secure Cloud RTX 4090, complete the real GPT Live scenarios, five-minute stability test, visual review, and measured report within the then-authorized lifetime/usage limits, and terminate the pod immediately.

Only a **passing** real gate permits integration into the then-current canonical release branch, a second integrated-tree regression/build, push, production deployment at the exact commit, and Phase 4 canary guidance. For this attempt: **not merged, not deployed, default OFF, Phase 4 canary NOT READY**.
