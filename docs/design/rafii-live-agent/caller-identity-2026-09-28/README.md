# Rafii Phone caller identity — local implementation receipt

> **Superseded authentication design:** hosted Supabase rejected the WebAuthn-MFA enrollment used by
> this historical candidate. The supported passkey-sign-in repair and current activation boundary
> are recorded in [the passkey identity receipt](../passkey-identity-2026-09-28/README.md). The
> evidence below remains a record of the original caller-routing candidate, not approval to release
> its WebAuthn-MFA flow.

Status: **release candidate committed and initial branch push completed; automated regression and human audio audition passed. Production migration/deployment and real-device gates remain pending.**

Worktree: `/Users/ouxianxing/.codex/worktrees/rafii-caller-identity/James-Au-Studio`.
Current integration base: `a25bb459b7676bdaec8c007c9f6096ac45a8ed3b`. The release branch is `codex/rafii-phone-caller-identity`. The requested voice-opening worktree was clean at `eefff65`, not the historical dirty `84165f1`, and remains untouched. See [source reconciliation](source-state.md).

## Plan execution

| Task | Result |
|---|---|
| 0 Current source/ownership | Reconciled; isolated worktree from current voice source; no reset/stash/overwrite of owner work. |
| 1 Pairing terminology | Source and installed manifests use Agent Pairing Code; exact required initial sentence. |
| 2 Speech/keypad isolation | Exactly 12 digits; keypad waits for `*`; `#` clears; spoken pause submits without `*`; first meaningful input owns attempt. |
| 3 Trusted callers | Successful atomic pairing enrolls a keyed caller-hash route; ambiguous mappings do not select a user. Listing/revocation added. |
| 4 Call challenges | One 90-second challenge per signed provider call, bound to user/workspace/caller route; atomic claim and billing reservation. |
| 5 Passkey/AAL2 | Existing verifyPasskey extended with server-owned Supabase MFA nonce, exact factor/session/RP, verified MFA AMR time and UP/UV flags. No second key/biometric store. |
| 6 Media admission | Signed stream waits for consumed challenge before PhoneSessionController/Live/private context. Hang-up/cancel/deny/revoke/expiry/replay fail closed. |
| 7 Notification/deep link | Existing transactional in-app/Web Push outbox, exact challenge URL, no private workspace content or SMS/email/phone fallback. Disabled/missing delivery falls back to code. |
| 8 Recovery/settings | Agent call security, passkey readiness, existing Security enrollment/backup link, trusted-route revoke; fresh one-use five-minute recovery code. |
| 9 Recordings | Exactly 3 freshly approved requests completed and installed; old assets preserved. Format/content checks and the user’s human audition passed. |
| 10 Security regression | Local SQL/HTTP/signed ASGI, forced RLS/browser grants denied/deletion cascades, replay/races, fresh nonce and secret isolation passed. |
| 11 Full validation | Local regression below passed; **real supported-device end-to-end gate unavailable** until approved environment and user enrollment/operation. |
| 12 Release | Audio approval, commit and initial branch push complete. Deployment is authorized, but its required production migration 045 remains separately gated. No merge, production migration, deployment or paid call has been executed yet. |

## Security details and review

- Bootstrap keeps the existing keyed code hash, five-minute expiry, six issues/hour and 30-second issue interval, three call attempts, 45-second code window, active membership checks and atomic call/credit reservation. Raw code is returned only by issue; no raw code in database, normal transcript or diagnostic output.
- Caller ID/hash is only a notification route. Repeat prompts are limited to one/minute and three/hour per user; denial suppresses further prompts for ten minutes. Inbound caller/hour/operator budget gates remain. Initial and repeat admissions share the operator budget lock, including extra repeat waiting exposure.
- Supabase creates/verifies the actual WebAuthn challenge. Only its server-stored nonce is sent to verify. Each nonce gets at most one verification request, including uncertain failures. A new attempt requires a new nonce; at most three ceremonies. No DB locks are held over assertion verification; state is checked again after the response.
- A fresh `mfa/webauthn` AMR timestamp is required, not JWT refresh `iat`, sign-in `passkey`, or a generic old AAL2 session. Subject/session/factor/RP and the exact provider call must still match. The backend requires signed authenticator user-presence and user-verification flags. Credential-bearing HTTP does not follow redirects.
- Membership, local session revocation, route revocation and factor removal are rechecked at admission. Web Push cannot approve; the authenticated page must start an explicit ceremony. Cancellation/timeout returns to a newly issued code or ends the call. Reconnect uses the existing committed-handoff gate.
- Migration [045_phone_caller_identity.sql](../../../../migrations/postriff/045_phone_caller_identity.sql) creates only routing/challenge metadata, applies FORCE RLS, revokes browser roles and cascades account/workspace deletion. Only this worktree claimed 045 in the final all-ref/all-worktree scan; recheck before integration.
- Existing Phone Mode credit limits, publishing permissions and task approvals remain effective after authentication. Authentication alone does not approve publication or additional paid work.

## Observed validation

Full outputs are in [logs](logs/) and checksummed by [validation.json](validation.json). Counts overlap where targeted checks were rerun after a concrete fix; do not add them into one unique-test count.

- 151 Phone/Voice/runtime unit tests passed; 54 notification/billing/credit unit tests and 28 frontend Voice/credit tests passed.
- Final focused Phone unit run: 48 passed. Final auth/notification/hosted run after redaction and adapter changes: 55 passed. Hosted/deployment regression: 28 passed.
- Disposable PostgreSQL: billing/Stripe, credits, duration, Phone Mode, caller identity, notifications; inbound keypad and separately spoken/no-star. Final caller suite includes no-delivery fallback, old-code rejection, operator budget exposure, wrong user/session, cross-call assertion, racing consume, expiry, in-flight hangup and route/factor/session/membership revocation.
- Full signed ASGI bootstrap and repeat flow: synthetic telephony/Supabase/Live; no Live connection or pre-auth audio delivery before successful code/challenge claim. Real agent draft mutation still requires separate publishing approval.
- Existing Phone Mode browser journey passed: explicit single call, navigation/reload never dial, credit gate, draft visibility, publication approval, hang-up/failure/history/schedules/revoke/mobile/axe. Repaired its pre-existing delete timing race by waiting for the rule to disappear before reading API state.
- Existing Browser Voice: 6 opening scenarios across Chromium/WebKit, plus 49 desktop/mobile interaction checks.
- Existing notifications browser journey passed Chromium/WebKit desktop/mobile light/dark: consent, STOP, authenticated notification navigation and zero unintended calls.
- New verify-call page: Chromium/WebKit at 1280/390/320, keyboard fallback/deny, no navigation approval, consumed state, reduced motion, no overflow, axe WCAG checks. Desktop/mobile screenshots visually inspected. Local dev identity has no Supabase client; the approval button is intentionally disabled there.
- Actual `navigator.credentials.get` + existing verifyPasskey helper under a Chromium **virtual** authenticator: signature, exact fresh nonce, RP, UV and abort/no-approval passed. This is not physical-device evidence.
- TypeScript, lint (0 warnings/errors), production build, diff whitespace and offline secret scan passed. Seven exact public manifest hashes were reviewed in the existing secret allowlist; no broad exemption. Copy audit had 18 pre-existing flags, zero introduced flags (see copy-review.json).
- After rebase onto the latest production source: 49 focused Phone tests and 94 hosted/notification tests passed; the seven-suite disposable PostgreSQL regression passed; spoken/no-star was rerun separately; TypeScript, lint and production build passed. Migration 045's pinned release runner also passed local plan/apply/idempotency/partial-state-refusal rehearsal.
- After production advanced again to `a25bb45`, the release was rebased a second time. Final checks passed: 143 caller/hosted units, 269 overlapping hosted-social/registry units, 19 changed web tests, nine PostgreSQL suites, spoken/no-star, virtual WebAuthn, registry gate, lint, typecheck and production build.

Representative commands (from this worktree; external transports injected):

```sh
PYTHONPATH=src:tests /private/tmp/rafii-phone-env/bin/python -m unittest test_phone_caller_identity test_phone_code_speech test_rafii_inbound test_rafii_dial test_rafii_phone_media
PYTHONPATH=src:tests /private/tmp/rafii-phone-env/bin/python scripts/postriff_pg_suite.py postgres_caller_identity postgres_inbound_phone postgres_unified_notifications
RAFII_TEST_CODE_METHOD=spoken PYTHONPATH=src:tests /private/tmp/rafii-phone-env/bin/python scripts/postriff_pg_suite.py postgres_inbound_phone
npm run typecheck --prefix web
npm run lint --prefix web
npm run build --prefix web
node web/tests/phone-passkey-browser.cjs
RAFII_WEB_URL=http://localhost:3395 node web/tests/phone-verify-call-browser.cjs
RAFII_WEB_URL=http://localhost:3395 RAFII_HARNESS_PG_PORT=55795 RAFII_PYTHON=/private/tmp/rafii-phone-env/bin/python node web/tests/phone-mode-browser.cjs
```

## Audio and remaining gates

[Listen to the 3 clips](audio-review.html). [Authorization](tts-authorization.json), [generation receipt](recordings/generation.json), [offline inspection](recordings/offline-validation.json), [original assets](original-assets/) are preserved. New lengths: 7.25 / 8.65 / 13.25 seconds. Total estimated TTS cost US$0.03; approved ceiling US$0.25; actual billing unavailable. No retry or fourth request was made. The user approved all three samples on 2026-09-28 after listening. Offline tiny-Whisper has spelling uncertainty on “pairing”/“passkey”; the human audition is the acceptance evidence. Current prompt text/hash/byte matching is enforced before playback.

`validation_unavailable` — real supported-device end-to-end passkey/call handover: this source is local only, no separately authorized HTTPS test deployment or real paid call exists for it. A read-only check of the currently signed-in production Security page showed “Two-factor authentication Off.” The user is willing to participate; the account choice/enrollment question remains pending. Credential enrollment must be completed by the user in existing Rafii Security; no automatic account change occurred.

For the remaining gate, first identify the approved secure test origin and its existing Supabase MFA configuration. An existing passkey only works for its enrolled RP; localhost/another Vercel preview cannot reuse it by bypassing origin validation. After separate environment/release/live-call authorization, verify on iPhone/Safari or installed PWA: real Face ID/Touch ID, exact current-call challenge, call surviving app switch, return after approval, cancel then newly issued pairing fallback, and a replay/expired request being refused. Record physical device/browser and results. Do not label virtual WebAuthn, desktop-only MFA or this local receipt production-complete.

External API contract references checked against installed source and official documentation: [Supabase MFA](https://supabase.com/docs/guides/auth/auth-mfa), [Supabase auth types](https://github.com/supabase/supabase-js/blob/master/packages/core/auth-js/src/lib/types.ts). No Bilibili companion-ios change and no new biometric database.
