# Founder Intelligence preview implementation handoff

## Identity and authority

Repository: `dev-james0723/PostRiff`, verified from GitHub PR85 and upstream origin chain. Coordinator: **Build Rafii admin preview**, chat `01a0f5e0-aa3d-7da0-a6b0-3bb60338888d`. Worker branch `codex/rafii-founder-intelligence-preview-20261001` starts from coordinator-confirmed PR85 head `2ecd87edffe69c3b7a46eac577f9a542b4f291cd`. Worktree: `/Users/ouxianxing/Documents/James-Au-Studio/.preview/rafii-intelligence`. Original checkout and inherited coordinator WIP preserved.

User authorized preview implementation, commits and disposable/local testing. Coordinator owns shared auth/HTTP/workspace integration, canonical seed, UI and ONE preview deployment. This worker changes only three new service modules, their focused tests and this handoff. No hosted migrations, identity enrollment, provider provisioning, external publication, real outbound calls/messages or paid model/voice calls.

Read all four Founder package Markdown files plus the Admin Integration PRD v1.1. The package's referenced new analytics/84-case catalogs and contact-policy JSON contracts are absent in the supplied document directory. Existing Control tech-pack contracts are reused; missing new contracts remain a qualification gap, never a pass.

## Existing implementation to extension map

| Existing authority | Preview extension and limit |
| --- | --- |
| `demo_dataset.sample_data/receipt/refresh_summary` | SAME canonical 10,000 paid subscribers and financial/linked records. No second seed. Scenario patches preserve unrelated record edits and restore only owned values. Canonical receipt binds chart, answer, report, follow-up and summary. |
| `WorkspaceService` locked actor/environment Demo JSONB row | `data.founderIntelligence` persists conversations/reports/reminders/schedules/attempts/summaries in that row. Caller owns CSRF, RLS, revision, replay, transaction commit and audit. |
| `QueryService.require` and current operator/session | Founder, active grant, AAL2, environment, auth epoch, expiration/revocation, control.read/copilot.use/metrics.query checked. Selected customer/invoice requires customers.read; workspace requires workspaces.read, including derived content and replay. |
| `agent_runtime_v2.contracts.empty_result/new_trace_id` | Existing typed result vocabulary and zero-call cost receipt. Deterministic simulation explicitly labeled. Unqualified free text returns a blocked explanation; no hidden model fallback or second agent/router. |
| `phone.contracts.CallReceipt/transition` | Pure simulated call transitions with bounded retries, active/ambiguous-call blocking and reconcile-before-retry. No provider dispatch or arbitrary recipient. |
| `notifications.email_render.render` | Existing HTML/plain-text renderer for incident/recovery previews, safe founder-only metadata, no customer destination; external images/links removed from preview HTML. |
| Existing accounting boundary | Founder operations costState=not_applicable/providerCalls=0; customer credits unchanged. No second accounting store or fabricated live settlement. |

## Integration sequence and interface

Ordered commits: `cce22158` (first conversation/delivery slice; coordinator cherry-pick `f4edb352`), `e4f8dd52` (six scenarios/bounded outbox; coordinator cherry-pick `e9824486`), `f7b36420` (selected entity/current grants), then the final payment/evidence repair increment. Pick only the missing commits in order, never replay the whole branch. Worktrees share commit objects but not uncommitted files.

Coordinator imports `demo_snapshot`, `authorize_demo_action`, `apply_demo_action` from `rafii_control.founder_intelligence`. Call authorization BEFORE cached replay. Apply reducer inside the existing locked revision/replay transaction, persist before returning, and merge `demo_snapshot(data, principal)` into the existing bounded response. Unowned action returns False; malformed action raises safe ControlError; denied optional view returns code/readiness without conversations. Coordinator confirmed three focused disposable DB/HTTP authorization/isolation tests pass; final preview/build evidence belongs in its receipt.

Outer action remains `{action,targetId,value,revision,requestId}`; strict JSON value max4,000 UTF-8 bytes, UUID requestId, current revision, safe identifier targetId. All results disclose simulation and externalDelivery=false. UI consumes `founderIntelligence.lastActionResult`.

```json
{"message":"Which plan has the most subscribers?","conversationId":null,"chartContext":{"chartId":"plan-distribution","viewVersion":1,"queryReceiptId":"CURRENT_RECEIPT_ID","mode":"demo","environment":"CURRENT_ENVIRONMENT","selectedEntity":{"collection":"customers","id":"customer-1"}}}
```

Use above as `founder_turn.value`. Omit selectedEntity for ordinary chart questions. Supported chart IDs: plan-distribution, revenue-trend, usage-distribution, support-distribution. Current-source evidence resolves server-side; no caller KPI, identity or private fields accepted. Invoice trend is invoiced amount/cash in native minor currency units, distinct from MRR. Stale data abstains from current status; saved older receipts remain historical even when the scenario name stays unchanged. Selected entity links refer to that same entity.

| Action | Exact JSON value |
| --- | --- |
| founder_reminder | `{conversationId,intent,dueLocal,timeZone,confirmed}`; null date/false remains draft; explicit future local minute and confirmation saves sandbox schedule. |
| founder_report_schedule | Same, replace intent with `kind:daily\|weekly`. Returns reportId; report saves immutable receipt/facts/text. No scheduler activation. |
| founder_delivery | `{operation:start,channel:call\|email,sourceId}` then `{operation:advance,channel,sourceId,attemptId,outcome}`. Email queued/accepted/delivered/failed distinct; call live/completed distinct from acknowledgement. Retry waits at least five minutes; ambiguous requires definitive reconcile, never blind redial. |
| founder_follow_up | `{attemptId,message}` only while simulated report call is live. SAME saved conversation and report receipt. |
| founder_summary | `{conversationId}` persists receipt/follow-up references; humanAcknowledged stays false. |
| founder_voice | `{conversationId,operation:start\|interrupt\|stop\|repeat\|text,generationId?}`; generation fencing, liveVoiceConnected=false, no recording. |
| founder_follow_up_update | `{id,state:completed\|cancelled,revision}`; current item revision required. |
| founder_schedule_tick | `{}`; manual sandbox tick only, due/missed states, no cron. |
| set_scenario | targetId=`scenario`; plain string value `normal\|payment_failure\|outage\|stale_data\|notification_failure\|recovery`. |

First flow: chart turn → save exact reminder/report schedule → start/advance simulated report call → interactive follow-up → complete call → durable summary. Receipt/fact parity is tested. Notifications expose `{id,sourceId,incidentId,kind,state,attemptId,subject,html,text,recipientLabel,receiptId}` and simulation flags. Payment exception affects the existing Leo/Northline invoice/payment/subscription records; outage affects three existing fictional customers. Delivery failure preserves the active incident; recovery resolves that same episode and emits one notice. Provider acceptance, delivery, call completion and human acknowledgement stay separate.

Public projection: last3 conversations×4turns,16messages,5reports,10schedules/followUps/summaries/contactAttempts,3email previews. Full durable history retained; historyTruncated/totalTurnCount disclosed; internal replay maps omitted. Presentation remains below the existing480KiB limit in the60long-turn test.

## Validation and use

Run on integrated coordinator source:

```sh
PYTHONPATH=src:tests .control-venv/bin/python -m unittest control.test_founder_intelligence control.test_founder_preview_delivery control.test_founder_preview_scenarios
```

In isolated worker source, set `RAFII_FOUNDER_DEMO_MODULE` to the absolute coordinator-owned `src/rafii_control/demo_dataset.py` and use its qualified `.control-venv/bin/python`. This is a test-only module alias, never a seed copy. Focused checks cover exact10k/chart parity, persistence roundtrip, grant/environment/revocation, strict malformed fields, no socket egress/customer debit, DST fold/gap, drafts/confirmation, retry caps/ambiguity, terminal cleanup with saturated replay history, correlated incident/recovery and stale financial provenance. Required final builds/browser checks and the caller's transaction/audit/CSRF/RLS checks belong to coordinator integration; no shared security or dispatch paths edited here.

## Full package scope retained

| Work package | State after this increment; remaining acceptance |
| --- | --- |
| WP00 identity/map | Preview identity/base/ownership verified; hosted deployment/current identity qualification remains gated. |
| WP01 contracts/permissions | Strict preview boundaries tested; missing supplied JSON/contact-policy contracts and production contact admission pending. |
| WP02 receipt metrics | SAME Demo receipt/fact parity; authoritative Live qualification, metric definitions/corrections/cohort tests pending. |
| WP03 contextual UI | Coordinator owned; final desktop/mobile/accessibility/latest-query evidence pending its receipt. |
| WP04 conversations/tools | Durable Demo conversation/result integration; live router permissions, cancellation/media races, full paging and hosted evidence authority pending. |
| WP05 reports/reminders | Saved sandbox drafts/confirmed schedules/report versions/follow-ups/summaries; full decision outcomes and real scheduled delivery pending. |
| WP06 scheduling/contact | Local timezone/DST/due/missed semantics only; durable occurrence leases/replacement, contact consent/destination and hosted scheduler pending. |
| WP07 delivery/budget | Pure simulation state machine/retry/ambiguity/customer-cost isolation tested; real operations reservation/settlement and provider reconciliation pending. |
| WP08 call admission | Current Founder/AAL2 on actions; exact call-bound90s challenge/revocation and real media admission pending. |
| WP09 voice | Explicit simulation controls only; live audio played/cleared/interrupt/latency/English-Cantonese measurements pending. |
| WP10 incidents | Source-backed Demo payment/outage/stale/failure/recovery episodes; reviewed Live detectors/acknowledgement/escalation policy pending. |
| WP11 watchdog | Not implemented/activated; independent degraded-state and finite-budget qualification pending. |
| WP12 A01–A08 | All retained: activation, retention, recurring revenue/cash, AI cost/useful outcome, reliability/releases, feature repeat adoption, support aging/response, security/impact. Demo plan/invoice/usage/support charts and incidents are intermediate evidence, not complete qualified business analytics. |
| WP13 release/acceptance | Coordinator owns preview; exact-head CI/build/browser/rollback and hosted qualification pending. Live final calling needs separate explicit authority. Missing84-case catalog remains not_run/unavailable. |

Implementation, focused tests, preview integration, deployment and activation are separate states. The first two service slices were observed in the coordinator's local preview branch; this document alone proves no hosted deployment. Real scheduled owner-device calling while Mac/browser are closed, interactive live follow-up, durable summary/source parity and explicit acknowledgement remain final acceptance requirements. A simulated call, locally running preview or READY build does not satisfy them.
