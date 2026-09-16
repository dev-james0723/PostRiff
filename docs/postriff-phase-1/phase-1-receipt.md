# PostRiff private founder-alpha receipt

Date: 2026-09-14. **Authorized founder-alpha scope complete and ready for founder testing.** This is a local prototype with deterministic draft generation, simulated account verification, and procedural artwork.

**Phase 0 remains incomplete: 0/5 full interviews; one approved founder summary; P02–P05 pending. No customer validation or market-demand claim.** The explicit founder-alpha exception supersedes the original stop-before-code gate only for this private slice. Full commercial Phase 1 research and real-agent qualification gates remain unmet.

## Open and review

- [Open the local founder alpha](http://127.0.0.1:4326/). Choose **Set up my agency** for a fresh private workspace, or **Explore with a sample** for a temporary fictional preview. Account controls are clearly labelled simulations; no real account credentials are needed. Email/phone use the displayed fixture code `123456`.
- [Acceptance results](acceptance-results.md), [implementation record](implementation-record.md), [final onboarding copy](onboarding-copy.md), and [internal skill migration manifest](skill-migration-manifest.md).
- [Desktop You overview](evidence/r22-you-desktop-overview.png), [mobile You overview](evidence/r22-you-mobile-overview.png), [mobile constellation](evidence/r22-you-mobile-constellation.png), and [eight browser journeys](evidence/browser-acceptance.json).
- [Example export: fictional hybrid draft pack](evidence/fixtures/fictional-hybrid-drafts.zip) and [portable voice package](evidence/fixtures/fictional-hybrid-profile.zip). These contain synthetic community-workshop material, not founder/customer content.

To restart from this project directory: `python3 scripts/postriff_alpha.py`. It binds only `127.0.0.1:4326`. Build the separate client with `cd studio/web && npx vite build --config vite.alpha.config.ts`.

## What is working

Personal Brand, Role Specific, Business and Hybrid paths; new-to-AI and experienced-AI branches; explicit profile source scope; portable builder request; untrusted JSON/Markdown/ZIP profile import; field evidence/privacy review; optional self-described MBTI; source-fact approval; provisional voice revisions; three neutral core templates and private customer overrides; English/Traditional Chinese platform variants; independent edits; review-before-replacement; remember/post-only/reject/undo/delete controls; SQLite persistence; return state; and ZIP export.

The **You** utility keeps the six work destinations intact. Overview, Voice & Knowledge, Skills & Learning, Usage & Plan, and Account & Privacy expose a deterministic constellation and equivalent list, exact field details and review links, identity sentence, revision comparison/restore, privacy-safe ArtBrief, and local watercolor refresh/download/removal. Profile changes do not silently replace selected artwork. Managed writing, managed images, storage and external-agent runs are distinguished as local/fixture state.

## Validation

**49 focused Python tests passed; 70 existing frontend contract tests passed; TypeScript and alpha production build passed.** Eight browser journeys covered every mode at 1440×1000 and 390×844 through draft/edit/preference/save/export/reload. Server restart, existing-account return, keyboard focus/errors, graph/list parity, artwork persistence, and quota recovery were also checked. Representative screenshots were visually inspected.

[Privacy and artifact checks](evidence/privacy-artifact-validation.json) verified **57 original private skill files and seven legacy source/configuration files unchanged**, neutral client/template/builder artifacts, eight synthetic ZIP CRCs, and every export-manifest hash. No new package dependency was added. The existing Studio at port 4310 was not restarted or modified.

These are functional and accessibility checks for the alpha, not a formal WCAG certification or assistive-technology user study. The installed source directory has no Git metadata; baseline hashes and [source inventory](evidence/source-inventory.json) are the review boundary. The planning reference `scripts/verify_project.py` is absent (`validation_unavailable`); focused tests, the actual frontend commands, browser checks and the scoped artifact validator provide the lower-level verification.

## Real routes and limits

| Route | Observed state | Qualification |
|---|---|---|
| Deterministic draft adapter v1.0.0 | Executed locally; all fixture cases passed | Tested fixture only |
| Codex CLI 0.154.0 | Executable/version inspected | Real generation untested; execution blocked/unqualified |
| Claude Code CLI 2.1.153 | Executable/version inspected | Real generation untested; execution blocked/unqualified |
| Gemini CLI 0.45.2 | Executable/version inspected | Real generation untested; execution blocked/unqualified |
| Portable AI handoff | Request/export/import/review tested with synthetic candidates | External AI execution and history access untested |
| Google/Apple/Microsoft/email/phone | Local verification adapter tested | Real OAuth, email/SMS, recovery and account linking unimplemented |
| Managed writing/images | No requests made | Blocked in this alpha |

Authentication, source access, native session resume, paid-route entitlement and provider usage were not inferred from installation or AI relationship answers. Custom source passages remain attributed quotes; automatic translation is deliberately limited and labelled for review. Fictional sample facts have paired bilingual wording. Voice fit, eight-minute human activation, repeated usage, willingness to pay, production auth/security, cloud synchronization and real account recovery remain unvalidated.

Local content lives separately under `~/Library/Application Support/PostRiffFounderAlpha/`; the browser retains its local access credential and unfinished editor text. This is not an encrypted cloud vault. Keep exported work before clearing browser storage.

No deployment, billing, paid generation, social-account connection/modification, scheduling, publishing, outreach or Phase 2 was performed. Next: resume the pending research interviews when real input is available and use this alpha for founder testing. Real model qualification and any hosted Phase 2 work need their own concrete scope; neither has begun.
