# Discord hourly ceiling: UI evidence

Screenshots taken by the browser harness (`web/tests/discord-sender-name-browser.cjs`, group `ceiling`) against the running
app with synthetic API answers only: the synthetic server answers an approval with the contract's refusal (HTTP 409, code
`discord_workspace_hourly_ceiling`, `limit` 300, `windowSeconds` 3600, no retry field) and never approves anything. No Discord,
no Production, no real workspace. Chromium 141.0.7390.37, reduced motion, light scheme.

Each picture is the surface itself (a dialog, or the post card), cropped by the harness; the dev server's own overlays are
hidden. The names are `<locale>-<width>-ceiling-<surface>.png`; every surface exists for the four locale and width runs the
harness makes (`en-1280`, `en-390`, `zh-Hant-390`, `zh-Hans-1280`), so 20 pictures.

| Surface | What the picture shows | Contract row |
| --- | --- | --- |
| `ceiling-single-dialog` | The explanation after one approval from a Queue card was refused: title, the rule with its number, "Nothing was approved. This post is still waiting for your approval.", the move sentence, "Choose another time", "See the posts in that hour", Close. | Approve a prepared review (`p2_approve`); the Queue move ends here |
| `ceiling-bulk-notice` | The bulk approval dialog after the whole batch was refused: the notice ("No post was approved, and your selection is unchanged"), the same three posts still listed, a Remove button on each, the approve button disabled. | Approve up to 10 reviews (`p2_approve_many`) |
| `ceiling-reply-notice` | The reply review dialog after the approval was refused: the notice inside the dialog, "Choose another time" and "See the posts in that hour"; the approve button disabled. | Approve a Discord reply |
| `ceiling-decision-notice` | The automation decision dialog after the approval was refused: the notice with "See the posts in that hour" (no "Choose another time": an automation post takes its time from its schedule); the post stays ready for review. | Approve an automation post (`raffi_run_decide`) |
| `ceiling-run-card` | The post card of a post the scheduler could not queue ("It couldn't be queued: ..." from the server, said in the person's language) with "Choose another time" (opens the kept draft) and "See the posts in that hour". | Queue commit of an approved automation post (`raffi_run_commit`) |

Not in these pictures: the answer to a refusal with another code (a toast with the server's words, as before; the cases check it
without a picture), the flash of the approve button ("Hour is full"), and any real device. The Calendar link goes to the day of
the post: the Calendar has no per-hour view.

How to take them again: start the app as the harness does, then
`RAFII_EVIDENCE_DIR=<folder> RAFII_SENDER_CASES=ceiling node web/tests/discord-sender-name-browser.cjs` with `CI=true` and
`RAFII_DISCORD_SYNTHETIC_FENCE=1` (the fixture `.depot/discord-p0-ui.json` comes from `tests/discord_ui_fixture.py`). A
narrowed run says in its receipt that it is not evidence of the whole suite.
