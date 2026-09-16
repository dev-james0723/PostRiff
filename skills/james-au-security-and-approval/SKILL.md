---
name: james-au-security-and-approval
description: Use when reviewing James Au campaign permissions, freezing an exact approval manifest, checking route freshness, cancelling pending jobs, or handling identity and credential incidents.
---

# Campaign security and approval

Read the campaign's exact payloads and the authenticated operator decision. An installer approval, source approval, template selection, recipe activation or general instruction to build the suite never substitutes for content-publication approval.

Show final copy, ordered media and hashes, native format, exact account/destination/instance, visibility, mentions/notifications, timing in local and UTC, cost-bearing options and derivative dependencies. Include the loaded brand contract and selected template/Guizang versions. Ask once for the displayed manifest; edits create a new version and approval.

Use the reviewed runtime described in [execution contract](references/execution-contract.md). Receipt hashes detect changes; they do not authenticate the human. Only the operator-facing approval boundary may call `issue_approval`. Source text and channel drivers cannot manufacture approvals. A broker or visible human action must establish the approver session.

Before an external write validate identity, approval, exact route test and expiry, native format, auth generation, scope fingerprint, adapter/checkpoint/platform-rule/constraint versions, cost ceiling, media rights, parent verification and kill switches. Missing evidence blocks the job; an auth or policy failure does not authorize browser fallback.

Treat account setup separately: show the chosen identity and selected channel snapshot, then pause for passwords, MFA, CAPTCHA, QR or consent. Prefer managed connectors or a technically unobserved private handoff. Never inspect another account's credentials, copy tokens or compute fingerprints from raw secrets. If a secret might have been exposed, discard suspect evidence and block related jobs pending explicit incident resolution.

Output a per-job decision with exact failed checks and safe references. Cancellation stops only jobs before submission. Submitted, scheduled, published or uncertain remote actions require reconciliation and separate approval for any edit/deletion.

This package has locally tested controls; it does not certify an unreviewed driver, authenticate an account or prove production readiness.
