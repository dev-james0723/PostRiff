# RAPv2: the nine BLOCKED rows: what was built, and the decisions for James

Branch `claude/rapv2-blocked-features-v2`, stacked on PR #199. Every new behaviour is inert in production until a flag
turns it on, or is read-only. Migration 127 is written but **not applied anywhere**.

| Row | Built | Off in production because |
| --- | --- | --- |
| RAP-016 | `/api/me` `signIn` and per-session `signInMethod` from the verified `amr`; "Unknown" in the Security Center | read-only; other sessions' methods are recorded only with `RAFII_SIGN_IN_DETAILS` |
| RAP-076 | approximate location from Vercel's edge geo headers; notices say "Approximate location unavailable" when there is none | `RAFII_SIGN_IN_DETAILS` unset |
| RAP-084, RAP-121 | `GET /api/auth/devices`, `POST /api/auth/devices/{id}/revoke`, Security Center "Browsers" view | `RAFII_DEVICE_TRUST_V2` unset (404) |
| RAP-111 | `GET/POST /api/auth/security/recovery` (support path, never an email code) | `RAFII_SECURITY_INCIDENT_HOLD` unset (404) |
| RAP-112, RAP-113 | `POST /api/auth/security/incidents/{id}/resolve`, "End the hold" in the Security Center | `RAFII_SECURITY_INCIDENT_HOLD` unset (404) |
| RAP-127 | the "This wasn't me" dialog already shipped with P1; a browser scene now checks it | n/a |
| RAP-137 | migration 127 `pr_security_retention_purge` + `security_retention.py` from the cron | `RAFII_SECURITY_RETENTION` unset, migration not applied |

## Decisions (each implemented with the recommended default; none is settled)

1. **Location granularity** (RAP-076). Recommended: `RAFII_SIGN_IN_DETAILS=region` (country and region codes, such as "KKC, HK"). City is available but more identifying. Place names are not looked up. Only Vercel's own `x-vercel-ip-*` headers are read, and only when `VERCEL=1`. No IP address is stored and the location never affects a decision. Alternative: `method` (no place at all).
2. **Retention periods** (RAP-137). Recommended: 400 days (about 13 months) for login events, per-session security state and idle or revoked browsers, with a hard floor of 90 days. Incidents and account controls are kept until account deletion. Every record of a person with an open incident or an active hold is kept whatever its age. Run `dry_run` for at least a week before `on`.
3. **Recovery flow** (RAP-111). Recommended as built: a hold is lifted only with a fresh TOTP or WebAuthn MFA, on an AAL2 session, made after the report, with a factor enrolled *before* the report. A factor enrolled afterwards (possibly from the stolen session) never counts. `POST /api/auth/mfa` is refused during a hold. Without such a factor, the only path is support. Not built: the support side (who verifies identity out of band, and how).
4. **Who may release a hold** (RAP-113). Recommended: the account owner as above, plus a founder/support action that requires out-of-band verification and is audited. That support release is not built.
5. **Device revoke freshness**. Revoking a browser uses the same sign-in freshness rule as revoking a session (`assert_fresh`, JWT iat window). Alternative: require MFA step-up.
6. **Migration number**. 127, because 124–126 are taken by `codex/rafii-discord-release-20261015`.

Rows still needing a person stay NOT_RUN: RAP-077 and RAP-123 (Cantonese review), RAP-148 (release reviewer), RAP-149 (config review). VoiceOver itself is not run; RAP-119 is checked with axe.

## James's answers (2026-10-16)

James answered all twelve open RAPv2 decisions on 2026-10-16: the seven from PR #199 (P1 gaps) and the five above from
PR #200. Six stay as built; five needed building and one is a flag value. The five builds are in branch
`claude/rapv2-decisions-20261016` (migrations 129 and 130, **not applied anywhere**; 128 belongs to the Discord release). Every new behaviour stays off until
`RAFII_SECURITY_INCIDENT_HOLD`, `RAFII_DEVICE_TRUST_V2`, `RAFII_SIGN_IN_DETAILS` or enforce mode is set; all are unset in production.

| # | Decision | Answer | What it means |
| --- | --- | --- | --- |
| 1 | No-factor next step (RAP-045, #199 item 5) | **Keep as built** | An account with no second factor is always told to set one up (`enroll_mfa`). The low-risk-only limit was declined. |
| 2 | Known browser on AAL1 (RAP-021, #199 item 6) | **Keep as built** | A known browser without fresh MFA must give a fresh 2FA code for sensitive actions. |
| 3 | Private-data gating (RAP-033, #199 item 7) | **Keep the block, build a screen** | Built: when a workspace read is refused at high risk, the web app shows a "Confirm it's you" step-up screen instead of a generic error (`web/src/components/auth/step-up-screen.tsx`, AppGate). With a factor the person confirms there and the workspace loads again; without one they are sent to set one up (account pages stay reachable). |
| 4 | Inactivity expiry (RAP-138, #199 item 4) | **Keep as built** | A browser counts as unknown again after 180 days idle. |
| 5 | Incident notice channel (RAP-064/114, #199 item 1) | **Email plus an in-app banner** | Built: the email through Notification V2 as before, plus a banner at the next sign-in until dismissed (`GET /api/me` `securityNotice`, `POST /api/auth/security/incidents/{id}/dismiss-notice`; migration 129 adds `reported_session_id` and `notice_dismissed_at`). The reporting session never gets the banner. |
| 6 | Risk-decision notices (RAP-064, #199 item 2) | **Notify only failed or blocked step-ups** | Built in `security_gate.py` (enforce mode only): a blocked risky sign-in (high or critical risk refused; once per session) and a repeatedly failed step-up (3 challenges of one session within 30 minutes without fresh proof; at most one per session per hour) each send a transactional security notice. A successful, self-initiated step-up stays quiet. |
| 7 | Old contact channel (RAP-114, #199 item 3) | **Previous address for 14 days** | Built: a trigger on `auth.users` (migration 129) records the address an account had before an email change; for 14 days every security notice also goes there, with a line saying why. Never fails the email change; rows older than 14 days are deleted on each change and on account deletion. |
| 8 | Location granularity (RAP-076, #200 item 1) | **City** | Set `RAFII_SIGN_IN_DETAILS=city` when the flag is turned on (country, region and city from Vercel's edge headers). Already supported; tests added. Overrides the recommended `region`. |
| 9 | Retention periods (RAP-137, #200 item 2) | **Keep as built** | 400 days, with `RAFII_SECURITY_RETENTION=dry_run` for at least a week before `on`. |
| 10 | Recovery flow (RAP-111, #200 item 3) | **Keep as built** | A held account is recovered with a factor enrolled before the report, otherwise through support. Email codes never work. |
| 11 | Who may release a hold (RAP-113, #200 item 4) | **Build the founder/support release** | Built: Founder Admin → Customer 360 → "Lift security hold" (`/api/control/v2/actions/accounts/{id}/security-hold/release/preview|confirm`, capability `accounts.block`, fresh second factor, typed `RELEASE`). The founder must record how identity was verified out of band (one of five methods, never an email code) and a support case reference. It reuses `security_holds.release`, resolves open incidents as `support_verified`, writes the ledger, the consumer audit `security.hold_released_by_support` and the Control audit, and emails the person. Migration 130 adds the action kind. |
| 12 | Device revoke freshness (#200 item 5) | **Keep as built** | Revoking a browser needs a recent sign-in (`assert_fresh`), not a 2FA code. |

### Wording for James to approve

New security notice text, in English, Hong Kong Cantonese written Chinese (zh-Hant-HK), Traditional and Simplified
Chinese, is in `src/postriff_phase2/notifications/email_locales.json` under `security_alert` (`titleIncidentReported`,
`titleStepUpFailed`, `titleSignInBlocked`, `titleHoldReleasedBySupport`, `detailPreviousAddress`, `previousAddressNote`).
The incident headline is now localized too (before, it was English in every language). The Cantonese review is still
acceptance rows RAP-077 and RAP-123. The in-app banner, the "Confirm it's you" screen and the founder dialog are
English-only, like the rest of the app.

### Before turning the flags on

Apply migration 129 (consumer) and 130 (Control) first. With `RAFII_SECURITY_INCIDENT_HOLD` on and 129 missing, the
banner and the previous-address copy are skipped (never an error), and the step-up notices skip themselves under a
savepoint in enforce mode.

