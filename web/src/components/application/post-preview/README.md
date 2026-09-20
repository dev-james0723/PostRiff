# Post preview

An iPhone mockup of a post inside its destination app, one template per channel in `src/config/channels.ts`. It appears beside the details in the calendar's event popover, inside each approval card in the Queue, behind the eye button on every publishing job, and in the agent conversation while drafting (the inspector's Preview tab, the draft card's Preview button, and Compare for every draft side by side).

- `manifest-preview.tsx`: `ManifestPreview` is the one to use for approved posts. Give it a manifest; it resolves the time zone, media and the account's picture, and renders nothing on the server.
- `draft-preview.tsx`: `DraftPreview` does the same for a draft that has no manifest yet (platform, text, account, optional planned time and channel id).
- `post-preview.tsx`: `PostPreview` picks the channel's template (lazy-loaded), holds what the reader is looking at (slide, playback, guides, light or dark) and renders the tools and caption under the phone.
- `use-preview-post.ts`, `use-account-picture.ts`: manifest to `PreviewPost`, loading private media under the Library's cache key and the connected account's stored profile picture.
- `phone-frame.tsx`: the 393x852 screen, bezel, Dynamic Island, status bar and home indicator. Templates lay out at real app sizes; the frame scales the whole screen.
- `parts.tsx`: shared pieces: avatar (real picture or monogram), link colouring, line clamp with the app's "more" label, media fill, carousel, sideways strip, playable video, grid, tab bar, time helpers.
- `guides.tsx`, `limits.ts`: notes on what readers will not see (text limits, missing media, crops, folds, areas under an app's buttons) and the marks drawn for them.
- `playback.tsx`: the slide in view and video playback, shared by the phone and the pager under it.
- `appearance.tsx`: light or dark for templates with a sourced dark palette.
- `preview-tools.tsx`, `export-image.ts`, `preview-settings.ts`: the row under the phone (pager, play, light/dark, Guides, Copy image, Download PNG), the PNG export, and per-viewer choices kept in this browser.
- `app-icons.ts`: glyphs that stand in for other apps' chrome, kept apart from PostRiff's own icon set.
- `templates/<slug>.tsx`: one default export per channel; `templates/index.ts` maps slugs to loaders; `generic.tsx` covers anything unmapped; `templates/checks.ts` records when each was last checked against its app.
- `gallery.tsx` with `src/app/dev/post-previews/page.tsx`: every template side by side with sample posts (text only, one image, a tall photo, several images, a recorded video, a sample profile picture). Development only; production answers 404.

## Using it

```tsx
<ManifestPreview manifest={review.manifest} scale={0.5} />
<DraftPreview platform='LinkedIn' text={draft} account='Your Studio' channelId={channel?.id} scale={0.7} />
```

`scale` sets the phone size (0.62 ≈ 262px wide, 0.5 ≈ 214px). Pass `timeZone` only when the page already draws times in a specific zone. `tools={false}` on `PostPreview` hides the row and notes under the phone.

## What the notes and guides say

- **Length**: only limits with a published source (`limits.ts` cites each one), counted the app's way (X's weighted count with links as 23, Bluesky graphemes, Mastodon links as 23). A channel without a confirmed limit says nothing.
- **Missing media**: from the dashed `MissingMedia` note, in English under the phone.
- **Crop**: only where a template declares the app's documented ratio range (`MediaFill crop`): Instagram 1.91:1 to 4:5, Facebook taller than 4:5. Reported for the slide in view.
- **Fold**: measured from the drawn text (how much shows before "… more", quoting the last words), or from the length cut for captions over video.
- **Covered areas**: in full-screen video apps, the controls drawn over the picture (`COVER_MARK`) are shaded while guides show.
- Notes are reminders. Nothing here blocks scheduling or publishing.

## Adding or updating a template

1. Look up the app's current iPhone UI for the exact surface PostRiff publishes to (feed post, note page, channel view, chat room), including recent redesigns. The research notes and sources are in `docs/postriff-post-preview-templates.md`.
2. Write `templates/<slug>.tsx`: `PhoneFrame` with the app's background and status bar tone, then the app's chrome and the post. Use the app's UI language for chrome strings. Use `MediaCarousel` where the app pages through photos, `MediaStrip` where it scrolls a row, and mark overlay controls with `COVER_MARK`.
3. A dark version only with dark colours from the app's own tokens or code: put both palettes through `usePalette`. Templates that never call it show no light/dark switch.
4. Register the slug in `templates/index.ts`, add its row to `templates/checks.ts`, and check it in `/dev/post-previews` with every media choice.

## Keeping templates accurate

- `templates/checks.ts` holds the date each template was last checked and how sure that check was. Previews show "checked <date>", and say the check is old after 60 days.
- `node scripts/snapshot-post-previews.mjs` (with the dev server running) screenshots every template at a pinned time into `web/.snapshots/post-previews/<date>/` and reports which drawings changed since the last run.
- A scheduled task (`postriff-post-preview-recheck`, 1st of each month) researches app redesigns, updates the research doc and check dates it can confirm, runs the snapshots, and proposes template changes for approval.

## Honesty rules

- Only the post is real. The account's name comes from the manifest. The avatar is the account's own profile picture when the provider gave PostRiff one at connect or re-verify (stored small, deleted on disconnect); otherwise a lettered monogram, never a stand-in photo.
- No invented engagement. Counts that would be zero at publish time are hidden, or shown as the app shows zero.
- Times are the approved publish time (the status bar clock too), in the viewer's zone.
- When the app needs media the post lacks, a dashed PostRiff note says so. It is never drawn as part of the app. Guides, arrows and the play button are PostRiff's too, and exports leave the controls out.
- The caption under every phone says when the template was checked and that the app has the final say on layout; an exported PNG carries the same note so it never passes for a screenshot.
