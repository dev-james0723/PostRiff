# Phase 2 implementation record

2026-09-14 · local execution under the explicit research-gate exception.

## Changed implementation

| Area | Source | Implemented behavior |
|---|---|---|
| Isolated launch | `scripts/postriff_phase2.py` | Port 4328, separate private database, local worker and no active external transports |
| Account/trial | `src/postriff_phase2/auth.py` | State/PKCE-bound expiring challenges, Google/email fixtures, atomic owner/workspace/trial, replay and recovery |
| Workspace/distribution | `src/postriff_phase2/store.py` | Scoped commands, one-time trial, artwork consent/cache, decoded media, manifest preflight, exact/batch approval, leases, recovery and receipts |
| Contracts | `src/postriff_phase2/contracts.py` | Repository/provider interfaces, versioned local limits, IANA/DST resolution and scenario adapters |
| Media | `src/postriff_phase2/media.py` | Signature validation, full decode, metadata-free JPEG rendition, hashes and dimensions |
| Hosted repository | `src/postriff_phase2/hosted.py` | Verified-principal membership reads, transactional commands, revision checks and injected command engine |
| Hosted application | `src/postriff_phase2/hosted_app.py`, `hosted_storage.py`, `hosted_worker.py` | Supabase session verification, PostgreSQL composition, private immutable Storage lifecycle, cron-secret worker, advisory lock, leases and reconciliation |
| Content system | `src/postriff_phase2/content_types.py` | Workspace catalog, 11-type optional Creator pack, ten formats, four creation paths, review proposals, preflight and private versioned templates |
| Provider candidates | `src/postriff_phase2/provider_candidates.py` | Exact-authorization transport; LinkedIn image initialize/upload/status and post/reconciliation contracts; Instagram container/status/publish/evidence contracts; image privacy boundary; Supabase verified-user boundary |
| Candidate schema | `migrations/postriff/001_phase2.sql` | Additive tenant tables, service-only bootstrap/trial and private Storage policy |
| Shared HTTP hook | `src/postriff_alpha/server.py` | Optional Phase 2 auth/catalog/challenge hook, bounded image requests and selected-image style attribute CSP |
| UI | `studio/web/src/founder/Phase2.tsx`, `ContentTypes.tsx`, related types/styles plus FounderApp/AuthEntry/YouProfile/api | Trial, channel and schedule flows plus responsive content-type library, guided builder, proposal review, private-template save and runtime-accurate local/hosted privacy labels |
| Tests | `tests/test_postriff_phase2.py`, `test_postriff_content_types.py`, `tests/phase2/rls.sql`, `tests/phase2/postgres_repository.py` | Local command/security/provider/content/recovery tests and real local PostgreSQL checks |

The hosted frontend pins `@supabase/supabase-js` 2.116.0 for PKCE and refresh handling. The local app uses standard Python plus the existing ffmpeg/ffprobe installation. The hosted Vercel function pins Pillow 12.3.0 for full in-process image decoding and psycopg 3.3.5 for PostgreSQL. The optional PostgreSQL repository check used psycopg 3.3.5 in `/private/tmp/postriff-phase2-runtime-20260914`; no global Python package change. Disposable databases are stopped after validation.

## Reuse and boundaries

The original alpha domain, authentication module, generalized templates, generation engine, profile builder and procedural artwork source remain unchanged. No installed private skill was edited. Original alpha data remains separate. New features are catalog-gated; the alpha's original route is retained.

[Source diff](evidence/source-diff.patch) and [bounded audit](evidence/local-audit.json) provide a reviewable receipt where Git metadata is absent. Existing file backups are in `evidence/pre-phase2/`.

## Repaired findings

The implementation checks caught and fixed: export being restricted to saved two-variant packs; lack of explicit draft uncertainty review; edits needing renewed review; trial/capability checks at approval; media signature/playlist rejection; lease fencing across heartbeat extension; and long-account-name overflow on narrow screens. Initial failing output was superseded by the final passing suite. Native datetime entry through the browser driver's fill operation did not populate the control; a useful “Set two minutes from now” action was added and tested, while backend IANA/DST validation remains authoritative.

The PostgreSQL harness used an SQL-ASCII default database; the repository test now explicitly requests UTF-8, matching the intended hosted text encoding. Real database command and rollback checks pass.

## Remaining work

Full Phase 2 is **not complete**. The additive lifecycle migration, configured Production deployment, private media lifecycle and one-minute worker are implemented and validated with synthetic users. The LinkedIn and Instagram request/evidence contracts are locally implemented; provider OAuth/token storage/refresh/revocation, hosted transport and live account qualification remain. Current fixtures do not prove live operations. Live image generation also remains unexecuted.

Deployment and real-provider validation then require exact target/access/action authorization as described in the external preview. Phases 3–5 have not begun.
