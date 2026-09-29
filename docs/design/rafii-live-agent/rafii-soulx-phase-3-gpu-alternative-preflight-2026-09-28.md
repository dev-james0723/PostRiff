# Rafii SoulX Phase 3: alternative GPU and credential preflight (2026-09-28)

## Decision and exact state

**Release held. Real Phase 3 acceptance is still NOT RUN.** This continuation found an existing Google Colab account with 200 compute units, but the account is stopped at its own Terms of Service agreement before a runtime can be inspected or started. No GPU was provisioned, no SoulX weights were downloaded, no GPT Live session was opened, and no real inference or lip-sync metric was measured. Actual incremental direct acceptance spend remains **USD $0.00**. Avatar remains default-OFF. The feature is neither merged nor production-deployed.

Preflight checkout: `codex/rafii-soulx-avatar-20260928` at `9d8a4ca592ac9dd2cd39691d852fbbb91557829f`, clean and identical to `origin/codex/rafii-soulx-avatar-20260928` before this note. The remote default branch was `consumer-saas` at `ee688397dd39d9cf3df6c99f22c488fa355b54ee`. The earlier [Phase 3 attempt](rafii-soulx-live-avatar-phase-3-acceptance-2026-09-28.md) records the passed local regressions and the unrun real gates. No product source changed in this continuation.

## Cheapest observed account path

- **Google Colab:** In the signed-in account, Colab's plan page showed **200 existing compute units** under the current Google AI plan. No additional credit purchase is required to consume those units. GPU type, availability, unit burn, and ability to run the pinned workload remain unverified because opening a notebook displayed **Review Terms of Service**. Accepting that legal agreement is a human-only step. The Colab tab was left open for the account owner. [Google's FAQ](https://research.google.com/colaboratory/faq.html) says GPU availability and runtime limits vary; the displayed balance alone is not a GPU allocation or a stability pass.
- The official [Google Colab CLI](https://github.com/googlecolab/google-colab-cli) version `0.7.4` was fetched to the local `uvx` cache and its `new`/`ssh` help was checked. It supports requesting an L4 and a WebSocket-backed SSH ProxyCommand. After account access, that would permit a local `ssh -L 8765:127.0.0.1:8765` tunnel to a loopback-bound worker, without publishing the worker or uploading a private SSH key. This transport is researched, **not exercised**.
- **Expected incremental GPU cash cost:** $0 if an eligible GPU is supplied from the already available units, with compute-unit consumption to be measured. The GPU's actual unit rate and availability are not known yet. The pinned Lite source and weights, CUDA device, inference speed, and visual quality must all be checked on the allocated host. The pinned setup currently requires Linux x86_64 with NVIDIA CUDA and at least 20 GiB free for transfer/cache.
- **GPT Live direct cost:** [OpenAI lists `gpt-live-1` at $0.05 per minute, billed per second](https://developers.openai.com/api/docs/models/gpt-live-1), with delegated backend calls billed separately. A five-minute session would cost at least about $0.25; a 15-minute acceptance window would cost about $0.75 before any backend use. These are estimates, **not incurred charges**. The $3 total hard cap still applies to the combined GPU, Live, backend, tax, and any other direct acceptance charges.

## Other paths checked

- Local Apple M3 Pro is `arm64` with Metal, no NVIDIA CUDA. The only configured SSH host (`openclaw-sg`) still reports no `nvidia-smi` or NVIDIA container runtime. Tailscale lists only two iOS peers. Neither can run the pinned Linux CUDA setup as-is.
- Existing RunPod account has $0 balance and requires a $10 minimum credit purchase, as recorded in the previous attempt. [Vast.ai advertises a $5 starting credit](https://vast.ai/), still above the cap.
- [Modal Starter advertises $30 monthly free compute credits](https://modal.com/pricing), and an L40S at $0.000542/second, but [Modal requires a valid payment method for GPU use](https://modal.com/docs/guide/gpu). No existing Modal session or local token was found. A new GitHub OAuth grant would share read-only GitHub email addresses; that grant has not been authorized or completed. Modal is a fallback only after account access and an enforceable $3 aggregate budget are verified.
- The existing Google Cloud project `rafii-509720` showed **no linked billing account**, and Compute Engine API was not enabled. No project setting was changed or VM started. Replicate's [prepaid-credit requirement](https://replicate.com/docs/topics/billing/prepaid-credit) does not establish a cheaper ready arbitrary CUDA worker for this account.

## GPT Live credential status

`OPENAI_API_KEY` and alternative provider token variable names were absent from this task's shell. The checked feature checkout has only example env files; the main repo's local `.env.local` has no relevant key. No matching OpenAI generic-password entry was found in the inspected macOS Keychain service names. The linked Vercel project lists `OPENAI_API_KEY` as a **protected Production secret**; Development and Preview list neither `OPENAI_API_KEY` nor `AI_GATEWAY_API_KEY`. Its value was not read or copied, and the Production presence does not prove that a local acceptance run can use it.

The Rafii browser normally sends a WebRTC offer to its authenticated backend, which holds the OpenAI key. A local development frontend could in principle proxy `/api` to the existing production backend while serving the feature branch locally, but authenticated local sign-in, route compatibility, cost guardrails, and use of that production secret for this acceptance run have **not** been verified. An already authorized key securely injected into the local acceptance backend is the other route. No credential was created, rotated, printed, logged, or committed.

## Next execution boundary

1. The account owner reviews and personally accepts the Colab Terms of Service if they choose. Then verify available NVIDIA GPU type/VRAM, CUDA, free disk, compute-unit debit rate and any CLI OAuth scope before allocating. Use existing units only; never purchase more.
2. On a qualifying runtime, run the exact `scripts/setup_rafii_soulx_lite.sh` source/model revisions, record checksums, GPU and Python/torch versions, run **real** inference, and establish the private SSH tunnel. Stop the runtime when finished.
3. Resolve GPT Live through an authorized backend credential path without exposing a secret. Limit Live time and delegated work so the total direct spend cannot exceed $3. Then run the real normal, barge-in, resume, repeated-turn, five-minute, failure/reconnect, latency and visual checks in the prior Phase 3 matrix.
4. Only a complete real PASS allows the integrated regression, acceptance-record update, commit/push, merge, exact-commit production deploy and production verification. On the present evidence, none of those release steps is authorized by the gate.

Token Pilot's existing records do not provide a controlled before/after pair for this exact acceptance task with matched inputs, model, environment and verification. A reproducible token-saving figure cannot be derived from this preflight; session usage, if reported separately, is not a causal savings measurement.
