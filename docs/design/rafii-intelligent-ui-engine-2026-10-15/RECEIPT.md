# Engineering receipt — Rafii Intelligent UI engine (2026-10-15)

Branch: `claude/rafii-intelligent-ui-engine-20261015` (local worktree `.agent-worktrees/rafii-intelligent-ui-engine-20261015`), based on `origin/consumer-saas@0822c541`.
**Not pushed, not merged, not deployed. No production change. No paid model calls.**

## Commits

| SHA | What | Why |
|---|---|---|
| 455cea47 | Adaptive UI Planner (cherry-pick of PR #183) | form choice, text-first downgrades, safe upgrades; default off |
| 0fe61357 | Guardrail: Chinese status sentences are not change claims | root cause of 4 of the 8 live no-view cases; affected every Chinese answer about connections, consent, automations and campaigns |
| 28be3654, 6054fe78 | Active-mode `context.layout` hint to the presenter, self-describing | the planner's form reaches the model without changing generated prompts |
| ce45a6f3 | Frozen blinded 60-case holdout plus ARCHITECTURE.md | independent acceptance corpus, sha256 `398dd488…` |
| 41d3c527 | Panel reconciles turns a background tab lost | live J07-b: stuck "Working…" meant no presentation |
| d1419c02 | J10 Interactive tools: NumberField, Slider, Toggle, Readout; `localOnly` validator; flag-gated `toolBrief` | general-purpose UI the model composes from a description (Scenario G) |
| 40f6a435 | `ManagerReply.presentation` (text, view, tool) consumed by the planner | model-driven form choice instead of keywords |

## Parity assessment (honest)

| Capability (brief §) | Status | Evidence |
|---|---|---|
| Model composes the UI tree from typed primitives (§2, §3B) | **Achieved (pre-existing)** | OpenUI Lang programs, validator, 9 journeys, plus J10 |
| Plain text when better (§6H) | **Achieved offline** | blinded no-data subset: 17/17 text cases stayed text |
| General-purpose generated tools (§6G) | **Implemented, flag-off; live UNVERIFIED** | J10 + reactive Readout. A web test drives a Slider and Readout with 0 fetches. No live model run yet |
| Model-driven planner (§3A) | **Implemented, live UNVERIFIED** | presentationHint; rules remain as fallback |
| Local reactive controls with no model calls (§4) | **Achieved (pre-existing + J10)** | `$state` bindings, sort/filter/tabs, Readout recompute test |
| Real actions through approval (§4) | **Partial** | ActionButton then native approval exists; **0 confirmed live UI actions** to date |
| Adapt during conversation (§7) | **Partial** | "Change this view" is a real model patch with a revision. Follow-up continuity has a server-resolved selection only |
| Streaming, cancel, retry, reconnect (§7) | **Achieved live 2026-10-14** | F-cancel and F-retry pass; F-disconnect passes with a deviation |
| Context-sensitive differences between users (§5) | **Partial** | manifest per member role, data-dependent queries; the blinded "same question" groups are untested live |
| iPhone, VoiceOver, 繁/简 live acceptance (§8) | **UNVERIFIED** | needs a device and a signed-in founder run |
| 60-case holdout ≥59/60 (§11) | **NOT RUN live** | needs a paid run and approval; the offline subset is reported only as selection evidence |

## Tests run (all remote runs on Depot `depot-ubuntu-24.04-8` via JCB; temporary task remaps restored and SHA-256-verified)

| Run | Scope | Result |
|---|---|---|
| jwfpwr3212 | integration branch up to d1419c02 + 28be3654: drift, GenUI py/web, PG, full web, full Python patched vs base | drift OK; 450 py; 239 web; 6 PG; 947/947 web; Python regression identical to base (19 pre-existing Library-preview failures, fixed in PR #184) |
| ww98tlh36t | typecheck | exit 0 |
| c6t4w8c6wz | lint | 0 errors, 36 warnings (baseline) |
| **3z2px718h0 (final)** | same as jwfpwr3212, after 40f6a435 | drift OK; 457 py (pydantic schema test runs here); 239 web; 6 PG; 947/947 web; Python regression identical to base (patched 5114 run, base 5056; no failure only in patched); remote exit 0 |
| local | targeted modules: planner 44, tools 12, projection 23, contracts 19, presenter 31, presenter_assets 8, context_lens 30, AnswerPolicy 10 | OK (1 pydantic schema test skipped locally; runs in CI) |

Sub-workstream runs: hidden-tab fix `xb9ls2szhd` (936/936), typecheck `15zbr440b2`, lint `khv6wp81km`. J10 `bqp3hvb8ql` (drift, typecheck, lint, 447 py + 239 web GenUI, 940/940 web).

## Blinded holdout: offline selection evidence (no model, no data simulation)

Only the 25 cases whose correct answer needs no workspace data can be checked honestly offline. They were run with an empty tool log, before the model hint existed:

- text: 17/17 kept as text (including 3 adversarial cases)
- tool: 2/8 recognised by keywords

The missed phrasings were **not** added as keywords. The fix is the Manager's own `presentation` judgement (40f6a435), which only a live run can measure.

## Security notes

- J10 can contain no Query, `@Run`, ActionButton or action id. This is enforced by the validator (`localOnly`), by the Python client, and by flag and data-read gates at turn time, at view start and at presenter build.
- `toolBrief` is the only new egress: the person's own request, at most 600 characters, with URL- and secret-looking words removed. It is sent only for J10, with the tools flag on and no workspace reads, to the same provider. It is also stored in `result.ui`.
- `presentationHint` is an enum taken from a guardrail-passed reply. It grants nothing.
- `context.layout` holds enums re-validated against fixed tables.

## Flags (all absent in production, so OFF)

`RAFII_GENUI_PLANNER_ENABLED`, `RAFII_GENUI_PLANNER_ACTIVE`, `RAFII_GENUI_PLANNER_WORKSPACES`, `RAFII_GENUI_TOOLS_ENABLED`.

**Unflagged behaviour changes:**
- the Chinese guardrail fix (a correctness fix for every turn);
- the hidden-tab reconcile (client);
- the Manager reply schema's new optional field and one paragraph of Manager instructions.

## Rollback

- Revert the branch's commits; there is no schema or migration.
- Runtime: leave the flags unset.
- The guardrail fix and the hidden-tab fix are independent commits and can be reverted individually.

## Next release gates

1. Review and PR this branch (needs push approval).
2. Preview deployment and a browser check of J10 at 360 px, in dark mode and on iPhone (needs push approval).
3. Paid live run: `g03-live-60/v2` plus the blinded holdout, with planner active and tools on in the canary workspace. Needs a new budget approval (estimated US$8–10 for about 120 turns).
4. Owner decision on the J10 egress (`toolBrief`).
5. Founder sign-in for the J09 cases.
