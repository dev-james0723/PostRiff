---
name: postriff-publish-and-verify
description: Use when executing an exactly approved campaign job, inspecting scheduled or published results, or reconciling a submission whose remote outcome is uncertain.
---

# Publish and verify

Load the immutable job, authenticated approval receipt, current route test and the exact channel driver. Confirm the displayed account/destination, native format, ordered assets, copy, audience, schedule and derivative dependencies. The security skill owns authorization. Missing driver, broker, qualification or approval produces a blocked report with no submission.

Use [the execution interface](references/driver-interface.md). Reserve the durable account lock and attempt before calling a transport. Supply the same job ID as idempotency key on every permitted retry. A failed lock acquisition or uncertain earlier attempt never permits another submit.

A submit acknowledgement records `submitted`. Inspect the destination independently: exact provider ID/permalink, account, native surface, text/media, audience, schedule and any interactive elements must match. For video verify playback and native classification. Verify Stories during the observable window; if no stable identifier exists, use the adapter's reviewed timestamped safe-evidence procedure. Missing such a procedure remains unresolved.

Scheduled queue confirmation is `verified_scheduled`; verify again after the due time before claiming publication. Parent-dependent derivatives wait for their exact parent hash and verified remote result. Never substitute another parent post.

After timeout, lost response or process crash, inspect history and the scheduled queue before considering another action. Do not automatically retry ambiguous, published or scheduled jobs. A demonstrably pre-submit failure may use the adapter's bounded retry policy; the current generic driver conservatively treats all exceptions after the boundary as ambiguous.

Report every requested destination, including unstarted, blocked, failed and unresolved jobs. Any ambiguity keeps the campaign unresolved. Preserve successful posts during partial failure; rollback, editing or remote deletion require separate exact approval.

The current tested transport is a fake provider for fault injection. No live platform driver is qualified merely because these local tests pass.

## PostRiff runtime binding

PostRiff runs this skill's runtime server-side in `src/postriff_phase2/`; the package ships instructions and references only. Where a reference names a module, read it as the hosted equivalent and report `runtime_dependency_missing` when the host does not expose it. The voice contract is the `postriff-content-engine` skill resolved against the memory files the host supplies — in a writing run, `IDENTITY.md`, `VOICE.md` and `BOUNDARIES.md`. Other PostRiff skills remain separate dependencies for their own workflows. This package does not activate providers, authentication, paid calls or publishing.
