# Rafii × OpenUI — Full Production Engineering Package

**Prepared:** 2026-10-08 · America/Indiana/Indianapolis  
**User's launch target:** 2026-10-09; no exact launch hour was supplied.  
**Mandate:** Deliver the complete, integrated Generative UI release, not a prototype, demo, three-journey MVP, or another planning-only response. Execute independent work in parallel; converge on one verified production release.

> James 要一次過完成可真正使用嘅 production 版本：唔止生成卡片，要有即時資料、表單及安全操作、局部介面更新、持續對話、語音、保存、恢復、驗收及正式上線。日期係交付目標，唔係容許假報完成嘅理由。

## Authority and reading order

1. `01-ENGINEERING-SPEC.md` — complete product scope, non-negotiable architecture, safety, reliability, cost and UX requirements.
2. `02-CONTRACTS.md` — shared interfaces, state machines, event protocol, data/action restrictions and exact initial engineering limits.
3. `03-PARALLEL-EXECUTION.md` — seven roles, file ownership, dependencies, implementation tasks and session instructions.
4. `04-ACCEPTANCE.md` plus `acceptance.json` — mandatory evidence-based gates; all start unverified.
5. `05-RELEASE-RUNBOOK.md` — one release owner, deployment, activation, rollback and truthful completion.
6. `06-EVIDENCE-SOURCES.md` — verified source snapshot, local inspection and official references; distinguishes code facts from untested deployment assumptions.
7. `coordination.json` — initial machine-readable team state; coordinator becomes the only writer after kickoff.

This package supersedes the earlier `rafii-openui-plan-2026-10-08.md` **three-journey scope, two-implementer limit, and October 12–22 staged delivery calendar**. It retains compatible security, architecture and production evidence requirements. There is one full release scope; internal checkpoints and a short production rollout are safety controls, not later product phases. Do not treat the older plan as an instruction to defer features from this package.

## Verified starting point

- Laptop repository: `/Users/ouxianxing/Documents/James-Au-Studio`.
- Git origin: `https://github.com/dev-james0723/PostRiff.git`.
- Remote `consumer-saas` at inspection: `3da806f0e31a01396a3bd4a9e27f66f9b21ce816`.
- Local main worktree HEAD: `80bc24d20397a90257cb5571f8a3914a652bfb51`; it contains unrelated uncommitted social-connector edits and other work.
- **Do not implement in, reset, clean, stash, switch or pull that dirty worktree.** Fetch metadata safely, inspect current active PRs, then make isolated worktrees from the freshly resolved production baseline.
- Intended canonical origin: `https://rafii.io`. Actual domain assignment, running deployment SHA and authenticated production journeys were not checked while preparing this package.

## Operating model

A = coordinator/contracts/release; B = backend runtime/stream/accounting; C = renderer/components/parser boundary; D = query/action/security; E = domain journeys; F = history/surface/voice; G = independent QA/security/performance reviewer. There are five implementation lanes, one coordinator, and at most one independent reviewer active at a time.

Only A modifies the common contract, lockfiles, migration registry, shared configuration and deployment routes. Other agents own the paths in the execution plan. A single role may use cloud jobs, but must not launch overlapping agents into the same owned files. Heavy builds/tests use the existing cloud workflow when available. Local compilation/browser stress jobs are serialized; do not overwhelm the Mac with seven simultaneous builds.

## What this package has and has not done

Prepared deliverables: engineering design, contracts, task plan, release criteria and seed coordination state. Product implementation, dependency installation, tests, PRs, migrations and deployment have **not** been performed by this document-preparation task. A file-save receipt proves only document delivery, never product readiness.

Executing agents must continue through implementation, testing, integration, commit, push, PR, CI, safe merge, deployment, production activation and verification. Ask James only for genuinely missing credentials, new billing/egress authorization, unavoidable physical-device interaction, or an approval the existing release policy explicitly requires. Do not ask again whether he wants the approved work implemented.
