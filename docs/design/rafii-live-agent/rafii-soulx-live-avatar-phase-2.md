# Rafii GPT Live + SoulX Lite: Phase 2 engineering and acceptance

## Status and commits

Phase 1 implementation: `394c2d484bef045dc44c3d42de9111b7b376dbdd`. Phase 2 implementation: `69734ca2e6c6673bddd0ffe672573a547dfb5625`. Both are on `codex/rafii-soulx-avatar-20260928`. Neither phase has been merged or deployed. The avatar configuration route returns `disabled` in production, and unset `AVATAR_MODE` is disabled. Real GPU/GPT Live acceptance is **NOT RUN**. No provider, GPU, model, API, or cloud cost was incurred by this continuation.

## Architecture and failure boundary

```text
real GPT Live remote WebRTC audio track ─────────────→ original <audio> speaker path
                             └→ silent AudioWorklet observer (only when enabled locally)
                                → 16 kHz PCM16 resampler, bounded client queue
                                → protocol v2 (session ID, generation, packet ID)
                                → loopback/SSH-tunneled warm SoulX Lite worker
                                → bounded inference windows → JPEG frames
                                → current-session/current-generation Rafii overlay
```

The existing WebRTC, transcript, tool delegation, interruption, and speaker playback code remains authoritative. The avatar transport never awaits from the Live audio callback. Worker connection, inference, decoding, or rendering failure clears the optional overlay and keeps Live audio running. The browser retries a disconnected worker with capped exponential backoff, sends its current interruption generation before queued PCM on a new worker session, and discards frames from old socket epochs, other session IDs, or old generations. The queue holds at most two seconds of client PCM; the worker holds at most three inference windows. Worker WebSocket sends have a timeout and unattached sessions expire. One active worker session is admitted because the upstream pipeline has mutable conditioning state.

The worker is for loopback or an SSH tunnel only. It has an Origin allowlist but no production authentication. The development config route accepts only a loopback HTTP origin and intentionally never exposes the worker URL in production. A future production deployment requires its own authenticated network design and real acceptance evidence.

## Exact source, models, and reference

- Official source: [Soul-AILab/SoulX-FlashHead](https://github.com/Soul-AILab/SoulX-FlashHead), commit `9bc03de06bb0de82cd6bc477804512ae06144bf2` (clean local checkout inspected).
- Lite weights: [Soul-AILab/SoulX-FlashHead-1_3B](https://huggingface.co/Soul-AILab/SoulX-FlashHead-1_3B), revision `59119b6c681230c3eeee157e224ae1941746711e`. Only `Model_Lite/config.json` (357 B), `Model_Lite/diffusion_pytorch_model.safetensors` (6,107,542,048 B), `VAE_LTX/config.json` (501 B), and `VAE_LTX/diffusion_pytorch_model.safetensors` (1,676,798,532 B) are needed by the Lite path. The Pro/Wan VAE weights are not loaded. The official source describes an RTX 4090 as the one-GPU real-time Lite reference.
- Audio encoder: [facebook/wav2vec2-base-960h](https://huggingface.co/facebook/wav2vec2-base-960h), revision `22aad52d435eb6dbaf354bdad9b0da84ce7d6156`. The custom upstream wav2vec class loads `model.safetensors` (377,607,901 B) and `config.json`; `Wav2Vec2FeatureExtractor` loads `preprocessor_config.json`. Input is 16 kHz. The upstream requirements pin `transformers==4.57.3`; setup also pins PyTorch 2.7.1, torchvision 0.22.1, FlashAttention 2.8.0.post2, and its worker packages. The upstream requirements contain unpinned dependencies; first installation must capture `rafii-soulx-installed-freeze.txt` for repeatable later installs. A CUDA environment has not yet validated the resolved wheel set.
- The worker setup installs `uvicorn[standard]` so a real WebSocket server is present. A direct browser/socket test found and corrected the missing WebSocket backend in a plain Uvicorn test environment.
- Selected existing Rafii image: `web/public/raffi/avatar-256.png`, SHA-256 `6ac56752cb008d6dc27640cc53567fd724a4cd9068123289e8705683b88d792f`. Visual inspection confirms it is the currently shipped, front-facing Rafii raccoon face and hoodie. The larger `full-512.png` is the full-body fallback art, while the 256 px avatar gives SoulX more face area. No new character was invented. SoulX's human-oriented face crop is disabled. Visual suitability of this nonhuman reference is still unverified.

## Setup on an already-authorized CUDA host

The setup script verifies Linux x86_64, NVIDIA visibility, the exact SoulX source commit, and at least 20 GiB free before model transfer. It provisions no cloud resource. Keep both repositories and the model directory on the GPU host; do not commit weights or credentials.

```sh
git clone https://github.com/Soul-AILab/SoulX-FlashHead.git
git -C SoulX-FlashHead checkout 9bc03de06bb0de82cd6bc477804512ae06144bf2
git clone --branch codex/rafii-soulx-avatar-20260928 https://github.com/dev-james0723/PostRiff.git Rafii
export SOULX_REPO_PATH="$PWD/SoulX-FlashHead"
export SOULX_MODELS_DIR="$HOME/models/rafii-soulx-lite"
bash Rafii/scripts/setup_rafii_soulx_lite.sh install
bash Rafii/scripts/setup_rafii_soulx_lite.sh download
bash Rafii/scripts/setup_rafii_soulx_lite.sh check
bash Rafii/scripts/setup_rafii_soulx_lite.sh run
```

The worker defaults to `127.0.0.1:8765`. Set `RAFFII_AVATAR_REFERENCE` to an approved replacement only if visual review shows the selected shipped image cannot work. `SOULX_ALLOWED_ORIGINS`, `SOULX_BIND`, `SOULX_PORT`, `SOULX_SESSION_LEASE_SECONDS`, and `SOULX_SEND_TIMEOUT_SECONDS` are configurable. Check `GET /health` and `GET /ready` through the tunnel. From the local Mac, use `ssh -L 8765:127.0.0.1:8765 <authorized-gpu-host>`; in local Rafii `web/.env.local`, set `AVATAR_MODE=soulx` and `SOULX_AVATAR_URL=http://127.0.0.1:8765`. A `/health` success proves model startup and reachability only, not video quality.

## Timestamp and resource instrumentation

All browser timestamps use `performance.now()` in one tab: first audible GPT Live PCM observed by the worklet, first PCM sent on the worker socket, first worker acceptance acknowledgement received, first generated frame received, and first decoded image observed after a paint boundary. `firstAvatarFrameMs` is first audible PCM to first observed painted frame. `steadyFrameLatencyMs` correlates each displayed frame's `sourcePacketId` with the last contributing PCM packet sent by this browser. `steadyFrameIntervalMs` records displayed-frame cadence. The worker also reports its own first audio receipt to first encoded frame duration; clocks are not subtracted across machines.

Interruption metrics record request, worker cancellation acknowledgement received, final stale-frame discard, observed overlay stop after a paint boundary, and request-to-stop duration. Connection metrics include reconnect duration, queue depth, client audio drops, worker audio sample drops, stale/replaced video frame drops, current worker RSS and change since first reading, sampled CPU usage from process time, and sampled NVIDIA GPU utilization/memory via `nvidia-smi` when present. Browser metrics are exposed as `data-rafii-soulx-metrics` in development. Missing readings remain `null`, not zero.

The optional `web/tests/rafii-soulx-live-acceptance.cjs` opens a headed Chromium or WebKit session, waits for a **real** first avatar frame, then saves five minutes of one-second metrics to a private JSON file. It does not start a paid call or generate fake PCM. A human must sign in, start GPT Live, speak, interrupt, resume, and visually judge quality. Example after cost authorization and worker readiness:

```sh
cd Rafii/web
RAFII_ACCEPTANCE_BROWSER=chromium RAFII_ACCEPTANCE_URL=http://localhost:3000/app \
  RAFII_ACCEPTANCE_OUTPUT="$HOME/rafii-soulx-chromium.json" node tests/rafii-soulx-live-acceptance.cjs
# Repeat with RAFII_ACCEPTANCE_BROWSER=webkit.
```

## Current test matrix

| Check | Result | Evidence / limit |
| --- | --- | --- |
| Phase 1, 15-file scope review and push | PASS | `394c2d4` on origin feature branch; no unrelated changed paths |
| Synthetic bridge/renderer unit tests | PASS | 11 Node tests, including missing-worker retry, reconnect, and stale old-session frame rejection; no GPU |
| Fake-engine worker protocol/health tests | PASS | 5 Python tests; no real inference |
| Chromium + WebKit real HTTP/WebSocket to worker | PASS | Both browsers sent synthetic PCM to a running FastAPI worker with fake inference; frames, cancellation acknowledgement, and new generation arrived. No CUDA or GPT Live. |
| Chromium + WebKit voice opening | PASS | Six existing lifecycle scenarios; no real GPT Live API |
| Voice opening, transcript, stop, and consent unit checks | PASS | 14 existing Node tests; no real GPT Live API |
| Chromium + WebKit worklet capture | PASS | Both browsers, synthetic oscillator; original speaker element remained active |
| Node 24 typecheck and web lint | PASS | Current Phase 2 source; no real GPU |
| Full Next production build | `validation_unavailable` | The Phase 1 source compiled and passed TypeScript, then local `ENOSPC` stopped static page generation. Phase 2 source passed typecheck/lint but a complete build has not run. |
| Real GPT Live audio → SoulX → visible Rafii | NOT RUN | No authorized reachable CUDA host or locally configured Live key |
| Real interruption, resume, five continuous minutes | NOT RUN | Same external boundary |
| Real Chromium and WebKit avatar acceptance | NOT RUN | Same external boundary |

## Real acceptance and quality record

The required sequence is: normal GPT Live conversation; verify the original speaker audio; verify worker receives tapped PCM; verify visible Rafii mouth motion; several turns; interrupt during speech; verify GPT Live stop, SoulX cancellation and no stale frames; resume; then keep the actual call and avatar running for at least five continuous minutes in both applicable browsers. Inspect lip-sync quality, mouth timing, drift, visual continuity, frame stability and reconnect behavior separately. Every real latency, interruption, resource, and quality result is currently **unmeasured / NOT RUN**. The synthetic five-minute buffer-volume test is not a real-time stability run.

## Infrastructure search, cost, and remaining boundary

The local validation environment is Apple M3 Pro (`arm64`), Node 24, and Python 3.14 for fake-engine tests; it has no NVIDIA CUDA. During the search it had about 0.3–2.2 GiB free, below the roughly 8.16 GB of required weights alone. The only configured SSH host, `openclaw-sg`, was reachable but had no `nvidia-smi` and no NVIDIA Docker runtime. Tailscale showed only two phone peers; Docker contexts were local/default and Colima. Searches of relevant source, docs, environment key names, SSH config, cloud CLI/config locations, model cache, and project assets found no usable already-running CUDA worker or existing FlashHead weights. The local worktree had no configured OpenAI Live key; a production credential was not inspected or used. This is a resource and paid-action boundary, not a claim that SoulX works or fails visually.

Cost incurred: **$0**. No GPU was rented, no model weights downloaded, and no real GPT Live/API call was made. A possible later approval is one Runpod Secure Cloud RTX 4090 24 GB Pod with 30 GB container storage for at most two hours, plus at most 20 minutes of OpenAI `gpt-live-1` with no delegated backend/model/tool calls. [Runpod's current price card](https://www.runpod.io/pricing) lists RTX 4090 Secure Cloud at $0.74/hour and container storage at $0.10/GB/month; the two-hour compute estimate is $1.48 and prorated storage is under $0.01. [OpenAI lists GPT Live 1](https://developers.openai.com/api/docs/models/gpt-live-1) at $0.05/minute, so 20 minutes adds $1.00. Estimated total is under $2.49 before any account minimum, tax, or separately billed backend delegation. A proposed $3 authorization cap would require stopping before any extra backend call or charge. Check rates and account requirements again at action time; do not create that resource or start a call without explicit approval. Keep the feature branch default-off and unmerged until the real acceptance record exists.
