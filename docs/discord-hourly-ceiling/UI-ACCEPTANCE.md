# Discord hourly ceiling: UI acceptance

Branch `claude/discord-rc2-sendername-ui-20261023`, 2026-10-28, on top of `6cfb2b78`. Written against `docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md` as it is on `origin/claude/discord-rc2-g2a-fixes-20261023` at `217a2c8f` (owner decision, reply 16, D-4); that branch is not merged here. Author: web/UI engineer.

## 1. What this is

A workspace may have at most 300 approved Discord posts scheduled within any one hour. The approval that would make the 301st is refused with HTTP 409, code `discord_workspace_hourly_ceiling`, body `{error, code, limit, windowSeconds}`, and no retry field. This note says what the web shows at each place a person meets that refusal, how it was checked, and what could not be built. It is checked against synthetic answers only; the real server was not involved. **It does not say the feature passes as a whole.**

## 2. Summary

| Check | Result |
| --- | --- |
| New web unit tests (`web/tests/discord-hourly-ceiling.test.cjs`) | 19 of 19 pass |
| All Discord node tests (`node --test tests/discord-*.test.cjs`) | 85 of 85 pass (66 before this change; the sender-name file is still 39) |
| Contract pin | the exported constant equals the contract's `limit`, the fixture equals the contract's JSON block, and the English copy equals its suggested copy word for word; the contract text was read from `origin/claude/discord-rc2-g2a-fixes-20261023` (`git show`), because this tree does not have the file. Once the fixes branch is merged the same test reads the file from the tree. If the file is in neither place the comparison skips with a message and the fixture still pins the number |
| Type check (`tsc --noEmit`) / lint (`oxlint src`) | exit 0 / 0 errors, 37 warnings (the baseline count) |
| Copy audit (`node scripts/copy-audit.mjs --check`) | 0 banned phrases; nothing new in the review list |
| Browser acceptance (`web/tests/discord-sender-name-browser.cjs`, synthetic API, Chromium 141.0.7390.37) | pass: 4 runs (en-1280, en-390, zh-Hant-390, zh-Hans-1280) of 98 cases each (86 before; 12 new `ceiling-*` cases), plus 6 once-per-run cases (5 before; `axe-ceiling` is new); about 19 minutes |
| Test helper | `web/tests/discord-sender-name-load.cjs` now resolves an extensionless request to the `.ts` file before a `.json` of the same name, as webpack and tsc do (node did not, so `./discord-copy` loaded the JSON). The 39 sender-name tests still pass |
| Offline secret scan | 0 findings in every file added or changed (scanned file by file before the push) |

## 3. Where a person meets it, and what the web does

All text is in the three locales (en, zh-Hant, zh-Hans) of `discord-copy.json`, keyed on `code`; the server's English `error` is the fallback for any other code. The number comes from the response's own `limit` when it carries one (`ApiError.body`), else from the one exported constant `WORKSPACE_HOURLY_CEILING = 300` in `discord-copy.ts`. Nothing counts down, nothing retries by itself, and no button sends the refused request again.

| Contract row | What the person sees | After it | Browser cases (all 4 runs) | Evidence (`ui-evidence/`) |
| --- | --- | --- | --- | --- |
| Approve a prepared review (`p2_approve`): the Queue card (browser-tested); the Pipeline sheet and the site agent's prepared review use the same button | A dialog: "That hour is full", the rule with its number, "Nothing was approved. This post is still waiting for your approval.", "Moving a post? The earlier time is already cancelled. This new time is still waiting for your approval.", then "Choose another time" (the draft in Drafts), "See the posts in that hour" (the Calendar day of the post) and Close. Closing returns the keyboard to the approve button | The review is untouched and the card stays; nothing was approved and no second request is made | `ceiling-single-dialog`, `ceiling-single-uses-server-limit`, `ceiling-single-unknown-code` | `*-ceiling-single-dialog.png` |
| Approve up to 10 reviews (`p2_approve_many`): "Approve all N" in the Queue | A notice at the top of the dialog (heading focused): the rule, "No post was approved, and your selection is unchanged. Remove some posts from it, then approve the rest.", "See the scheduled posts" (the Calendar day of the earliest post: the response does not say which hour crossed). The same posts stay listed, each with Remove; the approve button is off for that exact selection | Taking a post out is a new question: the notice goes, the approve button is back (and focused), the next request carries only the posts left; the last post cannot be removed; closing and reopening starts from the whole batch | `ceiling-bulk-keeps-selection`, `ceiling-bulk-remove-then-approve`, `ceiling-bulk-unknown-code` | `*-ceiling-bulk-notice.png` |
| Approve an automation post (`raffi_run_decide`, approve): the decision dialog on the run's post card | The same notice inside the dialog: "Nothing was approved. This post is still ready for review." and "See the posts in that hour". No "Choose another time": an automation post takes its time from its schedule | The dialog stays open; the post stays "Ready for review"; the approve button is off until the dialog is reopened | `ceiling-decision-dialog`, `ceiling-decision-unknown-code` | `*-ceiling-decision-notice.png` |
| Queue commit by the scheduler (`raffi_run_commit`): no request from the UI | The card of the failed post says it in the person's language: "It couldn't be queued: that hour is full. A workspace can have at most N approved Discord posts in any one hour. The approved draft is kept. Approve it again for another hour." with "Choose another time" (opens the kept draft) and "See the posts in that hour". Any other reason is shown exactly as the server wrote it | State "Failed"; the draft is kept | `ceiling-run-card-text` | `*-ceiling-run-card.png` |
| Approve a Discord reply (engagement): the reply review dialog | The notice inside the review dialog: "The reply was not approved. It is still waiting for your approval.", "Choose another time" (closes the review and puts the keyboard on the reply form's time field), "See the posts in that hour" | The review stays open and unchanged; its approve button is off; a new review (another time) can be approved | `ceiling-reply-dialog`, `ceiling-reply-unknown-code` | `*-ceiling-reply-notice.png` |
| Move a post (cancel, new review, approve): the Queue | The approve step above. The web has no Move action, so the "Moving a post? ..." sentence is part of every single-approve refusal | The old post stays cancelled, as the server does it | covered by `ceiling-single-dialog` | `*-ceiling-single-dialog.png` |

The cases also check, where each applies: no horizontal overflow at 390 and 1280 px, 44 px targets for each new action, no retry or countdown wording or elements in the refusal, no toast for the ceiling, exactly one request per press (and still one 1.5 seconds later), the request body, and that a refusal with another code keeps its old path (toast with the server's words and "Reload" for the Queue; the bulk and decision buttons stay usable; the reply panel shows the message at its top). `ceiling-no-page-errors` fails the run on an uncaught error or a React warning on these surfaces. `axe-ceiling` runs WCAG 2 A and AA on the five surfaces (English, 1280 px).

## 4. Decisions

- **A dialog, not a toast, for one approval.** The approve button sits in cards of three layouts, and a message with two actions that must be read should not disappear. The dialog is portaled, so no card layout changes.
- **The same selection is not offered again.** After a refusal the bulk and decision buttons are off and the reply review's approve button is off: the same request would get the same answer. A change (a post removed, a new review) turns them on. A single approval keeps its normal button, because the person may have changed the plan in another tab.
- **The number.** One exported constant, `WORKSPACE_HOURLY_CEILING = 300`, as asked; no other file writes it (a test checks the sources and the copy). The refusal's own `limit` wins when present, because the contract says the owner may change it.

## 5. What the contract does not let me build, and what I would ask for

1. **The hour.** The 409 body names no hour, and the Calendar has no per-hour view, so "See the posts in that hour" opens the Calendar day of the post being approved (for a bulk approval, of the earliest post). A `windowStart` in the body would let the link and the text name the hour.
2. **Which post crossed.** The bulk response does not say (by design), so Remove is offered on every row and the person tries again.
3. **A time for an automation post.** There is no per-post time to choose; no "Choose another time" in the decision dialog.
4. **A code on the failed post.** The scheduler stores only the English sentence in the item's `reason` (`automation_runs.py`), so the card recognises "This hour is full: a workspace can have at most N approved Discord posts" and takes N from it. If the server rewords that sentence the card falls back to the server's English text. A `reasonCode` (and `limit`) on the item would remove the matching.
5. **Move.** There is no Move action to hook, so the cancelled-old-post sentence is shown on every single-approve refusal.
6. **The agent's plan card** (`features/agent/plan.ts`, `p2_approve_many`) is not a place the contract lists; its review carries no Discord destination today, so it cannot reach the ceiling. If it could, it would show the server's English text in a toast.

## 6. Not verified, and for the owner

- Nothing here ran against the real backend, 300 real posts, Discord, or Production. The synthetic server answers with the contract's JSON body; whether the real routes render it as the contract says is the backend's test (`tests/test_discord_hourly_ceiling.py` on the fixes branch).
- Chromium only; no real phone, no Safari or Firefox. The 390 px runs are a narrow desktop viewport.
- The Chinese text was written for this change and has not been read by a native reviewer. The owner may want to read the three strings that carry the rule (`hourlyCeilingBody`, `hourlyCeilingBulkNone`, `hourlyCeilingQueueFailed`).
- The dark scheme was not checked for these surfaces (they use the app's tokens; axe ran in the light scheme).
- `web/src/lib/api/client.ts` is unchanged by this work, but on this branch it already differs from the fixes branch: `ApiError.body` (the sender-name editor reads `reason`, `reasons` and `retryAfterSeconds` from it) came with the sender-name work. The ceiling text reads `limit` from it defensively, so it still works (with 300) if `body` is gone. `destination-picker.tsx` and `publication-receipt.tsx` are untouched, and the ceiling text does not need either: it is an approval-time refusal, not a destination or a receipt.
