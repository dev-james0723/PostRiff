# Pinterest acceptance and capability matrix

**Current18Oct~05:30UTC:** live730d/Eobk; real4scopeOAuth/eligibleboardPASS; refresh403/snapshot500remain. Repair66c5cedd cloud08m85w3gj9PASS32tests+3476hashmatch; deploymentapproved but0submissions because protectedsecretCopyrequireshuman. CIbudgetconsumed/build1+promotion1remain. Publicall4NO-GO. Latestsectionbelow supersedes pending-CIrows.

Updated2026-10-17 UTC. Live product source `e2e5169ff19ac268c0a0ad06994f67b41f69f949`, deployment2tFM READY/promoted20:28Z; source receipt10486d8b. Earlier real read-only provider acceptance was on qualified c8/sF. Baseline7432 incorporated. **NOT PRODUCTION-READY.** Synthetic/disposable checks do not supply real acceptance. [Deployed-source cloud result](evidence/capabilities-validation-20261017.json).

| Required acceptance | Status | Evidence / remaining requirement |
|---|---|---|
| Callback console registration | PASS | App1615884 exact rafii.io callback approved/saved/reload-verified2026-10-15. [Receipt](evidence/pinterest-callback-registration.json). Runtime code exchange and identity passed2026-10-17; existing consent reused. |
| Approved local5e4/current7432 sync | PASS | Both completed2026-10-17; current7432 mergeea4bbd36/cloudvvmpxv3mmg. [Receipt](evidence/current7432-validation.json). Same-type local sync approval standing. |
| Public OAuth onboarding | NOT RUN | Needs real eligible new user, provider consent, Standard and release gates. |
| Identity and boards | PASS | REAL official identity200 and boards200 on2026-10-17, same approved business account. Empty items/valid shape/no bookmark; eligible board selection and sections NOT RUN. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Token refresh | PASS | REAL refresh_token POST200 at19:33:32Z, same-account identity200, DB rotation/expiry updated. Normal human fresh sign-in; no security bypass. Automated expiry-triggered live recovery remains NOT RUN. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Reconnection | PASS | REAL new authorization transaction2a93315a exchanged/consumed19:12:39Z after earlier local revocation, same stable business account, two read scopes. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Multi-tenant isolation | NOT RUN | Separate real accounts pending; disposablePG tenant/same-tenant-other-owner/custody/Agent negatives PASS2026-10-17. |
| Image Pin publication | NOT RUN | No approved exact payload or provider Pin ID. Read-only pilot prohibits all Pin operations. |
| Pin verification/visibility | NOT RUN | No real read-back or visibility observation. Exact frozen-metadata/uncertain-outcome checks passed synthetically. |
| Scheduling | NOT RUN | Actual provider execution/edit/cancel/recovery unobserved; worker contracts tested synthetically. |
| Duplicate prevention | PASS | Synthetic concurrency/leases/final authority/known-ID persistence and no lost-response rePOST passed2026-10-17. Real provider behavior unobserved. |
| Account disconnection | PASS | REAL final human-completed DELETE20019:43:55Z; DB revoked and both token ciphertexts erased.0real jobs,0active future jobs; nonempty real cancellation and Pinterest consent revoke NOT RUN. Earlier403 preserved. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| AI Agent authorized end-to-end | NOT RUN | Registration/tenant/current-intent tests PASS2026-10-17; provider-data/write gates closed. |
| Standard Access | BLOCKED | Native My apps17Oct~22:35Z says Trial access active; Upgrade form available with blank video. No active pending/approval displayed; owner mail search found only14Oct Trial approval. Actual compliant OAuth/API video and policy review missing. |
| Production release/canary | NOT RUN | One approved private Trial quota/config/deployment completed on existing production resources, not public release. No approved canary Pin. [Deployment receipt](evidence/pilot-deployment-20261017.json). |
| Public availability | NOT RUN | Eligible customer's production journey not demonstrated. |
| Synthetic concurrent scale | PASS |1000 simultaneous arrivals/64workers;5007.90users/s;p50/p95/p99 90.28/165.99/171.89ms;0unexpected failures;20expected uncertain outcomes;0provider traffic,2026-10-17. In-process only. |
| Quota/security/callback binding | PASS | DisposablePG17.11 verifies app/host/username/expiry callback rejection and durable consumption, old-env custody denial, forced RLS/bounded DML/no TRUNCATE, quotas/recovery,2026-10-17. Actual PostgreSQL17.6 apply and privilege metadata PASS2026-10-17; no destructive/DML probe. [Apply receipt](evidence/pilot-quota-production-apply-20261017.json). |
| Scoped CI/browser | PASS | Deployed baseline e2e5169f:463Python/51Node,7PG scripts,Agent,typecheck/lint36warnings0errors/build/synthetic browser,2026-10-17. [Receipt](evidence/capabilities-validation-20261017.json). Full-project CI NOT RUN. |
| Real private pilot execution | PASS | Bounded read-only exchange/identity/empty boards/real refresh/reconnect/final local disconnect verified2026-10-17. No publication, analytics, Agent or new-user/public proof. Original expiry20:40:56Z unchanged. [Receipt](evidence/pilot-reconnect-refresh-disconnect-20261017.json). |
| Provider retention/AI-data policy | BLOCKED | Exact data-flow clarification unresolved; policy/Agent provider-data gates remain closed. |

## Supported feature/access-tier gates

| Capability | Candidate | Bounded read-only Trial | Public Standard acceptance |
|---|---|---|---|
| OAuth/refresh/reconnect | Implemented/tested | REAL exchange/identity/refresh/reconnect PASS for exact approved actor/workspace/business account; final grant locally revoked | Public new-user acceptance NOT RUN |
| Board discovery | Bounded pagination/eligibility | REAL official GET200/empty boards PASS; no eligible destination selected | NOT RUN |
| Board sections | Implemented/tested publishing path | Excluded by egress/action gate | NOT RUN |
| Image Pin | JPEG/PNG≤10MiB Rafii limit; frozen review/approval/read-back | Prohibited; separate exact write approval | Standard/release/action gates |
| Scheduling | Existing durable timezone/worker path; server_schedule metadata fixed in local candidate | Prohibited by original read-only scope | Actual execution NOT RUN |
| Disconnect/pause | Atomic local authority/job/callback cancellation | Available after expiry; actual local disconnect PASS after human MFA | NOT RUN |
| Agent boards | Optional read tool and current-intent/data gates | Excluded from pilot | NOT RUN |
| Native Pin analytics | New local gated adapter/metric-worker implementation;4 native metrics, UTC window definitions | Not enabled; no pins:read; live analytics NOT RUN | Separate release/permission/schema gates |
| Comments/reply | Official public API5.28.0 has no operation; explicitly Unsupported with reason | No unofficial workaround | Provider capability absent |
| Video/tagging/board mutation/updates | Separate future capability gates | Not enabled | NOT RUN |

Identity scope:user_accounts:read; profile/boards adds boards:read; approved image publication/read-back additionally needs pins:read,pins:write. No secret-board scopes; broader old grants rejected in read-only mode. API host selection is distinct from access tier. Sandbox entities/tokens are separate; Trial content is not proof of public visibility. Personal-account data may require Pinterest authorization; actual personal-account eligibility of app1615884 remains unverified. Approved business account identity succeeded; this does not establish personal-account access. [Official recheck2026-10-17](evidence/official-docs-recheck-20261017.json).

## Local capability candidate — 2026-10-17

Product ddbcdde7 plus fixture correction **e2e5169ff19ac268c0a0ad06994f67b41f69f949**, built once as READY dpl_2tFM, not promoted. New exact-source [JCB qd2tzg2hn0](https://depot.dev/orgs/jf34f85hr0/workflows/qd2tzg2hn0) PASS:463Python/51Node,7disposablePG17.11 scripts, typecheck/lint36warnings0errors/build/synthetic browser. Remote/controller0,178.406s.3302local input hashes; remote3555-file fingerprint matches submission. [Receipt](evidence/capabilities-validation-20261017.json). Analytics uses only user_accounts:read,boards:read,pins:read, is disabled by default, requires reviewed provider/execution/current tenant grant plus metric workspace admission and the separately applied schema. No production metric migration or new scopes have been approved/applied. [Official API audit](evidence/capabilities-official-api-20261017.json).

## Current deployment boundary

The exact code deployment was later approved/executed once. READY2tFM/sourcee2e/receipt104 has2217matchingfiles and health/configured PASS. Promotion **BLOCKED**: shared production Discord-token updatedAt changed20:11:17Z before build; actual value change unverified. Live remains sF/c8; flag-off new-source UI NOT RUN. [Receipt](evidence/capabilities-deployment-20261017.json) · [Disposition](NEXT-ACTION-PROMOTION-CONFIG-DRIFT.md).

## Final promotion result

Separate direct APPROVE accepted known shared Discord-setting metadata drift. One promotion completed20:28:14Z, CLI0; rafii.io and project production target2tFM verified, health200/configuredtrue and actual Channels GET200/private read-only UI PASS. Earlier BLOCKED promotion is resolved. No second build/OAuth/provider call/SQL/analytics/public enablement; original20:40:56Z expiry unchanged. Discord behavior unverified. [Receipt](evidence/capabilities-promotion-20261017.json). All provider-write/public-release gates above remain unchanged.


## Current feature-specific decision — 2026-10-17

Production remains e2e5169f/2tFM READY; local repaired source **776930ed3851047ee5d9022cc49a1a69fe128830 is not deployed**. The private read-only window expired20:40:56Z; no new grant/extension. These decisions concern public third-party use, not previously passed owner read-only tests.

| Feature | Decision | Exact remaining gate / owner |
|---|---|---|
| Connect | NO-GO | Pinterest Standard/eligibility; restore intended session and separately approve fresh bounded demo authority; real non-owner onboarding/isolation/refresh/disconnect; policy/security release review. Pinterest + customer/human + engineering. |
| Publish | NO-GO | Connect gates, real board ID and exact approved Pin; qualified private write authority, actual POST ID/read-back/visibility/no duplicate proof. Human + engineering/provider. |
| Schedule | NO-GO | Publish gates, delta remote qualification/deployment and actual>1h due execution, edit/cancel/pause/timezone/refresh/recovery proof. Engineering + human test operator. |
| Analytics | NO-GO | Delta remote qualification/deployment, approved schema/flag/read grant, own real Pin/window success/no-data/failure and retention permission. Engineering + Pinterest/product owner. |

| New delta acceptance | Status | Evidence |
|---|---|---|
| Analytics outcome/empty durable receipt | PASS | Two selected synthetic local Python controls2026-10-17,0.005/0.003s; not full module/DB/live proof. |
| Stale proof before write / revocation fences | PASS | Two selected synthetic local Python controls2026-10-17,0.015/0.040s with positive+cancel/reconnect/lease/member/account/approval subcases. Actual scheduled execution NOT RUN. |
| Expired pilot diagnosis fail-closed | PASS | One selected synthetic Python control2026-10-17,0.006s. Live message still older e2e implementation; local fix not deployed. |
| New source Node/typecheck/build/browser/PG | PASS | Approved exact v0czdxw6gg remote delta run completed17Oct; see latest execution below. Full-project CI NOT RUN. |
| Two Pin preview metadata | PASS | Frozen original PNG/HTTP200/MIME/dimensions/SHA and local JSON checked; actualboardID1126814837958721891bound; immutableContentStudioasset/Pinapproval stillpending. pin-previews/. |
| Real approved board creation | PASS |17Oct22:25UTC, onePUBLICnativeUIboard1126814837958721891,0Pins, owner/description/reload+anonymouspublicwidget verified. OAuth/v5eligibility NOT RUN. |
| Review video | NOT RUN | Dedicated agent produced actual partial footage; see video receipt for format/segment limitations. Full compliant OAuth/Pin demonstration is not supplied. |

Connect+Publish may proceed in an approved two-customer canary when their own gates pass, while Schedule/Analytics remain off. No current feature is public GO; this is not a blanket postponement tied to the slower optional features.

## Four-capability private Trial candidate — current2026-10-17

This is a separate private acceptance lane, not publicGO. The original read-only grant/window remains revoked/expired. New code binds one actor/workspace/stable provider account/exact boards/caps/<=24h policy and at most2non-refundable create attempts; no public Standard/review flags are asserted. Publish+Schedule use the existing approval/worker path and exact immutable asset source. Known returned IDs get an independent immutable response journal, allowing GET-only recovery after lost workspace proof; unknown response/noID stays uncertain without repost. Analytics admits only exact current-policy recorded Pins and the actual metric workspace/schema grant, with success/no_data/read_failed distinct. [Activation/recovery candidate](PRIVATE-TRIAL-RUNBOOK.md).

| Private Trial capability | Current decision | Actual evidence / remaining gate |
|---|---|---|
| Connect | NO-GO for new window | Earlier owner read-only lifecycle realPASS retained; new bound four-scope consent/config/source not activated or accepted. |
| Publish | NO-GO | Code candidate prepared; exact board/immutable image/new SQL+config/deployment/Pin approval and actual PinID/read-back NOT RUN. |
| Schedule | NO-GO | Code/negative/concurrency/timezone preparation; proposed, unapproved18Oct12:00EDT due execution NOT RUN. The revised time is unapproved. |
| Analytics | NO-GO | Candidate bypasses Standard only for exact private policy; cloud deltaPASS; productionSQL/deployment/nativecurrentPindataread NOTRUN. Confirmed zero/no-data remains legitimate Trial evidence, no fabricated engagement. |

Prepared private-Trial journal/RLS/concurrency suite passed in the approved v0czdxw6gg remote delta run. Earlier local-only limitations are superseded for that exactcandidate; liveproduction/provider acceptance remainsNOTRUN. The paidgrant is1/1consumed,0remaining. Public Connect/Publish/Schedule/Analytics all remain NO-GO until their separate provider/customer/release gates pass.

## Latest delta execution —730d0440,2026-10-17

The paid approval was received and executed once. [v0czdxw6gg](https://depot.dev/orgs/jf34f85hr0/workflows/v0czdxw6gg) **PASS**:212Python,7actual disposablePG17.11scripts,12Node,typecheck/lint36warnings0errors/build and3synthetic actual-component browser groups; nativefinished/submission+controller+remote0. Product730d0440/receiptHEADbbe1f0c8,3563inputhashes/fingerprintmatch,487707bytepatch;3mappingfilesrestored. Prior cost-BLOCKED rows are now resolved for this exact candidate. [Receipt](evidence/private-trial-cloud-validation-20261017.json).

| Feature | Scoped implementation acceptance | New live Trial acceptance |
|---|---|---|
| Connect | PASS — bound policy/scopes/account/refresh/tenant negatives; original owner read-only lifecycle realPASS retained | NOT RUN — new four-scope window/grant not activated |
| Publish | PASS — immutable media/approval/lease/scopes/quota/knownIDjournal/read-back/uncertain-no-rePOST | NOT RUN — actualboardcreatedandbound; no currentOAuth-v5eligibility/approvedPinID/providerreadback |
| Schedule | PASS — timezone/DST/stale reverify/cancel/disconnect/lease/quota/recovery contracts | NOT RUN — no approved real scheduled due execution |
| Analytics | PASS — native-response fixtures,zero/no_data/read_failed,tenant/schema/recordedPin/lease guards and actual disposableDB | NOT RUN — no current real Pin/native data read |

All four public/newlive decisions remainNO-GO. Source qualification alone does not activate them. Full-project CI, real non-owner acceptance and compliant Standard demo remainNOTRUN. Canonical production still2tFM/e2e on fresh2026-10-17T22:07:21.583987+00:00read-onlyinspect; no source drift.

## Approved board and activation preflight —17Oct~22:35UTC

OnePUBLICboard1126814837958721891 actualUIcreate/readbackPASS; noPins. NativeMyappsstillTrialactive/noStandardapprovalorpendingdisplayed. CanonicalDB/quota/ownmember/revokedgrant/173productionenvmetadatapreflightPASS as scoped;8backupentriesvisible,restoreintegrityNOTRUN. Exactconfig/SQL/oneconditionaldeployment/freshconsent/mediaingestbundleprepared,notapproved. [Evidence](evidence/private-trial-activation-preflight-20261017.json). All4newlive/publicNO-GOremain; no mock-to-realpromotion.

## Approved activation execution —18Oct02:39–03:01UTC

| Test | Status | Evidence |
|---|---|---|
| Two canonical migrations | PASS | Journal20261018023938, metrics20261018023956; RLS/grants/trigger/definitions verified. [SQL](evidence/private-trial-sql-production-apply-20261018.json). |
| One build and promotion | PASS | Eobk/730d0440,2217source matches,3services/cron,alias+target and HTTP200health. [Promotion](evidence/private-trial-promotion-20261018.json). |
| Four-scope OAuth start and official screen | PASS |9af24e11, exact workspace/actor/callback/scopes, Giveaccess displayed. |
| New exchange/identity/boards/refresh | BLOCKED | Human consent pending as of03:01UTC; old grant revoked/erased. Start is not completed OAuth. |
| Approved image ingest | NOT RUN | Actual immutable object/hash pending return. |
| Pin/schedule/native analytics | NOT RUN |0Pin creates; exact publication approval and actual provider receipts still needed. |

Earlier unapplied/undeployed statements are superseded by this execution. Public all4features remainNO-GO; Standard/actual compliant video/non-owner journey remain gated.

## Current four-scope acceptance and recoverable authoring defect —18Oct03:44UTC

| Test | Status | Evidence |
|---|---|---|
| Fresh human OAuth + correct binding/vault | PASS |69297f6a exchanged03:29:14Z; correct actor/workspace/stable account; all4scopes; token-presence booleans only. |
| Actual eligible destination | PASS | Real View boards for @jamesaucreates shows Rafii — Product & Content Workflows / Public board; exact policy allowlist ties eligibility to approved1126814837958721891. Raw response body not exported; sectionsNOTRUN. |
| New-grant explicit refresh | BLOCKED | Two RafiiPOST403, unchanged rotation; human normal same-account fresh sign-in requested. Earlier2-scope real refreshPASS is historical, not current proof. |
| Actual workspace snapshot / Library authoring | FAIL | GET500/KeyError; canonical own workspace revision104 lacks phase2.trial and has0SQLtrialrows. Librarylist200; metadata-change list503. Upload disabled,0attempts. |
| Snapshot repair regression | PASS | LOCAL SYNTHETIC candidate66c5cedd: missing/null/active/expired4cases and existing YouTube authority/provenance test; diffcheckPASS. Broader remote validation and deployed acceptanceNOTRUN. |
| Approved immutable image ingest | BLOCKED | No matching sourceHash assets; repair/approved deployed acceptance needed.0uploads. |
| Real Pin / due schedule / native Analytics | NOT RUN |0creates/0Pinterestjobs,0exactPinapprovals. Drafts remain nonexecutable until final actual normalized object/hash review. |
| Standard Access | BLOCKED | Native Myapps rechecked~03:41UTC: Rafii/Trialaccessactive/Upgrade. No Standard approval or submission by this task. Dedicated recording agent progressing installedOBS qualification; full compliant videoNOTRUN. |

[Exact current receipt](evidence/private-trial-four-scope-acceptance-20261018.json) · [Concrete new revision validation/deployment approval](NEXT-ACTION-SNAPSHOT-REPAIR.md). Earlier expired9af transaction remains preserved as historical evidence; it was not reused. Policy still18Oct18UTC; no new resources/SQL/build/promotion/CI/Pin effects this continuation.

## Approved snapshot repair validation —18Oct~05:30UTC

| Test | Status | Evidence |
|---|---|---|
| Newsource focused cloud compatibility | PASS |08m85w3gj9:32tests0.562s,controller87.782s,all3exit0;3476inputfingerprintmatch,3mappingexactrestore. UnchangedPG/Node/frontendresultsreused. |
| Current production/env preflight | PASS |05:18UTC Eobkalias+projecttargetREADY;173productionenvmetadata recordsunchanged; privateexistingbucketverified. Mustrefreshbeforebuild. |
| Repair deployment | BLOCKED |HumanCI+conditionaldeployapprovalgranted;0buildsubmissions/0promotions. ProtectedCopycontrolreturnsSECURE_INPUT_BLOCKED; humanmustcopyexistingmaskedkey. No newapproval or bypass. |
| SourcefixedactualsnapshotGET200/Library | NOT RUN |Live730d500 remains; candidate66c5cedd isnotdeployed. |
| ApprovedPNGingest/finalPinasset | BLOCKED |0attempts; revision-fenceduploaddisabledbysnapshot500. |
| FullStandardAccessvideo | BLOCKED |DedicatedagentissuednoStartRecording/scene/profile/source/windowcreation; CUAgetAppOBSblocked6120s thenparentinterrupted. Rootprobe4527stimeout. No newfootage; existing4fpspartialinsufficient. ExistingOBSstateunknown/MissingFilesuntouched. |

[NewCI/sourceproof](evidence/snapshot-repair-cloud-validation-20261018.json) · [currentexecutionhandoff](evidence/snapshot-repair-deployment-blocker-20261018.json) · [recordingattempt](evidence/obs-qualification-attempt-20261018.json). No realPin/schedule/nativeAnalytics/Standard/nonowner/publicresultadded.
