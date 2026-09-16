# PostRiff Consumer Web — Decisions

Append-only. Each decision records what conflicted, what was chosen, and why. Earlier entries are not rewritten.

## D1 — No Git; hashed backups are the change record (2026-09-15)
**Finding:** installed tree has no `.git` (re-verified). Every prior round recorded the same and ruled: do not initialize Git, do not substitute the old `b1f5` checkout (`docs/postriff-improvement-20260914/DECISIONS.md:27`, `RECEIPT.md:7`).
**Decision:** follow the established convention exactly. Before editing any file: copy to `docs/postriff-consumer-web/evidence/before/<relative path>` and record SHA-256 in `evidence/baseline.json`. After each milestone: `evidence/changed-files.json` (before/after hashes) and `evidence/source-diff.patch`. Rollback is hunk-level only, after checking current hash equals the round's "after" hash.
**Validation impact:** `validation_unavailable: Git history/diff unavailable because this installed source has no .git`.

## D2 — Phase numbering and product mode (2026-09-15)
Consumer plan controls numbering: P3 runtime/desktop, P4 paid beta, P5 evidence-led expansion (`…/postriff-product-plan/implementation-plan.md:94-96`; adjudicated `docs/postriff-phase-3-review.md:7-9`). This objective is the **P4 consumer web** scope. Architecture-spec §26 phase labels are not used. Cloud = paying runtime; Remote = founder alpha; Bridge optional (§31.1–4 adopted).

## D3 — Prices are proposals, not code (2026-09-15)
Consumer plan `$19/$39/$79` and the improvement round's single `$39` 8-batch offer are both unvalidated (`pricing-and-economics.md:3` "Prices are not implemented"; `ECONOMICS.md:3` all scenarios simulated). Per `docs/postriff-phase-4-execution-prompt.md:229`: consumer plan is the implementable contract; the bounded-batch offer is a versioned experiment. **Decision:** plan/trial terms are implemented as *versioned decision records* in data, no hardcoded price, no live charge. `Usage & Plan` shows real trial state and labels any price as "proposed".

## D4 — One event vocabulary: architecture §10.4 (2026-09-15)
Three unreconciled vocabularies exist: Phase-2 job states (`store.py:17-18`), Phase-3 runtime kinds (`postriff_phase3/contracts.py:75`), and domain action verbs. None matches the spec's client contract. **Decision:** the client-facing safe event contract is exactly §10.4 (`run.started … run.cancelled`). Job states remain the *execution* ledger (unchanged, backward-compatible). Runtime adapter kinds are translated server-side into §10.4 events; no raw adapter event is forwarded.

## D5 — Analytics and Audience at first sale (2026-09-15)
Spec §31.10 left this open. §27 includes "basic post performance when provider data exists" but not Audience. **Decision:** Analytics ships as a truthful limited surface (native definitions, `Unavailable` ≠ 0, n/d on rates, insufficient-sample <3). Audience ships as a truthful limited state (original-thread context + manual/labelled-AI reply draft only where a qualified connector supports it; otherwise "not available for this provider"). Neither is described as complete.

## D6 — Baseline test numbers (2026-09-15)
Receipts disagree (146/127/135/128/90). Re-baselined this round: Python **152/152**, web **75/75**, tsc 0, hosted build OK. Postgres scripted suites and live hosted validation not run in the audit pass. Only this round's numbers are cited going forward.

## D7 — Python version mismatch (2026-09-15)
`.venv` is 3.14.5; `.python-version` pins 3.12 (Vercel). Tests pass on 3.14. **Decision:** do not change the pin; add no 3.13+-only syntax to `src/postriff_phase2`/`api` (hosted bundle). Note in receipts.

## D8 — Reuse, do not rebuild (2026-09-15)
Keep as-is and build on: `src/postriff_phase2/content_types.py` + tests (spec-complete); approval chain `store.py:247/294/315` and `outcomes.py`; `hosted_worker.py` lease/fencing; `hosted.py` membership transaction; `hosted_storage.py`; migrations 001/002 (additive only from here). The Ideas plan's FastAPI/SQLite service and local broker are transitional founder architecture — its UI/domain *contracts* are adapted, its runtime is not copied.

## D9 — Launch connector candidates require a fresh audit (2026-09-15)
Only LinkedIn (local publish-capable) and Instagram (local identity verified, `publish_ready` probe) have any evidence; both live in the owner-only local broker, never hosted. **Decision:** Milestone C begins with a current official-provider audit before selection. No connector is exposed publicly before its review gate. A local Studio grant is not a cloud customer grant.

## D10 — Four-class source policy is a P0 gate before real-model enablement (2026-09-15)
Current code has only `active/private-local` source flags; the improvement round declares the four-class policy (`public_quote / rewrite_approval / internal_reference / prohibited`, `docs/postriff-improvement-20260914/SPEC.md:104-112`) a red line before any real model call (`DECISIONS.md:42`). **Decision:** Milestone B implements `project_context(...)` as the single pure projection consulted at entry and at worker claim; legacy rows without `sourcePolicy`/`egressConsent` default to forbidden for public generation; publish never enters the tool registry. Real-model routes stay blocked until this passes hostile/private/retraction tests.

## D11 — Milestone order (2026-09-15)
A (tenant/auth/roles/isolation proof) → B (conversation + AgentRuntime + source policy + tools + media) → C (connector audit, hosted OAuth, durable multi-destination execution) → D (entitlements/ledger/privacy/analytics/audience) → E (six-destination shell, PWA, ops, launch acceptance). Visual redesign does not precede the core journey.
