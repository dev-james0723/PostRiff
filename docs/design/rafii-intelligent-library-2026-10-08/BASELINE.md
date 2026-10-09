# T00 Baseline — Rafii Intelligent Library

Recorded 2026-10-08 by the implementation coordinator (Claude Code session "Rafii Intelligent Library upgrade"). Read-only discovery; no shared-checkout edits.

## Repository identity
| Item | Observed value | How |
|---|---|---|
| Origin | `https://github.com/dev-james0723/PostRiff.git` | `git remote` |
| Base `origin/consumer-saas` | `3da806f0e31a01396a3bd4a9e27f66f9b21ce816` (merge of PR #133 thumbnails) | `git fetch origin --prune` then `git rev-parse origin/consumer-saas` |
| Base CI | James Cloud Build test/build/ci/e2e all `success` on 3da806f0 | `gh api .../commits/3da806f0.../check-runs` |
| Shared root HEAD | `80bc24d2` on `consumer-saas`, **174 commits behind** origin, dirty (social-connector edits + many untracked packages) | `git rev-list --left-right --count` |
| Candidate worktree | `/Users/ouxianxing/Documents/.agent-worktrees/rafii-intelligent-library-20261008` | `git worktree add -b claude/rafii-intelligent-library-20261008 … origin/consumer-saas` |
| Candidate branch | `claude/rafii-intelligent-library-20261008` (local only; nothing pushed) | |
| Package copy | `docs/design/rafii-intelligent-library-2026-10-08/` — SHA-256 of all 8 copied files match `MANIFEST.sha256` | `shasum -a 256` |
| Token Pilot write lease (shared root) | `free`; the candidate writes only inside its own worktree, so no root lease was taken | `write_lease.py --root … status` |

The shared root (`/Users/ouxianxing/Documents/James-Au-Studio`) was not reset, cleaned, stashed, switched or pulled.

## Concurrent work found and its boundary
- **PR #134** (draft, Codex, updated 2026-10-08 15:52Z, head `6596c197`): real document page renditions (LibreOffice rasterizer), adaptive document reader, inline audio/video gallery players with a waveform decoded from real audio after play. Touches `asset-thumbnail.tsx`, `asset-card.tsx`, `asset-list-row.tsx`, `document-viewer.tsx`, `gallery-media-preview.tsx`, `library-view.tsx`, `library_preview.py`, `library_assets.py`, `hosted_app.py`, `vercel.json`, CI workflows. **Boundary:** this candidate does not edit `document-viewer.tsx`, `gallery-media-preview.tsx` or `library_preview.py`. It changes `asset-thumbnail.tsx` only to replace the hash-seeded decorative waveform and the mislabelled text covers. That change is also required by R04/R05, and #134 changes the same file. Expect a textual merge conflict there; resolve it in favour of whichever real rendering lands first. Genuine first-page renditions (A016 "first page" labels) depend on #134 or an equivalent.
- **Site-wide OpenUI rollout** (Claude session "Rafii × OpenUI 正式版發佈", worktree `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008`, branch `claude/rafii-openui-production-20261008` @ 3da806f0, nothing pushed). Agreed by message on 2026-10-08:
  - That team pins `@openuidev/react-lang` and `@openuidev/lang-core` at exactly 0.3.2. The registry lives in `web/src/features/agent/generative-ui/library.tsx` (their lane C).
  - This candidate adds no `@openuidev/*` dependency and does not edit `vercel.json`, `web/package.json`, the lockfile, `.james-cloud-build.json` or `agent_runtime_v2/http.py`.
  - Library exports plain descriptors `{name, version, propsSchema (zod v4, ordered), component, actions[]}` and importable Python functions in `library_intelligence/api.py`: `search`, `read`, `answer` and `apply_action`, each taking `(cur, principal, workspace_id, params)`.
  - Merge order: OpenUI runtime first, then this candidate rebases and registers its descriptors.
  - Migrations: this candidate first used 097. On 2026-10-09 consumer-saas shipped `097_youtube_capacity.sql` (and 098–103 are claimed by the YouTube, LinkedIn, OpenUI and Growth Studio branches), so the Library migration is now **104**.
- No other open PR touches Library intelligence. The `codex/rafii-universal-library-*` branches are merged (#116, #132, #133).

## Migration numbering (all local branches + remotes scanned)
Used anywhere: 001–071 (with gaps), 080–081, 083–084, 087–096, 100–101. **This candidate: 104** (renumbered from 097 when it merged consumer-saas on 2026-10-09; the runner refuses duplicate numbers). `104_library_intelligence.sql` is additive. It adds a pgvector column/indexes only where the `vector` extension is available.

## Baseline capability diff (verified in code at 3da806f0)
| Area | Baseline behaviour | Evidence |
|---|---|---|
| Agent Library search | Considers only the **200 newest** admitted assets (`ORDER BY a.created_at DESC LIMIT 200`), then Python substring matching over approved facts | `src/postriff_phase2/site_agent/library_reads.py:30-40` |
| UI Library list | Postgres `simple` tsvector + ILIKE. Page size ≤200 with offset paging. Counts, kind counts and totals are computed **client-side over loaded pages** | `library_assets.py:362-386`; `web/src/features/library/use-library.ts:146-177` |
| Chinese text search | `to_tsvector('simple', …)` treats an unspaced CJK run as one token, so no bigram or Traditional/Simplified folding | `migrations/postriff/093_universal_library.sql:39` |
| Semantic / visual search | **None.** No embedding provider, no pgvector, no visual index | grep: no `embedding`/`vector` use; `site_agent/knowledge.py:12` |
| Transcription | **Unavailable.** Audio rows `transcription_status='unavailable'`; `capabilities.automaticTranscription=False`; user-supplied transcript import only | `library_assets.py:142,300,386` |
| Audio waveform | **Hash-seeded decorative bars** | `web/src/features/library/asset-thumbnail.tsx` `AudioCover` |
| Document covers | Extracted-text faux pages labelled "PDF · FIRST PAGE", "SHEET PREVIEW", "SLIDE PREVIEW" | `asset-thumbnail.tsx` `DocumentCover` |
| Locators | Chunks are 6000-char slices with no page/slide/sheet/time locator | `library_extract.py:13-14` |
| Understanding | `analysis_status='not_applicable'`; no annotations or suggestions | `library_assets.py:218` |
| Versions / lineage | None. Hash dedup marks later identical uploads `duplicate` | `library_assets.py:210-214` |
| Collections | Manual only, 100 per workspace. No rules, overrides or undo | `library_assets.py:280-298` |
| Voice | Canonical samples in `state.sources` (`kind:'voice_sample'`) with owner-only `voice_sample_grant` and `voice_sample_revoke` (marks speaker revisions stale) | `voice_sources.py:137-241` |
| Generated outputs | Agent images already enter `state.phase2.assets` with lineage. No document deliverable registration | `agent_runtime_v2/creative.py:353-468` |
| UI shell | Two competing actions ("Add assets" and "Upload images"). "Manage collections" accordion and storage line above results. No multi-select or batch actions. No URL state | `library-view.tsx:368-383,602-659` |
| Jobs | Row-based on `pr_library_assets`; 3 jobs per cron tick; 180 s lease with no heartbeat | `library_assets.py:175-225,388-409` |

## Existing implementations reused (not recreated)
- Private object storage and signed URLs: `hosted_storage.PrivateAssetService`.
- Upload begin/commit with quotas: 50 MiB per file, `POSTRIFF_LIBRARY_WORKSPACE_BYTES` default 1 GiB.
- Bounded extraction subprocess, chunks and tsvector, collections and labels, hash dedup, `as_source` fact review.
- `source_policy` classify/use approval (the authority for `draft_evidence` and `public_use`).
- `voice_sources` grant/revoke and speaker-revision staleness.
- `billing.Ledger` reserve/settle and `ai_call_events` metering.
- AI Gateway transport (`model_runtime.model_transport`) and the existing vision route (`media_notes.MediaReader` pattern).
- Phone STT path (`OPENAI_API_KEY`, OpenAI transcription).
- Repository `effects` hooks, cron `/api/cron/worker`, and the notifications store.

## Baseline evidence not yet captured
- **UI baseline screenshots** need a running web app. This worktree has no `web/node_modules`, and the shared root's install is from a different lockfile (Next 16.3.6 vs 16.3.8; `thinking-orbs` missing). Per the cloud-first resource policy, a local `npm ci` needs explicit authorization. The baseline capture is therefore pending: either a cloud browser run or an authorized local install.
- No production or authenticated-production reads were made.
