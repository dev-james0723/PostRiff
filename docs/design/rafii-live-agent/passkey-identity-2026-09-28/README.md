# Rafii passkey account unlock and agent-call identity — local candidate receipt

Status: **implemented and validated locally in an isolated worktree. No production Auth setting,
database migration, environment variable, deployment, passkey enrollment, or paid phone call was
performed.**

Worktree: `/Users/ouxianxing/.codex/worktrees/rafii-passkey-identity/James-Au-Studio`

Branch: `codex/rafii-passkey-identity`

Base: `9b67eb09` (`codex/rafii-inbound-budget-rate-fix`)

## Outcome

Hosted Supabase currently rejects WebAuthn as an MFA enrollment method. Its supported passkey
feature is passkey **sign-in**: Face ID, Touch ID, Windows Hello, a device PIN, or a security key can
unlock an account, while TOTP remains the actual second factor for accounts that enable MFA. The
account UI now reflects that distinction and no longer offers the unsupported WebAuthn-MFA path
that produced “MFA enroll is disabled for WebAuthn.”

Returning AI-agent calls now use two independent checks:

1. A one-use Agent Pairing Code binds a caller route to the exact user and workspace. Caller ID can
   locate a pending route but never authorizes access.
2. Every returning call creates a 90-second challenge. The signed-in user must complete a fresh
   passkey ceremony. Rafii sends the exact paired user an in-app/Web Push notification whose link
   opens that challenge and explicitly asks for Face ID, Touch ID, Windows Hello, or a security key.
   Push requires that the user previously enabled notifications and has an active browser/PWA
   subscription; the notification itself cannot approve a call. A separate memory-only Supabase
   client sends only the resulting access token to that one approval action and then signs its local
   session out.

The backend verifies the token with Supabase, the exact user, signed `amr: passkey` time after the
call challenge began, a session distinct from the normal app session, active membership, the exact
provider call, and an unused proof session. The proof-use ledger is service-role-only with forced
RLS. A proof session can authorize only one protected action across call approval and trusted-caller
revocation. Expiry, replay, wrong user/session/method, removed passkeys, revoked local sessions,
route revocation, membership loss, hang-up, cancellation, denial, or an ambiguous caller route all
fail closed. Existing Agent Pairing Code recovery remains available.

This verifies the account owner authorizing the paired AI-agent call; it does not claim that an AI
model itself owns a biometric identity. Biometric templates remain on the user's device.

## Scoped changes

- Passkey account-unlock copy and sign-in entry points are under the existing
  `NEXT_PUBLIC_PASSKEY_SIGN_IN` gate.
- TOTP is the only newly offered MFA enrollment method; historical verified WebAuthn factors remain
  removable/verifiable for compatibility.
- Phone approval no longer asks hosted Supabase for an unsupported WebAuthn-MFA challenge or
  returns/replaces the app session.
- Migration `046_phone_passkey_identity.sql` accepts the new `passkey` proof class and adds the
  private one-action proof ledger.
- Server-side passkey inventory uses Supabase's secret-key Admin endpoint. No biometric data,
  credential public key, refresh token, caller number, or pairing code is added to application
  storage.

## Production activation preview — not executed

The last read-only production inspection found TOTP available, but WebAuthn MFA enrollment,
WebAuthn MFA verification, and passkey sign-in disabled. A narrow attempt to enable WebAuthn MFA
was rejected by hosted Supabase with HTTP 422; the setting did not change.

The reviewed activation bundle is:

1. Apply migration `046_phone_passkey_identity.sql`.
2. Enable Supabase passkeys with display name `Rafii`, RP ID
   `postriff-phase2-private.vercel.app`, and RP origin
   `https://postriff-phase2-private.vercel.app`.
3. Set Vercel `NEXT_PUBLIC_PASSKEY_SIGN_IN=true` and deploy this exact candidate.
4. Enroll a passkey on a real supported device, then verify account unlock and one real returning
   agent call end to end.

The RP ID is intentionally security-sensitive: changing from the `vercel.app` hostname to a future
custom domain would require users to enroll new passkeys. Migration, Auth configuration, environment
change, deployment, enrollment, and a paid real call remain separate action-time approvals.

## Validation

- 55 focused Python identity, account-security, UI-contract, and migration-number tests passed; 81 additional
  Phone, media, inbound, Dial, pairing-code, and hosted-deployment regression tests passed.
- Disposable PostgreSQL caller-identity suite passed real SQL, HTTP, signed ASGI, forced RLS,
  deletion cascades, three-attempt cap, cross-call and cross-action replay refusal, racing consume,
  revocation, hang-up, and synthetic media admission. Telephony, Supabase, Live, and model transports
  were synthetic; no network provider call was made.
- TypeScript passed; frontend lint reported 0 warnings/errors; diff whitespace checks passed.
- Production Next.js build passed on the repository's pinned Node 24 runtime.
- The memory-only proof-client test passed exact one-action token handoff, abort forwarding, and
  best-effort local cleanup.
- Chromium virtual WebAuthn validation passed assertion signature, user-verification flag, fresh
  challenge, RP, and cancellation behavior. This is not physical biometric evidence.
- The real verification page passed Chromium and WebKit at 1280, 390, and 320 pixels: no navigation
  approval, keyboard fallback/deny, consumed state, reduced motion, no overflow, and axe WCAG 2 A/AA
  checks. Desktop and phone screenshots were visually inspected in [browser evidence](../caller-identity-2026-09-28/browser/).

`validation_unavailable` — physical Face ID/Touch ID and a real phone handover require the production
activation bundle and user-operated enrollment/call. Local, virtual-authenticator, and synthetic
phone results must not be described as production completion.

Current platform references: [Supabase passkeys](https://supabase.com/docs/guides/auth/passkeys),
[Supabase Auth routes](https://github.com/supabase/auth/blob/master/internal/api/api.go), and
[Supabase Auth passkey session implementation](https://github.com/supabase/auth/blob/master/internal/api/passkey_authentication.go).
