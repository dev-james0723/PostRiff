# PostRiff Phase 3 execution prompt — Runtime choice and desktop

Prepared 2026-09-14 from the current source tree and the updated consumer product plan.

**State: reviewable prompt only. Writing this document does not start Phase 3 or authorize external actions.** Copy the prompt below into the implementation task when ready.

---

## Objective and execution scope

Work in `/Users/ouxianxing/Documents/James-Au-Studio` as the engineer implementing **PostRiff Phase 3: runtime choice and desktop**.

Build a shared desktop/web creation experience with a constrained local agent host, revocable device pairing, qualified Codex/Claude/Gemini adapters, a managed-writing option, and reliable synchronization. Users must retain their approved voice, sources, personalized skills, content types, templates and edited drafts when changing devices or agents.

When I explicitly ask you to execute this prompt, proceed with local reversible implementation, packaging and validation. That instruction grants a **local Phase 3 research-gate exception** despite incomplete Phase 0 research and outstanding Phase 2 external validation. Record the exception without marking either phase complete. Do not restart recruitment or send invitations. Continue independent local work while external dependencies are unavailable; report partial completion truthfully.

Existing authorization remains valid only for its actual scope. This prompt does not authorize cloud provisioning/deployment, account or credential changes, sign-in on my behalf, paid model requests, sensitive-data transfer, social publication, replies, billing, public release or changes to installed/global skills. Prepare exact bounded previews for any such required action and ask only for missing authorization after the implementation and reviewable test payload are ready. Never treat an installed/authenticated CLI as consent to spend or upload data.

## 1. Establish the current source of truth

Read applicable project instructions. Inspect the actual source and current receipts before choosing files or changing code. This installed tree had no `.git` at prompt preparation; if still true, record `validation_unavailable` for Git history/diff and use scoped backups, hashes and a source diff. Do not initialize a repository or overwrite unrelated work merely to obtain Git metadata.

The newer consumer plan controls **phase numbering, runtime strategy and packaging**. The content-type specification controls its specialized contracts. Use the older experience/SaaS specs for retained UX and security requirements, not their superseded delivery phases or prices.

Planning directory:

`/Users/ouxianxing/Documents/Codex/2026-09-14/ok-just-to-continue-from-the/`

Read these files there:

- `postriff-product-plan/README.md`
- `postriff-product-plan/product-spec.md`, especially sections 5, 7 and 9
- `postriff-product-plan/implementation-plan.md`, especially milestones and the agent conformance suite
- `postriff-agent-aware-onboarding-workflow.md`
- `postriff-personal-voice-profile-builder-prompt.md`
- `postriff-account-auth-and-deployment-addendum.md`
- `postriff-you-profile-and-watercolor-spec.md`
- Relevant Phase 2 execution-prompt requirements when resolving inherited behavior.

Read these repo documents:

- `docs/postriff-phase-0/phase-1-decision.md`
- `docs/postriff-phase-1/phase-1-receipt.md` and `skill-migration-manifest.md`
- `docs/postriff-phase-2/phase-2-receipt.md`, `acceptance-results.md`, `readiness-report.md`, `hosted-deployment-preparation.md` and `content-type-template-results.md`
- `docs/superpowers/specs/2026-09-14-postriff-content-type-template-system.md`
- Relevant retained sections of the product-design and SaaS-product-architecture specs in the same directory.

Resolve documentation disagreements against current code and newer evidence. In particular, the older Phase 2 architecture decision says hosted composition is unimplemented, while newer code and the hosted preparation receipt contain it. Do not rebuild that composition solely because the older note is stale.

**Phase map:** P3 = runtime choice and desktop; P4 = paid beta and production billing/metering; P5 = evidence-led expansion, including richer Analytics/Audience. Do not implement the older “P3 Analytics” or “P3 Paid beta” roadmap.

## 2. Starting implementation and dependency boundaries

Audit and reuse these actual boundaries:

- React/TypeScript/Vite frontend: `studio/web/src/founder/`, including `FounderApp.tsx`, `AgentOnboarding.tsx`, `YouProfile.tsx`, `ContentTypes.tsx`, `Phase2.tsx`, API/types and hosted auth.
- Founder domain: `src/postriff_alpha/`. `generation.py` currently has a synchronous deterministic `AgentAdapter.generate()` contract; `profiles.py` detects CLI versions and prepares scoped profile requests, but blocks real CLI execution.
- Distribution/hosted foundation: `src/postriff_phase2/`, including repository, auth, content types, hosted application, private storage and worker; `migrations/postriff/001_phase2.sql`; `api/index.py`.
- Separate local launchers: `scripts/postriff_alpha.py` and `scripts/postriff_phase2.py`.
- Existing tests: `tests/test_postriff*.py`, `tests/phase2/` and `studio/web/tests/`.

The current Phase 2 runtime is a fixture application. Hosted composition is prepared locally; actual deployment, hosted auth/storage/isolation, laptop-off scheduling, live artwork generation and LinkedIn/Instagram qualification remain incomplete according to its latest receipt. Verify any newer evidence before repeating that statement.

Create a readiness ledger separating:

1. Local engineering work that can proceed now.
2. Hosted prerequisites needed for real pairing and cross-device cloud acceptance.
3. Provider access/consent/cost prerequisites for each real agent route.
4. Remaining Phase 2 distribution work, tracked separately from Phase 3.

Repair local regressions blocking Phase 3. Do not absorb the entire Phase 2 live connector backlog into this milestone. Synthetic pairing/sync tests can validate contracts; they cannot satisfy hosted acceptance. Cloud publishing independent of the laptop remains a Phase 2 dependency, not a new Phase 3 success claim.

## 3. Preserve the product experience

- Keep Dashboard, Ideas, Scheduling, Channels, Analytics and Audience as the six primary destinations. Keep **You** in the utility area, with its existing profile, skills, usage and privacy sections. Place runtime/device controls contextually in Ideas and You; do not add a seventh work tab or permanent agent rail.
- Preserve Personal Brand, Role Specific, Business and Hybrid; experienced-AI and guided-new-user branches; optional portable profile transfer; reviewed VoiceRevisions; explicit remember/post-only/reject/undo/delete; source retraction; export and recovery.
- Distinguish PostRiff sign-in, workspace membership, desktop/device identity, agent authentication, social account capabilities and user-reported AI relationship. Prior chat familiarity does not grant a CLI access to that chat history.
- Preserve the three-layer content model: content type → format → destination variant. Retain the small workspace catalog, optional 11-type Creator pack, ten formats, four type-creation paths, reviewed proposals and private versioned templates. Do not force founder types onto unrelated workspaces.
- Pass content-type/template versions, selected neutral skill versions, private overrides, speaker/voice revision and approved source provenance into generation. Switching type, runtime or device must not silently overwrite customized variants.
- Every available plan/trial exposes every released generalized skill and all onboarding modes. Runtime dependencies affect execution readiness, not library entitlement. Preserve the original private skills; package only released neutral templates and customer-owned overrides. Do not claim the full installed skill inventory has been generalized merely because three templates were released.
- Preserve You graph/list equivalence, privacy-aware artwork behavior, existing account/trial contracts and exact distribution approvals. A provider or plan switch cannot issue another trial grant or reset expiry.

## 4. Shared desktop application and constrained host

Use the existing React/Vite UI and Python domain logic. Evaluate the plan's Electron recommendation against the installed toolchain and source, then record a short architecture decision. Avoid a frontend/framework rewrite. A different shell needs a concrete compatibility reason.

Implement an actual launchable desktop application, not only a browser mock. Default the first executable acceptance target to the available macOS host, record its architecture and supported minimums, and make Windows build/CI configuration reviewable. Do not claim Windows installation/runtime acceptance without a Windows environment. Keep signing, notarization, public distribution and automatic updates separately qualified; label unsigned local packages accurately.

Separate renderer, privileged shell/preload boundary and local agent process host. For Electron, enable sandbox/context isolation, disable renderer Node integration, validate sender/origin and typed IPC arguments, constrain navigation and external links, and expose no general shell/filesystem IPC. Reuse Python through a controlled packaged sidecar or another explicit bounded transport; do not assume end users have a development Python installation.

Use a dedicated private run directory and explicit executable argument arrays. Never interpolate model/user text into a shell command. Enforce approved file scope, path traversal/symlink boundaries, tool allowlists, environment minimization, output limits and timeouts. Do not load arbitrary repository/global hooks, MCP servers or unrelated skills into a customer run. If a provider route cannot enforce the required isolation, mark it unsupported rather than weakening the boundary.

Keep native provider login with the official runtime. Do not copy CLI tokens, browser profiles or founder sessions into cloud storage, exports, prompts or customer packages. Use an appropriate OS-protected credential boundary for the device identity. Do not bundle agent executables until redistribution terms are checked.

## 5. Pairing, scoped jobs and device lifecycle

Implement short-lived single-use enrollment confirmed on the signed-in desktop. Show the exact workspace and device; defend against replay, brute-force attempts, wrong-user confirmation and cross-workspace pairing. Store only the necessary revocable device credential representation in the cloud.

The host connects outbound to fetch authenticated workspace/device-scoped jobs. A web browser cannot launch an arbitrary local CLI. Each job binds workspace, authorized actor/device, operation, expiry, source manifest, permission scope, content revision and idempotency key. Verify membership and scope at claim and artifact submission; reject expired/revoked work and forged resource IDs.

Persist claims, bounded leases, run identifiers and event cursors. Duplicated delivery or reconnection cannot start a second model run blindly. Reconcile ambiguous run state before any retry that could spend again. Reject late output from an invalidated device or obsolete attempt; preserve already accepted artifacts and report what happened.

Expose online/offline, last-seen, runtime readiness, waiting, running, interrupted and revoked states consistently in web and desktop. Revocation stops new claims and result writes; cancel active work where supported and explain any already-started provider request that cannot be recalled. Pairing never grants social-publishing authority.

## 6. Runtime adapters and managed writing

Evolve the deterministic adapter behind a transport-neutral lifecycle contract: inspect, start, cancel, supported resume, health, validated artifact submission and usage. Separate installed/version-supported/authenticated/source-approved/executed/qualified states. Record the exact OS, executable version, authentication route, model, supported operations and evidence date.

Implement:

1. **Codex:** qualify a release-capable structured exec/JSON path. Keep experimental app-server integration behind a feature flag unless its current support is established. Test native permissions, streaming and cancellation; map reasoning choices only to supported values.
2. **Claude Code:** qualify the supported headless/structured path and native permission/session behavior. Use the SDK only if needed for this architecture. Verify current third-party authentication and billing terms before enabling a route.
3. **Gemini:** retain a distinct adapter and qualify currently supported authentication/API/enterprise routes. Recheck current official documentation rather than copying a dated consumer-login claim. Keep unavailable combinations visible with a precise reason. Antigravity is a separate later decision, not a silent Gemini rename.
4. **Managed writing:** implement the real server-side provider adapter and durable run integration so web users need no desktop. Select the existing qualified provider if there is one; otherwise prepare a provider/model/configuration and bounded cost preview. Keep keys server-side, inputs scoped and cancellation/retry behavior explicit. Complete authorized local integration while actual paid execution remains pending approval.

Consult installed help/source first for exact CLI behavior and current official provider documentation for capabilities/terms. If introducing an external service on Vercel, follow the applicable marketplace discovery workflow before selecting/provisioning it. Do not upgrade global tooling automatically. The session reports Vercel CLI 59.15.1 with 59.17.0 available; strongly recommend `npm i -g vercel@latest` or `pnpm add -g vercel@latest` before later Vercel work, rechecking versions then.

Normalize lifecycle, visible text, tool summaries, permission requests, attachments, errors and completion events. Persist events with stable IDs/sequence numbers; do not expose hidden reasoning, raw credentials or unsanitized runtime events.

Preserve partial artifacts on quota exhaustion, cancellation, timeout and disconnect. Never widen permissions, switch agents or incur a billable fallback automatically. Switching providers starts a new native session from canonical approved state; use native resume only where actually supported. Do not promise shared hidden context, identical output or shared provider billing history.

Usage must be provider-reported, explicitly measured locally or `Unavailable`, with provenance. Implement idempotent run-level accounting needed for bounded execution and reuse the existing trial contract; checkout, production metering, paid conversion and overages remain Phase 4. Failed requests without usable output must not consume the user allowance; record any incurred provider cost separately.

## 7. Both agent entry points and profile transfer

Support creation **inside PostRiff** through the runtime selector and **inside a supported external agent** through a small scoped PostRiff integration. Reuse an existing suitable tool/API boundary; otherwise implement a minimal reviewed skill/MCP surface for reading selected context, submitting candidate drafts and opening their review link. Do not create a general remote shell or duplicate publishing backend.

The integration must use the same permission, schema, workspace, revision and idempotency checks as the app. It cannot publish, approve its own proposal, change connections or bypass review. Export only neutral integration instructions and the customer's selected material; never install or rewrite global skills implicitly.

Connect the existing portable voice-builder request to the selected qualified runtime using its exact source manifest. Show requested versus actually accessible context. Import results as untrusted candidates through existing field-level review. New-to-AI users can continue guided onboarding without installing a CLI.

## 8. Synchronization and offline recovery

Cache only selected profiles/drafts and preserve local-only visibility. Synchronization/upload is explicit for local material; pairing does not consent to uploading every file. A cloud run must reject inaccessible local-only sources with a useful recovery choice, not silently substitute other context.

Use expected revisions, durable pending operations, idempotency and conflict presentation. A web edit and desktop edit of the same variant cannot silently overwrite each other. Distinguish unsent local edits, synced canonical state and external native session state. Reconnect by run/event cursor and deduplicate artifacts.

Test sleep/wake, browser closure, desktop restart, network loss, expired sessions, device revocation and source deletion/retraction. Resume safe editing without promising offline model inference. Already-approved cloud publication remains owned by the independent distribution service; agent availability must not become its execution dependency.

## 9. Validation and acceptance

Before editing, establish the smallest relevant Phase 1/2 baseline. At prompt preparation, these fresh checks passed:

- `python3 -m unittest discover -s tests -p 'test_postriff*.py'`: 90 discovered, 89 passed, 1 skipped because the pinned hosted Pillow dependency is not installed in this interpreter. The hosted image-decoder check therefore has `validation_unavailable` in this interpreter; older isolated-environment evidence is separate.
- `npm --prefix studio/web test`: 70 passed.
- `npm --prefix studio/web run typecheck`: passed.

Those counts are a snapshot, not a target. The older receipt's 102 Python tests use a different reported scope; do not substitute that number for current execution. Inspect test/verification scripts before running them; some rewrite historical evidence. Preserve previous receipts rather than regenerating Phase 2 artifacts to describe Phase 3 source.

Add focused tests for the actual new risks:

- Two-workspace/device isolation for discovery, pairing, claims, events, artifacts, export and revocation; no cross-tenant existence leak.
- Renderer/IPC and shell-injection rejection; denied filesystem access, symlink escape, hostile source instructions and no credential/private-skill leakage.
- Each route's structured output, approved source loading, supported inputs, interruption, native resume or explicit new-run recovery, permission denial, malformed output, timeout, missing model and quota exhaustion.
- Restart/reconnect/event replay, duplicate claims, ambiguous model start, stale completion, expired jobs and rejected results after revocation.
- Cross-device conflicts, local-only exclusion, source deletion and retained customized variants.
- Two fictional customers with different identities/languages using each released skill; template-update overrides, all-mode/all-plan parity and no founder leakage.
- Agent output cannot invoke external actions or turn an old approval into authority for changed content.
- Managed request accounting and trial replay/expiry behavior without billing.

Run the current frontend tests, typecheck and relevant web/desktop builds, plus focused Python and real local PostgreSQL tests for changed persistence/RLS. Inspect desktop launch and the complete interaction at desktop and 390×844 mobile widths. Cover keyboard/focus, accessible statuses, reduced motion, runtime selection, source approval, streaming, interruption, conflict recovery and profile review. Validate the packaged app outside its development working directory, including sidecar startup and shutdown without orphan processes. Record Windows/signing/update limitations separately.

For **each real qualified route**, run the same explicitly authorized synthetic brief: an approved fictional profile/source → English LinkedIn and Traditional Chinese Instagram text variants → independent edit → save → restart/return. Verify type/format/skill/source/version provenance, switching continuity and no unsupported first-person claims. Live tests need exact source scope and a bounded cost/usage authorization; parser fixtures never prove real compatibility.

For **hosted acceptance**, use authorized test accounts and devices against the exact configured environment. Demonstrate pairing, two-user isolation, cross-device conflicts, disconnect/reconnect and revocation. A disposable local server or two browser tabs is not hosted/multi-device proof.

If a required environment, credential, authorization or OS is unavailable, record `validation_unavailable` with the exact reason and the best lower-level check. Keep that route or milestone incomplete. Do not repeat passed checks without a relevant source/environment change.

## 10. Deliverables, sequence and definition of done

Work in this order: audit and readiness → bounded architecture decision → shared run contracts and desktop host → pairing and scoped transport → provider adapters/managed writing → Ideas/profile integration and sync → packaging, conformance and UI acceptance → receipt. Keep the existing alpha usable throughout. Do not finish with only another plan when implementation is authorized.

Create a compact handoff under `docs/postriff-phase-3/` containing:

- Readiness/architecture record, resolved specification precedence and exact remaining Phase 2 dependencies.
- Runtime qualification matrix with route/version/OS/auth/capability, real versus fixture checks, official sources, usage evidence and blockers.
- Pairing/sync/security acceptance evidence and reviewable migration/rollback notes.
- Desktop artifact path, launch commands, package hash and signing/OS test status.
- Focused test/browser evidence, scoped source diff and a concise implementation receipt.
- One concrete external-action preview if execution is pending: exact environment/provider/model/device/account target, synthetic inputs, scope, maximum cost, cleanup/rollback boundaries and expected evidence. Never include secrets.

Report these completion states separately:

1. Local implementation and packaged desktop validated.
2. Each Codex/Claude/Gemini/managed route actually qualified, limited or blocked.
3. Hosted pairing and cross-device sync validated or pending.
4. Inherited Phase 2 live acceptance complete or still pending.

Full Phase 3 completion requires the supported route/version matrix, real bounded generation on each advertised ready route, no credential transfer, tested cross-device edits and quota/disconnect recovery, and an executable desktop artifact. An unsupported provider can remain visibly limited, but its promised parity remains an explicit unmet requirement; do not report three working agents after only one passes.

Do not start Phase 4 billing, public launch, Analytics/Audience expansion, automatic publishing/replies or additional platform rollout. End with files, validation, observed execution state and the smallest concrete remaining action.
