# Rafii Intelligent Library — Evidence, References and Delivery

Prepared: 2026-10-08. Evidence categories are deliberately separated. A prior conversation inspection, a fresh local file read and an execution test are not interchangeable.

## A. Prior conversation findings carried forward
The preceding user-visible review inspected the authenticated Library overview and an audio detail panel through Open Remote Computer. Screenshots showed a narrow desktop window, not a real iPhone session. The UI contained Add assets, Upload images, Gallery/List, Used/Unused, search, detail controls and an audio-playback entry. These observations motivate the UI spec but are not candidate acceptance evidence.

The review read remote `dev-james0723/PostRiff`, branch `consumer-saas`, including:
- `src/postriff_phase2/site_agent/library_reads.py`: source blob `98a8ca7701c431f180e56cc11b6a3a330c7b5b1f`; the inspected Agent search was bounded to 200 newest admitted assets before word matching. This observation does not describe all search paths or a later deployment.
- `web/src/features/library/use-library.ts`: source blob `0c30dbfed46f0baa068745b11fe7021ee5bfc35b`; normalized paginated retrieval with legacy fallback and client-derived counts.
- `web/src/features/library/asset-detail.tsx`: source blob `a9450b76dcb954fdf7d946aefd08e7ec6c2fea92`; desktop Sheet/mobile Drawer, playback and document text paths.
- `web/src/features/library/asset-thumbnail.tsx`: source blob `0544c0fc6e511b9f5be79e827815875e10a0a06e`; hash-seeded decorative audio bars, text-cover previews and separate PDF first-page path.
- PR #116, titled Rafii Universal Library and Living Archive, recorded merged on 2026-10-08 at merge SHA `8377ebbb037633d7a360207872f37c51ae088fba`. The PR body described private files, signed access, extraction chunks, retryable processing, collections, hash deduplication and source-consent gates, and explicitly described automatic transcription as unavailable in that release. PR descriptions are implementation claims, not proof of each production path.

Repository reference: https://github.com/dev-james0723/PostRiff/pull/116

The preceding screenshots were visible in the conversation, but no durable screenshot bytes were copied into this package. Do not tell a future agent that reference images are attached. Recapture the current baseline through an authorized browser before UI edits.

## B. Fresh local inspection during packaging
Direct Mac file reads verified:
- Project folder `/Users/ouxianxing/Documents/James-Au-Studio` exists; `docs/design` exists.
- `.git/config` points origin to `https://github.com/dev-james0723/PostRiff.git`.
- `.git/HEAD` names `consumer-saas`; direct local branch ref contained `80bc24d20397a90257cb5571f8a3914a652bfb51`.
- `AGENTS.md` and `CLAUDE.md` contain Token Pilot lifecycle instructions. The automation reference says plan/prompt-only work does not require enrollment/checkpoint writes and requires project write-lease handling for substantive implementation.
- Local `web/package.json` describes the Next.js/React frontend, `typecheck`, `lint`, `build`, Node 24.x and npm 11.12.1. The executing agent must use the latest implementation base's actual lockfile, not treat this snapshot as current deployment configuration.
- The local path `src/postriff_phase2/site_agent/library_reads.py` was absent. A previously remembered universal-library worktree path was also absent. This is a reason to reconcile current Git state, not permission to recreate stale code or claim the remote feature is missing.
- Git config includes branches for Library production fixes, thumbnails and real document previews dated 2026-10-08. Their configuration entries alone do not prove which code is merged or deployed.

Several remote terminal calls, including read-only Git commands and an interactive Python launch, returned a timeout while waiting for a safe execution slot. The response explicitly said no effect was dispatched. Therefore this packaging task did not establish a clean Git status, acquire a project write lease, run Token Pilot resume, fetch the current branch, execute tests or perform a repository commit. It did not bypass a denied lease or restart/kill another session.

## C. Save destination and authority
The independent document folder is `/Users/ouxianxing/Documents/Rafii-Intelligent-Library-2026-10-08/`. It is associated with the verified Rafii project but is not inside its potentially shared checkout. Files are authored in this conversation's working environment and transferred directly to the Mac through Open Remote Computer. Readback/listing verification is recorded in the final delivery response; hashes in MANIFEST.sha256 describe the authored package and are not, by themselves, proof of a remote checksum run.

At implementation start, verify the base and lease, create an isolated worktree, then copy the whole package into `docs/design/rafii-intelligent-library-2026-10-08/` there. Do not modify the shared root to make its state look clean. Respect active workers and current OpenUI integration ownership.

This request is an engineering handoff only: no application code changes, build/test execution against the user's repository, production migrations, backfill, provider setup, paid inference, external notifications, Git push/merge or deployment. The coding prompt in chat authorizes implementation when James supplies it to the coding agent, not retroactively in this documentation task. Release authority remains explicit and separate. All acceptance cases start UNVERIFIED.

## D. Primary-source reference register
These public pages were opened during this packaging turn, on 2026-10-08. Vendor descriptions are reference patterns, not an independent product benchmark or endorsement. The design specifications are Rafii engineering decisions; their proposed thresholds and modules are not asserted by these references.

**E1 — OpenUI renderer, official documentation**
https://www.openui.com/docs/openui-lang/renderer
The page documents a React renderer supplied with a component library, streaming, structured action/state callbacks, tool-provider integration and error handling. Reuse its capabilities through a bounded Rafii host adapter; the documentation is not an authorization policy or a guarantee of compatibility with the current Rafii branch.

**E2 — Iconik media search, official product page**
https://www.iconik.io/media-asset-search
The page describes searching spoken dialogue and navigating to timed media moments, plus virtual collections without copying source files. Rafii adopts the moment-centric interaction pattern, not vendor scale/ROI claims.

**E3 — Air, official help article**
https://help.air.inc/en/articles/8602415-what-is-air
The article describes visual search, revision stacks and approval/creative-review organization. These support the comparison and lineage direction; none of its marketing figures are used as a Rafii forecast.

**E4 — Fabric Smart Organization, official site**
https://developers.fabric.so/features/smart-organization
The page describes automatic metadata, dynamic collections and content similarity. It also labels smart fields as coming soon; this package does not treat that labelled future feature as independently verified available functionality.

**E5 — Bynder UCV AI Search, official support**
https://support.bynder.com/hc/en-us/articles/28988145584530-AI-Search-For-Universal-Compact-View-UCV
The support page describes natural-language and image-similarity search within an embedded asset-selection surface. It does not independently establish every duplicate-management claim in the previous discussion.

**E6 — Supabase hybrid search, official documentation**
https://supabase.com/docs/guides/ai/hybrid-search
The guide describes combining lexical and semantic retrieval and a Postgres implementation. It is an architecture reference, not a read of James's database, enabled extensions, billing or production RLS configuration.

**E7 — WCAG 2.2, W3C Recommendation**
https://www.w3.org/TR/WCAG22/
Accessibility acceptance uses the standard as a reference. The 44-pixel design target in the UI spec is a Rafii target, not a claim that every AA control must meet that size. Automated tests and screenshots alone do not establish conformance.

## E. Decision ledger
Use one shared retrieval/policy service; preserve originals and legacy media; separate purpose from egress and publication consent; retain source/version locators; implement real media understanding; keep a stable Library shell; restrict OpenUI to task regions; use author-approved voice spans; auto-archive final outputs only; keep suggestions quiet and reversible; use evidence rather than decorative intelligence scores; all six workstreams and P0/P1/P2 remain included.

Logical workstreams may progress in parallel after contracts are agreed, but shared files, migrations and release actions have single ownership. There is no promised production completion date. The same acceptance gates apply regardless of number of agents.
