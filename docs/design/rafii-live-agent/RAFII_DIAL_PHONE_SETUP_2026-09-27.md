# Rafii → Dial phone integration

Execution state: **locally implemented and tested; Self-Hosted access reported granted; account configuration, deployment and real calls are pending**.
Candidate branch: `codex/dial-access-finalization`, based on `feat/rafii-dial-phone` and the current local `origin/consumer-saas`.
The [verification receipt and evidence](evidence/dial-phone-2026-09-27/verification.json)
pin the tested files and distinguish local checks from pending external execution.
The original Dial implementation started from `origin/consumer-saas` at `d5bb9d6`,
with Phone Mode repair `eacba35` cherry-picked as `e7ee572`. This candidate also merges
the current local `origin/consumer-saas` at `1afda4a`; other worktrees were preserved.

## What changed

Set `RAFII_PHONE_PROVIDER=dial` to select Dial. The existing phone settings, call button,
verified encrypted number, conversation, agent runtime, tools, approval rules, credit limits,
ledger and cron remain the entry points. Dial carries μ-law audio; GPT-Live and Rafii's
existing `AgentRuntimeService.turn` drive the conversation. There is no managed-agent fallback.
Twilio's adapter remains available for rollback, but Dial needs no Twilio credentials.

Before each new call, server GETs check Dial's granted access, active audio mode, exact
WSS URL, codecs, outgoing line availability and free-account duration ceiling. Each create
uses `Idempotency-Key: rafii-phone:<local-call-id>`. Lost results are reconciled with GETs and
an exact server-generated correlation instruction; there is no automatic redial.

Dial's audio protocol has no human/voicemail metadata. A stock public greeting asks the
recipient to press 1. Only then may Rafii open its Live session and workspace context.
Another digit or timeout ends the call without a Live session. The existing agent speaks
in its configured language after acceptance; the stock acceptance prompt is currently English.

Signed audio connections bind provider call ID, originating line, verified destination,
local call ID, state and a single media claim. Signed account webhooks use exact raw bytes,
five-minute freshness and event-ID deduplication. Raw numbers, provider bodies and OTPs
do not enter public call records. SMS verification stores only a number-bound keyed digest
and preserves existing ten-minute/five-attempt/rate limits.

## Account requirement

Dial's **Self-Hosted audio mode requires per-account human approval**. It routes **all new
inbound and outbound calls on that Dial account** to the selected server. Use a dedicated
Rafii account/line. This integration accepts only outbound calls already authorized in Rafii;
unsolicited inbound calls receive no workspace access. Calling configuration remains unchanged.

The user-selected email and personal SMS number were verified through Dial's dashboard on
2026-09-27. Sign-in succeeded and Dial automatically provisioned **+16055978162** with SMS
and Voice capabilities and Calling On. An existing default API key is available in Settings;
it has not been exported or saved to Rafii's server environment. There are no webhooks.

Account evidence from the signed-in dashboard:

- After the user's explicit approval, the Self-Hosted request below was submitted once on
  2026-09-27. The user subsequently reported that access was granted. In the signed-in
  dashboard, the Self-Hosted page now exposes the Audio mode WebSocket configuration,
  Save and Enable controls. Audio mode remains **Disabled**, with no WebSocket URL or
  signing secret saved. A credential-backed `GET /api/v1/self-hosted` check has not yet
  confirmed the account's `access` value; that check is still required before activation.
- The number is **not registered for 10DLC**. Outbound US SMS/MMS is blocked; voice and inbound
  texts are unaffected. Rafii's new-user SMS verification for US numbers needs registration
  before launch. The dashboard quotes a **one-time $25 fee** and **3–5 business days**;
  registration and payment have not been submitted. The registration flow requires a
  confirmed sole-proprietor or business identity, brand/contact/address details, and the
  campaign's consent flow and sample messages. These details must come from the account owner.
  The user selected **sole proprietor (no EIN)**. The browser draft selects **Technology**;
  legal name, trading name, a US/Canadian registered address and carrier contact confirmation
  are pending. The carrier will text the contact mobile in 1–2 business days and requires a
  **YES** reply within 24 hours. The $2 balance is below the $25 submission fee.
- Billing shows **$5 welcome credit**, **$3 deducted for the first month of number ownership**,
  and **$2 remaining**. The line costs **$3/month plus usage**. No payment method is attached,
  auto-reload is off, and new spend pauses at a zero balance.
- Free accounts are capped at **5 minutes per call** and **2 simultaneous calls**. Audio-mode
  and destination-specific metered rates still need confirmation before a live call.

The provider readiness check reports `smsReady: false` and the 10DLC registration state when
US carrier registration is incomplete. This diagnostic does not block voice calls to users
whose Rafii numbers are already verified; all existing consent and spending gates still apply.

After that local merge, 49 focused Dial, Phone Mode, media and deployment unit tests pass.
The no-secret local setup check still reports `configuration_pending`: Dial credentials,
the public origin, encryption key and telephony rate are absent from this worktree.
It has not made a credential-backed provider GET, activated Audio mode or placed a call.
The local privacy notice and public legal data now name Dial, the optional Twilio path,
GPT-Live and phone retention. These are candidate disclosures for release review; no
public page has been redeployed. Nineteen related privacy/data tests pass.

The Self-Hosted access request was submitted and the user reports approval. No 10DLC
registration, webhook registration, mode activation, deployment or live call has been submitted.

The [10DLC candidate](RAFII_DIAL_10DLC_CANDIDATE_2026-09-27.json) is **not ready to submit**.
Its sample SMS includes proposed opt-out wording that is not yet in the runtime. Before
filing it, implement or officially verify STOP suppression, deploy the matching SMS consent
notice, and review the messaging privacy/terms. Dial's checkbox to publish notices in the
operator's name remains unchecked. Do not present a proposed message/consent flow as deployed.

Submitted access-request text:

> Rafii is our authenticated social-media assistant. We want it to call verified users
> who request a call, and later users who explicitly opt into scheduled briefings. Our
> existing Rafii server must drive the call using the same conversation, memory, tools,
> workspace permissions, publication approvals and spending limits. We need Self-Hosted
> audio mode to connect that existing agent and voice stack. We do not record call audio.

The documented request is `POST https://api.getdial.ai/api/v1/self-hosted` with
`{"action":"request_access","useCase":"<reviewed text>","companyUrl":"<confirmed public company URL>"}`.
Do not use the `/v1/...` shorthand shown in some guide examples; the OpenAPI base is `/api/v1`.

## Server setup after access is granted

1. Drain and settle existing Twilio calls before changing the runtime provider. Reconcile
   unknown calls and retained holds; do not pretend those calls belong to Dial.
2. Keep all `RAFII_PHONE_*_ENABLED` egress flags off while preparing the deployment.
3. Configure only server-held values: `DIAL_API_KEY`, `DIAL_PHONE_NUMBER` (an owned standard
   SMS/call E.164 line; iMessage lines cannot force the SMS rail), `DIAL_AUDIO_SIGNING_SECRET`, `DIAL_WEBHOOK_SIGNING_SECRET`,
   `DIAL_VERIFICATION_SECRET` (at least 32 random characters), existing phone encryption key,
   public HTTPS origin, country allowlist, model credentials and a verified telephony rate ceiling.
   No `NEXT_PUBLIC_*` secret. Preview deployments still prohibit calling/SMS and require
   deliberately pinned staging fingerprints for every Dial secret.
4. Reconcile migration numbering at merge, then apply `036_dial_phone_provider.sql` through
   the normal authorized migration process. It adds `dial` to the existing private ledger
   check constraint; migration 033 is not rewritten.
5. Deploy the candidate with the dedicated ASGI media service. Dial's route must precede the
   broad `/api/*` rewrite. Existing 660-second media-function duration remains required.
6. Save Dial's audio config using `POST /api/v1/self-hosted`:

   ```json
   {"action":"save","config":{"type":"audio","wsUrl":"wss://YOUR_RAFII_DOMAIN/api/phone/dial/media","audioInboundFormat":"mulaw_8000","audioOutboundFormat":"mulaw_8000"}}
   ```

   Retrieve that mode's signing secret securely into the server environment. `save` does
   not activate the account. Review and authorize the account-wide `activate` separately
   once the deployed server is ready; its config body is identical apart from `action`.
7. Register one account webhook for `call.status_changed` and `call.ended` at
   `https://YOUR_RAFII_DOMAIN/api/phone/dial/events`. Store its separate signing secret on
   the server. A signed `webhook.ping` is supported. Reconcile existing subscriptions before
   creating one to avoid duplicates.
8. Run the read-only setup check, then explicitly approve the deployment's calling/SMS
   switches. Scheduled/proactive flags stay off until separately enabled by policy and user opt-in.
9. Sign into Rafii, verify the chosen recipient's number through SMS and enable Call Rafii.
   Approve one test call with its exact recipient, content and spend ceiling. Verify the
   ringing phone, press-1 gate, spoken Rafii reply, same conversation/tool result, hang-up,
   signed final event and settled usage. Only that evidence establishes a working live call.

```sh
PYTHONPATH=src .venv/bin/python scripts/check_rafii_dial.py --env-file /path/to/server.env
PYTHONPATH=src .venv/bin/python scripts/check_rafii_dial.py --env-file /path/to/server.env --provider-read-only
```

These commands only inspect configuration/GET account state. They never activate an account,
send an SMS, place a call or deploy. The default run currently reports `configuration_pending`.

## Rates and limits

The public [pricing page](https://getdial.ai/pricing) lists $3/month per number, US SMS at
$0.02/message and self-hosted calls from $0.13/minute. Its self-hosted explanation describes
the **LLM** variant; confirm the audio variant's destination-specific account rate and billing
rounding before setting `RAFII_PHONE_USD_MICRO_PER_MINUTE`. GPT-Live adds its existing model
cost. Do not infer a free audio tier or treat starter credit as authorization to spend.
Dial's account API supplies the free-account call cap; the adapter caps each call accordingly.

## Validation and limits

All HTTP, SMS and model events in these checks are synthetic. PostgreSQL, auth fences,
ASGI sockets, conversation writes, actual draft commands and usage settlement are real local execution.

- Focused unit contracts: **58 passed** across Dial/Phone Mode/deployment/preview/migration checks.
- `postgres_dial_phone.py`: passed signed audio, generic greeting/keypad gate, same-conversation
  real draft edit, reply, hang-up, both settled reservations, signed duplicate/out-of-order events,
  lost create response without another call, cross-worker end and decline without a model session.
- Existing `postgres_phone_mode.py`: passed text/browser/phone continuity, publish approval,
  opt-out and membership fences, limits, credit holds, uncertain outcomes, RLS and account deletion.
- Audio: locally generated mono μ-law/8 kHz stock prompt; duration 5.886 seconds; decoding checked.
- Official Dial OpenAPI validates the generated call and SMS bodies; the official Vercel schema
  validates routing/configuration. SMS uses the standard line's default rail, not an unsupported `channel: sms` field.
- Hosted routing/packaging structure and migration-number tests pass. Full release CI and a
  deployed archive were not run; production and live calling remain unverified.

Hang-up uses the documented `end_call` audio frame and authoritative GET/webhook confirmation.
The public REST spec has **no cancel endpoint**. A call still ringing may remain `ending` until
it connects to the media host or terminates; retain its reservation and avoid another call.
Mid-call reconnect is deliberately ended rather than creating a second model session or
replaying tool effects. Automatic session resumption is a future enhancement.

## Primary references checked 2026-09-27

- [Self-Hosted modes and approval](https://docs.getdial.ai/documentation/platform/self-hosted)
- [Audio protocol](https://docs.getdial.ai/api-reference/self-hosted-audio-protocol/overview)
- [Call creation and idempotency](https://docs.getdial.ai/api-reference/rest-api/calls/make-call)
- [Webhook signatures](https://docs.getdial.ai/documentation/platform/webhooks)
- [Call status event](https://docs.getdial.ai/api-reference/events/call-status-changed)
- [Final call event](https://docs.getdial.ai/api-reference/events/call-ended)
- [Current OpenAPI](https://docs.getdial.ai/openapi.json)

Vercel Marketplace read-only messaging discovery returned Resend only, with no Dial integration.
The user explicitly selected Dial; this candidate uses Dial's official REST/audio surface directly.
