# Rafii Library Skill + Post Preview — Engineering Spec

Date: 2026-09-29  
Status: Approved for implementation  
Scope: Agent composer attachment picker only

## Decision

Two different preview interactions are intentional:

1. **Skill rows: tap to read.** Tapping a skill opens a readable preview of the actual installed `SKILL.md` content. The preview has one explicit **Use skill** action; merely reading it must not attach it.
2. **Post rows: tap to use, hold to preview.** The Post picker keeps its existing tap-to-attach behavior. A 450 ms press opens Rafii's existing platform-specific iPhone mockup. The mockup must reuse the production post-preview renderer, never a new fake renderer.

## Goals

- A person can understand every available skill before attaching it.
- A person can inspect a post in the destination app UI without leaving the attachment picker.
- The preview shows the same platform template, media loading, account identity, and honesty caption already used by Rafii elsewhere.
- Existing fast tap behavior remains unchanged.
- Mobile interaction is discoverable without adding repeated per-row copy.

## Non-goals

- Editing a skill.
- Editing a post inside the preview.
- Publishing from the preview.
- Inventing engagement counts, handles, media, timestamps, or account identity.
- Exposing skill instructions through the public model catalogue.

## Skill preview

### Interaction

- The Skills sheet keeps the search field and list.
- Each skill row is a semantic button.
- Tap a row:
  - fetch `GET /api/workspaces/:workspaceId/skills/:skillId`;
  - replace the list body with a reader for that skill;
  - preserve a clear Back action to return to the list;
  - show name, version, description, then the installed `SKILL.md` body;
  - show a fixed **Use skill** action.
- Loading, unavailable and error states stay inside the sheet.
- **Use skill** performs the existing attachment action and closes the picker.

### Data boundary

The current `/api/ideas/models` catalogue is public and must continue to expose metadata only. Full skill text is available only through an authenticated workspace route.

The server:
- verifies workspace access first;
- accepts only an id that appears in `SkillLibrary.eligible()`;
- loads through `SkillLibrary.load()`, retaining its safe-id, product-prefix and path-jail rules;
- returns the installed SKILL.md body and immutable metadata;
- returns 404 for unavailable/ineligible ids.

Response:

```json
{
  "id": "postriff-content-craft",
  "name": "Content Craft",
  "description": "...",
  "version": "1.2.0",
  "sha256": "...",
  "files": [{"path":"SKILL.md","sha256":"...","chars":1234}],
  "body": "# ..."
}
```

No reference file is fetched implicitly. The preview is the actual primary skill document, not duplicated UI copy.

### Rendering

Render Markdown as safe React elements, never `dangerouslySetInnerHTML`. Minimum supported syntax:
- headings;
- paragraphs;
- unordered and ordered lists;
- blockquotes;
- fenced code;
- horizontal rules;
- inline code and emphasis where practical.

Unknown syntax remains readable text.

## Post preview

### Discoverability

In the Post view, directly below the search field:

> Hold a post to preview

This hint appears once for the view, never repeated per row.

### Pointer behavior

For each Post row:
- normal tap/click: existing `onPick`, unchanged;
- pointer down starts a 450 ms hold timer;
- moving more than 10 px, pointer cancel, or early release cancels the hold;
- completed hold opens preview and suppresses the synthetic click that follows;
- native iOS callout/context menu is suppressed only for these rows;
- scrolling must win over the hold when movement crosses the threshold.

### Keyboard / desktop alternative

Long press cannot be the only accessible path. A trailing phone/preview control is exposed on keyboard focus and fine-pointer hover. It opens the same preview without changing the row's tap action.

### Preview renderer

Do not duplicate platform UI.

Resolve the selected snapshot variant:
- if a current review/job manifest exists for the same `variantId`, render from that manifest so scheduled time and approved media stay exact;
- otherwise render the draft using its platform, text, connected account, run media and current local time.

Reuse:
- `usePreviewPost` for manifests;
- `useRunPreviewMedia` for draft media;
- `useAccountPicture`;
- `previewFromDraft`;
- `ExpandedPreviewDialog` / `PreviewDeck` / `PostPreview`.

Therefore Instagram, LinkedIn, Threads, etc. remain the same iPhone templates used throughout Rafii. The existing honesty caption remains visible.

## Accessibility

- Every interactive row/action is keyboard reachable.
- Skill reader Back and Use skill are labelled buttons.
- Post hold behavior has a keyboard/fine-pointer preview alternative.
- Preview modal retains existing focus trap, Escape/close behavior and reduced-motion behavior.
- Do not disable vertical touch scrolling for the list.
- Reader text must preserve readable contrast and line length.

## Tests

Backend:
- authenticated member can preview an eligible installed skill;
- response body is the installed `SKILL.md` body;
- unknown/private/ineligible ids return 404;
- the public model catalogue remains metadata-only.

Frontend/unit:
- Skills no longer attach on row tap; they enter reader mode;
- Use skill calls the original picker action;
- Post view contains exactly one "Hold a post to preview" hint;
- 450 ms hold opens preview, quick tap still selects, movement cancels;
- keyboard/fine-pointer preview action exists;
- implementation imports and reuses the existing post-preview stack.

Build gates:
- web typecheck;
- web lint;
- relevant node tests;
- Python skill/hosted route tests;
- production build.

Browser acceptance when the authenticated harness is available:
- widths 390, 430, 768, 1440;
- Skill: search → tap → reader → back → reader → Use skill;
- Post: quick tap remains selection; hold opens correct app phone; close returns to list;
- media post loads media in mockup;
- vertical scroll does not accidentally preview;
- keyboard preview control works;
- no console/runtime/network errors; axe has no new A/AA issues.

## Release

Implement on isolated branch `feat/library-skill-post-previews-20260929`. Do not touch unrelated WIP. Merge only after required checks pass, then verify the production deployment and the authenticated critical path where tooling allows it.
