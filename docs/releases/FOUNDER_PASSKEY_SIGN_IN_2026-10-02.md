# Founder passkey sign-in — October 2, 2026

## Approved scope

Use the owner's existing Rafii identity for Founder access. Add a primary passkey/Face ID/Touch ID option to the Founder sign-in page, preserve password and authenticator fallbacks, and offer optional passkey registration only after a server-accepted Founder exchange. Do not create a second account, grant Founder by a client-entered email, collect biometric data, or weaken MFA.

## Authentication sequence

1. The user chooses a primary passkey or enters the existing account's email/password. A new Supabase client holds this identity only in memory (`persistSession`, `autoRefreshToken`, `detectSessionInUrl` all false; isolated storage key).
2. Supabase `getUser` validates the identity and confirmed email against the returned session. The page displays the verified account and uses its fixed UUID. Client-entered email is not a Founder allowlist.
3. Prove a fresh verified second factor. Prefer an already-enrolled WebAuthn MFA factor when the browser supports it; otherwise use an authenticator code. Primary passkey authentication is NOT itself accepted as fresh MFA. Provider support for registering new WebAuthn MFA factors is not assumed.
4. The unchanged `/api/control/v2/session/exchange` enforces the active operator row, AAL2, MFA freshness, origin and the existing session boundary. The browser receives its existing HttpOnly Founder cookie only if the server accepts the exchange.
5. When an independently verified account still needs initial operator enrollment, keep the existing 15-second retry and 270-second limit. A refused session never creates an operator, grants itself permissions or displays the passkey setup step.
6. After accepted password/MFA exchange, offer optional "Set up Face ID / Passkey". Supabase checks the current same-user AAL2 session and handles the user-initiated registration ceremony. "Continue to Founder" skips registration. Existing primary-passkey sign-ins navigate directly after MFA/exchange.

A successful Founder cookie remains bound to its upstream session. Do not revoke that upstream session while navigating away after a successful exchange. Abandoning an unaccepted login revokes only that temporary session, never every device or the user's consumer session.

## Files

- `web/src/lib/founder/sign-in.ts`: isolated primary authentication, identity/factor validation, safe errors, optional registration and the unchanged exchange transport.
- `web/src/features/founder/shell/sign-in-form.tsx`: passkey-first UI, password fallback, second-factor selection, cancellation/retry, approved enrollment wait and post-exchange registration.
- `web/tests/founder-sign-in.test.cjs`: real authentication helper/MFA adapters, with only external SDK/network boundaries doubled.
- `web/tests/founder-sign-in-browser.cjs`: real production-built UI and pinned Supabase SDK, Chromium's real WebAuthn interface with a virtual authenticator, local Auth/Control fixtures. Verifies actual assertion signature, challenge, relying party, origin and user-verification flag; no provider credentials or hosted user accounts.
- `scripts/founder_signin_web.py`: a separate credential-free build and local server for those browser scenes. It refuses hosted execution and only terminates the test server it started.
- `tests/control/test_boundary.py`: primary passkey alone and even an AAL2 label without a recognized fresh factor remain rejected; a WebAuthn MFA result still requires AAL2 and an enrolled operator.
- Founder browser workflow and required-check manifest: run/retain the additional isolated browser evidence without changing trust boundaries or release requirements.

## Deployment and user gate

The production Supabase project must expose passkey authentication, and `NEXT_PUBLIC_PASSKEY_SIGN_IN=true` must be present at build time. The relying-party domain must match the real login origin. The readiness probe observed the expected production RP domain; an options response is not a biometric login or a completed enrollment.

The existing guarded activation process must independently bind the owner-confirmed account UUID before creating an initial `platform_operators` row. Do not reuse a refused identity as its own authorization evidence. No migration, new account, automatic operator enrollment or passkey is created by this frontend change.

On a real iPhone, the owner must personally complete the first existing-account password/MFA sign-in and the Face ID/passkey registration prompt. Later primary passkey sign-in replaces the password, but the second-factor requirement remains. A Mac may show Touch ID or a phone/security-key chooser rather than Face ID.

Release acceptance requires the exact deployed commit, healthy customer traffic, protected unauthenticated Founder API, owner UUID verification/enrollment, actual signed-in desktop/mobile checks, user-driven biometric registration and a later successful passkey sign-in. Local virtual-authenticator tests are explicitly NOT real iPhone biometric acceptance. Do not describe account binding or full production activation as complete until those remaining user-dependent gates have evidence.
