# Phone call failure repair — 2026-09-27

Execution state: locally implemented and verified; production code release awaiting separate approval. No live call, SMS, customer email/push, credential change or migration was performed in this repair.

Correct production target remains `postriff-phase2-private.vercel.app`, Vercel `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`, Supabase `buoyhkbodnhzngaotoel`. Verified deployed source is `0a7615478d1ba33b82fde7b7e3cf3590d0e85742`, deployment `dpl_FDNsc9yQxRut53yY3NUSgZ6ynWTy`. The isolated repair branch starts at that exact source; the release branch and unrelated worktrees remain unchanged. This receipt supersedes the earlier setup-only receipt's claim of no blockers for live calling.

The user's number is verified and Call Rafii is enabled. The failed production attempt has no accepted provider call identifier, an original reservation of 2,250,000 USD micro, and confirmed Live/telephony costs of zero. The previous policy incorrectly summed original reservations even after settlement, so a zero-cost failure prevented a subsequent ten-minute call under the 3,000,000 daily budget. An immediate second request also encounters the existing five-minute duplicate guard. The screenshot's generic message did not distinguish these policy reasons. The original Twilio HTTP error code was discarded by the adapter; its exact historic rejection reason cannot be recovered from the call row.

Implemented:

- Daily policy uses confirmed component costs once both components settle. Unknown or partial settlement retains the full original ceiling. The request, delivery recheck and Notification V2 attention policy share the same expression. Existing failed rows are corrected automatically without any data rewrite.
- Policy denials explain the actual cause: cooldown, active/uncertain call, daily spending/request limit, provider/Live availability, verification, calling preference and membership.
- The Twilio adapter extracts only a bounded numeric error code and maps it to a provider-neutral failure class. It discards messages, URLs and recipient/credential data. Known rejection stays terminal; ambiguous acceptance still never authorizes redial.
- Confirmed provider failures appear immediately after the response and in recent call history. Unconfirmed responses preserve the original idempotency key. Mobile error text wraps without horizontal overflow.
- Browser Voice, the shared Rafii Agent path, tools, publishing approvals, call limits and scheduled/proactive switches are unchanged.

Files changed: `src/postriff_phase2/phone/{billing,contracts,delivery,service,store}.py`, `src/postriff_phase2/phone/providers/twilio.py`, `tests/test_rafii_phone.py`, `tests/phase2/postgres_phone_mode.py`, `web/src/features/rafii-phone/{call-rafii,phone-settings}.tsx`, `web/src/lib/phone/types.ts`, `web/tests/phone-mode-browser.cjs`, and this receipt.

Migrations added/applied: none.

Validation:

- `PYTHONPATH=src /tmp/rafii-phone-env/bin/python -m unittest tests/test_rafii_phone.py` — 20 pass.
- Same runner with `tests/test_agent_runtime.py tests/test_consumer_deployment.py tests/test_rafii_notifications.py` — 112 pass, including existing GPT-Live/voice and Notification V2 checks.
- `RAFII_PG_PORT=55761 PYTHONPATH=src /tmp/rafii-phone-env/bin/python scripts/rafii_pg_private.py postgres_phone_mode` — pass: budget regression at request/delivery/attention; unknown/partial holds; fake lifecycle/signatures/idempotency; shared text/browser/phone conversation; actual second LinkedIn draft edit; publishing approval; interrupted tool fencing; RLS; credits; number revocation/account deletion.
- Same private PostgreSQL runner with `postgres_unified_notifications` — pass: existing notification consent, policy/outbox, ambiguous responses, signed callbacks, RLS and deletion. No real SMS.
- Node 24 `--test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` — 388 pass.
- `tsc --noEmit --incremental false`, `oxlint src`, copy audit `--check`, `next build` — pass; lint zero warnings/errors, copy zero banned phrases. The first build failed because a temporary dependency symlink was outside Turbopack's root; an isolated filesystem clone resolved that environment issue, and the standard build passed.
- `python3 /tmp/rafii-phone-repair-browser-run.py` — pass on the built app with disposable PostgreSQL and fake Phone/Live: explicit single dial, reload/navigation never dial, actual draft sync, publishing approval, immediate provider failure/history, specific cooldown, retained key, hangup/schedules/revocation, 390px layout and zero serious/critical axe violations. New provider-error UI inputs are local response fixtures, not evidence of real Twilio acceptance. Screenshot `/tmp/rafii-phone-repair-errors-mobile.png` visually inspected.
- `git diff --check` — pass.

External blocker: Twilio account is active/full, but its Primary Customer Profile is still Draft/Individual. Current Twilio rules require an approved Business Primary Customer Profile for +1 calling from newer accounts registered outside US/Canada. The profile and original rejection code must not be treated as already approved/proven live acceptance. The user has been asked to complete the required legal business details and compliance attestation in Twilio Trust Hub. No profile data was changed or submitted. Official reference: https://www.twilio.com/docs/api/errors/21216

Before a live test: approve/release this code fix to the correct existing production project; complete any required Twilio profile approval; confirm final deployment/alias/phone flags; then the user presses Call Rafii once in `/app/account/notifications#phone-mode` after the existing five-minute cooldown. The new error class will identify any remaining provider rejection. A successful paid PSTN/GPT-Live conversation and live draft-edit acceptance remain untested. The agent requires separate concrete paid-call authorization to press that button itself.
