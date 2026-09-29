# Rafii Library Skill + Post Preview — Implementation Plan

Date: 2026-09-29  
Branch: `feat/library-skill-post-previews-20260929`

## 1. Server contract

1. Add `HostedWorkspaceService.skill_preview(workspace_id, token, skill_id)`.
2. Authenticate with `repository.get` before reading a skill.
3. Resolve the skill against `self.ideas.skills.eligible()`.
4. Load through `self.ideas.skills.load(skill_id)`; return metadata + primary body only.
5. Add authenticated GET route `/api/workspaces/:workspaceId/skills/:skillId`.
6. Add tests covering success, auth/ineligible behavior and metadata-only public catalogue.

## 2. Web API

1. Add `SkillPreview` type.
2. Add `api.skillPreview(workspaceId, skillId)`.

## 3. Skill reader

1. Keep the existing skills search/list.
2. Change skill row tap from attach to preview.
3. Add reader state with loading/error.
4. Render the returned Markdown with a small safe renderer.
5. Add Back and **Use skill**.
6. Only **Use skill** calls the existing `onPick` path.

## 4. Post hold preview

1. Extend Post SearchView only; templates/sources/accounts remain unchanged.
2. Add one "Hold a post to preview" hint under the Post search box.
3. Add reusable hold recognizer:
   - 450 ms threshold;
   - >10 px movement cancels;
   - cancel/release cleans timers;
   - completed hold suppresses click.
4. Add focus/hover preview action for keyboard/fine pointer.
5. Resolve selected variant and prefer an existing matching manifest.
6. Reuse the existing iPhone preview pipeline:
   - manifest -> `usePreviewPost`;
   - draft -> `useRunPreviewMedia` + `useAccountPicture` + `previewFromDraft`;
   - display -> `ExpandedPreviewDialog`.

## 5. Verification

Run or obtain CI evidence for:
- Python focused tests;
- web focused node tests;
- TypeScript;
- lint;
- production build;
- existing preview tests.

Where authenticated browser automation is available, exercise 390/430/768/1440 and inspect console/network plus accessibility. If the remote-computer quota prevents this, do not claim that gate passed; use CI/Vercel evidence and record the exact residual blocker.

## 6. Ship

1. Open PR to `consumer-saas`.
2. Wait for required checks.
3. Review diff for unrelated files and secrets.
4. Merge with expected head SHA.
5. Confirm Vercel production deployment points at the merge commit.
6. Verify production health and, if an authenticated browser is available, the Skill and Post critical paths.
