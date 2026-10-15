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
