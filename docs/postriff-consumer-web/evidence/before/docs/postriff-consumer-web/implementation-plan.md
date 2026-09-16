# PostRiff Consumer Web — Implementation Plan & Milestone Checklist

Created 2026-09-15. Checkboxes are ticked only with the validation that proves them. `[~]` = partial. Each milestone ends with a receipt in `receipts/`.

## Conventions
- Pre-edit backup + SHA-256 for every touched file (D1). Helper: `scripts/postriff_consumer_web_evidence.py`.
- Additive migrations only: `migrations/postriff/004_*.sql` onward. Never edit 001–003.
- Backward-compatible API: keep `POST /api/workspaces/{id}/actions`; add §21 routes alongside.
- No live external effect without an exact action preview and explicit approval. Fixtures are labelled fixture.
- Hosted bundle (`src/postriff_phase2`, `api/`) stays Python-3.12-compatible (D7).

## Milestone A — Secure SaaS foundation
- [ ] A1 Migration 004: `pr_invitations`, `pr_audit_events`, extend membership role enum → owner/admin/editor/approver/viewer + `can_publish/can_reply/can_moderate/can_manage_connections`; additive, RLS forced, service_role writes.
- [ ] A2 Service-layer permission model (`postriff_phase2/permissions.py`): role × action matrix; every mutation names its required permission; unknown action → 403.
- [ ] A3 Invitations: expiring, workspace/role-bound, single-use, accept requires verified session; revocation.
- [ ] A4 Session/device list + remote revoke; step-up (fresh-auth window) for delete/billing/token/representational actions; login throttling (per IP/user, DB-backed).
- [ ] A5 Two-synthetic-tenant isolation suite on disposable PG: enumerate/read/infer/mutate/stream/export/object/job/error paths; 404-vs-403 uniformity; role revocation mid-job.
- [ ] A6 Run existing `tests/phase2/postgres_*.py` + `tests/phase3/postgres.py` on disposable PG; record results.
- [ ] A7 Receipt `receipts/milestone-a.md`; ledger update.

## Milestone B — Real cloud Ideas and agent journey
- [ ] B1 Migration 005: `pr_conversations`, `pr_messages`, `pr_attachments`, `pr_agent_runs`, `pr_agent_events` (cursor, dedup key), `pr_skill_releases`, `pr_tool_releases`.
- [ ] B2 `AgentRuntime` interface (§10.2) + adapter translation to §10.4 safe events (D4); fixture runtime first; real route stays blocked until qualified.
- [ ] B3 Conversation API (§21 Ideas routes) + SSE with stable IDs/cursors/replay; safe-event allowlist enforced server-side.
- [ ] B4 Four-class source policy: `project_context(...)`, entry + claim double-check, legacy default-forbidden, hostile/private/retraction tests (D10).
- [ ] B5 Source-first activation: thought/URL/TXT-MD/image/transcript → one useful preview without a channel; facts vs viewpoint separated; canonical brief + ≥2 variants with citations; edit/review/remember/post-only/reject/undo without silent memory mutation.
- [ ] B6 Tool registry: versioned structured tools with schemas, effect class, cost class, bounded limits; unknown IDs fail closed. Isolation audit: if no real isolation on Vercel, block public tool route and record gap.
- [ ] B7 Media: renditions, provenance, rights/AI-label declaration, alt text, cost gate before generation (generation itself stays blocked until authorized).
- [ ] B8 Preflight severity model (Blocker/Warning/Tip) bound to revision + manifest; compact control.
- [ ] B9 Neutral skill releases from orchestrator contracts; verify no `james-*` bodies/identities in bundle.
- [ ] B10 Receipt + ledger.

## Milestone C — Channels, scheduling, publication, receipts
- [ ] C1 Fresh official-provider audit (LinkedIn, Instagram/Meta, + candidates) → `connector-audit.md`; select 2–3 (D9).
- [ ] C2 Migration 006: `pr_oauth_transactions`, `pr_encrypted_credentials`, `pr_channel_capabilities`.
- [ ] C3 Hosted OAuth: PostRiff-owned callback, state bound to workspace/member/provider/capability/redirect/expiry, PKCE, account confirm, incremental scopes, encrypted custody, refresh/expiry/revoke/scope-drift, disconnect.
- [ ] C4 Capability taxonomy Direct/Assisted/Bridge/Unsupported per capability in UI.
- [ ] C5 Durable multi-destination schedules: tz-db version, per-destination states, leases/re-auth, partial success, crash recovery, duplicates, rate limits, revocation mid-run.
- [ ] C6 List + real calendar views.
- [ ] C7 Exact action preview (`Schedule N posts`); real publication only after explicit approval (external gate).
- [ ] C8 Receipt + ledger.

## Milestone D — Billing, privacy, Analytics, Audience
- [ ] D1 Migration 007: `pr_subscriptions`, `pr_entitlements`, `pr_usage_ledger` (append-only, idempotent), `pr_billing_events`, `pr_plan_terms` (versioned decisions).
- [ ] D2 Reserve/settle/release; per-model/media/tool attribution; quotas + global stop; `Usage & Plan` surface.
- [ ] D3 Payment adapter behind interface; fixture adapter labelled; webhook signature/replay/idempotency tests; live: external gate.
- [ ] D4 Privacy notice, rights declaration, retention classes, diagnostics consent, export receipt, deletion/tombstone, disconnect, retraction + derivative cleanup.
- [ ] D5 Analytics truthful limited surface (D5).
- [ ] D6 Audience truthful limited state (D5).
- [ ] D7 Receipt + ledger.

## Milestone E — Web experience, operations, launch acceptance
- [ ] E1 Exactly six primary destinations; utility menu; collapsible sidebar; mobile bottom nav (4 + More); global Create → Ideas.
- [ ] E2 Mobile Chat/Edit/Preview segments; 44×44 targets; PWA manifest + SW; safe offline recent drafts; share-sheet; push (gesture, opens only).
- [ ] E3 Onboarding one-question-at-a-time; sample workspace cannot publish; support paths.
- [ ] E4 Status/incident surface, analytics freshness, feature flags, sanitized logs, backup-restore test, runbooks.
- [ ] E5 Browser acceptance 390×844 + desktop; keyboard/SR/contrast/reduced-motion; screenshots.
- [ ] E6 End-to-end cloud journey with founder laptop off (external observation); second workspace isolation; label observed/real/synthetic/blocked.
- [ ] E7 `consumer-web-release-receipt.md`.
