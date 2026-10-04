# Rafii Universal Library / Living Archive — Recovery Handoff

**Recovered:** 2026-10-04  
**Repository:** `dev-james0723/PostRiff`  
**Recovery branch:** `codex/rafii-universal-library-phase1-20261004`  
**Draft PR:** #116

## What was recovered

The original local Codex worktree was:

`/Users/ouxianxing/.codex/worktrees/rafii-universal-library/James-Au-Studio`

The parent worktree marker still exists, but the repository checkout is no longer present. Historical inventory records `codex/rafii-universal-library` at `7b5ece8b343c` with no unique committed delta relative to its canonical lineage. Therefore the reported mixed-file/PDF/indexing candidate was uncommitted local WIP and must not be represented as recoverable committed source.

The original Living Archive authority was recorded under these paths:

- `docs/superpowers/specs/2026-09-28-rafii-library-living-archive-design.md`
- `docs/superpowers/plans/2026-09-28-rafii-library-living-archive.md`
- `docs/superpowers/handoffs/2026-09-28-rafii-library-living-archive-handoff.md`
- `docs/design/rafii-library-living-archive/selection-rationale.html`

The separate Smart Title design was recorded under:

- `docs/design/rafii-library-smart-title/RAFII_LIBRARY_SMART_TITLE_ENGINEERING_SPEC_2026-09-28.md`
- `docs/design/rafii-library-smart-title/RAFII_LIBRARY_SMART_TITLE_AGENT_HANDOFF_2026-09-28.md`

## Current canonical foundation

Do not rebuild capabilities already present on `consumer-saas`.

Already present:
- private image ingestion and Library storage
- verified direct-to-private-storage MP4/MOV upload flow
- Library listing of photo + video media
- global Now Playing handoff for Library videos
- chat photo/video attachments and media notes
- text-file attachment flow in the chat composer

Not present as a normalized Universal Library:
- canonical `library_assets` / extracted-text chunk storage
- PDF/Office/generic-file Library ingestion
- Library full-text document search
- durable Smart Title / AI summary / tag analysis pipeline
- generated-document auto-ingest into Library

## Recovery slice implemented in PR #116

Phase 1 recovery deliberately starts from the current product instead of reviving stale code:

- Gallery and List representations
- All media / Photos / Videos filtering
- media-aware card/detail/delete/accessibility copy
- title/original-filename/summary/tag-aware Library search hooks
- backward-compatible Universal metadata fields on the web Asset contract
- video-only behavior stays on the existing verified Now Playing path
- focused source-contract regression tests

This slice does **not** claim that document/audio/generic-file ingestion is shipped.

## Living Archive interaction direction to preserve

Use restrained spatial motion. The recovered selected interactions were:
1. folder fan
2. morphing detail canvas
3. animated filter surface
4. upload/selection contextual action island
5. conditional interactive grid

Do not turn the Library into permanent glassmorphism, parallax, a reactive-background demo, or a homepage knowledge graph.

## Next implementation package

### U1 — Normalized asset identity
Create a normalized server-owned Library asset model rather than storing extracted document bodies inside `phase2.state`. Preserve legacy image/video IDs and expose a merged read projection during migration.

Minimum metadata:
- workspace / asset identity
- original filename
- user/AI display title
- asset kind
- MIME and extension
- byte size and immutable content hash
- provenance / creator / timestamps
- processing, analysis and indexing status

Before assigning a migration number, re-audit canonical plus every open schema-changing PR. At recovery time canonical reached `088_founder_activation_integrity.sql`; no `089_*` file was found on canonical and the sampled open PR diffs did not add a PostRiff migration.

### U2 — Private file upload boundary
Reuse the security shape of `video_uploads.py`: browser-to-private-storage signed upload, pending row, immutable object identity, server HEAD verification, bounded caps, abort/sweep and account-deletion cleanup.

Do not tunnel documents through `PrivateAssetService`'s image path. Current storage object rules intentionally accept only image categories and the dedicated video category.

### U3 — Text extraction
Implement bounded extraction for:
- TXT / Markdown
- HTML
- JSON
- CSV
- PDF
- DOCX
- XLSX
- PPTX

OOXML can be parsed from ZIP/XML with explicit safety limits; PDF needs an explicit reviewed parser dependency or another approved extraction boundary. Never execute embedded content, macros, scripts or formulas.

Persist normalized extracted text/chunks outside the workspace JSON state. Generic binary files remain valid Library assets even when no extractor exists.

### U4 — Search and analysis
Add workspace-scoped indexed lexical search over title, filename, tags, summary and extracted text. Semantic search is additive, not required to pretend lexical search is semantic.

Smart Title / summary / tags are asynchronous derived metadata:
- original filename is never destroyed
- failure never blocks the asset itself
- user rename wins over generated title
- regeneration is explicit and auditable

### U5 — Product integration
- Library upload surface accepts the supported file classes only after U1–U3 are real.
- Detail canvas renders media preview, extracted text/document facts, provenance and analysis state by kind.
- Rafii references Library assets by stable asset ID.
- Generated PDFs/docs enter the same ingestion path instead of requiring download/re-upload.

## Verification boundary

No production promotion is implied by this recovery. Required gates:
- focused Python/unit tests
- existing Library/chat media web contracts
- TypeScript + lint
- disposable PostgreSQL migration/RLS tests for normalized Library tables
- browser acceptance for Gallery/List/upload/detail/search at desktop + mobile + reduced motion
- account deletion/storage cleanup coverage
- clean secret scan / release gates


## 2026-10-04 release closeout checkpoint

- Latest canonical `consumer-saas` was reconciled as a real two-parent merge at `3e54f0b0d451cc90494ac3667e51bf84daa5d72e`; no canonical changes were dropped.
- Universal Library implementation now includes normalized server-owned asset/chunk storage, private signed file upload, bounded TXT/Markdown/HTML/JSON/CSV/PDF/DOCX/XLSX/PPTX extraction, metadata-only generic binaries, lexical/full-text search, rename, signed original-file access, delete/sweep/account cleanup, and Living Archive Gallery/List UI.
- Audio remains intentionally unsupported in this release rather than being advertised without a reviewed ingestion/player path.
- Previous candidate evidence: Growth Studio, Growth Metrics, Control Foundation and Founder Admin passed; Library/workflow browser scenes themselves reported zero failures. Remaining failures were an OAuth fixture compatibility regression already present/fixed in latest canonical and a disposable PostgreSQL startup failure in the browser runner. This checkpoint intentionally triggers a fresh full gate run on the reconciled head.
- Production activation still requires verification that the configured `POSTRIFF_LIBRARY_BUCKET` exists as a private bucket with the reviewed size/type policy; code success alone is not activation evidence.
