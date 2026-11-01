# Third-party Pinterest acceptance — execution candidate

Prepared 2026-10-17. **NOT RUN.** This is an executable acceptance plan, not provider approval or a live-test receipt. Recorded production baseline: product `e2e5169ff19ac268c0a0ad06994f67b41f69f949`, `dpl_2tFM29HomWyWcrzTqTtikWN6Pvti`; verify the current alias/configuration before execution. Use only `rafii.io` and canonical Supabase `postriff-phase2-private / buoyhkbodnhzngaotoel`. No staging substitution or new resources.

Prior owner evidence is reusable only for its recorded scope: OAuth, stable business identity, empty boards, refresh, reconnect and credential erasure. It does **not** pass the non-owner customer journey. [Current receipt](FINAL-RECEIPT.md) · [Prior real receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json) · [Synthetic exact-source coverage](evidence/capabilities-validation-20261017.json).

## Participants and preflight

Use customer A, an independently consenting Pinterest business account whose owner is **not an owner/developer/tester of Pinterest app 1615884**. A needs a normal Rafii login and a separate customer-owned Rafii workspace. Record the provider's actual eligibility decision and app tier; business status alone does not establish access. Do not add A as an app owner/tester to manufacture third-party eligibility. If Trial blocks A, preserve the actual result as BLOCKED and obtain Standard approval before repeating.

Use customer B, separately consenting and eligible, in a different Rafii workspace for real cross-tenant isolation. B may perform only identity/boards/disconnect while A performs the two individually approved Pin actions. Synthetic negative tests remain necessary but do not replace A/B real authorization. No customer credentials, passwords, cookies, MFA codes or browser exports enter the chat, files or CI. Each customer controls their own official authorization and security verification. Do not operate another person's browser without consent.

Before the test, record approved participants, Rafii workspace/connection IDs, provider account IDs, source/deployment, exact callback, current access tier and requested/granted scopes. Read-only identity/boards uses `user_accounts:read,boards:read`; image publish/read-back additionally needs `pins:read,pins:write`; Pin analytics needs `user_accounts:read,boards:read,pins:read`. Do not request advertising, secret-board or board-write permissions for the image-Pin acceptance path. Creating a test board is a separate exact action approval.

The earlier private pilot expired at **2026-10-17 16:40:56 America/Indiana/Indianapolis (20:40:56 UTC)** and its local credentials were erased. It grants no continuing live token access or publication authority. Verify actual consent and current narrowly approved runtime admission before any new API operation. Keep public/review/policy/Agent gates closed until their requirements are separately satisfied.

## Approval packet before live writes

Prepare two immutable review cards, A-I (immediate) and A-S (scheduled), before requesting execution approval. Each must include:

- Actual customer workspace/connection, stable Pinterest account/handle and current provider tier/API host.
- Actual eligible public board name/ID and optional section name/ID, proven by fresh authorized provider discovery. A public board does not prove public Trial visibility.
- Final image preview and immutable source/hash, MIME, dimensions, bytes, ownership/rights and alt text; exact title, description and HTTPS destination link.
- Exact `POST /v5/pins` body, expected account/board and visibility, permitted one creation plus read-back; an independent expected result for Trial versus Standard.
- Immediate execution window, or the exact scheduled local date/time, IANA zone, UTC instant and DST fold when relevant. Re-approve if the fixed window expires or payload/account/destination changes.
- Explicit decision on keeping the two resulting Pins or separately approving deletion of those exact IDs. Local cancellation cannot recall a provider-accepted Pin.

For scheduling, choose an approved time **more than one hour after connection verification** so the test exercises the recovered stale-identity path. Select a window the customer can observe. Keep A-S pending until its distinct schedule approval; approval of A-I does not approve A-S. Request approval for any enabling production configuration/schema/deployment separately, with reviewed diff, restricted affected users, relevant validation and rollback. Do not bundle public enablement into a private canary.

## Actual flow and required receipt

| Case | Action | Required evidence | Initial status |
|---|---|---|---|
| A-C1 | Normal customer login → Connect Pinterest → official consent → callback | Non-app-owner eligibility, exact scopes, callback/exchange success, stable account binding, no token exposure | NOT RUN |
| A-C2 | Read boards and sections; select destination | Provider account ID, board/section ownership/access/privacy/eligibility and pagination completion; selected IDs match review | NOT RUN |
| B-C1 | B connects in their own workspace | Separate connection/custody/account and own board results, recorded consent | NOT RUN |
| A-R1 | Refresh authorization; recover/reconnect if revoked | Actual refresh grant/read-back and safe rotation metadata, same account, no old approval revived | NOT RUN |
| A-I | Review → approve → publish one image Pin | Exact approved manifest/digest, provider Pin ID/URL, timestamp and safe request/response evidence | NOT RUN |
| A-I-V | Read back A-I and check visibility | GET Pin ID, correct account/board/section/title/description/link/image type; actual independent visibility observation, tier accurately labelled | NOT RUN |
| A-S | Review → approve → schedule A-S | Durable job/manifest, chosen local zone/time and UTC, remains unposted before due; UI status never equates queued with published | NOT RUN |
| A-S-V | Observe due execution with client closed | Actual worker claim/lease/reverification/refresh if due, one create, provider ID/read-back, correct execution time/zone and visibility | NOT RUN |
| A-M1 | Read native metrics of verified Pin | Endpoint/window/observation time and native impressions/saves/Pin clicks/outbound clicks; explicit zero preserved | NOT RUN |
| A-M2 | Observe successful empty metrics | Successful read recorded as no data/awaiting data; no fabricated zero or fake success value | NOT RUN |
| A-M3 | Observe permitted failure recovery | Safe failure classification/retry/reconnect, prior good data retains timestamp; do not intentionally revoke customer authorization without consent | NOT RUN |
| A-D1 | Disconnect with a separate pending approved job | Token ciphertext erased, pending job canceled/no future write, in-flight outcome reconciled accurately; provider consent revocation separately described | NOT RUN |
| B-D1 | B disconnects | B credentials erased; A jobs/history/custody unaffected | NOT RUN |

For each receipt record UTC and local execution times, environment/tier, source/deployment, participant consent reference, workspace/connection/account/destination, request method/path, safe status, job/attempt/lease references, approval digest, Pin ID/URL, read-back fields, observed visibility and the concrete evidence file. Do not retain bearer tokens, authorization codes, OAuth state, refresh tokens, full query-bearing callback URLs or unrelated private data. Provider messages are untrusted and require redaction.

No duplicate claim requires actual evidence: one approved job identity, number of attempted POSTs, distinct returned Pin IDs and lookup of the selected board during the approved observation window. A lost create response with no Pin ID stays **uncertain** and requires manual provider reconciliation; never blindly POST again. “One visible Pin” alone does not prove one attempt. Do not fault-inject network failures against the live provider to obtain this proof; use the approved synthetic/disposable harness for such injections.

## Negative and recovery checks

1. A's normal authenticated session requests B's known connection/destination/job IDs and vice versa through the application's existing authorization boundary. Expect 403/404 before token retrieval/provider traffic and no leaked names/IDs. Use only the participants' exact approved test resources; never enumerate customers.
2. Repeat within one workspace using a member without connection-management/approval rights. Confirm no OAuth start/refresh/disconnect or publish privilege escalation. Recheck membership when the worker dispatches.
3. Try a destination/section absent from the account's fresh authorized list. Expect rejection before `POST /pins`; never write to a guessed or unrelated board. Private/ad-only/unknown destinations remain ineligible for v1.
4. Edit A-S's image, text, link, board, section or time. The previous immutable approval must not authorize changed content. Cancel the old pending job, create a fresh review and require the customer's exact re-approval. Distinct revised approvals must not accidentally produce both versions.
5. Create an additional **unexecuted** scheduled intent for cancellation acceptance. Cancel before due; record durable canceled state and zero create attempts after due. For automation pause, use a separately reviewed local policy/test fixture; activating recurring live publishing requires a distinct grant. Verify pause cancels eligible open items and no paused operation is dispatched.
6. Use synthetic/disposable tests for duplicate workers, lease expiry/takeover, crash before/after acceptance, quota exhaustion/recovery, 429/backoff, time-zone DST gap/fold, storage outage and refresh concurrency. Reuse matching passed source evidence. Do not send unnecessary provider traffic or mislabel these as live tests.
7. Disconnect while a scheduled job is pending, then reconnect the same account. Previous approval/jobs remain canceled or held; a new consent must not resume them. Test late callbacks and worker-result races synthetically; record actual nonempty pending-job cancellation separately from the earlier zero-job disconnect proof.

## Feature-specific public release gates

| Feature | Public GO requires | Independent hold condition |
|---|---|---|
| Connect | Official Standard/customer eligibility confirmed; exact callback/scopes; real A/B onboarding, stable account/tenant isolation, refresh/reconnect/disconnect; current security/policy/release approval | Trial-only owner proof, ineligible personal account or missing customer consent keeps Connect NO-GO |
| Publish | Connect GO; approved exact A-I, actual provider ID + matching read-back/visibility; immutable media/metadata approval, quotas/idempotency/failure handling; approved bounded production canary | Queued/ambiguous result or absent public visibility proof keeps Publish NO-GO |
| Schedule | Publish GO; A-S actual due execution after stale proof/refresh recovery, timezone/edit/cancel/pause, durable leases/retry/uncertain reconciliation; deployed qualified scheduling fix | Source/synthetic PASS alone keeps Schedule NO-GO; it need not block an otherwise qualified manual Publish release |
| Analytics | Connect plus verified owned Pin; approved read scopes and metric schema/flag; real success/no-data/failure projection and retention review, tenant/revocation fencing | No Pin data or unenabled read/schema gates keep Analytics NO-GO; it need not block a qualified Connect/Publish release |

A feature can become GO only from its recorded evidence and explicit release authorization. Partial GO must be named; it is not “all production-ready.” Start with the explicitly authorized customer allowlist and per-account limits, with immediate provider/publishing pause and tested rollback to the recorded immutable predecessor. Never open anonymous/public connection admission as part of a read-only check.

## Review recording and submission

Prepare a shot list matching A-C1/C2 → A-I/V → A-S/V → A-M1/2 → A-D1, with visible real Rafii UI, official Pinterest consent, correct account/destination, actual ID/read-back and truthful tier/visibility. Record scheduled waiting and due execution with timestamped continuity; do not imply edited waiting footage is immediate execution. Show customer consent only with permission; mask personal details without masking proof of account separation. Exclude secrets, callback query strings and other sessions.

If Standard is required before A can authorize, record the separately approved app-owner Trial demonstration first, label it accurately, submit only after James reviews the final actual video/application, then execute A/B customer acceptance after provider approval. The Trial demonstration and Standard application are separate from third-party/public acceptance. Check the existing application status before any submission to avoid duplicates; retain actual provider submission ID/status/rejection reasons and do not invent an approval date.
