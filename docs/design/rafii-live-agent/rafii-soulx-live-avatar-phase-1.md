# Rafii Live → SoulX FlashHead avatar, Phase 1

## Status and source

This is a local proof of concept on branch `codex/rafii-soulx-avatar-20260928`, based on Rafii HEAD `a6033925bd8c94b8f8b98efea48741fb57f110da`. The official SoulX source checkout is `/Users/ouxianxing/Documents/SoulX-FlashHead`, HEAD `9bc03de06bb0de82cd6bc477804512ae06144bf2`, `origin=https://github.com/Soul-AILab/SoulX-FlashHead.git`, Apache 2.0. The [official model card](https://huggingface.co/Soul-AILab/SoulX-FlashHead-1_3B) also labels the FlashHead weights Apache 2.0; the wav2vec dependency has its own terms. No SoulX model weights were downloaded by this task. The previous local search found SoulX-Singer but no SoulX-FlashHead checkout, so the official source was cloned separately. The M3 Pro host has no NVIDIA CUDA device; **real SoulX inference and Rafii visual fidelity have not been demonstrated**. The protocol tests use a fake inference engine, not a substitute for a CUDA smoke test.

## Existing Live path, verified in source

```text
microphone → getUserMedia → RTCPeerConnection.addTrack
                         → Rafii voiceStart SDP relay → OpenAI GPT Live
                         → remote WebRTC audio track → hidden <audio> (speaker)
                                                     └→ AudioWorklet tap (observer only)
                    oai-events data channel → transcript/delegation/session events
                                             → existing agent/turns delegation, tool routing
```

`web/src/lib/agent-runtime/live-transport.ts` creates the peer connection and speaker element. `voice-session.ts` owns the one Live call, opening, user/assistant transcript events, delegation to the existing `agent/turns` API, `stopSpeaking`, reconnect, and close. The GPT Live data channel contains transcript and control events, but the actual assistant audio is a **remote media track**, not `session.output_audio.delta` in the browser. The new tap connects a silent `AudioWorkletNode` to the same `MediaStreamAudioSourceNode`; the original `<audio>.srcObject` keeps normal playback. No additional LLM or TTS is invoked.

## Avatar flow and lifecycle

```text
GPT Live remote track ───────────────→ existing <audio> playback
            │
            └→ worklet mono Float32 packets (~2048 source samples)
               → per-call AvatarSession + 16 kHz PCM16 resampler
               → bounded SoulXRenderer WebSocket queue
               → warm SoulX Lite worker, rolling eight-second audio context
               → JPEG frames over WebSocket, one response generation ID
               → SoulX overlay in existing Voice Mode / GLB fallback
```

The `AvatarRenderer` interface isolates the SoulX transport from Live and can later admit a native GLB renderer. Each `AvatarSession` has its own resampler, turn generation, subscriptions, metrics, and renderer. The browser presently opens one Live session per tab. The Phase 1 CUDA worker admits one active session because upstream `FlashHeadPipeline` holds mutable conditioning and motion state; a second session gets HTTP 503 instead of cross-user audio leakage. Its session buffers remain isolated. Future concurrency needs separate model instances or a scheduler with safe state restoration.

The browser asks `/api/rafii/avatar/config` for `AVATAR_MODE` and `SOULX_AVATAR_URL` concurrently with Live connection setup. `disabled` does not attach a tap or start a worker. In `soulx` mode the worker starts a session, opens the stream, and accepts incremental audio. The client queues at most about two seconds before the socket opens; longer startup drops oldest avatar audio while Live speaker playback continues. The worker queues at most three inference windows and drops old audio under load. The upstream Lite `frame_num`, `motion_frames_num`, sample rate and FPS come from `flash_head/configs/infer_params.yaml`; the checked-out config specifies 16 kHz, 25 FPS, and an eight-second cached audio context. The demo's complete-file loading, WAV files and MP4 segments are not used.

On user transcript speech, Stop talking, or Live disconnection, `AvatarSession.interrupt()` increments a monotonic generation, clears the visible frame and local audio state, and sends an interrupt control message. After 1.5 seconds without audible output, the browser also retires the turn so late frames cannot reopen the mouth. The worker clears its pending audio and discards any result returned by an already-running CUDA inference for an older generation. The browser also rejects any stale frame, even if it arrives after the interrupt. GPT Live's existing barge-in and output mute continue to control **audio**. The avatar resumes only with a new assistant response. The first-frame boundary is affected by the upstream inference window, so the <800 ms preference may require a later model or buffering strategy change. The exact Live transcript event timing relative to the first microphone phoneme has not been measured.

## Worker protocol

- `GET /health` reports readiness, model, sample rate, inference window, and active sessions.
- `POST /session` creates one isolated session and returns `id`, `sampleRate`, `windowSamples`.
- `WS /session/{id}/stream` carries both input and output. Binary input is four-byte little-endian unsigned generation followed by signed 16-bit little-endian mono PCM at 16 kHz. Each packet is bounded to two seconds. Text control is `{"type":"interrupt","generation":N}`. Worker messages include `audio_accepted`, `metrics`, `frame` (generation, sequence, JPEG base64), `interrupted`, and `error`.
- `DELETE /session/{id}` ends a session. Closing the WebSocket also closes it.

The worker binds to loopback by default, checks browser Origin, and allows `localhost:3000` and `127.0.0.1:3000` unless configured. The browser receives the configured worker URL from a local-development-only Next route. This POC has no production worker authentication: expose the port only on loopback or through a local SSH tunnel. The Next config route returns `disabled` in production, even if environment variables are present.

## Setup

Normal Live behavior: leave `AVATAR_MODE=disabled` (default when unset). A fresh Rafii web checkout needs its normal `cd web && npm ci` setup. For a local CUDA machine or a remote CUDA worker reachable through a local tunnel, set in `web/.env.local`:

```dotenv
AVATAR_MODE=soulx
SOULX_AVATAR_URL=http://127.0.0.1:8765
```

In a separate Python 3.10 CUDA environment, install the [official SoulX requirements](https://github.com/Soul-AILab/SoulX-FlashHead/blob/main/README.md) and `fastapi` and `uvicorn`. Configure the worker with **external** model/cache paths; do not place weights in the Rafii repository:

```sh
export SOULX_REPO_PATH=/path/to/SoulX-FlashHead
export SOULX_CHECKPOINT_DIR=/path/to/SoulX-FlashHead-1_3B
export SOULX_WAV2VEC_DIR=/path/to/wav2vec2-base-960h
export RAFFII_AVATAR_REFERENCE=/path/to/approved/rafii-reference.png
export SOULX_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
python scripts/rafii_soulx_worker.py
```

Run that final command from the Rafii checkout, with the CUDA environment active. The worker changes its own working directory to the configured SoulX source because upstream inference reads a relative YAML path. It loads the Lite pipeline and reference conditioning once at startup, then stays warm. For a remote GPU, run the worker bound to `127.0.0.1:8765` on the GPU host and forward it with `ssh -L 8765:127.0.0.1:8765 <gpu-host>`. The browser and Next app then use the same local URL; no GPT Live code or OpenAI session settings change. Do not interpret `/health` as evidence that a Rafii frame passed visual review.

## Rafii reference image and visual review

The existing canonical `web/public/raffi/full-512.png` is a transparent, full-body raccoon illustration with a small closed mouth. It is a plausible **reference candidate** but is not a face-framed human portrait. Supply a legal, approved local reference via `RAFFII_AVATAR_REFERENCE`. The worker sets `use_face_crop=False` so SoulX's human face detector does not silently substitute a crop; it also converts the PNG to RGB as upstream code does. The canonical art remains untouched. CUDA visual review must record muzzle and mouth deformation, eye and ear stability, fur/marking consistency, framing, and identity drift over several turns. **No such visual result exists yet.**

## Failure behavior and measurements

If configuration is disabled, the Live path is unchanged. If SoulX fails to connect, infer, or stream, the avatar state becomes `offline`, queued video is discarded, and the existing GLB/static Rafii surface remains visible; Live audio, tools, transcript and session lifecycle continue. The browser WebSocket queue and worker audio queue are bounded. A slow worker can cause frame lag or drops without causing speaker playback to wait.

The client snapshot records `audioToWorkerMs` as first captured audio to the worker's **acknowledgement received** (an upper bound including return network time), `workerFirstFrameMs` as the worker's first audio receipt to its first encoded frame, `firstAvatarFrameMs` as first captured audio to image load plus a paint frame, average received FPS, queue depth, actual dropped video frames, separately counted dropped browser audio packets and worker audio samples, and `interruptToStopMs` as interrupt to the next browser paint. In development, inspect `data-rafii-soulx-metrics` on the avatar layer. These values have **not** been measured with real CUDA inference; no claim of meeting 800/1500 ms, 500 ms interruption, lip sync, or five-minute stability is made. Remote clock skew does not enter these elapsed-time values, but the acknowledgement metric includes round-trip delay.

## Verification and next phase

Release hygiene recheck on 2026-09-28: all 15 changed paths belong to this optional avatar slice. The three Python fake-engine protocol tests, nine Node avatar/bridge tests, six Chromium/WebKit voice-opening scenarios, both Chromium/WebKit audio-worklet checks, Node 24 typecheck, and full web lint passed. A fresh production build compiled and passed TypeScript, then failed during static page generation with `ENOSPC` on the local disk; the generated `.next` output was removed. Thus a complete fresh production build is **validation_unavailable** for this commit. No real CUDA or GPT Live acceptance was run.

Before changes, the focused voice/frontend tests passed 16/16. After changes, the existing focused voice tests plus bridge/config/buffer tests passed 25/25; the six Chromium/WebKit voice-opening lifecycle scenarios passed; the actual audio worklet captured synthetic media streams in Chromium and WebKit while their original speaker elements stayed active; typecheck, lint, Python compilation and the Next production build passed; and three fake-engine/core worker protocol and buffer tests passed. A synthetic five-minute volume test confirmed that the pending audio buffer stays capped at three seconds; it is not a five-minute real-time inference run. An earlier build encountered a Turbopack cache write warning while the host disk was nearly full; the final build exited successfully without that warning. Temporary dependencies, Python test environment, and build artifacts were removed afterward. These are integration checks, not real GPU inference. The remaining Phase 1 acceptance requires a CUDA host with the configured Lite and wav2vec weights, a reference image reviewed for rights and suitability, a live GPT Live call with actual voice audio, a visual lip-sync check including interruption, and a timed five-minute run. Measure the actual t0–t3 and drift before choosing any performance optimization. If the raccoon face deforms, compare against the existing GLB renderer and consider a specialized non-human visual model in a later phase.
