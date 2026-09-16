# Post preview

An iPhone mockup of a post inside its destination app, one template per channel in `src/config/channels.ts`. It appears in three places: beside the details in the calendar's event popover, inside each approval card in the Queue, and behind the eye button on every publishing job.

- `manifest-preview.tsx`: `ManifestPreview` is the one to use in pages. Give it a manifest; it resolves the browser's time zone and media and renders nothing on the server.
- `post-preview.tsx`: `PostPreview` picks the channel's template (lazy-loaded) and captions it.
- `use-preview-post.ts`: `usePreviewPost(manifest, timeZone)` turns an approved manifest into a `PreviewPost`, loading private media through the API under the Library's cache key.
- `phone-frame.tsx`: the 393x852 screen, bezel, Dynamic Island, status bar and home indicator. Templates lay out at real app sizes; the frame scales the whole screen.
- `parts.tsx`: shared pieces (lettered avatar, link colouring, line clamp with the app's "more" label, media fill and grid, tab bar, time helpers).
- `app-icons.ts`: glyphs that stand in for other apps' chrome, kept apart from PostRiff's own icon set.
- `templates/<slug>.tsx`: one default export per channel; `templates/index.ts` maps slugs to loaders; `generic.tsx` covers anything unmapped.
- `gallery.tsx` with `src/app/dev/post-previews/page.tsx`: every template side by side with sample posts. Development only; production answers 404.

## Using it

```tsx
<ManifestPreview manifest={review.manifest} scale={0.5} />
```

`scale` sets the phone size (0.62 ≈ 262px wide, 0.5 ≈ 214px). Pass `timeZone` only when the page already draws times in a specific zone.

## Adding or updating a template

1. Look up the app's current iPhone UI for the exact surface PostRiff publishes to (feed post, note page, channel view, chat room), including recent redesigns. The research notes and sources are in `docs/postriff-post-preview-templates.md`.
2. Write `templates/<slug>.tsx`: `PhoneFrame` with the app's background and status bar tone, then the app's chrome and the post. Use the app's UI language for chrome strings.
3. Register the slug in `templates/index.ts` and check it in `/dev/post-previews` with no media, one image and several.

## Honesty rules

- Only the post is real. The account's name comes from the manifest; the avatar is a lettered monogram because PostRiff does not hold the profile photo.
- No invented engagement. Counts that would be zero at publish time are hidden, or shown as the app shows zero.
- Times are the approved publish time (the status bar clock too), in the viewer's zone.
- When the app needs media the post lacks, a dashed PostRiff note says so. It is never drawn as part of the app.
- The caption under every phone says the app has the final say on layout.
