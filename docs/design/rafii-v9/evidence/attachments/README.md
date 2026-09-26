# Chat attachments — browser evidence

`web/tests/rafii-attachments.cjs` writes its screenshots here (or to `--out=<dir>`). It runs against the loopback dev
harness only (`scripts/postriff_dev_hosted.py` + the web app, seeded by `rafii-seed.cjs`), aborts any drafting request
whose model isn't `deterministic-preview`, and forwards the harness's Supabase-shaped signed upload URL to
`PUT /dev/upload/{token}`. Nothing here is production, storage or live-writer proof. See chat-context SPEC §12 and
`docs/design/chat-context/VERIFICATION.md`.

## What the scene checks (Chromium, desktop 1440×1000 and phone 390×844)

- ＋ opens the menu (desktop) or the sheet (phone); Library shows "Add 1" after picking a photo
- PNG upload → Uploading → ready; the second photo can be set to Reference
- `改@帖` typed with `keyboard.type` opens Posts with focus kept on the textarea; Enter keeps the literal text;
  ArrowDown + Enter inserts 「label」; `name@mail` and a pasted `threads.com/@x` don't open the list; Escape closes only the list
- IME through CDP (`Input.imeSetComposition`, `Input.insertText`): the list follows the composition and Enter or
  ⌘+Enter while composing neither picks nor sends
- send → "Used this time" lists the post and "Photo A · in the post"; "Photo B" is under Not used with the free-writer reason
- a handcrafted MP4 goes through begin → PUT → commit and its chip shows "No preview in this browser"
- phone: the first search result is inside `visualViewport`, no horizontal overflow, the textbox is at least 16 px

## Manual device checklist (not automatable here; record date, device, OS and result)

| Check | Device | Result |
|---|---|---|
| `@` list with Cantonese Cangjie, Sucheng, handwriting, Pinyin and Japanese kana | iPhone Safari | not yet run |
| `@` list with Gboard | Android Chrome | not yet run |
| `@` list with Microsoft Quick and ChangJie | Windows | not yet run |
| `@` list with Pinyin | macOS | not yet run |
| HEVC `.MOV`: frames, location blanking, 100 MB upload over cellular with the screen on | iPhone | not yet run |
| HEIC photo | Android | not yet run |
| `@` list announcements | VoiceOver and TalkBack | not yet run |

These need real devices and a deployment with the chat-media flags on, which in turn needs James's permission
(SPEC §14.1): until then they are validation_unavailable.
