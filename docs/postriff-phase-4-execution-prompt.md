# PostRiff Phase 4 execution prompt — Paid beta, Halaska UI, and Dashboard Agent Room

Prepared 2026-09-14 from the current installed source, current Phase 3 receipt, the controlling consumer implementation plan, the retained product/experience specifications, the later product-risk review, and Halaska Kit's live API reference.

**State: reviewable prompt only. This file does not start Phase 4, install Halaska Kit, provision billing, recruit users, charge anyone, deploy anything, or perform any other external action.** Copy the prompt below into the implementation task when ready.

---

## Objective and execution scope

Work in `/Users/ouxianxing/Documents/James-Au-Studio` as the engineer implementing **PostRiff Phase 4: paid beta**, including the product-wide Halaska Kit UI foundation and a real agent chat room on Dashboard.

Deliver Phase 4 in three independently reportable tracks:

1. **P4A — Halaska foundation and Dashboard Agent Room:** install and verify Halaska Kit, retrofit the product one screen at a time, and expose the existing Phase 3 agent lifecycle on Dashboard through a persistent, safe, resumable chat room.
2. **P4B — paid-beta product contracts:** production-grade usage/metering, live `You → Usage & Plan`, plan/trial entitlements, managed-writing/image allowances, support diagnostics, cancellation and export, billing-provider integration behind explicit external authorization, and billing/security tests.
3. **P4C — observed beta:** prepare the ten-user pilot and measurement system, but do not contact, enroll, charge, or publish to users without separate explicit authorization covering the actual recipients, content, accounts, data, and cost.

When I explicitly ask you to execute this prompt, proceed with local, reversible implementation and validation. That authorizes the scoped local P4A/P4B work, but not deployment, production billing activation, purchases, paid generation, provider/account changes, credential entry, sensitive-data upload, customer messages, recruitment, publication, or public release. Prepare exact action previews for those external steps. Do not infer consent from existing credentials, a connected provider, or an installed CLI.

Do not mark all of Phase 4 complete merely because the UI, fixtures, or local billing contracts pass. Report local engineering, Halaska retrofit, Dashboard Agent Room, production billing/provider state, deployment, and four-week pilot evidence separately.

## 1. Establish the controlling source of truth

Read applicable project instructions and inspect current code and receipts before editing. The installed tree had no `.git` when this prompt was prepared. If that remains true, record `validation_unavailable` for Git history/diff; preserve scoped pre-edit backups, SHA-256 hashes, and a reviewable source diff. Do not initialize a repository or overwrite concurrent work.

Use this precedence when documents disagree:

1. Current source plus newer verified receipts for what actually exists.
2. The consumer plan below for phase numbering, paid-beta scope, runtime strategy, plans, and agent direction.
3. `docs/postriff-improvement-20260914/` for later risk, source-policy, economics, support-cost, and evidence-gate corrections.
4. The retained product-design and SaaS architecture specs for information architecture, UX, data, and security requirements—not their superseded phase numbers.

Read:

- `/Users/ouxianxing/Documents/Codex/2026-09-14/ok-just-to-continue-from-the/postriff-product-plan/README.md`
- The same directory's `product-spec.md`, especially sections 5, 7, 9, and 10.
- The same directory's `implementation-plan.md`, especially sections 2, 4, 5, 7, and 8.
- `docs/postriff-phase-3/phase-3-receipt.md`
- `docs/postriff-phase-3/readiness-and-architecture.md`
- `docs/postriff-phase-3/runtime-qualification.md`
- `docs/postriff-phase-3/security-sync-acceptance.md`
- `docs/postriff-phase-2/phase-2-receipt.md`
- `docs/superpowers/specs/2026-09-14-postriff-product-design.md`
- `docs/superpowers/specs/2026-09-14-postriff-saas-product-architecture.md`
- `docs/superpowers/specs/2026-09-14-postriff-content-type-template-system.md`
- `docs/postriff-improvement-20260914/DECISIONS.md`
- `docs/postriff-improvement-20260914/SPEC.md`
- `docs/postriff-improvement-20260914/ROADMAP.md`
- `docs/postriff-improvement-20260914/ECONOMICS.md`

**Controlling phase map:** P3 = runtime choice and desktop; P4 = paid beta; P5 = evidence-led expansion, including richer Analytics/Audience and additional channels. Do not implement the older “Phase 4 Audience” roadmap as this milestone.

The current Phase 3 receipt reports a packaged local desktop foundation but zero real model routes qualified, hosted pairing/sync unmounted, and inherited Phase 2 external gates still open. Verify whether newer evidence exists. A synthetic runtime or billing fixture is never a production claim.

## 2. Audit and preserve the current implementation

Start from the actual boundaries:

- React 19 + TypeScript + Vite: `studio/web/`.
- Founder/customer UI: `studio/web/src/founder/`.
- Current shell and simple Dashboard: `studio/web/src/founder/FounderApp.tsx`.
- Current P2 Channels, Scheduling, Privacy, and fixture Plan surfaces: `studio/web/src/founder/Phase2.tsx`.
- Current P3 runtime/device UI: `studio/web/src/founder/RuntimePanel.tsx` and related types/state/CSS.
- Legacy guided agent surface that may provide behavior but must not be copied blindly: `studio/web/src/AgentPanel.tsx`, `agentApi.ts`, and `agentHistory.ts`.
- Founder/P1/P2/P3 Python domains: `src/postriff_alpha/`, `src/postriff_phase2/`, and `src/postriff_phase3/`.
- Current additive migrations: `migrations/postriff/`.
- Hosted API entry: `api/index.py`.
- Electron shell/sidecar: `desktop/`.
- Current frontend and Python tests plus historical evidence under `docs/postriff-phase-*`.

Preserve routing, state, stored user work, revisions, approvals, exact receipts, local/hosted distinctions, profile and skill personalization, and desktop packaging. Do not rewrite the product or change framework as part of the visual retrofit.

Keep the six primary destinations: Dashboard, Ideas, Scheduling, Channels, Analytics, and Audience. Keep You and Skills as utility destinations. Do not add a seventh permanent work tab for the agent.

Create a readiness ledger before implementation with separate rows for:

- existing local behavior;
- Phase 3 runtime/pairing behavior;
- Halaska retrofit per screen;
- Dashboard Agent Room contracts and real-runtime qualification;
- metering/entitlements/billing local engineering;
- billing-provider selection/provisioning/current API status;
- deployment/live webhook state;
- pilot recruitment and four-week observation.

## 3. Install and verify Halaska Kit before UI edits

Read the current API reference before writing UI code:

`https://ui.halaska.com/llms.txt`

Then download the upstream kit into this TypeScript frontend:

```sh
curl -L --fail -o studio/web/src/halaska-kit.jsx https://ui.halaska.com/halaska-kit.jsx
curl -L --fail -o studio/web/src/halaska-kit.d.ts https://ui.halaska.com/halaska-kit.d.ts
```

If either URL is unreachable, stop the kit-dependent edits and ask me to provide the files. Do not invent or hand-recreate a substitute kit. Record the retrieval date, source URLs, file hashes, and any upstream license/provenance included in the files.

Verify the real integration by temporarily rendering this named import in the actual founder app entry:

```tsx
import { Button } from "../halaska-kit";

<Button variant="primary">Test</Button>
```

Confirm it builds and visually renders as the Geist dark rounded button. Remove the test immediately after verification and prove it is absent. Ensure the `.jsx` plus `.d.ts` import works with the existing strict TypeScript/Vite setup; make the smallest configuration change only if necessary.

Use named imports. Wrap the customer application in `ThemeProvider`; retain the product's chosen theme and use `AccentContext.Provider` only for the approved PostRiff accent. Use `usePal(theme)` and `tokens` for component colors, radii, typography, and spacing. Do not introduce new hardcoded grays or brand colors. Existing CSS may remain for page layout during migration, but touched interactive elements must use kit components.

Do not edit the downloaded kit to customize product behavior. Build thin PostRiff wrappers or composed patterns beside it. If a demo-driven pattern is needed, copy only that pattern's structure into a PostRiff-owned component, replace its demo data, and retain its state and motion behavior. Never ship Halaska's Alpha/Acme demo copy or demo records.

## 4. Retrofit all existing customer screens, one screen at a time

This is a skin and UX pass, not a state/routing rewrite. Finish and validate one destination before starting the next. Suggested order:

1. Application shell, navigation, top bar, global banners, loading, error, and empty states.
2. Dashboard plus Agent Room.
3. Ideas/onboarding/profile transfer/source review/voice review/draft studio.
4. Scheduling and approval/detail flows.
5. Channels and connection/detail flows.
6. You, Usage & Plan, Privacy, and account flows.
7. Skills and content-type/template flows.
8. Analytics and Audience placeholders/current states without pretending unavailable data is live.

Map raw/ad-hoc UI to Halaska components:

- Buttons and actions → `Button`, `IconButton`, `LinkButton`, `ButtonGroup`, `SplitButton`.
- Inputs → `TextInput`, `TextArea`, `Select`, `Checkbox`, `RadioGroup`, `SwitchToggle`, `SegmentedControl`, `SearchInput`, `Choicebox`, `DatePicker`.
- Surfaces → `Card`, `CardHeader`, `Stack`, `Divider`, `Tabs`, `SubtleTabs`, `ScrollArea`.
- Labels/state → `Badge`, `Tag`, `StatusBadge`, `StatusDot`, `AlertBanner`.
- Data → `Stat`, `Table`, `DataTable`, `Progress`, `Pagination`.
- Overlays → `Dialog`, `AlertDialog`, `FormDialog`, `CardDialog`, `Sheet`, `Popover`, `DropdownMenu`, `CommandPalette`.
- Loading/empty/error → `Skeleton`, `Spinner`, `ThinkingIndicator`, `EmptyState`, `Toast`, `ErrorRepairPattern`.

Replace native confirmation dialogs used for ordinary recoverable actions with product state and `ActionReceiptPattern` plus undo where the domain supports a real safe undo. Retain explicit confirmation/approval for irreversible, external, privacy, billing, deletion, or publication actions. Do not claim an undo exists if the backend cannot perform it.

For agent lifecycle moments use the kit's patterns with PostRiff data:

- thinking/planning → `ThinkingTracePattern` or `PlanPreviewPattern`;
- streaming answer → `StreamingAnswerPattern`;
- exact consequence approval → `ApprovalCardPattern`;
- active run → `AgentStatusPattern` plus a PostRiff adaptation of `ToolStreamPattern`;
- handoff/permission boundary → `HandoffPattern`;
- completed action → `ActionReceiptPattern`;
- failed/recoverable state → `ErrorRepairPattern`.

Keep lifecycle patterns prop-driven. Persist real states outside demo component timers. `autoplay` demonstrations must not masquerade as server/runtime progress. No fake tool calls, fake receipts, fake sources, or fake billing activity.

After each screen, add a short screen receipt listing: behavior preserved, kit components/patterns used, raw elements intentionally retained and why, responsive/a11y result, and screenshot/evidence paths.

## 5. Add the Dashboard Agent Room in P4A

Implement the agent chat room **during Phase 4A**, before billing activation or pilot recruitment. Phase 3 supplied the runtime/event foundation; P4 exposes the coherent customer experience. Do not defer this to P5.

Dashboard is the agent command, status, and resumption hub. Ideas remains the detailed creation workspace. The Dashboard room must:

- welcome the user with the current workspace/voice context;
- show active, waiting, paused, completed, limited, offline, and failed runtime states;
- resume recent PostRiff conversations and runs across Dashboard and Ideas;
- accept a prompt, attachment selection, agent/runtime choice, and bounded scope;
- route creation/deep editing into the canonical Ideas conversation without duplicating a separate draft store;
- show what context will be used before a run;
- save the conversation and any partial streamed artifact;
- link generated candidates to their canonical brief, variant revision, source manifest, voice revision, content-type/template/skill versions, and runtime provenance;
- allow safe stop, supported resume, redirect, handoff, open-in-Ideas, and review actions;
- never publish, reply, change a connection, widen file scope, buy credits, or charge a plan from an ordinary chat sentence.

Use a PostRiff-owned adaptation of `AgentChatPattern` as the room structure. Because `AgentChatPattern` is demo-driven rather than a full backend contract, copy its source structure out of `halaska-kit.jsx`, replace all demo data, and connect it to PostRiff's canonical conversation/run APIs. Use:

- `Orb` and `AgentGlyph` for presence;
- `MessageThreadPattern` structure for history;
- `PromptInputPattern` structure for composition;
- `ThinkingTracePattern` for concise visible steps, never hidden chain-of-thought;
- `StreamingAnswerPattern` for streamed user-visible copy and source chips;
- `AgentStatusPattern` for durable run phases;
- `PlanPreviewPattern` or `ApprovalCardPattern` before consequential proposals;
- `ActionReceiptPattern` after a real saved/reviewed action;
- `ErrorRepairPattern` for timeout, quota, disconnect, malformed output, stale revision, or unavailable route;
- `HandoffPattern` when the agent cannot safely continue.

The room must not show raw hidden reasoning, secrets, unsanitized tool output, internal system prompts, or browser/CLI credentials. “Thinking” copy should describe bounded visible work such as “Checking approved sources” or “Preparing two channel variants.”

Reuse the Phase 3 normalized event contract. If it is insufficient, extend it additively with stable event IDs, sequence numbers, persisted visible segments, source/artifact references, permission requests, error codes, usage provenance, and completion state. Reconnect by run/event cursor and deduplicate replay. Preserve unsent composer text locally. Cross-device edits use expected revisions and conflict recovery; never silently overwrite.

Dashboard layout requirements:

- The Agent Room is the primary interactive area, visible without navigating elsewhere.
- A calm compact status rail shows selected runtime/device, plan/trial allowance, active job, and connection limitations.
- “Continue where you left off” and recent artifacts remain discoverable, not replaced by chat transcript archaeology.
- On mobile, the room becomes the first content section; details/status can move into a `Sheet` or collapsible surface. No horizontal overflow at 390 px.
- Empty state offers three concrete starters based on approved context, not generic demo prompts.
- A user can open the full canonical task in Ideas at any time.

Add tests for persistent conversation history, event replay/deduplication, partial output, stop/resume, runtime switch, stale revision, unsupported route, quota exhaustion, offline/online changes, cross-workspace access, hostile attachment instructions, source retraction, permission denial, and external-action blocking. Test that the same run viewed from Dashboard and Ideas resolves to one canonical record.

## 6. Implement the paid-beta product contracts

### 6.1 Usage and cost ledger

Implement an append-only, workspace-scoped ledger with idempotency keys and auditable links to the originating run, asset request, schedule, provider attempt, plan period, and reversal. Separate:

- customer allowance reserved;
- allowance settled;
- allowance released;
- provider cost incurred even when no customer allowance is consumed;
- measured cost versus unavailable cost;
- writing, image/media, storage, scheduling, support, and billing events.

Failed writing requests with no usable output do not consume customer allowance, but actual provider cost remains internally visible. Do not estimate provider usage as reported fact. Enforce tenant and global budgets, concurrency/rate limits, and a fail-closed stop control.

### 6.2 Plans and trials

Implement the controlling consumer-plan contracts unless a newer explicitly approved decision supersedes them:

- Studio candidate: `$19/month`, own-agent workflow.
- Studio Assist candidate: `$39/month`, managed assistance.
- Business remains unavailable until later evidence; do not sell a coming-soon plan.
- Every available plan has a `14-day`, no-card, no-auto-convert free trial.
- Both launch trials share `10` managed standard writing requests for the trial.
- Trial plan switching preserves the original expiry and remaining allowance; it never grants a second trial.
- Every released generalized skill and every onboarding mode remains available on every released plan/trial. Runtime dependencies are readiness states, not skill paywalls.
- Trial/service expiry holds pending publication, preserves review/export, and shows the proposed retention deadline.
- No automatic overages. Any add-on or media generation requires a separate explicit quoted purchase flow.

Treat the later improvement report's preference for a tighter `$39` assisted offer and bounded batches as a beta experiment proposal, not an invisible rewrite of the controlling plan. Make offer/limit configuration versioned and record which cohort saw which terms. Do not hardcode an unapproved commercial change.

Define “standard writing request” exactly as the product spec does and display the scope before starting. Use actual events for allowance, not prompt count inferred in the browser.

### 6.3 Live `You → Usage & Plan`

Replace the fixture Plan view with a real account-bound surface showing:

- current plan/trial and terms version;
- trial/service dates and timezone;
- managed-writing allowance reserved/used/remaining;
- image/media purchases or allowance separately;
- storage, channels, schedules, and workspace limits;
- own-agent/provider cost distinction;
- held jobs and why;
- billing/payment state only when confirmed by the provider;
- export, cancellation, deletion, support diagnostics, and recovery entry points.

Use Halaska `Stat`, `Progress`, `Card`, `DataTable`, `AlertBanner`, `Tabs`, `ActionReceiptPattern`, and `ErrorRepairPattern`. Avoid dark patterns: no preselected paid conversion, hidden retention deadline, disguised trial expiry, or misleading “unlimited” copy.

### 6.4 Billing boundary

Before choosing or hardcoding a payment/billing provider for a Vercel deployment, load the applicable Vercel Marketplace integration guidance and run its discovery workflow. Compare the current official options against PostRiff's actual jurisdiction, taxes, webhooks, subscriptions, refunds, cancellation, export, data processing, pricing, failure modes, and exit plan. Do not select a provider from an old document example alone.

Keep provider-specific code behind a billing adapter. Require signed webhook verification, provider event uniqueness, object/version checks, idempotent entitlement updates, out-of-order and replay handling, refund/dispute/cancellation states, reconciliation, and an operations queue for unresolved events. Never trust price, plan, credits, or workspace identity from the client.

Implement and test the adapter contract and a labelled fixture locally. Provisioning, production credentials, live checkout, webhook endpoints, tax settings, real charges, refunds, and production activation require exact separate authorization. A successful fixture checkout or provider test-mode screen is not revenue.

### 6.5 Cancellation, export, deletion, and support

Cancellation keeps access through the paid period, then holds future jobs. It must show what changes, the effective time, retained/exportable data, and retention deadline before final confirmation. Export must include customer-owned profiles, skills/configuration, sources allowed for export, briefs, variants, assets/metadata, schedules, receipts, usage, and an omissions/error manifest.

Keep source retraction distinct from account deletion. Implement a derived-data dependency graph, tombstones where needed, private-storage cleanup, backup/restore policy, and a deletion receipt. Database restore alone does not prove object/media restore.

Support diagnostics must be user-reviewable and redact credentials, private prompts, private source bodies, access tokens, browser profiles, full local paths, and unrelated agent history. Sharing diagnostics is a separate explicit action.

## 7. Preserve trust and external-action boundaries

- Agent output is always a candidate until reviewed.
- Publication/reply approval binds exact content revision, account, assets, timing, scope, and approving actor. Any change invalidates it.
- Billing approval binds exact offer/version, price, currency, cadence, tax disclosure, account/workspace, and effective time.
- A chat sentence may open a `PlanPreviewPattern` or `ApprovalCardPattern`; it cannot self-authorize the action.
- Never conflate connected, identity verified, capability verified, publish ready, billing active, deployed, or observed-customer-success states.
- Reconcile uncertain paid, media, or publication submissions before retrying. Obtain fresh authorization if a retry could duplicate cost or external effects.
- Enforce source policy in the context builder, not just as UI labels. Private/local-only fields cannot leak into managed/cloud generation.
- Preserve the current exact approval and uncertainty protections in Phase 2/3. Do not weaken them for a smoother demo.

## 8. Validation before done

Establish a fresh baseline before editing. At prompt preparation, the latest Phase 3 receipt reported 127 Python tests passed in its isolated environment, 72 frontend tests passed, typecheck/builds passed, 2 desktop IPC tests passed, and packaged macOS acceptance passed. Treat those as historical evidence, not guaranteed current results.

Run the smallest sufficient current checks after each screen and at integration completion:

- frontend tests, strict typecheck, existing web build, hosted build, and desktop build/package checks affected by the kit;
- focused Python tests for ledger, entitlements, agent events, billing adapter, export/cancellation/deletion, and tenancy;
- disposable PostgreSQL migration/RLS/isolation tests with at least two workspaces and revoked membership;
- browser acceptance for every completed screen at desktop and 390×844 mobile;
- keyboard, focus, labels/live regions, contrast, reduced motion, and screen-reader-oriented semantics;
- persisted reload/restart, offline/reconnect, stale revision, event replay, duplicate webhooks, out-of-order billing events, cancellation race, and held-job behavior;
- package audit proving Halaska source plus only intended public assets are included and secrets/private skills/runtime data are excluded.

Visually inspect every retrofitted screen. A build or DOM check is not visual approval. Record screenshots per destination and a final screen-by-screen summary.

For the Dashboard Agent Room, validate a fixture route and every actually authorized real route separately. Fixture timers and synthetic transport do not qualify a model route. Do not spend credits or send real private data without explicit authorization.

For billing, test local fixtures and, only after separate authorization, the exact provider's sandbox/test mode. Test mode is not a real charge. Production billing remains incomplete until signed live webhooks, real account configuration, operational reconciliation, cancellation/refund handling, and an explicitly authorized bounded live transaction are evidenced.

If any required validation cannot run, state `validation_unavailable` with the exact reason and perform the best lower-level check. Repair concrete regressions before proceeding. Preserve previous receipts instead of rewriting them to describe new work.

## 9. Completion receipt and stop conditions

Write `docs/postriff-phase-4/phase-4-receipt.md` plus evidence paths. Report these independent states:

1. Halaska Kit installed/verified and exact screens retrofitted.
2. Dashboard Agent Room local behavior and canonical Dashboard↔Ideas continuity.
3. Real runtime routes qualified, limited, or blocked.
4. Usage/metering and entitlement contracts.
5. Billing adapter fixture versus provider test mode versus production activation.
6. Cancellation/export/deletion/support readiness.
7. Deployment state.
8. Pilot invitations/enrollment, repeat use, paid choice, real payment, refunds, contribution margin, and observation maturity.

Keep pilot thresholds as hypotheses: at least 6 of 10 activated users create useful content in three of four consecutive weeks; median self-reported editing time falls 30% against their own baseline; at least 4 choose the offered paid plan. Report numerator/denominator, cohort version, assisted versus self-serve, and maturity window. Do not count invitations, verbal interest, plan selection, or fixture checkout as payment.

Pause the affected route if testing finds cross-workspace access, wrong-identity execution, unauthorized publication/reply/charge, private-source egress, duplicate external effect, or unreconciled billing state. Preserve bounded evidence, repair, and rerun the relevant acceptance before restoring it.

Recommend no connector, plan, or team expansion merely to make Phase 4 look larger. Phase 5 remains evidence-led.

## 10. Vercel tooling note

If Vercel work becomes authorized and necessary, first verify the current CLI. The preparation environment reported `59.15.1` with `59.17.0` available. Strongly recommend upgrading before Vercel operations:

```sh
npm i -g vercel@latest
# or
pnpm add -g vercel@latest
```

Do not perform this global upgrade silently; it is outside the local Phase 4 source edit unless separately requested.
