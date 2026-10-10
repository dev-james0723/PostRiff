# Rafii agent OS — amended P0 contracts CF-1, CF-2, CF-3

**What this is:** the three P0 foundation contracts for the Rafii Agent Experience Program. The 22 corrections from the adversarial review, the coordinator settlements X1–X13 and James's 2026-10-09 decisions are folded into **one written DDL and amendment set**. The review's verdict was that CF-2 and CF-3 must not freeze until that set exists.
**Status:** PROPOSED, docs only. No product code changes and no real migrations. The DDL lives in this folder, not in `migrations/postriff/`, so the migration runner never sees it.
**Base:** `origin/consumer-saas` `de4e5907`. That is production after PR #138 merged on top of `2af255fd`; #138 touched `agent_runtime_v2/{manager,service,tool_adapter,ui_projection,ui_stream}.py` and added migrations 098/099/100/106. Every code claim was re-read at that SHA (§7).

| File | Contents |
|---|---|
| [CF-1-capability-registry.md](CF-1-capability-registry.md) | Vocabulary, `ToolSpec` fields, `CapabilitySpec`, **`SurfaceBinding` (legacy confirmation per surface)**, classification, `LEGACY_BASELINE_V1`, agent reach, GenUI gate |
| [CF-2-authz-consent.md](CF-2-authz-consent.md) | Presets, consent store, membership end and account deletion, revocation, `decide()`, `decide_for_step`, approvals rules, step-up, **the one client-visible error table**, HTTP API, rollout gates |
| [CF-3-task-engine.md](CF-3-task-engine.md) | Durable task engine: per-person tasks, executors, leases, approvals and resume, checkpoints, cancel, undo, revocation, Task Center API and visibility |
| [migrations/108_agent_tasks.sql](migrations/108_agent_tasks.sql) | Full proposed DDL for CF-3, including the single approvals table |
| [migrations/109_agent_permissions.sql](migrations/109_agent_permissions.sql) | Full proposed DDL for CF-2 (renumbered from the first draft: PR #162 took that number, §5) |
| [DECISIONS-NEEDED.md](DECISIONS-NEEDED.md) | Still-open decisions plus the dated approval ledger and its execution conditions |

Two tests come with the contracts. Neither touches product code:
- `tests/test_agent_os_contract_docs.py` (static, runs in seconds) keeps the amendments folded in, and keeps the real `migrations/postriff/NNN_agent_tasks.sql` and `NNN_agent_permissions.sql`, once J creates them, byte-identical to the frozen proposal and under the same number. It names those exact files and reserves no number range, so another lane's neighbouring migration never fails it.
- `tests/phase2/postgres_agent_os_ddl.py` (disposable PostgreSQL in CI) applies 108 and then 109 on top of the repository's partial disposable-test migration chain, in numeric order (the approved production order remains permissions then tasks), and proves the database rules: RLS, grants, guards, composite keys, cascades and the observer verdict.

---

## 1. Status per contract

| Contract | Status | What freezing needs |
|---|---|---|
| **CF-1** capability registry | **Amended; independent review and recorded remote validation required before freeze.** The review's one condition is met: legacy confirmation moved onto the surface binding, and INV-10 added (correction 6). | J records it in the ledger. No behaviour change. |
| **CF-2** consent, permissions and enforcement (109) | **Amended; independent review and recorded remote validation required before freeze.** Every critical and high correction is folded in. One literal stays open on James's instruction: Recommended's spend scope (SD-1), frozen with the recommended value `all`. | J records it. SD-1 changes only the `PRESETS` literal, not the schema. The DP-6 copy is needed before the UI reaches general release, not before the freeze. |
| **CF-3** task engine (108) | **Amended; independent review and recorded remote validation required before freeze.** Every critical and high correction is folded in. | J records it. GA-A signs off X12, and the founder lane is told that `partial` tasks now count as `failed`. |

**Freeze mechanics (correction 14):**
- J creates `migrations/postriff/108_agent_tasks.sql` and `migrations/postriff/109_agent_permissions.sql` byte-identical to the files here; the static test enforces this. The numbers are proposals: J re-runs the open-PR scan of §5 just before creating the files, and if a number has moved it renames the docs copy and the real file together (the static test requires the same name).
- `scripts/postriff_migrate.py:15-36` keys its ledger by filename and sha256. It refuses duplicate numbers, drifted checksums, and databases holding files the release lacks. So once either file is applied **anywhere** (staging, a shared disposable database or production), it can never be edited, and every change becomes a newly allocated forward migration.
- Gaps and out-of-order numbers are fine, because the ledger is a set.

## 2. James decisions applied (2026-10-09)

| Decision | Where it lands |
|---|---|
| **DP-3/DP-4:** existing users and anyone choosing "Not now" keep exactly today's behaviour (`LEGACY_BASELINE_V1`, no backfill). A non-blocking reminder appears at most every 7 days. | CF-2 §3, `pr_agent_permission_reminders` (109) |
| **DP-4:** Recommended = read/navigate/create at Assist, everything else at Ask. Full needs a fresh sign-in, never covers R2/R3, and respects workspace budget ceilings. Spend scope stays open. | CF-2 §2, §10, §16 (PUT `stepUp`); 109 CHECKs; SD-1 |
| **DP-5:** R2 needs a native button. For R3, Rafii only navigates there, with re-auth ≤ 5 min. Typed or spoken "yes" works only for legacy schedule/automation proposals. Consent-type GenUI actions stay R2 with a native confirmation. | CF-1 §8, §10; CF-2 §9, §10; CF-3 §10; 108 CHECK `pr_agent_approvals_yes` |
| **DP-10:** the task list shows "mine" by default; owners may see workspace scope. Only the task owner and workspace owners can cancel. | CF-3 §12, §17.2 |
| **DP-1:** the gate is a fixed 60-case live corpus with ≥ 59/60 first-pass. Enforcement waits until it passes with the full manifest **and** a narrowed-grant fixture. | CF-1 §9; CF-2 §15 |
| **LIB-D1..D5:** approved canary-first. `library_browse` is **not** in `LEGACY_BASELINE_V1`. | CF-1 §7; CF-2 §15 |
| **DP-8:** 332ed6e6 is the ordinary-user test workspace. | CF-2 §15; CF-3 §21.3 |

## 3. Corrections (critique.json) → where each one landed

| # | Sev. | Correction | Section changed | Status |
|---|---|---|---|---|
| 1 | critical | Another member's request could extend a task and run it under the owner's authority | CF-3 §0, §4.6, §5.1–5.2, §6.1, §17.2, §21.2, §22.5; 108: per-person open-task index, anchor/attempt/approval/receipt guards | **Adopted** |
| 2 | critical | The two contracts gave opposite resume rules for an approval by a non-owner | CF-3 §10.3, §22.4; CF-2 E7; 108 CHECK `owner_kinds` | **Adopted** (one rule: another member's approval completes the step and the owner continues) |
| 3 | high | Rechecks ran only when the epoch rose, which missed several kinds of revocation | CF-2 §1, §7.7, §8.4, A7; CF-3 §6.2, §14, §22.6; 108 `authz_token` | **Adopted**. X2 (the epoch sum) is dropped. |
| 4 | high | Two approval executors and two routes remained after X1 | CF-2 §9; CF-3 §10.2, §17.1; 108 approvals table | **Adopted**, with one refinement: the approval state `failed` is dropped, because execution failure belongs to the step and attempt. `requested_for` is kept and must equal `created_by` (guard). |
| 5 | high | A narrowing action could widen the Manager's toolset | CF-1 §12 test 3, §13; CF-2 §5 `catalogue_diff`, §16 | **Adopted** |
| 6 | high | Legacy confirmation was stored per capability instead of per surface | CF-1 INV-10, §5, §6, §12; CF-2 §8.1 | **Adopted** |
| 7 | high | DP-1 weakened the GenUI gate | CF-1 §9; CF-2 §15 | **Adopted, in James's decided form.** The critic proposed 29/30 twice; James fixed a 60-case corpus at ≥ 59/60, twice (full manifest and narrowed fixture). |
| 8 | high | The GenUI allowlist fails open when empty | CF-1 §9; CF-2 §15 | **Adopted:** a deploy preflight plus a CI test. An explicit `*` remains GA-A's choice. |
| 9 | high | Model-planned inputs could run unattended in cron | CF-1 §4 (`background_eligible` R0 READ only); CF-2 §8.1 `Actor.request_text`, PI-5; CF-3 §5.1–5.2, §7.1–7.2, §22.7; 108 CHECK + guard | **Adopted** |
| 10 | medium | Members could read each other's task details | CF-3 §17.2, §22.13 | **Adopted** |
| 11 | medium | Idempotency was per workspace, not per actor | CF-2 §16, 109 `request_fingerprint`; CF-3 §8.3 | **Adopted with an adjustment.** The unique key stays workspace-wide `(workspace_id, request_key)`, and `created_by` goes into `request_digest`. A per-actor unique would let a replayed key silently create a second member's task instead of the required 409. |
| 12 | medium | Membership end did not match the schema | CF-2 §6; 109 (`ON DELETE RESTRICT`, `ended_at`, no server DELETE, erase function); PG test AOS-04 | **Adopted and extended.** `account_deletion.py:154` deletes the membership rows, so with RESTRICT the account-deletion path must call `postriff_private.agent_permissions_erase` first. That is now part of the contract and is tested. |
| 13 | medium | Nothing enforced same-workspace rows | 108 composite `(id, workspace_id)` / `(id, task_id, workspace_id)` keys; guard triggers; CF-2 §16 `scope_invalid`; CF-3 §7.3 delegate scoping | **Adopted.** The anchor run and conversation are checked by trigger, because composite keys on `pr_agent_runs`/`pr_conversations` would alter existing tables. |
| 14 | medium | The migration plan ignored the runner's rules | §1 above; 108/109 headers; static byte-identical test (exact file names, no reserved range); DECISIONS DP-9 (method) and DP-15 (wording) | **Adopted** (renumbered after the review of #160, §5) |
| 15 | medium | The Library decisions were mislabelled | §6 below; DECISIONS LIB-D6a; CF-2 §15 (LIB-D1 general-release condition) | **Adopted** (journal wording) |
| 16 | medium | The contracts used two error vocabularies | CF-2 §13 (one table); CF-3 §2, §17.1; static test | **Adopted** |
| 17 | medium | "Yes" could approve new R1 rows | CF-2 §9; CF-3 §10.2 step 2, §22.14; 108 CHECK | **Adopted** (DP-5) |
| 18 | medium | Infrastructure would be duplicated (the #104 run store, and leases taken from an unmerged PR) | CF-3 §5.2 (`leases.py` from merged `ui_store.py` only), §15 decision D-EX-1 | **Adopted** |
| 19 | medium | An expired task could misreport a publish | CF-3 §4.4, §22.15; 108 `observes_external` | **Adopted** |
| 20 | medium | The ordinary-user gate did not prove the workspace is non-founder | CF-2 §15; CF-1 §9 | **Adopted** (DP-8) |
| 21 | low | Full had no step-up in the PUT | CF-2 §10, §16 (`stepUp` field); 109 CHECKs | **Adopted** (DP-4) |
| 22 | low | Notes on `brand_summary`/`voice_profile` were wrong | CF-1 §7 ("gated after HF-1") | **Adopted** |

No correction is rejected. Two are adopted with an explained adjustment (11, and the 4 refinement), and one in a form James decided differently from the critic (7).

### 3.1 Adversarial review of draft PR #160 (head `0751ee3c`) → where each finding landed

Each finding was re-verified against the code at `de4e5907` before it was fixed; all eight held.

| # | Sev. | Finding | Fix | Where |
|---|---|---|---|---|
| R1 | blocking | Shadow enforced on GenUI surfaces (E4/E5/E6 called `decide()` or denied in shadow), breaking DP-1 | Shadow computes and logs `wouldOutcome`/`wouldRequired`; every value a person, client or model receives is byte-identical to `off`; only enforce narrows, denies or adds a confirmation. Every enforcement point goes through the mode-aware gate; the manifest revision changes only in enforce. | CF-1 INV-11, §8; CF-2 §8.2, §8.3 (E1–E11), §15, A13 |
| R2 | blocking | `LEGACY_BASELINE_V1` left out the `context.*` capabilities, so enforce would strip every existing user's APP_STATE | The baseline is every consumer capability with `since == 1` of every kind except `native_only`, listing the five `CONTEXT_CAPABILITIES` and the site catalogue explicitly; generated from the registry | CF-1 §12; CF-2 E11, A1 |
| R3 | blocking | PR #162 takes 107, and the static test reserved the whole 107/108 range | Permissions DDL renumbered to 109 (108 stays the task engine); register, X7, DDL headers, DP-9 and the PG suite updated; the static test names exact files only and checks every mention uses the proposed numbers | §5; `migrations/109_agent_permissions.sql`; `tests/test_agent_os_contract_docs.py` `MigrationNumbers` |
| R4 | major | Cancel and membership end stopped the external-effect observers that correction 19 exempts | Claim SQL exempts `observes_external` steps from the cancel filter and delegate polls from `attempts_left`; derive rule 1 waits for open observers; an ended membership or a cancelled task is observed by a read-only observer (verdict `observe`, no `principal_repository`, never acts or spends); 108 accepts `observe` only from cron on such steps | CF-3 §4.2, §4.4, §5.2, §6.1, §12, §14, §22.6, §22.9; CF-2 §8.4; 108 attempts CHECK + guard; PG AOS-13 |
| R5 | major | Correction 10 not closed: the legacy `task` key and the member-readable anchor carried full step detail | The engine writes a redacted projection to `pr_agent_runs` (no outputs, entities, approvals, reason); the legacy `task` key is per caller; the conversation itself is stated honestly as DP-18 | CF-3 §4.5, §17.2, §22.13 |
| R6 | major | The golden tests used ≥ for legacy, so a stricter confirmation or a new deny for legacy users would pass | Legacy (no row, ended row, `LEGACY_EQUIVALENT`) requires equality under off, shadow and enforce on every surface; ≥ kept only for explicit presets | CF-1 §12 tests 2–4; CF-2 A1 |
| R7 | major | CF-3 shadow was not behaviour-preserving (pendingRun moved, legacy tasks superseded, recovery not allowlisted) | Engine modes `off | shadow | on` with `RAFII_TASK_ENGINE_AUTHORITATIVE`; shadow copies `pendingRun`, changes no legacy state and claims or recovers nothing; every adoption, recovery and claim path carries the allowlist predicate | CF-3 §0, §1, §5.2, §5.3, §11, §21.1–21.3, §22.19 |
| R8 | major | The registry build left out the grounded site agent's catalogue | `site_tools.CATALOG` is an `ensure()` source with the frozen `site_capability()` rule (36 adapted ids → `tool.*`, `automation.patch_propose` → `site.automation_patch_propose`); lint, baseline and goldens cover it | CF-1 §1, §5.1, §6, §7, §12, §14; CF-2 E3, A14 |

### 3.2 Remaining review details folded into the takeover amendment

- New confirmation/spend approvals bind `decided_by` to `requested_for`; Full state binds sign-in freshness to `decided_at` (300 seconds; the server separately verifies signed proof). Consent grants/autopilot bind their receipt to the same person.
- Receipts bind attempts to the same task/step, compensations bind their receipt's task/step, planned runs are workspace-checked, and approval conversations equal their task's conversation. AOS writes use `service_role`; only fixture administration/deletion resets to the database owner.
- Claim states include `awaiting_approval`, with one 30-second execution margin. Due external observers still claim after twenty polls and zero task attempts; a hard-TTL predicate stops them at expiry (AOS-17). Shadow revocation handlers cannot mutate legacy results. Workspace-wide revocation explicitly matches all subjects when `user_id=None`.
- Legacy proposal error codes are retained and permission revocation is consistently 403. Permission receipt idempotency is per actor; reminder replay uses its single-row cadence without promising a missing request-key store.
- Server-side GenUI gate evidence downgrades enforce to shadow when absent/stale. R3 handoffs require a server-bound single-use record; a client marker is not sufficient enforcement.
- Test coverage is described as the partial disposable migration chain. Preview cleanup and still-unsupported cross-workspace account erasure are recorded explicitly, not represented as completed product fixes. These contracts remain proposed implementation requirements.

## 4. Coordinator settlements X1–X13 (plan §1)

| ID | Settlement in this set |
|---|---|
| X1 | One `pr_agent_approvals` table, in 108 (union of both schemas, with correction 4 applied); 109 creates none. Enforce mode needs the engine flag in the same workspace. |
| X2 | **Dropped** (correction 3): `Grants.token()` text compared with `<>`, and `decide_for_step` runs on every claim. |
| X3 | `authz.decide_for_step(cur, task, step, *, actor, now) -> StepVerdict`, with the frozen reason mapping in CF-2 §8.4. |
| X4 | Decided by DP-5: native button for every new approval kind; "yes" only for legacy proposals. |
| X5 | Lane J is GA-A or a successor GA-A names. Every patch to `migrations/**`, `vercel.json`, `http.py`, `config.py` FLAGS, `service.py` seams and workflows goes through J. |
| X6 | No change to the `pr_agent_runs` status CHECK; the anchor status is a mirror. |
| X7 | **Amended after the review of #160:** PR #162 (opened 14 minutes after #160) claims the number the first draft gave the permissions DDL, so that DDL moved to 109; 108 remains allocated to the task lane; 109 has no competing claim at the takeover scan in §5; 110 remains observability. J re-scans at freeze. |
| X8 | The `ideas.cancel` actor guard belongs to HF-1; CF-3 no longer lists it. |
| X9 | `pr_library_action_receipts` stays (#144 is not reopened); consolidation is post-GA. |
| X10 | Empty means none in every new allowlist, and `*` must be explicit. The GenUI allowlist is guarded by a preflight (correction 8). |
| X11 | A.1's first commit adds both lanes' `RafiiRunContext` fields; A.2 never edits `context.py`. |
| X12 | Open for GA-A sign-off: `TaskPlan.conversation_id` makes the dead `task_progress` cross-conversation guard live. The founder lane must also be told that `partial` tasks now count as `failed`. |
| X13 | The spend scope is SD-1 (open), with the recommendation `all`. |

**EX-D1..D10:**
- D1 and D2: decided (DP-10, plus correction 10).
- D3: coordinator default, 72 h sliding and 14 d hard (also a CHECK).
- D4: DP-12, open, needed only before R2. P0 runs recovery and expiry inside `/api/cron/worker`, and the new route stays unscheduled.
- D5: no background paid continuations in P0 (correction 9).
- D6: DP-13, open, default 24 h.
- D7: DP-5, decided.
- D8: coordinator default `task_owner` (now also a CHECK).
- D9: X9.
- D10: coordinator default, 1 MiB.

**Decision dependencies:**

| DP | State | Contract sections that depend on it |
|---|---|---|
| DP-1 | decided | CF-1 §9, CF-2 §15 |
| DP-2 | **approved: US$20 total cap** (2026-10-09T21:52:56Z) | Running DP-1's paid live gate after current spend/unknown-cost reconciliation; no fresh allowance |
| DP-3/DP-4 | decided (spend scope = SD-1, **open**) | CF-2 §2, §3, §10, §16 |
| DP-5 | decided | CF-1 §8, §10; CF-2 §9–10; CF-3 §10; 108 |
| DP-6 | **open** | CF-2 §2 copy, §17 (before general release) |
| DP-8 | decided | CF-2 §15; CF-3 §21.3 |
| DP-9 | **approved, conditional** (2026-10-10T01:05:39Z) | Permissions then tasks, each after exact-head CI/review/merge and feature-OFF deploy; rollout gates remain separate |
| DP-17 | **approved, canary only** (same decision) | C5 review; separate visible-state flag; only tab, filter ids and date ranges initially for 267f7d90 |
| DP-11 | **approved in principle** (same decision) | Exact account/post confirmation still required at execution; D Festival public channels excluded |
| DP-10 | decided | CF-3 §12, §17.2 |
| DP-12 | **open** (before R2) | CF-3 §5.3 |
| DP-13 | **open** | CF-3 §13 default |
| DP-15 | conditional | §5 below |
| DP-18, DP-22, DP-7 | deferred | CF-2 §12; 109 `ceiling`; staffing order |
| LIB-D1..D5 | decided (canary-first) | CF-1 §7, CF-2 §15 |
| LIB-D6a | **open** | DECISIONS-NEEDED |
| R3-1 | **open** (clarifies DP-5) | CF-1 §10, CF-2 §10 |

## 5. Migration numbering (takeover scan 2026-10-10T02:25:27Z)

- **Production:** `de4e5907`, migration ledger includes `youtube_planner_fairness_107` from #162 at `20261010015553`; that is unrelated to agent permissions. Read-only schema checks at 02:20Z found all 13 proposed permissions/task relations absent.
- **Open-PR scan:** all 37 open PR file lists were read through GitHub. #162 claims `migrations/postriff/107_youtube_planner_fairness.sql`; no open PR file claims 108, 109 or 110. This is a dated scan, not a reservation.
- **Local worktree scan:** the task-engine lane already has `108_agent_tasks.sql`; permissions WIP still has the old conflicting number and must adopt 109 before integration; the observability lane has `110_agent_observability.sql`. The only local 109 found was this recovered permissions proposal. Other worktrees were preserved, not renamed by this contracts patch.
- **Proposed allocation:** **108 = `108_agent_tasks.sql` (CF-3), 109 = `109_agent_permissions.sql` (CF-2), 110 remains observability.** #162 owns 107. J must update the permission implementation copy and any references, then re-check actual PRs/ledgers before freezing. This docs patch creates no production migration.
- **Order:** the DDL files have no foreign key to one another. The disposable suite applies 108 then 109 to cover numeric ordering. DP-9's approved production sequence is permissions then tasks, separately after each release gate. A pinned exact-file runner must preserve that sequence; this contract does not silently authorize applying all pending migrations.
- **Other historical collisions:** #131's `100_social_cost_reservations.sql` overlaps merged `100_youtube_api_privacy_erasure.sql`; its owner must read affected ledgers before any renumber (DP-15). No unrelated migration is changed here.
- **Freeze safety:** re-scan before creating files; once applied, preserve the recorded filename/checksum and use forward migrations for changes. Static checks compare exact agent OS filenames and bytes and reject another real file occupying either allocated number, without reserving a neighbouring number range.

## 6. No duplicate infrastructure; Library decisions as written

- **Leases:** `postriff_phase2/leases.py` is extracted only from merged `ui_store.py` semantics, plus the backoff spec written out in CF-3 §9.2. #144 may adopt it after it merges; nothing waits on #144.
- **Client run store (D-EX-1, for J's A-DECISIONS):** PR #104 adds `useLiveRunStore` (`web/src/features/notifications/live-state.ts`, fed by `features/agent/use-run.ts`, head `fa6297b0`). EX-W6 adds only read hooks that report into it, and waits for #104. If #104 is closed or still unmerged when EX-W6 is ready, J hands that single store to EX-W6 at the same path and shape. There are never two stores.
- **Receipts:** `pr_agent_receipts` (engine steps), `pr_ui_actions` (GenUI, authoritative) and `pr_library_action_receipts` (#144) each keep their domain; engine steps link through delegates.
- **Queues:** no Vercel Queues. The existing cron, leases and `principal_repository` are reused.
- **Library plan journal (wf_d5b0d850), replacing the plan's reconstructed rows (correction 15):**
  - **D1:** metadata egress, canary 267f7d90 first. General release needs an owner toggle (off by default) and the privacy page update.
  - **D2:** photos and videos stay attach-only.
  - **D3:** document text waits for #144.
  - **D4:** #144/#145 stay on hold, with the D-A51 note about the `library_browse._backend` seam.
  - **D5:** the env change, deploy and uploads for 267f7d90.
  - **D6a:** Library card titles reach the model through the page outline (open, DECISIONS-NEEDED).
  - **D6b:** `content_search` snippets (HF-1).
  - **D6c:** upload `createdAt` (separate task).
  - James approved D1–D5 canary-first.

## 7. Code facts re-verified at `de4e5907` (read-only)

| Claim | Evidence |
|---|---|
| `task_state.active()` has no actor filter (correction 1) | `agent_runtime_v2/task_state.py:204-209` |
| Role check skipped when membership is missing | `agent_runtime_v2/tool_adapter.py:109` |
| `classify()` falls back to `"edit"` (HF-1) | `permissions.py:86-89` |
| Empty GenUI allowlist = every workspace (the draft cited `:147`) | `agent_runtime_v2/config.py:146-154` |
| `actionTargets` is server-only | `agent_runtime_v2/ui_contracts.py:398-399` |
| G03 coded gate is 29/30 | `tests/agent_ui_acceptance/test_agent_ui_acceptance_release.py:158` |
| Runner ledger by filename + sha256; refuses duplicates and drift; `--apply-local` loopback only | `scripts/postriff_migrate.py:15-36, 47-57` |
| Membership end is `status='revoked'`; a re-invite reactivates the row | `migrations/postriff/001_phase2.sql:13-17`; `hosted.py:801` (leave), `:1033` (remove), `:1117` (join) |
| **New:** account deletion deletes membership rows, then the workspace | `account_deletion.py:154, 167` |
| `brand_summary`/`voice_profile` have no egress check (the draft cited `60-100`) | `site_agent/reads.py:60-97` |
| `pr_agent_runs.actor` exists; runs and events are member-readable | `migrations/postriff/005_consumer_web_ideas.sql:40-58, 87-93` |
| Credit quotes cover paid writer runs, media notes and images alike (SD-1) | `credit_wallet.py:116-160`; `credit_requests.py:23, 141-159`; `ideas.py:1312, 1463`; `media_notes.py:261, 318` |
| Agent-route line drift after #138 | `service.py` decide `:1267`, `task_view` `:1240`, pending-run functions `:1063/:1081/:1095` (the drafts cited `1232-1247`, `1034-1141`); `http.py:76-79` |
| Step-up window | `permissions.py:57-58` (`STEP_UP_WINDOW = 600`) |
| `postriff_private` usage for the server comes from 040, which the PG harness does not load, so 109 grants it itself | `migrations/postriff/040_social_trend_intelligence.sql:331`; `tests/phase2/rls.sql` |
| PR #104 live-run store | `gh` read of PR #104 `web/src/features/agent/use-run.ts` at `fa6297b0` |
| **Review of #160:** the grounded site agent's 37 dotted ids are separate from `REGISTRY`; 36 are adapted under `id.replace('.', '_')`, `automation.patch_propose` is not | `site_agent/tools.py:30-96`; `agent_runtime_v2/tool_adapter.py:233, 406-422` |
| **Review of #160:** GenUI counts are 17 actions and 45 queries | `ui_domain.ACTIONS`, `ui_domain.QUERIES` at `de4e5907` |
| **Review of #160:** the cron worker identity re-checks membership in every transaction | `automation_runs.py:38-61` (`principal_repository`) |
| **Review of #160:** `GET tasks/{task}` returns `plan.view()`, whose steps carry outputs, entities, approvals and reason | `agent_runtime_v2/service.py:1240-1250`; `task_state.py:47-53`; `contracts.py:87-90` |
| **Review of #160:** `permission_revision` and the `revised` flag feed every manifest | `agent_runtime_v2/ui_capabilities.py:42, 130, 183` |
| **Review of #160:** PR #162 adds `migrations/postriff/107_youtube_planner_fairness.sql` | `gh api repos/dev-james0723/PostRiff/pulls/162/files` |

The synthesis inputs were recovered from the synthesis workflow's journal (`wf_56f4f1fb-914`: out0–out4, plan, critique) and the Library journal (`wf_d5b0d850-007`), because the scratchpad copies were gone.

## 8. Validation

- **Static test, remote validation:** `tests/test_agent_os_contract_docs.py` (the focused Python contract module).
- **Disposable-PostgreSQL scenarios AOS-01..AOS-17, run in CI only (`local-gates` → `scripts/postriff_pg_suite.py`), never on the Mac:** `tests/phase2/postgres_agent_os_ddl.py`. They cover:
  - apply and re-apply on the partial disposable-test migration chain (not every production migration);
  - browser roles denied;
  - append-only consent history;
  - membership end and the account-deletion erase;
  - creator-anchored tasks;
  - one open chat task per person;
  - composite keys;
  - cron limits and actor guards;
  - the approval CHECKs;
  - the request-key conflict;
  - checkpoint clearing;
  - no server DELETE, and the conversation cascade with SET NULL;
  - the read-only `observe` verdict only on external-effect observer steps, from cron, as the creator (AOS-13);
  - fresh Full decisions and same-person consent receipts (AOS-14);
  - same-task/step attempts and compensations (AOS-15);
  - planned-run tenant and approval-conversation binding (AOS-16);
  - the actual frozen claim SQL with cancellation, ended membership, pending approval, zero retry budget and fail-closed workspace scope (AOS-17).
- **Remote evidence:** the CI result for the PR head is recorded in the PR.

## 9. What J does next

1. Review this PR. Record CF-1, CF-2 and CF-3 as frozen in the ledger, and copy the amendments into `A-DECISIONS` (including D-EX-1).
2. Preserve the approved DP-2/DP-9/DP-17 decisions and the action-specific DP-11 boundary. Only ask the unresolved questions in DECISIONS-NEEDED when their actual gate is reached.
3. Re-run the §5 open-PR migration scan, then hand 109 to lane B and 108 to lane A.2 as the frozen DDL. J alone creates the migration files, byte-identical to these and under the same numbers (renaming both copies together if a number moved).
4. Before applying anything anywhere: read every environment's migration ledger read-only, and confirm the migration owner bypasses RLS on staging (needed by the account-deletion erase function, as for `100_youtube_api_privacy_erasure.sql`).
