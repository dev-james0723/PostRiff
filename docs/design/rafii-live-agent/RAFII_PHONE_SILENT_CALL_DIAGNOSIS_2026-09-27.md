# Rafii silent phone call: diagnostic candidate

## Verified production result

PR [#41](https://github.com/dev-james0723/PostRiff/pull/41) is merged and deployed as production source `6cdfe8fdf7011ca0ac0f2c8fb281caca3e73e64d`. The approved real test reached the verified phone ending 0208 on 2026-09-27. Twilio recorded an eight-second answered call (20:20:03–20:20:11 UTC) and US$0.014 Voice cost. This is one cost component, not the total provider bill. The user confirmed no sound. Rafii records the call as failed; its public failure field is null. The app sent the provider hangup request.

The exact media/Live failure cause is still unknown. Existing media exceptions and Live error events did not record diagnostic details. This candidate does not claim to repair real-call audio.

## Candidate scope

Start from the exact deployed production commit. Add bounded diagnostics for runtime initialization, signed stream handling, controller initialization, Live connection/start/events, phone audio transfer and session guards. Record only a valid internal call UUID, a fixed phase, a known exception class, HTTP status and allowlisted error code/type/parameter. Drop exception text, stack traces, response bodies, phone numbers, audio, transcripts and credentials. Normal `session.closed` completion emits no failure warning.

Preserve the existing failed-call hangup, usage settlement and unknown usage holds. No settings, credentials, model, provider, spend cap, duration cap, schedules, proactive calls, schema, permissions or browser voice changes.

## Local validation

- 139 focused Python tests passed, including seven new media checks using installed OpenAI SDK 3.19.2 over a loopback WebSocket and the actual TwilioMediaTransport. Synthetic server events verify PCMU audio in both directions, final usage, admission failure, HTTP 401, early close, callback failure and private-payload redaction.
- Disposable PostgreSQL Phone Mode suite passed: actual shared Rafii runtime and database, signed ASGI audio roundtrip, draft edits, approval and identity boundaries, hangup fencing, unknown usage, idempotency and budget settlement. External telephony and model services remain synthetic.
- No second real call has been placed. The user's one retry approval is unconsumed.
- A read-only production ledger check was unavailable because the Supabase connector denied permission. No credential export or alternate privileged query was attempted.
- The pre-existing production cron TypeError remains unresolved. The diagnostic candidate does not change or invoke cron.

Structured receipt: [verification.json](evidence/phone-live-diagnostics-2026-09-27/verification.json).

## Release and retry boundary

The earlier deployment approval was executed for PR #41. This is a new production source change and awaits scoped deployment approval under the project's AGENTS.md. After approval, deploy only the reviewed candidate, verify its source and production alias, then use the already-approved retry to phone ending 0208 for roughly one minute, within the existing ten-minute maximum and configured US$3 daily ceiling. Keep scheduled and proactive calls off. A successful provider call record alone is insufficient: confirm that the user hears Rafii and receives a reply to speech.

If the retry fails, reconcile it and inspect the bounded diagnostics before any further paid call. Do not consume another retry, erase unknown holds, expand spending or alter credentials without the relevant authority.
