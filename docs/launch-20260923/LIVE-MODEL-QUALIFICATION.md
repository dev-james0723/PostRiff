# Live model qualification — 2026-09-24

Real Vercel AI Gateway calls through PostRiff's own code paths (`ServerModelRuntime` drafting, `request_model` +
`GatewayCall` request reading, deterministic fallbacks). Tool: `scripts/live_model_qualification.py` (budget guard,
synthetic fixtures, nothing stored or published). Credential: the production team's OIDC token (never printed).

**Spend: US$0.1229 of the approved US$3 cap** (139 requests; 84 answered, 55 refused before any work and not billed).
Cost source for every answered call: the gateway's own `usage.cost`.

## Blocker: the team's AI Gateway is on the free tier

| Finding | Evidence |
|---|---|
| Every model we intended to qualify is refused with 403 `RestrictedModelsError` ("Free tier users do not have access to this model") | Claude Opus 5.5, Sonnet 5 (the app's default writer), Haiku 4.5 (the app's request-reading model); GPT-6 Sol, GPT-6 Luna, GPT-5.4 mini; Gemini 3.1 Pro, 3.x Flash, 2.5 Pro |
| Free tier allows only older models | `claude-3-haiku`, `gpt-4.1-mini`, `gpt-4o-mini`, `gpt-5-nano`, `gpt-oss-120b`, `gemini-2.5-flash`, `gemini-2.5-flash-lite` |
| Free tier rate limit: **5 requests per minute per model and region** | 35 × 429 `rate_limit_exceeded` until the tool paced itself |
| Production has no `AI_GATEWAY_API_KEY` | the managed writer is not mounted in production at all |

**Unblock (owner):** buy AI Gateway credits for the Vercel team, create an AI Gateway API key and set it as
`AI_GATEWAY_API_KEY` in Production, then run the strong-tier qualification (≈ US$0.30–0.60 expected, capped):

```
AI_GATEWAY_API_KEY=... python3 scripts/live_model_qualification.py --confirm-spend --cap 2.5 \
  --models anthropic/claude-opus-5.5,openai/gpt-6-sol,google/gemini-3.1-pro-preview,anthropic/claude-sonnet-5 \
  --run strong-1 --failures anthropic/claude-haiku-4.5
```

## What was qualified (best model the free tier allows per family)

| Scenario | Claude 3 Haiku (via Bedrock / Vertex) | GPT-4.1 mini | Gemini 2.5 Flash |
|---|---|---|---|
| Drafting: 2 destinations (en-GB account-bound; zh-Hant-HK), no invented numbers, no hashtags/emoji, limits, citations | PASS | PASS | PASS |
| Chat follow-up (shorter, keep facts) | FAIL: invalid JSON twice → clean failure, cost known | PASS | PASS |
| Structured decision: 5 chat requests → automation or draft (weekday, time, voice, "twice a week", Cantonese) | 4/5 (1 gateway 500) | 3/5 (2 × free-tier 429) | 5/5 |
| Research synthesis (3 web sources, conflicting figures surfaced, both sources cited) | PASS | PASS | PASS |
| Campaign planning (countdown request + countdown draft) | PASS | PASS | PASS |
| Rewrite in the author's voice (VOICE.md: no "!", no "#", sign-off, short sentences) | PASS | PASS | PASS |
| Long context: 16.4k tokens, venue change buried mid-context | PASS | PASS | PASS |
| Deep reasoning (draft + revise pass) | PASS | PASS | PASS |
| Latency p50 / p90 / max (s) | 2.2 / 3.2 / 4.0 | 2.6 / 3.9 / 8.2 | 3.1 / 8.3 / 12.9 |

Every failed structured decision was an infrastructure refusal, not a wrong reading: on each answered call all
three models read the request correctly, and the app falls back to its deterministic reading when the call fails.

Failure paths (Gemini 2.5 Flash-Lite and refused models), all PASS:

- malformed JSON once → one retry → valid draft, cost of both calls known
- malformed twice → run fails, no third paid call, cost known
- output limit reached twice → clean failure, cost known
- restricted model (403) and unknown model id (404) → failure, charged 0
- the app's request-reading model refused → deterministic reading creates the automation

## Defects found by the live runs and fixed (commit `8033255`)

1. A countdown request ("two weeks before, one week before and on the day of 18 October") was read as monthly days
   4, 11 and 18, or as weekdays: an automation that would keep running after the event. The reading now has a
   `countdown` shape mapped to the builder's countdown schedule. Re-run live: all three models read
   `eventDate 2026-10-18, daysBefore [14, 7, 0]`.
2. The chat reply card raised `IndexError` for any countdown schedule (`describe()`); it now words countdowns.

Other observations:

- The gateway reports cost in `usage.cost` / `usage.gateway_cost`. `providerMetadata.gateway` carries only
  `routing` and `generationId`, and only on errors. The runtime already reads `usage.cost` first.
- There is no `finalProvider` on success, so "which provider served this call" is not auditable from the
  response. The `only` restriction is enforced by the gateway: Claude with `only: [anthropic]` was refused, and
  with `[bedrock, vertexAnthropic]` it was served.
- OpenAI refuses `max_tokens` below 16 (the app never sends less than 700).

## Routing decision (provisional; strong tier to be confirmed by the run above)

| Tier | Model | Why |
|---|---|---|
| Strong (default managed writer) | `anthropic/claude-sonnet-5` (US$2/US$10 per M tokens) | unchanged app default; about half Opus's price; ≈ US$0.006 for a typical 2-destination draft, from measured tokens |
| Strong, owner-selectable | `anthropic/claude-opus-5.5` (US$4/US$20) | highest Claude quality; ≈ US$0.012 per typical draft, ≈ US$0.07 at 16k tokens of context |
| Light (request reading) | `anthropic/claude-haiku-4.5` (US$1/US$5) | unchanged; all three families read every answered request correctly, so a light model is enough |
| Fallback: same model, other approved provider | `POSTRIFF_MODEL_PROVIDERS`, e.g. `{"anthropic/claude-sonnet-5": ["anthropic", "vertexAnthropic", "bedrock"]}` | proven live: the gateway honours `only`. Off by default, so data stays with the model maker until the privacy notice lists those processors |
| Fallback: failure | deterministic request reading; drafting fails visibly with its cost recorded | no silent switch to another paid model (FINAL constraint) |

GPT-6 Sol and Gemini 3.1 Pro stay off until the strong-tier run shows their reasoning tokens fit the runtime's
2,400-token output ceiling (reasoning tokens count as output on those routes).
