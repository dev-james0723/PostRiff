# Evidence, official requirements and shortest release path

Candidate prepared2026-10-18 from `/Users/ouxianxing/Documents/.agent-worktrees/rafii-pinterest-production-prep-20261014/docs/pinterest-production-20261014`. Status vocabulary PASS / FAIL / BLOCKED / NOT RUN; public feature decisions use GO / NO-GO. A successful mock/CI is not actual provider acceptance.

## Official requirements verified18Oct

Pinterest's current upgrade guide requires existing Trial approval, policy compliance, an actual API-action video showing approved OAuth, accurate app/use-case/privacy information, and final upload/submission from Upgrade. Trial-created boards and Pins are creator-only; Pin Analytics is listed at both tiers. Standard has different/higher quotas. The same official HTML warns that apps registered on/after14Sep2026 can be denied non-business board/Pin data without Pinterest authorization. App1615884's registration date/exception remains unverified. These are provider rules; Rafii's additional customer/security/release gates remain separate. [Access tiers](https://dev.pinterest.com/docs/key-concepts/access-tiers/)

Authorization Code is the documented method for independent end users; exchange occurs on the server with the registered redirect and state verification. Read scopes for ordinary boards/Pins do not grant secret-board/Pin access. [Authentication and scopes](https://dev.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/)

Guidelines require informed approval of each scheduled Pin, forbid credential/cookie harvesting, undisclosed account actions, API scraping, unauthorized benchmarking and model development using Pinterest Materials. Storage and third-party-sharing restrictions need substantive review; their campaign-analytics exception must not be assumed for organic metrics. [Developer Guidelines](https://policy.pinterest.com/en/developer-guidelines)

The live17Oct form receipt specifies20–60fps and recommends MP4 under2GB. This format requirement is native form evidence, not a claim that the general public upgrade guide enumerates it. Current organic guidance says some reports need business accounts; do not promise all personal/business accounts or all metrics. [Organic reporting](https://dev.pinterest.com/docs/analytics-and-reports/organic-reporting/)

## Applicable evidence — preserve dates and scope

| Acceptance | Status and execution date | Exact evidence file | Limit |
|---|---|---|---|
| Current app tier | PASS verification18Oct15:10:38Z; Trial, no Standard approval | evidence/current-access-tier-20261018.json | Observed app card, no submission by this task |
| Deployed repair/source | PASS18Oct; product66c5cedd /5Z6 | evidence/snapshot-repair-deployed-20261018.json | Fixes actual workspace500; no public permission implied |
| Focused repair CI | PASS18Oct; remote08m85w3gj9,32tests,3476input fingerprints match | evidence/snapshot-repair-cloud-validation-20261018.json | Reuse unchanged prior PG/frontend checks; no rerun here |
| Four-scope OAuth/binding | PASS18Oct03:29:14Z | evidence/private-trial-four-scope-acceptance-20261018.json | App-owner business account only; human final consent |
| Eligible board read | PASS18Oct03:33Z | same four-scope receipt | Actual API-backed named board; section discovery NOT RUN |
| Historical refresh/reconnect/disconnect | PASS17Oct19:12–19:43Z | evidence/pilot-reconnect-refresh-disconnect-20261017.json | Previous two-read-scope grant; zero pending jobs |
| Current four-scope refresh | BLOCKED18Oct03:33/03:34; Rafii403 | evidence/private-trial-four-scope-acceptance-20261018.json | No proven provider refresh call; normal human Rafii fresh login/MFA needed |
| Current image authoring | PASS18Oct14:39–14:42Z | evidence/private-trial-image-ingest-20261018.json | One private normalized1200×630JPEG; one asset/readback200; no Pin |
| Immediate Pin/API read-back | NOT RUN18Oct | pin-previews/index.html + pins.json | Exact previews exist, zero approved/created Pins |
| Scheduled due execution | NOT RUN18Oct | same previews + THIRD-PARTY-ACCEPTANCE.md | Proposed18Oct12EDT/16UTC has no job/approval; do not roll forward silently |
| Native Analytics | NOT RUN18Oct | existing code/CI only | Success/no-data/error implementation is not a real metrics read |
| Compliant full video | BLOCKED18Oct15:10Z | evidence/recording-current-qualification-20261018.json | No qualified source/FPS/export;0newfootage; old4fps partial FAIL for submission |
| Non-app-owner customer | NOT RUN18Oct | THIRD-PARTY-ACCEPTANCE.md | App-owner consent cannot replace customer acceptance |
| Public policies | PASS reachability18Oct; BLOCKED substance | POLICY-GAPS.md in this candidate | Both200; draft/placeholders remain |
| Standard official decision | NOT RUN / no approval18Oct | current-tier receipt | Application upload/submission requires separate approval |

The four-scope receipt contains older snapshot/media/deployment failures; the later repair/image receipts supersede those fields only. They do not change its refresh or live-publishing status.

## Independent public feature decisions

| Feature | Current public decision | Shortest evidence still needed |
|---|---|---|
| Connect | NO-GO | Standard/eligibility, completed current refresh/reconnect/disconnect, non-app-ownerA/B normal OAuth and workspace isolation, reviewed policy/security and exact release approval |
| Publish | NO-GO | Connect gates plus individually approved real Pin ID, matching provider read-back/account/board and actual tier-appropriate visibility; canary/public enablement approval |
| Schedule | NO-GO | Publish gates plus observed actual due execution, including identity proof older than1h; real cancellation/disconnect with pending job, zone/time/DST and durable recovery evidence |
| Analytics | NO-GO | Current authorized own Pin, real API success/no-data/failure reporting, permissions/schema/flag and retention review; independent Analytics release approval |

Schedule/Analytics need not delay a separately qualified Connect+Publish canary. A partial release must name the enabled functions and exclusions. Current Trial can validate restricted owner behavior; it cannot prove public delivery. Do not add a customer as app developer/tester to manufacture non-owner acceptance.

## Final-demo shot list and acceptance attachment

1. Normal Rafii login and exact workspace, without capturing passwords/MFA values. Show Connect Pinterest and the official consent scope screen; human grants consent. Do not record callback code/state/query.
2. Return to Rafii; show stable connected account, current tier, fresh authorized board and selected section if used.
3. Show exact current stored image and all text/link/account/board/time; obtain real per-Pin approval outside AI inference. Record one approved immediate create, actual provider ID and read-back, and label Trial visibility accurately.
4. If Schedule is in the application claim, show its separate approval/job/timezone, before-due state and actual due execution with traceable time continuity. If Analytics is claimed, show actual native metrics/read state, period and last update. Empty successful data may be honestly shown; do not fabricate engagement or zero.
5. Show disconnect, local token removal and future-job stop; retained accepted Pin is separately explained. Protect personal details and other workspaces. Review every frame; final actual20–60fps MP4/hash/size and redacted receipts accompany the final package.

No approved Pin yet means steps3–5 cannot be reconstructed from mocks. Fresh OAuth must be captured when actually performed, not retroactively manufactured. Current private policy expires18Oct18:00UTC/14:00EDT; no automatic extension.

## Smallest ordered approval bundle, when concrete assets are complete

- Human normal Rafii fresh sign-in/MFA: security participation, no credentials in chat; then use already authorized current read-only refresh scope.
- Exact immediate/scheduled Pin cards: approve each immutable account/board/image/copy/link/time separately; maximum2, no blind create retries, deletion only under distinct exact-ID approval. Existing board/image approvals are consumed and must not be repeated.
- Policy/terms: owner supplies missing real facts, reviewer signs off exact text, then separately approve publication of the reviewed changes.
- Standard: review final actual video and app fields; separately approve exact upload/field update/submission. No extra app, organization or payment needed by this package.
- Production: after provider decision and eligible independent customer acceptance, review exact source/config/allowlist/limits/observability/rollback and separately approve bounded flags/canary. Preserve canonical production project.

No newly approved paid run, SQL, deployment, provider write, policy publication, application upload or submission was performed by this audit. Existing production flags remain untouched.
