# Post Doctor: contextual advice and evidence-based evaluation

Status: implementation plan approved by the user on 2026-09-27; implementation in progress. Paid pilot and production release remain separate approvals.

## Outcome

Help a creator choose a few grounded, useful changes to a draft and measure whether the resulting product helps their declared growth objective. The completed 5,440-post v1 benchmark remains an immutable baseline. Better model scores do not constitute observed engagement lift.

## Verified starting point

- Isolated branch `codex/postdoctor-evidence-v2-20260927` starts at V3 Phase 1 commit `8cf23512b809ccaf62f6cb837b7ad6ecf232590c`.
- Stage 2 subsequently completed commit `38a3a061a039ab28234a978aee6c0c570e5938b4`. Its local receipt was read and the commit was fast-forwarded into this isolated branch before implementation; its checkout remains untouched.
- The paid baseline used `postdoctor.v1`, empty creator context, Bluesky/Mastodon public posts and within-creator engagement. Both models failed the English and Traditional Chinese preregistered gates.
- v1 question `hook_curiosity` was excluded by the abstention policy on 4,809/5,440 JEV judgments. Audience scores were computable for 3,540 JEV judgments despite absent audience context. These are measurement/input concerns, not a proven complete cause of the benchmark failure.
- The Stage 2 and recovery v1 question files had identical SHA256 `de6eaebe32535295c7951a033f2c4f22a0c7376523170075c8f594aac339a075` when inspected.
- Completed offline audit reproduced all 16 baseline model/language results and verified unchanged input hashes. In English and Traditional Chinese, excluding audience, selecting complete eight-dimension cases, or retaining raw probabilities without audience left every exploratory AUC below 0.56. These analyses have no new pass/calibration claim and do not justify merely lowering an abstention threshold.

## Product requirements

1. Add an explicitly selected, versioned `postdoctor.v2` behind `POSTRIFF_POST_DOCTOR_V2=1`; preserve explicit v1 selection for existing runs, reports and profiles. Adding a file must not silently switch callers which currently use `questions.get('postdoctor')`.
2. Context includes draft language/platform/format, one declared goal (`conversation`, `shareability`, `authority`, `reach`, or `general`), consented audience and supported approved Genome statements. Use the existing permission, sample-grant and source-revision checks. Do not infer private audience facts from a draft.
3. Missing required context deterministically produces an unassessed dimension, `missing_context` reason and a useful next action. A confident model answer cannot override a missing input. Absence never becomes zero, weak, or fabricated audience information.
4. Use literal observable questions with explicit positive and negative criteria. v2 must distinguish a quality observation from a prediction of engagement. Do not lower uncertainty thresholds simply to improve benchmark pass rates.
5. Show at most three prioritized actions, selected using the declared goal, answer coverage and supported findings. Keep all dimension details available. Each action identifies the concern and suggested change; no promised percentage lift.
6. Preserve the existing creator-grounded writer, explicit fact sources, numerical-claim check, recheck and user acceptance. Compare an original with the grounded candidate through a bounded JEV choice: `original`, `candidate`, `equivalent`, `unsure`. A candidate is not a recommendation until it preserves facts and voice and improves the declared criterion. Unsupported candidates and uncertain comparisons remain available only for explicit review, not preselected acceptance.
7. The comparison is advice, never publication. Changing goal, audience, consent, draft revision, rubric or supporting source invalidates cached results, request replay and pending acceptance. Unknown paid submissions are reconciled, never silently repeated.
8. Freeze goal, rubric/model/version, relevant context digest, original/candidate identities and accepted changes with the exact published revision. Reuse Stage 2 postmortem and creator-calibration services after reconciliation; add no parallel Genome, analytics or experiment subsystem.
9. Personal outcome calibration remains separate from human writing-quality calibration. Missing platform metrics stay unavailable. No audience-fit or follower-conversion claim can be inferred from the public engagement proxy.

## Evaluation sequence

### A. Offline diagnostic, now

Read the completed SQLite checkpoint and CSV without network access or mutations. Verify identities and report per-language/question/dimension coverage, absent-context scoring, and fixed exploratory sensitivities: excluding audience; requiring all eight context-independent dimensions; retaining raw probabilities while excluding audience. Do not retune the original gate or relabel any exploratory result as a pass.

### B. Small paid pilot, only after a concrete run manifest and budget approval

- 160 public posts: 80 English, 80 Traditional Chinese; fixed IDs and input hashes before dispatch. Use only the previously authorized public snapshot. Choose development authors; reserve distinct authors for later validation.
- Run v2 JEV and Gemini on those 160 posts: at most 320 base evaluation calls.
- Add 40 locally curated original/candidate pairs, 20 per language; both display orders and both models: at most 160 comparison calls. Synthetic/constructed pairs are explicitly labeled; they are not evidence of real-world lift or human-reviewed ground truth.
- Maximum 480 planned calls, retries included in the approved money cap. No private creator corpus, external writer generation, new social collection or live publication is part of this pilot.
- Proposed new cap: USD 2.00, not yet approved. Fresh provider pricing and serialized-input estimates must fit that cap before execution. Stop before a reservation can exceed it; reconcile uncertain responses before any retry.
- Assess schema validity, missing-context enforcement, response coverage, conservative abstention and order consistency. Blind review of a manageable subset assesses useful versus harmful advice; model agreement is not a correctness label.
- When audience information is unavailable, test that the dimension is unassessed. Locally constructed contexts are separately labeled tests, not claimed as real authors' supplied profiles.

### C. Frozen held-out validation

Freeze the candidate only after the pilot review. Fix fresh author IDs, source hashes, platform/language cells, outcome window and analysis before accessing held-out outcomes. No development author or post overlaps. Preserve the original v1 association thresholds as the comparator, and evaluate comparable inputs with coverage reported. A separate manifest and cost approval are required; do not silently expand the pilot cap.

### D. Real product benefit

Stage 2 should support an explicitly enrolled, stable workspace-level comparison of the existing flow versus advice availability. Record all eligible exposures, adoption, publication and missing metrics; analyze all assigned workspaces rather than only adopters. Choose an available primary outcome and fixed observation horizon before launch. Determine sample size from observed variability and the minimum useful effect; two accounts per arm or 28 days alone cannot certify success. No real-user enrollment, traffic split or causal-improvement claim is authorized or achieved by this engineering plan.

## Release and verification

Reconcile the completed Stage 2 branch, run affected Python/PostgreSQL/web/browser checks, then prepare the exact release artifact and flag/budget state. James Gems Finish includes release verification, but the project requires action-specific authorization for production changes and paid execution. Preserve a rollback to v1/flag-off. Exercise the authenticated changed path in preview and production on desktop 1440x900 and mobile 390x844/430x932, with screenshots, keyboard checks, console/network checks and deployment identity. Human plan review, new paid costs, deployment scope and actual user study enrollment are separate facts; none is inferred from credentials.

## Evidence locations

Baseline: `/Users/ouxianxing/Documents/rafii-outcomes/recovery-20260927-01a0e3bf/`.
New diagnostic: `/Users/ouxianxing/Documents/rafii-outcomes/postdoctor-v2-audit-20260927/`.
No third-party post text or private creator data is committed to Git.
