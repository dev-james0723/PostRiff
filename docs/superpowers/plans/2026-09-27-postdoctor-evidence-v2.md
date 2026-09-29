# Post Doctor Evidence V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in this session. No worker delegation is required.

**Goal:** Deliver contextual, grounded Post Doctor advice with reproducible evaluation and truthful Stage 2 outcome tracking.

**Architecture:** Extend the existing judgment/router/service/UI path with explicit rubric selection, a context contract and a bounded comparison. Reuse Stage 2 persistence and experiment services after its active owner has committed a verifiable integration base. Keep the frozen v1 benchmark and its paid checkpoint immutable.

**Tech Stack:** Python/unittest, existing PostgreSQL services, Next.js/TypeScript, existing Playwright browser harness, JEV and Gemini through the existing Gateway router.

**Spec:** `docs/superpowers/specs/2026-09-27-postdoctor-evidence-v2.md`

## Global Constraints

- `POSTRIFF_POST_DOCTOR_V2=1` explicitly selects v2; absence retains v1.
- Goals: `conversation`, `shareability`, `authority`, `reach`, `general`; at most three actions.
- Bounded comparison: `original`, `candidate`, `equivalent`, `unsure`; never auto-publish.
- Preserve consent, source grants, exact revision, request idempotency, monetary reservation and unknown-dispatch fences.
- Missing context is unassessed, never zero; public engagement is not human quality calibration or causal lift.
- The USD 2 / 480-call pilot is a proposal awaiting separate cost approval. Held-out evaluation and real-user experimentation have separate manifests and authorization.
- No writes to the other active Stage 2 checkout; no unrelated deployment or global configuration changes.

## Review Focus

1. Blank audience plus high-confidence answers must still produce an unassessed audience dimension (Task 1).
2. A new rubric file must not silently select v2 for old benchmark, anonymous, cached or calibration paths (Task 1).
3. Goal/source/consent changes and partial rewrite acceptance must invalidate comparisons and frozen predictions (Tasks 2–3).
4. Model preference must not override unsupported claims, voice mismatch, an equivalent draft or order disagreement (Task 2).
5. Repeated posts, outcome leakage, missing measurements and adopter-only selection must not create a false quality/lift claim (Task 4).

---

### Task 1: Explicit versioning and evidence requirements

**Files:**
- Create `src/postriff_phase2/growth/advice_context.py`.
- Create `src/postriff_phase2/growth/question_sets/postdoctor.v2.json`.
- Modify `src/postriff_phase2/growth/post_doctor.py`, `service.py`, `compare.py`, `questions.py` and `.env.example`.
- Test `tests/test_growth_postdoctor_v2.py` and existing growth question/calibration tests.

**Interfaces:**
- `advice_context.build(creator, *, goal='general', format_id='text') -> dict`: bounded plain-text context, explicit missing fields, schema version and digest.
- `advice_context.missing(qs, state) -> dict[str, tuple[str, ...]]`: required state paths absent for each dimension.
- `PostDoctorService.check(..., goal='general', format_id='text')`: compatible optional arguments; v2 output carries reasons and context digest.
- `serialize(result, lang)` resolves the exact `result.question_set`, not the latest set.

- [ ] Write tests for absent/blank context despite confident audience answers, contextual cache separation, v1 exact behavior and rejection of a v1 calibration profile for v2.
- [ ] Run `PYTHONPATH=src:tests python -m unittest tests.test_growth_postdoctor_v2`; confirm the new-contract tests fail before implementation.
- [ ] Implement context requirements and explicit question-set selection. Pin existing v1 benchmark callers before adding the v2 file. Keep the v1 file and abstention thresholds unchanged.
- [ ] Run `PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_growth*.py'`; expected all pass.
- [ ] Commit only this task's source, tests, env documentation and reviewed spec/plan.

### Task 2: Focused advice and grounded comparison

**Files:**
- Create `src/postriff_phase2/growth/advice.py` and `question_sets/postdoctor_compare.v1.json`.
- Modify `src/postriff_phase2/growth/rewrite.py`, `router.py`, `service.py`.
- Test `tests/test_growth_advice.py` and PostgreSQL growth lifecycle tests.

**Interfaces:**
- `advice.prioritize(dimensions, *, goal, missing_context, limit=3) -> list[dict]`: stable unique actions, each with dimension and concern/change text; missing-context requests use a distinct action kind.
- `advice.comparison_state(original, candidate, *, context, facts, order) -> dict`: exact texts and allowed evidence only.
- `advice.decide(judgment, *, grounded, voice_preserved, swapped=None) -> dict`: recommended version, status and reasons; no numeric success probability.
- Rewrite result adds optional `comparison` and preserves existing `before`, `after`, `changes`, `missingFacts` fields.

- [ ] Test at most three unique actions, goal-sensitive ordering, unsupported/numeric claims, no-op candidates, uncertain/equivalent answers and inconsistent swapped order.
- [ ] Run the focused tests; verify each new behavior initially fails.
- [ ] Add the bounded comparison after the existing grounding check; use the existing router guard and budget ledger for every extra call. Keep equivalent/uncertain candidates unselected.
- [ ] Verify replay after response loss makes no duplicate paid call; revoked consent stops dispatch and fences completion.
- [ ] Run growth tests plus `python scripts/postriff_disposable_postgres.py tests/phase2/postgres_growth_phase1.py`; expected pass.
- [ ] Commit the coherent advice/comparison change.

### Task 3: Stage 2 integration and user-visible decisions

**Files:**
- Reconcile the eventual Stage 2 committed versions of `growth/service.py`, `closed_loop.py`, `postmortem.py`, `creator_calibration.py`.
- Modify `web/src/lib/growth/types.ts`, `web/src/features/growth/post-doctor-panel.tsx`, `shared.tsx` and existing API request types.
- Test existing/new growth UI tests and PostgreSQL lifecycle coverage.

**Interfaces:**
- Check request accepts optional `goal`; server validates it and fingerprints it. Anonymous check defaults to `general` without private context.
- Check result adds `goal`, `missingContext`, `priorityActions`; original dimensions remain available.
- Comparison result is qualitative; acceptance still uses explicit change IDs and current revision.
- Frozen publication prediction includes goal, context digest, rubric/model and accepted changes. Preserve Stage 2's authoritative metric definitions and owner-approved learning.

- [ ] Verify Stage 2 has a stable committed base and read its receipt before merging/rebasing; stop on ownership conflicts rather than modifying its active checkout.
- [ ] Test goal/audience changes make old check, comparison and request replay stale; partial acceptance requires the established recheck.
- [ ] Add accessible goal selection, at most three concrete actions and honest missing-context/comparison states using the existing Stage 2 visual system.
- [ ] Run Python/PostgreSQL growth suites; web tests, typecheck, lint and build.
- [ ] Run the actual composer → check → grounded rewrite → compare → selective accept → frozen outcome journey with local deterministic providers, at 1440x900, 390x844 and 430x932. Inspect screenshots, focus, overflow, errors and reduced-motion behavior; label these local fixture checks.
- [ ] Commit integration only after all affected checks pass.

### Task 4: Reproducible pilot, held-out evaluation and study readiness

**Files:**
- Create `src/postriff_phase2/growth/pilot.py`, `tests/test_growth_pilot.py` and `docs/design/postdoctor-v2/EVALUATION.md`.
- Reuse the prior paid-recovery journal design with its source identity, before-dispatch reservation, response persistence and unknown-dispatch blocking; do not copy private credentials or raw social content into Git.
- Extend the existing Stage 2 experiment evaluator only where needed; do not build a second experimental-assignment store.

**Interfaces:**
- `pilot.prepare(cases, *, rubric, models, cap_usd, holdout_authors) -> manifest`: fixed hashed inputs, no author overlap, serialized estimates and zero-network preflight.
- `pilot.run(manifest, *, journal_path, execute=False) -> report`: dry-run default, bounded execution only for an explicitly approved manifest.
- `pilot.report(...)` keeps fixture/constructed, human-reviewed and observed-outcome evidence distinct.

- [ ] Test overlap and future-context rejection, tampered manifest, cap reservation, incompatible resume, replay of persisted responses, uncertain dispatch refusal and blinded pair order mapping.
- [ ] Prepare 160 public-post cases plus 40 bilingual constructed pairs with both orders; record up to 480 planned calls and a proposed USD 2 cap.
- [ ] Complete concrete model/input/cost preview; obtain new paid-run approval before dispatch. Never treat the unused portion of the completed recovery cap as new authorization.
- [ ] Execute only the approved pilot and reconcile actual provider usage; review coverage/order consistency and separately reviewed advice quality.
- [ ] Freeze one candidate and a fresh-author validation manifest before examining its outcomes. Keep original gates; any explored sensitivities remain exploratory. Obtain its exact cost approval before execution.
- [ ] Verify experiment reporting includes assigned workspaces, missingness, uncertainty and sample adequacy; synthetic results cannot establish lift. Prepare enrollment/primary metric/horizon/rollback as a reviewable study proposal, without enrolling real users.
- [ ] Commit verified evaluation tooling and aggregate reports only.

### Task 5: Release and production verification

**Files:**
- Create `docs/design/postdoctor-v2/RELEASE-RECEIPT.md` and evidence directory.
- Use the repository's actual release scripts and existing migration/feature-flag workflow discovered at release time.

- [ ] Inspect final branch diff, Stage 2 dependency, deployment environment and current schema. Identify exact changed flags, credentials, cost limits and rollback. No migration is assumed necessary until reconciliation proves it.
- [ ] Obtain action-specific production approval if the existing current-session authorization does not cover this concrete artifact and flag state; do not reinterpret an unrelated release approval.
- [ ] Push reviewed commits/PR as required by the repository, attach any created PR, and validate the changed authenticated path on preview.
- [ ] Deploy/promote the verified artifact and verify release identity, original/rewritten decision path, missing audience state, fresh/stale inputs and all applicable browser/device/layout/runtime gates from James Gems.
- [ ] Reconcile any real smoke-test model charges under an approved cap, and preserve ordinary publication approvals.
- [ ] Report production verification separately from pilot validity and real-user engagement lift. If credentials, approval, sufficient data or Stage 2 integration remain unavailable, report the exact unfinished gate; do not mark Finish complete.

## Plan self-review

All product requirements map to Tasks 1–3; evaluation and leakage protections map to Task 4; release/rollback and production verification map to Task 5. The five review-focus risks have explicit tests. Same-session native execution is intended, preserving the user's earlier request to do recovery here. The installed writing-plans skill requires review of this concrete plan before feature implementation.
