# A066 — real iPhone Safari smoke procedure (requires James's device)

Desktop WebKit (Playwright) is recorded separately and does not satisfy this case. Use synthetic test files only. Do not open personal Library items while recording.

## Setup (coordinator)
1. The candidate dev pair runs on the Mac with `--library-intelligence`, bound to the LAN for this test only. The coordinator records the exact candidate SHA and the LAN URL in `iphone-smoke-receipt.md` and stops the servers afterwards.
2. The harness is seeded with synthetic assets:
   - an MP3/WAV interview clip
   - a PDF, a DOCX and an image
   - more than 30 filler items, so scrolling and bottom-bar clearance can be observed
3. The iPhone and the Mac must be on the same Wi-Fi network. No tunnel or public URL is used.

## Steps on the iPhone (record device model, iOS version, Safari version)
1. Open the LAN URL in Safari and sign in with the dev identity.
2. Open Library. Without scrolling, confirm that at least one asset preview and title is visible (A059).
3. Tap **Add → Upload files**, then choose a synthetic file from Files/Photos. Confirm that progress, then a processed state, appears and that a failure, if any, is explained.
4. Search for a word from the PDF. Confirm the result shows a passage and a "why it matched" reason.
5. Open the audio item. Confirm it does **not** autoplay. Tap Play, seek to about the middle, pause and tap **Save moment**. Close the detail drawer by swiping and confirm it reopens with focus restored.
6. Long-press or use the selection control to select two items. Confirm the batch bar appears and that neither the tab bar nor the Now Playing bar covers it or the last result. Rotate to landscape and check again.
7. Open an item, navigate to a draft through **Use in draft**, then press Back. Confirm the query, filters, selection and scroll position are restored.
8. Turn on Settings → Accessibility → Motion → Reduce Motion, reload Library, and confirm transitions are minimal.

## Evidence to keep
- A short screen recording (iOS Control Centre), or one screenshot per step.
- Device model, iOS version, date/time and the candidate SHA shown in the receipt.
- Pass or fail per step. Any failed step keeps A066 FAILED until it is fixed and re-run on the same candidate.
