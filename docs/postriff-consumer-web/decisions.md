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

## D12 — Launch connectors (2026-09-15)
From the fresh official audit (`connector-audit.md`): **LinkedIn member posting** (self-serve scope; org/analytics/comments deferred — Community Management API is a legal-entity gate; no refresh tokens → 60-day re-auth surfaced on the card), **Threads** (App Review only; insights + replies), **Instagram professional** (App Review + Business Verification; ships after Threads under the same Meta app). Alternate: Bluesky. All three schedule client-side (Assisted schedule level, PostRiff workers execute). No provider offers an idempotency key; manifest idempotency + reconciliation-before-retry remains the duplicate defense. Live execution mounts only when a provider is credentialed **and** explicitly flagged reviewed.

## D13 — Token custody (2026-09-15)
Provider tokens are encrypted at the application layer with Fernet (`cryptography==50.0.1`) under `POSTRIFF_CREDENTIAL_KEY` held in server secrets; the key id is stored with each ciphertext so rotation is detectable (re-authorization required after rotation rather than silent failure). Tokens are decrypted only in the worker path (`token_for_worker`) and never returned by any API or written to state, events, or audit rows.

## D14 — Local dev harness for the hosted code (2026-09-16)
The alpha SQLite server cannot exercise the cloud surfaces. `scripts/postriff_dev_hosted.py` runs the **real** hosted code (migrations 001–007, `HostedWorkspaceService`, permissions, Ideas runtime, source policy, OAuth custody, worker, ledger, audience) on a disposable PostgreSQL, with three things simulated and labelled `dev-synthetic` in the UI banner: identity (`Bearer dev:<uuid>`, no Supabase), the providers (a local consent page + canned responses), and private storage. OAuth rows keep an https PostRiff callback (the production `CHECK` is not weakened); the local consent page returns the browser to the loopback callback itself. The `dev` auth mode exists only when the catalog says so; a production catalog never does.

## D15 — Service worker strategy (2026-09-16)
Network-first for the shell (so a deploy is never masked by a stale `index.html`), cache-first only for hashed `/assets/*`, and a stale-while-revalidate copy of the idempotent workspace snapshot GET for safe offline viewing of recent drafts. No mutations, auth, tokens or media bytes are cached. Push notifications only open a URL; they never execute an action.

## D11 — Milestone order (2026-09-15)
A (tenant/auth/roles/isolation proof) → B (conversation + AgentRuntime + source policy + tools + media) → C (connector audit, hosted OAuth, durable multi-destination execution) → D (entitlements/ledger/privacy/analytics/audience) → E (six-destination shell, PWA, ops, launch acceptance). Visual redesign does not precede the core journey.

## D16 — Customer email is fetched from Supabase Auth at send time, never stored (2026-09-16)
**Conflict:** transactional email (welcome, trial ending/ended, payment failed, subscription activated) needs an address, but `pr_profiles` holds no PII by design and `pr_audit_events`/`pr_notifications` must stay content-free. **Finding:** the Supabase Admin API already used by `SupabaseIdentityAdmin` (`hosted_identity.py`, service key, `delete_user`) also serves `GET /auth/v1/admin/users/{id}`, whose record includes the verified `email`. **Decision:** no `email` column is added. `SupabaseIdentityAdmin.email_for(user_id) → str|None` performs that lookup through an injectable `fetch` transport (stdlib only, mirrors the existing `send` hook; service key travels only in headers, never in the URL). It validates the id as a UUID, returns `None` for 404 or a record without a usable address, and raises `AlphaError` (502/503) when the identity service fails. Callers must treat that error exactly like a mailer send failure: record `sent=false` in `pr_notifications`, never fail the business action, never log the address. `pr_notifications.dedupe_key` (migration 008) is the one-send guard; `meta` carries only kind-level facts (plan id, days left), never addresses or bodies. Invitations are the exception: the invitee's address is already the invitation subject (`pr_invitations.email`, 004) and is used directly. Local dev (D14) has no Supabase, so its identity stub returns `None` and email is reported as "not sent (dev)".

## D17 — Git is the change record from here on (2026-09-16)
Git was initialised on 2026-09-16 on branch `consumer-saas` (baseline commit "Baseline before consumer SaaS rebuild"). It supersedes D1's hashed-backup convention for this rebuild: diffs, rollback and receipts cite commits, not `evidence/before/*` copies. Earlier evidence files remain as the record of the pre-Git rounds and are not rewritten.
