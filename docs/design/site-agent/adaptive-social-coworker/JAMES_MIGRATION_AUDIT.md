# James Orchestration → Rafii migration audit

The machine-readable ledger is [capability-ledger.json](capability-ledger.json): 66 source entries, each with a destination capability, treatment, version and tests. The capability inventory is `skills/rafii-registry.json`.

## Rules applied

- **Nothing is copied wholesale.** Only transferable methods were generalised into product capabilities.
- **What stays out of defaults.** James's identity, biography, projects, career, tone, visual identity, private paths, local services and personal accounts never enter a default (product) skill.
- **Private Studio material.** The five `skills/james-au-*` packages are classified `private: true`:
  - excluded from the hosted build (`.vercelignore` `skills/james-au-*/`);
  - refused by the hosted `SkillLibrary.load`, which accepts product prefixes only;
  - forbidden by the deployment artifact check (`scripts/consumer_ready_artifact.cjs`).
  They keep serving the local Studio (`src/james_au_social/studio_codex.py`).
- **Global installs.** The global `~/.claude/skills/james-au-*` (56 skills) were audited and mapped. None of them is loaded by the product.

## Residual leaks found in the generic `postriff-*` files and removed (with version bumps)

These are the files bound on every writing run. The earlier generalisation missed them.

| File | Before | After |
|---|---|---|
| `postriff-content-craft/references/human-voice-pass.md` | a fixed voice ("reflective, specific, calm, curious, candid…", "Preserve natural Cantonese-English mixing") imposed on every customer; "every the creator draft" | anchor to the workspace's approved `VOICE.md`; no house personality; keep the creator's own code-switching |
| `…/editorial-workflow.md` | "a musical phrase", "Cantonese-facing Threads", "natural Cantonese" | "a phrase from the work", "in the audience's own language", "the creator's natural dialect or code-switching" |
| `…/visual-handoff.md` | "A calm piece of music…", "genuine performance frames", "musical pauses" | generic subject, frames of the work, natural pauses |
| `…/platform-playbooks.md` | "building/practice decision", "quiet musical opening", "music/practice moment" | work or practice decision, quiet opening, practice moment |
| `…/algorithm-practice.md` | "preserve musical context" | "preserve the content's own pacing" |
| `postriff-content-engine/references/content-pillars-and-workflows.md` | "connection to music, building, creativity, or living well"; "genuine musical understanding" | "the creator's field, work or audience"; "genuine understanding" |
| `postriff-content-engine/SKILL.md` | "a real person who is building, listening…" | "a real person or brand with a specific point of view" |
| `postriff-channel-bilibili`, `postriff-channel-linkedin` | "Music and software experiments", "builder lessons" | generic deep-dive / work lessons |
| `postriff-research-and-source-log`, `postriff-channel-xiaohongshu` | "RedFox signals" (a provider used locally) | "third-party signal providers" |

The versions are `postriff-content-craft` 1.2.0, `postriff-content-engine` 1.1.0, bilibili, linkedin, research-and-source-log and xiaohongshu 1.1.0, and every other product skill 1.0.0 (its first recorded version).

## The no-leak gate

`skill_registry.leak_findings` scans every file of every default skill. It looks for:
- a person's name (James);
- studio or brand names, projects (D Festival and others) and teachers;
- personal account handles;
- home-directory paths and local service addresses;
- one person's fixed voice anchors.

It passes generic domain words: "music rights" on a platform is fine, "Cantonese" as a locale is fine.

Tests:
- `test_no_james_content_in_the_default_bundle`: 0 findings.
- `test_customer_specific_content_in_a_default_skill_fails`: a planted "Write like James, the pianist" makes the check fail.
- `test_overlays_never_cross_workspaces`: one workspace's notes never appear in another's compiled context.
- `test_hosted_binder_refuses_person_specific_skills`: the private packages cannot be loaded by the hosted binder.

**Product copy (added after the WP10-WP11 review).** The review found one person's career in the new coworker UI's example text: "Piano masterclasses in Hong Kong", "Fill the autumn masterclass / Show how I teach slow practice" and "Say “masterclass”, never “workshop”". The examples are now neutral (bakery and workshop examples). `skill_registry.copy_leak_findings` scans the coworker UI (`web/src/features/coworker`, `web/src/lib/coworker`, the Weekly and Personalization routes) and `email_locales.json` with the same patterns plus career terms (piano, masterclass, slow practice, recital). It runs inside `--check`, which reports 0 findings. `RegistryGateTest.test_product_copy_is_scanned_for_one_persons_examples` plants a string and expects the gate to fail. The browser test's seed data no longer uses piano-teaching content either.

## Treatment summary

| Treatment | Examples |
|---|---|
| Transferable method → product capability | content-craft, discoverability, research-and-source-log, social-graphics → visual craft; automation-recipes → Weekly Operator; content-pack and derivative distribution → Source → Campaign; rss-news-intake → listening; Humanizer (EN/ZH) and lieflat → `rafii-humanizer-*` plus the evaluator |
| Deterministic policy (code, never prompt) | security-and-approval → permissions, forbidden effects, approvals and proposal digests; publish-and-verify → `outcomes.normalize_result`, `lifecycle.JOB_ITEM` |
| Executable tool | source-extraction-providers → `research_fetch`; video-transcript-intake → `source_normalize` (captions); media-generation → the runtime's image tools |
| Duplicate | 33 `james-au-channel-*` → the existing `postriff-channel-*` adapters; conversation-director (deprecated; runtime intake plus the Manager) |
| James-specific memory (excluded) | social-orchestrator, api-setup-wizard, browser-auth-and-session, template-library, james-daily-conductor, redfox provider |
| Obsolete for hosted | hyperframes-motion (dormant: no hosted renderer) |
| Local only | Agent Reach → `LocalAgentReachProvider`, never ready on a hosted deployment |

## Licences

- Humanizer-EN: MIT © 2025 Siqi Chen.
- Humanizer-ZH: MIT © 2026 歸藏.
- lieflat: MIT © 2026 shiujan.
- content-craft upstream: MIT © Sergey Bulaev.

The notices are in `skills/rafii-humanizer-*/LICENSE-NOTICE.md` and `skills/postriff-content-craft/LICENSE`.

The guizang visual catalogue signals an AGPL-3.0 upstream. It stays Studio-only and private, never in the product bundle.
