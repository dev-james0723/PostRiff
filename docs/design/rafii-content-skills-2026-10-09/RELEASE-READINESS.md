# Rafii Content Skills P0–P2: release readiness (2026-10-09 continuation)

Companion to [`ACCEPTANCE-EVIDENCE.md`](ACCEPTANCE-EVIDENCE.md), which is the only acceptance ledger (A01–A40). This file holds the lineage, the release gates, the security and review results, the blocker register, the preview and rollback plans and the one consolidated authorization request. Nothing here was pushed, merged, deployed, migrated, published, flag-enabled or run on a paid model.

## 1. Source lineage

| Item | Value |
|---|---|
| Worktree | `/Users/ouxianxing/Documents/.agent-worktrees/rafii-content-skills-20261009` (the handoff's relative path `.agent-worktrees/…` is under `Documents/`, not under the main checkout) |
| Branch | `claude/rafii-content-skills-20261009`, local only, no remote branch, no PR |
| Base at handoff | `origin/consumer-saas` `220d2de1` (PR #149) |
| Base now | `origin/consumer-saas` `de4e5907` (PR #138), fetched 2026-10-09; merged cleanly into the branch as `ea0d753c` (3 overlapping files, no conflicts, no migrations on this branch) |
| Feature commits | `f85beb67` … `5899fa86` (previous session, 10 commits), then this continuation: `ea0d753c` (base merge), `d90f2282` (A29 review facts), `cf9d0e0a` (security fixes, flags-off isolation, A17 fixes), `__DOCS_SHA__` (this documentation) |
| Release candidate | `__RC_SHA__` (code identical to `cf9d0e0a`; later commits are docs and evidence only) |
| Other sessions | No other worktree or open PR touches this branch. Open PRs #150–#158 are other lanes; none overlaps these files except through the already-merged base. |
| JCB mapping | `.james-cloud-build.json` `tasks.ci` was remapped to `ci:content-skills:web:jcb` and then `ci:content-skills:jcb` for the runs below (with `jcb setup --force` regenerating one line of `.depot/workflows/james-cloud-build.yml`), then restored. The remap was never committed. |

## 2. Release gates

| Gate | Status | Mandatory subconditions and evidence |
|---|---|---|
| G0 Source integrity | **PASS** | Correct branch; ancestry contains `de4e5907`; worktree clean apart from the temporary JCB remap (restored); no unowned changes; JamesOS untouched. |
| G1 Implementation completeness | **PASS (P0/P1/P2 code), with registered blockers** | Projection authoritative; native-format safety enforced at approval (two reads: `format` and `native.formatId`); review facts shipped. Rendering (A24/A25), the paid benchmark (A16/A39) and production release (A40) are registered blockers, not defects. |
| G2 Verification | **__G2__** | See §3. Every suite ran at `cf9d0e0a` in one remote run. |
| G3 Security and authorization | **PASS for code; production unverified** | Independent security review: no P0/P1; three P2 fixed and tested; flags default off and now leave even the original five unchanged; no provider operation, publication, paid call or flag change happened. |
| G4 PR readiness | **__G4__** | Reviewable commits; rollback plan (§7); independent review (§4) done; no open release-blocking defect. Needs the push/PR authorization in §8. |
| G5 Preview rollout | **NOT STARTED, needs authorization** | §6. |
| G6 Paid benchmark | **BLOCKED, needs a spend cap and route wiring** | §8 D3. |
| G7 Merge and production | **BLOCKED** | Requires G4–G6 and separate authorization. Never skipped to from G2. |

## 3. Remote validation (JCB → Depot)

| Run | Source SHA | Scope | Result |
|---|---|---|---|
| `87br6f0pln` | `8df9d86b` (prev. session) | Full content-skills CI | **Exit 1.** Python 4403 OK (371 skipped), every PostgreSQL group incl. CS01–CS05 PASS; one web contract (`preview-window.test.cjs` chip regression) failed, fixed in `54a5af6d`. Logs re-downloaded this session (`depot ci logs tcfc8hjvdd`). |
| `7qbh8hm9fn` | `54a5af6d` (prev. session) | Web stage only | Exit 0. Node 852/852, typecheck, lint 0 errors / 24 warnings, build, browser A32 PASS. One of those warnings (`automations-view.tsx:120`, `draftPlatforms`) **was introduced by this branch**; the earlier "none in changed files" note was wrong. Fixed in `d90f2282`. Screenshot hashes in the log match the committed evidence files. |
| `6wqb1w9gp4` | `d90f2282` | Web stage only | **Exit 1.** Node 854/855: the new `native-draft-facts.test.mjs` could not load (extensionless TS import under node type-stripping). Fixed in `cf9d0e0a`. The browser stage did not run. Receipt `20261010T003817255682Z-ci.json`. |
| `bvzf0zs30d` | `cf9d0e0a` | **Full**: targeted contracts, full Python discovery, every PostgreSQL group, node contracts, typecheck, lint, production build, cloud browser | __FULL_RESULT__ |

Local runs (seconds each, allowed by the cloud-first policy): `python3 -m unittest test_rafii_creation_capabilities test_asset_consumers` 50/50 OK at `cf9d0e0a`; `scripts/content_skills_benchmark.py` 67 cases, 0 critical violations (fixture route only); `scripts/rafii_skill_registry.py --check` 0 errors.

## 4. Independent review

| Review | Scope | Result |
|---|---|---|
| Codex CLI (previous session, fallback mode) | Branch vs `origin/consumer-saas` | 1 P1 + 8 P2, all fixed in `8df9d86b` (Instagram Story kept out of the feed-post path among them). |
| Security/regression review (this session, read-only Claude subagent) | Publish paths, flags, isolation, notes, export, concurrency | **No P0/P1.** Every provider publish reaches `store.build_manifest` through `p2_review`; jobs are created only in `store.approve`; providers read only `manifest.payload.text`. Findings and resolutions in §5. |
| Codex CLI `codex review --base origin/consumer-saas` (this session; the official `codex@openai-codex` plugin is installed, but its review command is not exposed to this session, so the CLI was used) | `cf9d0e0a` vs base | __CODEX__ |

## 5. Security and regression report

| ID | Sev. | Finding | Resolution |
|---|---|---|---|
| S-1 | P2 | Native formats (Story, Reel, carousel, thread, document) were offered and accepted on the original five with both flags off, changing the composer and the writer prompt in a flags-off deploy. | Fixed `cf9d0e0a`: with every wave off only each platform's default is offered (facet) or accepted (`format_not_enabled`). Rows keep every format, so drafts saved under a wave still review and export after a rollback. Review facts render only while a wave is on. Test `test_native_formats_are_offered_and_accepted_only_while_a_wave_is_on`. |
| S-2 | P2 | Reusing an existing source re-approved facts the person had unapproved and overwrote its origin. | Fixed: a reused source keeps its approvals and origin; the campaign drafts only from approved facts. PostgreSQL CS06. |
| S-3 | P2 | Regenerate/retry not idempotent under replay or concurrency (extra paid runs, double apply, lost ids). | Fixed: same `requestKey` replays the revision; retry claimed inside the transaction (`409 campaign_busy` for a concurrent one; a claim older than 15 min is taken over once under the same writer key); attempts counted once. CS06. |
| S-4 | P3 | Agent rewrite of a Story produced a new default post. | Fixed: rewrite keeps the draft's format. |
| S-5 | P3 | Approval gate read only `format`. | Hardened: also reads `native.formatId` (`test_a_native_record_alone_is_enough_to_refuse_a_non_default_format`). |
| S-6 | P3 | Export: list items as dict text; lone surrogates 500; unguarded projection. | Fixed and tested (`test_export_writes_list_items_as_text_and_survives_broken_unicode`). |
| S-7 | P3 | Explicit default formats of newer platforms (e.g. `youtube.video`) are refused at the gate because `DEFAULT_FORMATS` lists six platforms. | Open, fail-closed; only matters once those platforms have publishers. |
| S-8 | P3 | Flag rollback fails a whole automation run that saved a Facebook destination, including its LinkedIn target. | Open; message is generic. Preview plan step 6 covers it. |
| S-9 | P3 | Performance view returns learning preferences under the performance flag rather than the overlay flag (same workspace, no cross-tenant leak); provider "unsupported" collapses to "unavailable". | Open. |
| S-10 | P3 | Pre-existing: an identical request that arrives while its campaign is still `drafting` resumes drafting; with the shared writer key there is no second charge, but `ideas.apply` can race. | Pre-existing on `220d2de1`; recorded. |
| S-11 | P3 | Small: undo audit written on a no-op; retry allowed on a stale record; source-campaign export not flag-checked. | Open, low risk. |

Checked and safe: publish paths (above); disconnected-platform drafting creates no channel, review, schedule or job (also asserted in the cloud browser run); flags fail closed to the original five; cross-workspace reads of exports, attribution, undo and campaign destinations; private notes never reach export, text projection or publish payload; export sha256 is over exactly the bytes written; prompt-injection text never becomes an approved fact (CS03, unit).

## 6. Preview validation plan (G5, needs authorization)

1. Push the branch and open a draft PR against `consumer-saas`; let the repository CI and the Vercel preview build run.
2. On that preview only, set `RAFII_CREATION_PROJECTION_ENABLED=1` (Facebook wave). Leave `RAFII_CREATION_ALL_PLATFORMS_ENABLED` off.
3. Signed in as a real test account with no Facebook connection: draft LinkedIn + Instagram carousel + Facebook Reel; confirm the facts (format, export only, script ≠ video, no account connected) and that nothing appears in Queue/Reviews.
4. Instagram Story: save as draft, try to schedule; expect `format_not_publishable` with the export-only message. Export it; check the manifest hash.
5. Accessibility: VoiceOver (macOS Safari) and iOS VoiceOver walk-through of the composer, format select, drafts dock, caption editor and facts list; record by hand.
6. Flip the flag off on the preview: Facebook and non-default formats disappear from the composer; saved Story/Reel drafts still open, review and export; an automation holding a Facebook target reports a clear failure (S-8).
7. Paid benchmark (A39) on the preview only after D3.

## 7. Rollback plan

- Primary: turn `RAFII_CREATION_PROJECTION_ENABLED` / `RAFII_CREATION_ALL_PLATFORMS_ENABLED` off. Extra platforms, non-default formats and the review facts disappear; saved drafts, campaigns, exports and evidence stay and still export; re-validation fails closed with stable codes (`platform_not_enabled`, `format_not_enabled`).
- Code: revert the merge commit. No migration is added, so no schema rollback is needed. Stored `native` / `format` fields on variants are ignored by older code (they were additive).
- Skills: registry entries are versioned and locked; reverting restores the previous versions and hashes.

## 8. Consolidated authorization request (one decision packet)

| # | Decision | Recommendation | What happens on yes |
|---|---|---|---|
| D1 | Push `claude/rafii-content-skills-20261009` and open a **draft** PR against `consumer-saas` | Yes | Repository CI and Vercel preview build run on GitHub; no merge, no deploy. |
| D2 | Enable `RAFII_CREATION_PROJECTION_ENABLED=1` on **that preview only** and run §6 steps 3–6 (manual VoiceOver step 5 needs a person) | Yes, after D1 is green | Facebook wave on one preview. Production untouched. |
| D3 | Paid benchmark (A16/A39): wire the `model` route in `scripts/content_skills_benchmark.py` through the existing metered writer, then run it | Approve a **US$15 hard cap** | Model `anthropic/claude-sonnet-5` ($2 / $10 per M tokens, `model_runtime.DEFAULT_PRICES` 2026-09-24). Dataset: the fixed 67 cases (33 platforms; every Instagram/Facebook format; 4 Chinese registers × 6 Chinese platforms; injection and disputed-figure negatives). Volume: 67 cases × 2 (paired: current route vs. skill-qualified route) = 134 writer calls, about 12–15 k prompt tokens and ≤2.4 k output tokens each, roughly US$0.05–0.08 per call, so **US$7–11 expected**. Stop conditions: any critical factual or privacy violation; spend reaching the cap; more than 10 % provider errors; any publish or connection attempt. Voice and usefulness scores stay `needs_review` for a person. |
| D4 | A24 static renderer (Phase S in [`RENDERING-BLOCKER-REPORT.md`](RENDERING-BLOCKER-REPORT.md)): no provider cost, but it adds CJK fonts to the production function bundle and a new media state | Approve as its own follow-up PR | About 2–3 days; function-size check in CI. |
| D5 | A25 video: V0 (verify user-uploaded video, no new infra) now; V1 (Rafii-made video) needs a choice of ffmpeg-in-function, a render worker, or a paid provider | V0 yes; V1 later | V0 is about 200–300 lines. |
| D6 | A17 human editorial sign-off of the composed packs | A named reviewer completes §"Human editorial sign-off" in `A17-EDITORIAL-REVIEW.md` | 17 machine CONCERNs remain for that reviewer. |
| D7 | A40 merge and production: separate decision after D1–D3 and the preview are green | Not yet | — |

## 9. Continuation instructions (external blockers)

- **After D1:** `git push -u origin claude/rafii-content-skills-20261009`; `gh pr create --draft --base consumer-saas`; read CI; do not merge.
- **After D2:** set the flag on the preview environment only (Vercel project env, Preview scope, that branch); run §6; record results as new rows in `ACCEPTANCE-EVIDENCE.md` with the preview deployment id.
- **After D3:** implement the `model` route (call `ServerModelRuntime` through the existing ledger reservation; refuse without `--budget-usd` and `RAFII_BENCHMARK_AUTHORIZED=1`), run in cloud CI with the cap, attach the JSON report to `evidence/`, and update A16/A39.
- **JCB remap for this suite:** set `.james-cloud-build.json` `tasks.ci` to `ci:content-skills:jcb`, run `jcb setup --force`, `jcb doctor`, `jcb ci`, then restore both files with `git checkout -- .james-cloud-build.json .depot/workflows/james-cloud-build.yml`. Never commit the remap.
