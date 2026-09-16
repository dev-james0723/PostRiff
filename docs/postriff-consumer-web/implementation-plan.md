# PostRiff Consumer Web — Implementation Plan & Milestone Checklist

Created 2026-09-15. Checkboxes are ticked only with the validation that proves them. `[~]` = partial. Each milestone ends with a receipt in `receipts/`.

## Conventions
- Pre-edit backup + SHA-256 for every touched file (D1). Helper: `scripts/postriff_consumer_web_evidence.py`.
- Additive migrations only: `migrations/postriff/004_*.sql` onward. Never edit 001–003.
- Backward-compatible API: keep `POST /api/workspaces/{id}/actions`; add §21 routes alongside.
- No live external effect without an exact action preview and explicit approval. Fixtures are labelled fixture.
- Hosted bundle (`src/postriff_phase2`, `api/`) stays Python-3.12-compatible (D7).

## Milestone A — Secure SaaS foundation
- [x] A1 Migration 004: `pr_invitations`, `pr_audit_events`, `pr_sessions`, `pr_auth_throttle`; roles owner/admin/editor/approver/viewer + four permission flags; additive, RLS forced, service_role writes. *(Local only; hosted apply is gate 1 in the receipt.)*
- [x] A2 Service-layer permission model (`postriff_phase2/permissions.py`): role × requirement matrix; every mutation classified; unknown action → `edit` class (never elevated); viewer never elevated by flags.
- [x] A3 Invitations: 7-day expiry, workspace/role/flags-bound, hash-only at rest, single-use, accept requires verified session; revocation; pending cap 25.
- [x] A4 Session list + remote revoke; step-up (600 s fresh-auth window) for invitations, member changes, session revoke, account delete, channel disconnect; verify/invite throttling (DB fixed window).
- [x] A5 Two-tenant isolation suite (`tests/phase2/postgres_isolation.py`, 10 checks) — stream path deferred to B (no SSE yet).
- [x] A6 `postgres_repository.py`, `postgres_safety.py`, `phase3/postgres.py` pass on the 004 schema (`scripts/postriff_disposable_postgres.py`, `LC_ALL=C`).
- [x] A7 Receipt `receipts/milestone-a.md`; ledger updated.
- [ ] A8 *(external)* Apply 004 to hosted Supabase; deploy; enable MFA/passkey in Auth settings.

## Milestone B — Real cloud Ideas and agent journey
- [x] B1 Migration 005 (local only; hosted apply is an external gate).
- [x] B2 `AgentRuntime` + §10.4 translation; `FixtureAgentRuntime`; real routes reported unavailable, not faked.
- [x] B3 Ideas routes + cursor events + SSE replay (`Last-Event-ID`); safe-event allowlist enforced in code and DB CHECK.
- [x] B4 Four-class policy enforced at entry, apply, review/approval; hostile/private/retraction tests pass (unit + PG).
- [x] B5 `quick_start` (thought/text/URL → preview, no channel); facts vs viewpoint kept separate (facts approved per source; viewpoint in brief/brandHub); preference remember/post-only/reject/undo already existed (`domain.py:390-411`) and is untouched. *(Image/transcript intake and mobile UI → E.)*
- [x] B6 Tool registry fail-closed; isolation audited → **public invoke blocked**, gap recorded.
- [~] B7 Media provenance/AI-label/rights + credits gate → registry refuses paid generation without reservation; provenance chain and ledger → Milestone D.
- [~] B8 Preflight `blocker`/`warning` bound to manifest incl. source-policy rules; `tip` + compact control → E.
- [~] B9 Leak scan clean (rename shim only); release tables exist; seeding script → C receipt.
- [x] B10 Receipt `receipts/milestone-b.md`; ledger updated.
- [ ] B11 *(external)* Qualify a server-side production model route (account, key custody, price quote, cost ceiling); apply 005 to hosted DB.

## Milestone C — Channels, scheduling, publication, receipts
- [x] C1 Official audit (79 URLs) → `connector-audit.md`; selected LinkedIn member + Threads + Instagram (D12).
- [x] C2 Migration 006 (local only).
- [x] C3 Hosted OAuth transaction service + encrypted custody (D13); PG 9/9.
- [x] C4 Capability taxonomy in API (`GET …/channels`); card UI → E.
- [x] C5 `scheduleId` multi-destination, `tzdb`, daily limits; lease/re-auth/crash/duplicate behavior re-verified; connector executor with evidence rules.
- [ ] C6 Calendar grid view → Milestone E (UI).
- [~] C7 Action preview exists for single destination; `Schedule N posts` aggregate label → E; real publication = external gate.
- [x] C8 Receipt `receipts/milestone-c.md`; ledger updated.
- [ ] C9 *(external)* Provider apps + reviews + `POSTRIFF_CREDENTIAL_KEY`/`POSTRIFF_PUBLIC_BASE_URL`/client secrets; apply 006; non-founder end-to-end publish + reconcile per connector.

## Milestone D — Billing, privacy, Analytics, Audience
- [x] D1 Migration 007 (local only; hosted apply is an external gate).
- [x] D2 Reserve/settle/release with attribution, workspace + global stop-lines, entitlement decrement, `Usage & Plan` API + screen.
- [x] D3 `PaymentProvider` interface + labelled fixture; webhook signature/replay/stale/unknown-plan tested; live provider = external gate.
- [x] D4 Privacy notice (draft, legal review pending), rights declaration, retention classes, diagnostics-by-consent, export receipt, retraction, deletion request; disconnect already in C.
- [x] D5 Analytics limited surface (native definitions, Unavailable ≠ 0, n/d, cohorts, <3 insufficient).
- [x] D6 Audience limited state + exact reply approval with separate receipts.
- [x] D7 Receipt `receipts/milestone-d.md`; ledger updated.
- [ ] D8 *(external)* Payment provider selection + contract; legal/tax review; apply 007.

## Milestone E — Web experience, operations, launch acceptance
- [x] E1 Six primary destinations; account/utility menu; collapsible sidebar; bottom nav 4 + More; global Create.
- [x] E2 Chat/Edit/Preview segments; ≥44 px targets; PWA manifest + SW (network-first shell) + share target; offline snapshot cache; push handlers open-only. *(Push permission UI and real-device install: not verified.)*
- [~] E3 Source-first quick-start (two confirmations + language); guided setup retained; sample workspace read-only on hosted (existing); support paths → release receipt lists them as gaps.
- [~] E4 Analytics freshness shown per post; sanitized audit/diagnostics exist; status/incident surface, feature flags, backup-restore test, runbooks → not built (release receipt).
- [x] E5 Desktop + 375×812 browser pass with screenshots in this session; a11y primitives; automated a11y run `validation_unavailable`.
- [ ] E6 *(external)* End-to-end cloud journey with laptop off; second workspace on the deployed URL; cellular device.
- [ ] E7 `consumer-web-release-receipt.md` (next).
