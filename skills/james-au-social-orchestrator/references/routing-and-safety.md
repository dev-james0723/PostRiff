# Orchestrator routing, onboarding, and safety

## Entry decision

1. Resolve the bundled Content Engine.
2. Read the durable onboarding state.
3. If first-use intake is incomplete, ask only the returned question.
4. If the user chose content-only or draft-only, allow local drafting while connection work remains explicit.
5. If the user asks to connect channels, continue the selected setup batch rather than restarting intake.

## First-run state path

Use an owner-only SQLite file outside the skill package so skill upgrades do not erase progress. Supply its exact path to `scripts/first_run.py`; never store raw secrets there. The CLI supports `start`, `status`, and progressive `answer` operations. Treat its output as a decision record, not evidence that any external action happened.

`assessment_ready` means identity and channel preferences are frozen for read-only inventory. It does not mean setup is approved. The next live-capable stages are:

`inventory_selected_channels_read_only` -> `awaiting_exact_setup_manifest` -> `awaiting_setup_approval` -> `observable_setup` or `private_handoff` -> `identity_verified` -> `awaiting_test_publish_approval` -> `test_submitted` -> `ready` or a truthful terminal/degraded state.

Each channel advances independently. Never collapse partial readiness into one suite-level success flag.

## Route order

- Setup: conversation director, API setup wizard, security/approval, relevant channel adapter, optional browser-auth handoff, then publish-and-verify for a separately approved test.

- Current news: source acquisition boundary, claim/source review, discoverability, template decision, then eligible copy or graphics planning.
- Article repurposing: canonical meaning, target/language, template decision, discoverability, then native copy or graphics planning.
- Video analysis: source access decision, caption-first transcript intake, optional separate translation, fact/rights review, then derivative planning.
- Static visual: approved source and target, template decision, Guizang eligibility review, then graphics planning.
- Article to motion: approved article or brief, template decision, then HyperFrames motion planning.

## Conversation gate

Ask one question at a time. Material defaults must be visible. Never infer James's experience, reaction, belief, result, relationship, health state, or emotional state from a source. Known answers persist in the campaign session.

## State vocabulary

- `awaiting_answer`: one blocking answer is required; no downstream generation begins.
- `assessment_ready`: first-use choices are frozen; no provider inventory or mutation is implied.
- `awaiting_setup_approval`: the exact manifest is visible and no setup mutation has started.
- `private_handoff`: observation and actions are disabled while James completes a sensitive step.
- `identity_mismatch`: observed account signals differ from the approved batch identity; do not switch or sign out silently.
- `awaiting_test_publish_approval`: setup identity/capability checks passed, but the first write has no authority.
- `ready`: exact account and operation passed its independently approved route test and post-write verification.
- `local_plan_ready`: local routing decisions are complete; no external operation is implied.
- `blocked`: an unsupported mode, missing source, missing Content Engine, or safety boundary prevents progress.

## Execution boundary

Installed wrappers have zero provider and publication authority by themselves. Scheduling or publishing stays unavailable until the exact adapter operation, verified account identity, current approval, idempotency record, ambiguity reconciliation, and independent verification exist.

Every private handoff says where James is, what he must do, what he must not paste into chat, and the exact phrase that resumes the flow. Never retain screenshots, DOM, clipboard, URL, network, OCR, console, or event evidence from a secret-capable surface.
