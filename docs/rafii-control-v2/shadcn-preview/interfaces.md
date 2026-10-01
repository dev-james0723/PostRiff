# Rafii Admin preview shared interfaces and ownership

Coordinator chat: 01a0f5e0-aa3d-7da0-a6b0-3bb60338888d. Intelligence chat: 01a0f5e6-5017-7832-9ceb-627be8eb53f2. User explicitly assigned this split on 2026-10-01. Coordination: app send_message_to_thread when responsive plus this shared file and per-owner notes under this directory. Messaging calls have not returned acknowledgment; do not assume acceptance from dispatch.

## Checkout and base

Existing PostRiff dependent clone `.preview/rafii-admin`, branch `codex/rafii-shadcn-admin-preview-20261001`, base PR85 `2ecd87ed`. Preserved original owner's seven dirty source paths in base-snapshot.json and inherited-work.patch. Original worktree is untouched. D Festival is document storage only.

## Ownership

- Coordinator: control-web/app/control/founder-workspace.tsx and new UI components/contracts, globals.css, package+locks, integration, focused browser check and SINGLE preview deployment.
- Dataset worker: src/rafii_control/demo_dataset.py, workspace.py, tests/control/test_demo_dataset.py and demo-manifest.json.
- Runtime worker: scripts/rafii_admin_preview.py, tests/control/test_preview_launcher.py, control-web/app/demo-access/page.tsx and access.tsx.
- External Intelligence session: analytics/evidence conversations/reports/reminders/incident/notification/call simulation. Proposed files: src/rafii_control/founder_intelligence.py and owned tests; intelligence.py if required. Shared http.py must be coordinated before edits. This responsibility transfers to that session; Admin team has not begun these overlapping services.

## Dataset boundary (confirmed by dataset worker)

WorkspaceService.demo(principal) is full internal persistent actor/environment-isolated JSONB state. HTTP GET/action responses are bounded snapshots <=50 rows per collection. Add catalog, manifest, analytics, scenario, asOf, receipt. Existing collections customers/workspaces/subscriptions/payments/usage/tickets/activity persist. Invoices, members, credits are linked details. Exactly 10000 paid fictional subscriptions across source-backed implemented-v2 candidate Starter4500 Creator4000 Studio1500. Free is catalog-only. Monthly only; prices are proposed and production activation unverified.

Existing query fields {collection,search,status,page,recordId}; compatible optional {plan,billingCycle,sort,direction} for Demo only. recordId response adds bounded linkedRecords. Live retains current authority and rejects unsupported new filters.

## Proposed Intelligence integration

Functions receive FULL Demo dataset and verified principal/receipt/scenario context; no browser-provided authoritative actor or KPI. Return bounded typed analytics, incident, notifications, followUps, conversation and voiceReadiness. Persist sandbox actions in the SAME demo payload via delegated reducer, preserving revision/requestId/replay/audit boundary. No second fixture store/scheduler. Scenario controls use supported keys normal/payment_failure/outage/stale_data/notification_failure/recovery; optional loading/empty/permission/rate_limit/ai_unavailable. Please reply with agreed exact function/action contracts and deliver first completed slice promptly. Admin UI will consume those without implementing another service. No real model/provider, email, call or production faults.

## Review boundary

Build/typecheck + focused flows/permissions/isolation; desktop/mobile preview. Local review can reuse disposable PG/Synthetic AAL2 test harness but must label simulated access/AI/voice/delivery. Hosted qualification remains separate; production promotion waits for James review.
