# Handoff: Rafii Adaptive Social Coworker (WP0–WP11)

As of 2026-09-25. The work is isolated in **one local commit** on the branch `rafii/coworker-wp0-wp11`, built path-limited from the shared worktree `James-Au-Studio-site-agent` (branch `raffi/site-agent`): only Rafii-owned files and hunks. Nothing was pushed, merged, migrated on a shared database, deployed, sent to a real person, or charged.

## Status words

| Status | Meaning here |
|---|---|
| IMPLEMENTED_AND_VERIFIED | Built, and the claim is fully proven by local gates; it has no external provider in it. |
| IMPLEMENTED_LOCAL_ONLY | Built and proven locally with synthetic providers, a disposable database or a scripted model. The live part (a real provider, device, model or database) was not exercised. |
| IMPLEMENTED_UNVERIFIED | Built, not proven by a gate. |
| PARTIAL | Some of the requirement is missing; the gap is named. |
| BLOCKED_EXTERNAL | Needs an account, credential, spend or production authorization that was not given. |
| NOT_IMPLEMENTED | Not built. |

**Live verified: nothing.** Every result below is local or synthetic.

## Work packages

| WP | What | Status | Evidence |
|---|---|---|---|
| WP0 | Discovery and architecture lock | IMPLEMENTED_AND_VERIFIED | `ARCHITECTURE_LOCK.md` (facts, decisions, deviations, §9 implementation decisions, §10 review remediation) |
| WP1 | Capability registry, James → Rafii migration, Humanizer, no-leak gate | IMPLEMENTED_AND_VERIFIED | `skills/rafii-registry.json`, `capability-ledger.json`, `JAMES_MIGRATION_AUDIT.md`; registry gate, 33 + 14 unit tests |
| WP2 | Notification core (events, planner, preferences, deliveries, detector, digest, baseline) | IMPLEMENTED_LOCAL_ONLY | PG N01–N10, T01, V01–V03; migration 024 has run only on disposable databases |
| WP3 | HTML email (24 templates × 4 locales) | IMPLEMENTED_AND_VERIFIED | 96 previews, 768/768 renders (Chromium + WebKit, light/dark, 600/375 px, axe) |
| WP3 | Resend send, webhook, deliverability | BLOCKED_EXTERNAL | Code and Svix verification tested locally; no live send or webhook (needs Resend key, DNS, webhook secret) |
| WP3 | Web Push | IMPLEMENTED_LOCAL_ONLY | RFC 8291/8292 round trip, SSRF allowlist, service worker tests, browser opt-in states; no real device push (needs VAPID keys) |
| WP4 | Adaptive overlays (explicit/inferred, scope, decay, controls) | IMPLEMENTED_AND_VERIFIED | PG O01, OverlayTest, browser personalization checks |
| WP5 | Weekly Social Operator | IMPLEMENTED_LOCAL_ONLY | PG W01–W07, V04, V05; drafted by the deterministic preview writer, not a live model |
| WP6 | Source → Campaign and Research Broker | IMPLEMENTED_LOCAL_ONLY | PG S01, R01, V06; fixture providers (Exa/Jina never called) |
| WP7 | Creative planning | IMPLEMENTED_AND_VERIFIED | CreativeTest; plans are deterministic |
| WP7 | Image generation or editing | BLOCKED_EXTERNAL | Unchanged runtime path; paid, not exercised |
| WP8 | Performance learning (non-causal hypotheses, anomalies) | IMPLEMENTED_LOCAL_ONLY | PG P01, PerformanceTest, PerformanceWindowTest; synthetic metrics |
| WP9 | Listening, engagement copilot, attention | IMPLEMENTED_LOCAL_ONLY | PG L01, E01, A01; listening through a fixture broker |
| WP10 | Agent Runtime convergence | IMPLEMENTED_LOCAL_ONLY | `test_rafii_runtime_convergence` (scripted Manager → specialist runs), the runtime's own 42 tests; no live model turn |
| WP11 | Flags (11, default off; preview pins egress off) | IMPLEMENTED_AND_VERIFIED | FlagsTest, deployment tests, cron no-op with flags off |
| WP11 | Growth metrics, A/B assignment, fleet report | IMPLEMENTED_LOCAL_ONLY | PG G01, V07 (no ended trials locally, so the per-arm rates are empty) |
| WP11 | Positioning A/B exposure on a page | PARTIAL | Assignment and exposure API exist; no page renders the copy (that needs a change to shared marketing/onboarding pages) |
| WP11 | Load at production scale | PARTIAL | No load harness; cron steps are bounded by time and batch size instead |

## Gates (exact commands and counts)

**Where these results come from.** Every result in this table was produced from this commit's own tree, before it was committed: a throwaway worktree was created at the base commit (`cf48b42`) and the candidate tree (the base plus exactly the committed files) was checked out into it, with `web/node_modules` cloned from an existing install (no `npm` download). The evidence files in `evidence/` and `web/evidence/` were regenerated there (2026-09-25, about 05:45–06:10 UTC). The same gates were then re-run on the exact commit; the results are in the commit report.

Environment: Python 3.12.13 with `requirements-dev.txt` (openai-agents 0.22.3), `PYTHONPATH=src:tests POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0 PYTHONDONTWRITEBYTECODE=1`; Node 24; PostgreSQL 17; Playwright Chromium 1243 and WebKit 2359.

| Gate | Command | Result |
|---|---|---|
| All coworker gates | `python scripts/rafii_coworker_verify.py --full --web` | 10 PASS, 0 FAIL, 0 STALE, 0 NOT_RUN (`evidence/verification.json`) |
| Registry | `python scripts/rafii_skill_registry.py --check` | 90 registered (knowledge 46, tool 21, policy 10, evaluator 8, workflow 5); 82 default, 5 private; 0 orphans; 1 deprecated, 2 dormant; 0 James-leak findings (skills plus 22 product-copy files) |
| Python, coworker modules | `python -m unittest tests.test_rafii_skill_registry tests.test_rafii_humanizer tests.test_rafii_notifications tests.test_rafii_workflows tests.test_rafii_runtime_convergence tests.test_rafii_review_fixes` | 130 tests, OK |
| Python, everything | `python -m unittest discover -s tests -p 'test_*.py'` | 979 tests, OK |
| PostgreSQL, coworker | `RAFII_COWORKER_EVIDENCE=$PWD/docs/design/site-agent/adaptive-social-coworker/evidence/pg-coworker.json python scripts/rafii_pg_private.py postgres_coworker` | 35/35 PASS |
| PostgreSQL, every suite | `python scripts/rafii_pg_private.py` (private port 55738; the same scripts as `postriff_pg_suite.py`) | 41/41 scripts exit 0 |
| Email render | `RAFII_CHROMIUM_PATH=… RAFII_WEBKIT_PATH=… node scripts/rafii_email_render_check.cjs` | 768/768 |
| Web typecheck | `npm --prefix web run typecheck` | exit 0 |
| Web lint | `npm --prefix web run lint` | 0 warnings, 0 errors |
| Web node tests | `node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs` | 100 pass, 0 fail (48 existing, 52 coworker) |
| Browser QA | API harness (`scripts/postriff_dev_hosted.py --port 4741 --pg-port 55721` with the RAFII flags) plus `next dev` (`POSTRIFF_DIST_DIR=.next-coworker`), then `node web/tests/coworker-browser.cjs --browser=chromium` and `--browser=webkit` | 47/47 Chromium, 47/47 WebKit (axe: 0 serious/critical on the 3 new pages) |
| Local production build | `POSTRIFF_DIST_DIR=.next-codex-coworker-build npx next build` (in `web/`) | exit 0; `/app/weekly` and `/app/workspace/personalization` built. The build downloads Google Fonts (`next/font/google`, code already at the base): a public, unauthenticated read. Build output and the tsconfig lines Next added were removed afterwards |
| Secret scan | `python scripts/consumer_ready_secrets.py` | PASS: 1389 files, 0 unexpected |

**Why a private port.** Another session runs `postriff_pg_suite.py` on 55438. `scripts/rafii_pg_private.py` runs the same scripts on 55738 in a mirrored copy. An earlier version of this helper symlinked `docs/`, so two other suites rewrote evidence files owned by other sessions (`agent-runtime/evidence/pg-scenarios.json`, `postriff-research-20260918/evidence/receipt-snapshot.json`). Both were restored to their committed content (my run's copies are kept in the session scratchpad). The script in the repo copies `docs/`, so this cannot recur.

## Adversarial review (WP10–WP11)

Six read-only tracks: security/RLS/authz/SSRF; James leakage and egress; notification duplication and races; truthfulness and mutation verification; runtime wiring and registry integrity; spec coverage, accessibility and release readiness. A skeptic then tried to refute every medium or higher finding. One integration owner closed the findings.

Result: 53 findings (11 high, 9 medium, the rest low; the skeptic refuted 1). **50 fixed, 2 PARTIAL (the positioning exposure and the load test), 1 refuted.** One sub-item of a low finding (mapping a Resend 409 to "already sent") was not done because stable bodies make it unreachable. Every fix has a regression test or a scenario.

| Severity | Skeptic | Finding | File | Outcome |
|---|---|---|---|---|
| high | CONFIRMED | weekly_plan_prepare reports every already-drafted slot as a verified change made in this turn | `src/postriff_phase2/coworker/agent_tools.py` | Fixed: only drafts this call created and read back are changes (V7); PrepareLedgerTest |
| high | PLAUSIBLE | creative_plan and source_campaign_create declare array parameters without `items`; the provider likely rejects the tool schema and breaks three specia | `src/postriff_phase2/coworker/agent_tools.py` | Fixed: `items` declared; ToolSchemaTest checks every registered tool |
| high | CONFIRMED | Turning on RAFII_NOTIFICATIONS_V2_ENABLED emails every customer about all historical failures (no baseline, no cohort) | `src/postriff_phase2/notifications/service.py` | Fixed: first scan is a silent baseline (V1); PG V01 |
| high | CONFIRMED | A weekly drafting limit of $0 removes the cap, so paid drafting runs for every slot | `src/postriff_phase2/coworker/service.py` | Fixed: `spent >= limit` (V6); PG V04 |
| high | CONFIRMED | With the V2 flag on, the legacy automation 'review_ready' and item-level 'publish_failed' emails are suppressed, and v2 never emits an equivalent: app | `src/postriff_phase2/email.py` | Fixed: detector parity for review requests, voided approvals and item failures (V3); DetectorTest |
| high | CONFIRMED | Billing and time-based events (payment_failed, trial_ending, subscription_active, budget, token expiry) are detected only when the workspace revision  | `src/postriff_phase2/notifications/service.py` | Fixed: hourly re-scan of idle workspaces (V2); PG V02 |
| high | CONFIRMED | Enabling v2 triggers a first scan of every workspace with no baseline: stale immediate notices for all historical failures, and duplicates of legacy e | `src/postriff_phase2/notifications/service.py` | Fixed with the baseline above (duplicate) |
| high | CONFIRMED | Weekly drafting limit is not enforced for a $0 limit or for runs of unknown cost | `src/postriff_phase2/coworker/service.py` | Fixed: $0 cap and unknown cost counted at the reservation or $0.05 (V6); PG V04 |
| high | CONFIRMED | The weekly-ready email, push and in-app notice say 'Rafii prepared N posts… each one is drafted and checked' with N = every planned slot, including bl | `src/postriff_phase2/notifications/detector.py` | Fixed: count = drafted-and-checked posts; the lead says sources only where they exist (template 1.0.3); DetectorTest |
| high | CONFIRMED | An expired approval never blocks the week: the week is marked 'scheduled' with false history notes, and the approval_expired branch can never run | `src/postriff_phase2/coworker/weekly_operator.py` | Fixed: an expired approval blocks the week first (V7); WeeklyQueueReadBackTest |
| high | CONFIRMED | The weekly_plan_prepare agent tool reports every slot's draft as newly 'drafted … (confirmed)' on every call, including no-op calls and skipped or sch | `src/postriff_phase2/coworker/agent_tools.py` | Fixed (duplicate of the first) |
| medium | CONFIRMED | source_campaign_create is declared idempotent, but each repeat creates a new source, campaign, paid writer run and set of drafts | `src/postriff_phase2/coworker/agent_tools.py` | Fixed: content-addressed source ids, so a repeat finds the earlier record; SourceIdentityTest |
| medium | PLAUSIBLE | weekly_plan_prepare runs up to 8 sequential paid writer runs in one tool call, ignoring the turn deadline and cancellation | `src/postriff_phase2/coworker/agent_tools.py` | Fixed: 2 per call, refused under 100 s left; cron starts a run only with 95 s left (V8) |
| medium | CONFIRMED | Notifications v2 sends a transactional 'plan is active' email at every subscription renewal | `src/postriff_phase2/notifications/detector.py` | Fixed: keyed on the subscription; DetectorTest |
| medium | CONFIRMED | trial_ended is routed to v2, but v2 has no trial-ended event, so the trial-ended email is never sent while the flag is on | `src/postriff_phase2/email.py` | Fixed: trial_ended stays with the legacy mailer |
| medium | CONFIRMED | Unsubscribe, spam complaint, bounce suppression and mute apply only when a delivery is planned; digest and quiet-hours emails already queued are still | `src/postriff_phase2/notifications/delivery.py` | Fixed: preferences re-checked at send time (V4); PG V03 |
| medium | CONFIRMED | Growth metrics count notification preferences of every user on the platform, not just this workspace's members | `src/postriff_phase2/coworker/growth.py` | Fixed: joined to this workspace's active members |
| medium | CONFIRMED | Personalization: the 'Turn off' button on an expired learned preference sends status 'active' and always fails with 409 | `web/src/features/coworker/personalization/personalization-view.tsx` | Fixed: Turn off sends `disabled` (pauses) for an expired item |
| medium | CONFIRMED | Performance hypotheses put posts into 'morning' or 'weekend' groups using UTC time, not the post's scheduled time zone, so the hypothesis statements c | `src/postriff_phase2/coworker/performance.py` | Fixed: the post's own time zone; PerformanceWindowTest |
| medium | PLAUSIBLE | The meaning check is silently skipped for weekly drafts with no approved facts, yet the draft is marked 'ready' and presented as checked against sourc | `src/postriff_phase2/coworker/service.py` | Fixed: basis recorded (facts, answer, none); UI says "Facts not checked"; presentation test |
| low | CONFIRMED | attention_summary_v2 and source_normalize have no flag gate, breaking the documented 'every flag off = runtime unchanged' fallback | `src/postriff_phase2/coworker/agent_tools.py` | Fixed: both gated; the attention route too (V9) |
| low | CONFIRMED | Runtime trace provenance always records skills: [] even when the instruction hook compiled skills into agent instructions | `src/postriff_phase2/coworker/agent_tools.py` | Fixed: records the skills compiled into each routed agent's instructions |
| low | CONFIRMED | rafii-listening-opportunity passes the orphan gate only because the probe injects a workflow context that no production path sets | `src/postriff_phase2/skill_registry.py` | Fixed: marked dormant; probes must use a workflow production enters; RegistryGateTest |
| low | not checked (low) | rafii-engagement-triage and postriff-social-graphics are compiled but their text is discarded, while provenance records them as shaping the output | `src/postriff_phase2/coworker/engagement.py` | Fixed: provenance marks the method attached but not model-applied |
| low | not checked (low) | Research search and URL sources reach Exa/Jina before the edit permission check, so read-only members trigger egress | `src/postriff_phase2/coworker/service.py` | Fixed: `edit` checked before any provider call; PG V06 |
| low | not checked (low) | The coworker web UI's example text reuses James's career (piano masterclasses in Hong Kong) | `web/src/features/coworker/weekly/opportunities-panel.tsx` | Fixed: neutral examples; product-copy leak gate added |
| low | not checked (low) | After account deletion, the cron security scan re-creates 'user:<deleted id>' notification events from retained audit rows | `src/postriff_phase2/notifications/detector.py` | Fixed: security events skip deleted profiles |
| low | CONFIRMED | Digest rows left 'claimed' by a crash are recovered only if the same person has a new pending due digest row; otherwise they stay stuck forever, and o | `src/postriff_phase2/notifications/delivery.py` | Fixed: expired digest claims recovered on their own (same rows, key and body) |
| low | PLAUSIBLE | A retry after a crash or lost response sends the same Idempotency-Key with a different body (the unsubscribe token embeds the current time), so Resend | `src/postriff_phase2/notifications/webhooks.py` | Fixed: unsubscribe token based on the delivery's creation time. Not done: mapping Resend 409 to "already sent" (no longer reachable with stable bodies) |
| low | not checked (low) | email_unsubscribed=false is read back as 'unset': a narrower resubscribe cannot override a broader unsubscribe, and set_preference always reports veri | `src/postriff_phase2/notifications/store.py` | Fixed: nullable `in_app`/`email_unsubscribed` in 024; SendTimePreferenceTest |
| low | not checked (low) | The digest records rows it did not include as 'sent' with the digest id, marks an all-excluded digest 'failed' rather than 'cancelled', and provider w | `src/postriff_phase2/notifications/delivery.py` | Fixed: excluded rows cancelled/suppressed; webhook applies to every digest row |
| low | CONFIRMED | Research search and source-campaign URL fetch run external provider calls before the 'edit' permission check (viewers and approvers can trigger them) | `src/postriff_phase2/coworker/service.py` | Fixed (duplicate); PG V06 |
| low | REFUTED | Weekly cron keeps drafting under a recipe creator who is no longer owner ('edit' capability instead of 'owner') | `src/postriff_phase2/coworker/service.py` | Refuted by the skeptic; no change |
| low | CONFIRMED | GET week detail writes with requirement 'edit', so viewers and approvers get 403 just for viewing the week | `src/postriff_phase2/coworker/service.py` | Fixed: any member reads; only an editor's read saves; PG V05 |
| low | not checked (low) | Turning email back on always reports verified:false | `src/postriff_phase2/notifications/store.py` | Fixed with nullable preferences; PG V03 checks the re-subscribe is verified |
| low | not checked (low) | Svix verification crashes with 500 on a non-ASCII signature header | `src/postriff_phase2/notifications/webhooks.py` | Fixed: compared as bytes, 401; WebhookAndPushTest |
| low | not checked (low) | Web Push POST follows HTTP redirects, unlike the repository's other outbound calls (_NoRedirect) | `src/postriff_phase2/notifications/push.py` | Fixed: redirects refused; WebhookAndPushTest |
| low | CONFIRMED | 3 of the 24 required notification events are catalogued and templated but nothing ever emits them | `src/postriff_phase2/notifications/catalog.py` | Fixed: producers for research.needs_input, asset.review_required, analytics.anomaly_detected |
| low | not checked (low) | PG scenario N10 never asserts its claim ('the delivery is failed/dead') and passes vacuously | `tests/phase2/postgres_coworker.py` | Fixed: N10 asserts failed/permanent deliveries and an unchanged week |
| low | not checked (low) | Browser QA claims 'reduced motion is honoured' but only checks that the emulation flag is on | `web/tests/coworker-browser.cjs` | Fixed: asserts no looping animation runs under reduced motion |
| low | not checked (low) | The coworker cron step's 40 s budget is not passed to the weekly/learning/listening steps; weekly_cron checks its own 60 s budget only between recipes | `src/postriff_phase2/coworker/runtime.py` | Fixed: 120 s budget passed down to each step; PG V07 |
| low | not checked (low) | Architecture lock and capability ledger no longer match the code (notification schema and capability inventory) | `docs/design/site-agent/adaptive-social-coworker/ARCHITECTURE_LOCK.md` | Fixed: lock N1 updated; ledger regenerated (90, release set) |
| low | CONFIRMED | WP11: trial-to-paid and 30/60/90-day paid retention are never computed, and the positioning A/B is never exposed, so ROLLOUT step 7 cannot be run | `src/postriff_phase2/coworker/growth.py` | PARTIAL: fleet report added (PG V07); no page renders the positioning copy yet |
| low | CONFIRMED | Documented retention and deletion for pr_product_events is not implemented (no TTL sweep, person-keyed rows survive account deletion) | `src/postriff_phase2/account_deletion.py` | Fixed: deleted with the account; cron sweep; PG V07 |
| low | CONFIRMED | Focus is lost when in-place controls swap (weekly Accept confirmation, personalization Add/Edit note), and Accept has a dangling aria-describedby | `web/src/features/coworker/weekly/slot-card.tsx` | Fixed: focus moves into and back from the swap; alert role; dangling aria removed |
| low | CONFIRMED | Required HANDOFF.md is missing, yet README, TEST_MATRIX and ROLLOUT defer commands, gates and live-check costs to it; production build and performance | `docs/design/site-agent/adaptive-social-coworker/README.md` | Fixed: this file; local production build run; load test PARTIAL (none exists) |
| low | not checked (low) | ROLLOUT step 1 cannot be executed as written, and applying 024/025 to shared staging before merge blocks other branches' migration plans | `docs/design/site-agent/adaptive-social-coworker/ROLLOUT.md` | Fixed in ROLLOUT.md (reviewed runner; merge order) |
| low | not checked (low) | ROLLOUT claims flag-off behaviour is 'exactly as before', but the de-personalised skill text and the product-prefix load restriction are unconditional | `docs/design/site-agent/adaptive-social-coworker/ROLLOUT.md` | Fixed in ROLLOUT.md (what ships unconditionally) |
| low | not checked (low) | Default web copy shown to every customer carries James-specific examples (piano masterclasses in Hong Kong, teaching slow practice) | `web/src/features/coworker/weekly/opportunities-panel.tsx` | Fixed (duplicate) |
| low | PLAUSIBLE | rafii_coworker_verify.py reports PASS for the PostgreSQL, email-render and browser gates without running them, from whatever evidence files are on dis | `scripts/rafii_coworker_verify.py` | Fixed: evidence gates are STALE (non-zero exit) when a covered file is newer |
| low | not checked (low) | The 'weekly performance' email calls all-time cumulative metrics 'last week' and is sent even when nothing was posted last week | `src/postriff_phase2/coworker/performance.py` | Fixed: last 7 days only; not sent when none; PerformanceWindowTest |
| low | not checked (low) | The growth metric research_to_campaign_rate is always 100% because the 'research.search' product event is never recorded | `src/postriff_phase2/coworker/growth.py` | Fixed: research.search recorded; rate from events |
| low | not checked (low) | The weekly budget stop counts runs with unknown cost as $0, although its docstring says unknown counts as the estimate | `src/postriff_phase2/coworker/service.py` | Fixed (duplicate); PG V04 |

## Notifications

- 24 events, and every one now has a producer. There are 24 email templates in 4 locales (en, zh-Hant-HK also used for Cantonese, zh-Hant, zh-Hans), at template version `rafii-email/1.0.3`. The catalogue is `NOTIFICATION_CATALOG.md` (generated).
- Preferences: `(user, scope, category)` with nullable fields, quiet hours by time zone, digest, mute, per-scope unsubscribe (RFC 8058 one-click), and transactional exceptions. They are applied when a delivery is planned and again when it is sent.
- Delivery: a Postgres queue (SKIP LOCKED, leases, commit before any network call), Idempotency-Key per delivery, bounded retries, dead letter, digest recovery. The first scan after enabling is a silent baseline.
- Legacy bridge: with the flag on, v2 owns review_ready, approval_expired, platform_disconnected, publish_failed, run_skipped, drafts_ready, trial_ending, payment_failed, subscription_activated and new_device. trial_ended, invitations and welcome stay direct.

## Adaptive learning

Explicit notes outrank inferred items. Inferred items carry confidence and evidence, decay and expire, and can be scoped. Owners can disable, retire, reset and export, and none of this touches global skills or protected policy. Performance produces hypotheses only: never causal (enforced by a DB CHECK), at least 5 posts per arm, unavailable metrics are not zero, and the owner decides. Anomalies are signals, never patterns.

## Agent Runtime

13 coworker tools register through the runtime's own gate, with scopes, voice parity and array schemas with items, plus an instruction hook (flag-gated, bounded, policies never in prompt text) and a trace hook (registry release, the skills compiled into each routed agent, the tools actually used). A disabled feature answers `feature_disabled`. Registration re-binds after the runtime resets its extension points.

## Workflows

The Weekly Operator plans, drafts (bounded), checks, and stops at review or a real blocker. It reads Queue state back, and prepared ≠ scheduled ≠ published. Source → Campaign goes source → FactPack → brief → angles → drafts → creative briefs, with provenance ids at every stage. The Research Broker treats results as leads, never facts. Listening scores opportunities; engagement drafts are never sent; the attention list uses fixed rules.

## External blockers (each needs the owner's explicit authorization)

| What | Needs | Cost | Rollback |
|---|---|---|---|
| Real email send and the Resend webhook | Resend API key, a verified sending domain (SPF, DKIM, DMARC; `scripts/rafii_email_dns_check.py`), `RESEND_WEBHOOK_SECRET` | Resend plan | Turn `RAFII_NOTIFICATIONS_V2_ENABLED` off; the legacy path resumes |
| Real Web Push to a device | VAPID key pair stored as `POSTRIFF_VAPID_*`; a test device | None | Turn `RAFII_WEB_PUSH_ENABLED` off; revoke subscriptions |
| A live writer model for weekly drafts | Owner authorization per run (paid model usage) | Model tokens within the recipe's weekly limit | Pause the recipe |
| Live research (Exa, Jina) | API keys and the owner's research consent | Per query | Turn `RAFII_RESEARCH_BROKER_ENABLED` / `RAFII_LISTENING_ENABLED` off |
| Image generation or editing | Owner authorization (paid) | Per image | Not used by default |
| Migrations 024/025 on staging, then production | The reviewed remote runner; merge order with the branches holding 020–023 | None | Forward-only; flags off leave the tables unused |
| Deployment | Owner authorization; the site-agent session asked for no deploy until it reports done | Hosting | Previous deployment |
| Positioning A/B exposure | A change to shared marketing or onboarding pages | None | Remove the render |

## Concurrency and conflict risks

1. **Shared worktree.** The Agent Runtime session works in the same worktree on `raffi/site-agent` (its commits landed throughout this work). The Rafii files are isolated on `rafii/coworker-wp0-wp11`, but the shared worktree still holds the same files as uncommitted changes, so a broad `git add -A` there would sweep them into `raffi/site-agent`. The coworker files are all new paths except the surgical edits listed below.
2. **Runtime extension API.** `coworker/agent_tools.py` depends on the runtime's `EXTENSION_MODULES`, `specialists.extend_scope`, `INSTRUCTION_HOOKS` and `register_trace_hook` (commit `6b0a9af`). If they are renamed, the coworker tools stop registering, and the convergence tests say so.
3. **Migration numbering and ordering** (inspected read-only; nothing applied anywhere). This branch has 018, 019, 024 and 025. `origin/consumer-saas`, `raffi/launch-final`, `raffi/site-agent-release` and both `release/pr2-*` branches hold `020_credit_quotes`, `021_credit_purchases` and `022_credit_payment_lifecycle`. `ai-routing` holds `020_ai_routing`, `021_ai_connections`, `022_mcp_connector` and `023_companion_relay`: the same numbers, different files. `scripts/postriff_migrate.py` refuses duplicate numbers in one tree, and refuses a database whose ledger has a migration the branch lacks. Consequences:
   - 024/025 do not depend on 020–023 and touch none of their objects (checked by name). 025 only widens `pr_reply_drafts_origin_check` (adds `copilot`); no branch defines that constraint differently.
   - A database already migrated with 020–022 (for example from `consumer-saas`) refuses this branch until it is merged or rebased onto a base that contains 020–022.
   - `ai-routing` and the credit branches cannot both land with their current numbers; one set must be renumbered first. 024/025 stay above both sets either way.
   - Account deletion in this code deletes from 024/025 tables whatever the flags, so 024/025 must be applied to a database before this code is deployed against it (ROLLOUT.md).
4. **Context dependency on Agent Runtime commits.** The `hosted_app.py` coworker route sits right after the agent route (`17e2878`), and the `.env.example` block follows the `RAFII_AGENT_*` block (`6022e15`, `f512dc9`). The commit applies on `cf48b42`; cherry-picking it onto a branch without those commits conflicts in those two files.
5. **Surgical edits to shared files:** `hosted_app.py` (+11 lines), `email.py` (V2_KINDS, Idempotency-Key), `deployment.py`, `account_deletion.py`, `operational_signals.py`, `skills.py`, `vercel.json`, `.vercelignore`, `.env.example`, `scripts/consumer_ready_artifact.cjs`, `tests/phase2/rls.sql`, and five web layout/feature files. These are likely merge-conflict points with `raffi/launch-final`.
6. **Earlier-noted overlaps:** the rafii-v9 job-status relabel and a secret-scanner rename on other branches touch the same areas as `detector.py` and `consumer_ready_secrets` usage.
7. **The peer session's request.** Do not merge, push to consumer-saas, run 024/025 on the production database, or deploy PostRiff until the site-agent session reports done. None of these was done.
8. **Token Pilot** keeps its project enrollment in the root `CLAUDE.md` and `.token-pilot/`; other sessions in this worktree read the same `CLAUDE.md`. `.claude/skills/` is untracked and not part of this work.

## Readiness

- **Merge readiness: NOT_READY.** Every local gate passed on this commit's tree, but the migration order across branches is unresolved (see risk 3), the peer session asked for no merge yet, and the next release stage is not authorized.
- **Deployment readiness: NOT_READY.** Nothing is live-verified, 024/025 are not applied anywhere shared (and must be before this code is deployed, because of account deletion), the Resend/VAPID secrets and DNS are not configured, and deployment is on hold at the peer's request. With every flag off the coworker features are inert, but the unconditional skill-text changes still ship (ROLLOUT.md).

## Next action

The owner reviews the isolated candidate on `rafii/coworker-wp0-wp11` and decides the next release stage. Before any shared database migrates, that includes ordering migrations 024/025 after the 020–023 migrations on `raffi/launch-final` and `ai-routing`.

## Local paths in committed files

`evidence/verification.json` records the absolute interpreter path used for the run, and the supplied execution prompt (`../RAFII_ADAPTIVE_SOCIAL_COWORKER_EXECUTION_PROMPT_2026-09-24.md`) names the local worktree path. Neither contains a secret (the secret scan passes); other committed docs in the repository already contain such paths.

