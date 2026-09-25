# Content pipeline: UI simplification audit

Area: ideas and composer inputs, drafts, approvals, queue, schedule, publish, calendar, library and media, post previews.
Scope: `web/src/features/{queue,pipeline,calendar,ideas,library}`, `web/src/components/{jobs,application}`, `web/src/app/app/{queue,pipeline,calendar,ideas,library}`.

## Audit

| Screen/component | Current copy (short) | Class | New copy / action |
|---|---|---|---|
| Queue header | "Drafts waiting to be scheduled, approvals waiting on you, then everything the worker is handling." | REMOVE | Title only |
| Queue info panel | 7 sections (manifest, digest, provider, reconciles, receipts…) | COMPRESS | 6 short sections in user words ("Result not confirmed", "Needs action", "Cancel") |
| Queue first run | "Nothing publishes on its own" + "three steps" + 3 step cards + 2 CTAs + account paragraph | REMOVE / restructure | One empty state: **Nothing scheduled** + one CTA (Connect account → Create post), short line only when needed |
| Queue approvals heading | "Waiting for approval" | COMPRESS | "Needs review" (`STATUS.needsReview`) |
| Review card status | raw `needs review` / `expired` | COMPRESS | `STATUS.needsReview` / `STATUS.expired` |
| Review card meta | "2026-10-01 09:00 (Europe/London) · English · 0 media · a1b2c3d4e5f6…" | COMPRESS / MOVE | Formatted time; language and media `md+` only; zone and digest in the title attribute |
| Review card notes | "This draft has no approved voice profile. Review its wording carefully before approving." | COMPRESS | "No voice profile. Check the wording before approving." |
| Review card footnote | "Approves exactly this text, media, account and time." | KEEP (public publishing) | "Approves this exact text, media, account and time." |
| Stale reviews | "N reviews went stale · the draft, voice, account or sources changed after they were prepared" | COMPRESS | "N out of date · something changed after they were prepared" (detail `md+` only) |
| Already-a-job reviews | "N reviews are already a job · the same post … schedules nothing" | COMPRESS | "N already scheduled · approving again changes nothing" |
| Queue load error | "The queue could not be loaded." + message + "Retry" | COMPRESS | "Couldn't load the queue" / "Couldn't refresh the queue" + Try again; server text as detail |
| Queue permission / sample | "Scheduling, approving and cancelling posts is for the owner, approvers and…" / "Sample workspaces are read-only." + sentence | COMPRESS | "Only approvers can schedule, approve or cancel posts." / "Sample workspace · read only" |
| Jobs section | "Publishing jobs" + "Latest worker event on a job · 3 min ago" / "No worker events recorded yet" | COMPRESS | "Posts" + "Updated 3 min ago" (`md+`, hidden when unknown) |
| Job filters | All / Waiting / In flight / Held / Verified / Ended | COMPRESS | All / Scheduled / Publishing / Needs action / Published / Ended |
| Jobs empty | "No jobs yet" + filter essay mentioning provider | COMPRESS | "Nothing scheduled" / "No scheduled posts" + Show all |
| Jobs table | State · Destination · Scheduled · Attempts · Provider · Last event | COMPRESS / REMOVE | Status · Account · Time · Attempts · Last update (Provider column removed; post ID lives in details) |
| Job row time | Exact date and countdown | COMPRESS | Relative (countdown while scheduled); exact in title and screen-reader text |
| Job row card (narrow) | "Attempts 1 / 3", last event line, "No events recorded" | MOVE | Attempts only when >1 and `md+`; last event `md+`; empty fallback removed |
| Job status badges | waiting, preparing media, accepted · checking result, published · verifying, verified · provider lookup, failed, cancelled | COMPRESS | Scheduled / Publishing / Published / Failed / Cancelled / Needs action / Result not confirmed; the reason is in the tooltip (`features/queue/job-status.ts`) |
| Failed job note | worker message as headline | MOVE | **Couldn't publish this post**; worker message in title and sr-only |
| Fixture badge | "Fixture" / "Synthetic provider; nothing reaches a real account" | COMPRESS | "Test" / "Test post; nothing reaches a real account" |
| Job row buttons | title "Timeline, attempts and what the provider confirmed"; "Open the receipt for…" | COMPRESS | title "Details"; aria "Open details for the X post" |
| Job sheet | "What was approved", "Provider", "Provider said", "Reference", "Verification", "Last worker note", "Approval digest", "Next look" | COMPRESS / REMOVE | "Approved post", "Platform", "Response", "Latest note", "Approval ID", "Next check" (relative); Verification row removed (the receipt shows it) |
| Job sheet time | Local time (zone) + "X in your time" | COMPRESS | One time; the approved zone in the title |
| Job sheet failed | "Prepare again" | COMPRESS | Headline "Couldn't publish this post" + primary **Try again** (same action); held jobs keep "Prepare again" |
| Job sheet missing | "Job not found" + "It may belong to another workspace, or the link is out of date." | COMPRESS | "Post not found" + "This link is out of date." |
| Publication receipt | "Container: … · not proof of publication", "Provider reference: …", ISO timestamp, "Publication not verified" | COMPRESS | "Upload: … · not yet published", "Post ID: …" (with copy), "Verified · method · date", "Not verified yet" |
| Hold to cancel | title "Press and hold (or hold Space) to request cancellation. A post already with the provider cannot be recalled." | COMPRESS (kept: irreversible) | "Hold to cancel (or hold Space). A post already sent can't be recalled." |
| Cancel toasts | "Cancel requested." / "Could not cancel." | REMOVE / COMPRESS | No success toast (badge shows Cancelling…); "Couldn't cancel this post" + detail |
| Approve button toasts | "Approved and scheduled." / "This exact post was already a job, so nothing new was scheduled." / "The approval was answered, but no job appeared…" / "Approval failed." | COMPRESS | "Scheduled" / "Already scheduled" + Open / "Couldn't confirm it was scheduled" + Reload / "Couldn't approve this post" + detail |
| Approve many dialog | "Approve N exact posts" + "Each one is approved with exactly … All or nothing…" + digest per row | COMPRESS (kept: public publishing confirm) | "Approve N posts?" + "Each publishes exactly as reviewed, at its time. If one can't be approved, none are."; digest and zone in the title |
| Approve many toasts | success toast for full batch; long partial explanations | REMOVE / COMPRESS | Full batch shows on the button only; "Already scheduled; nothing changed." / "2 of 3 scheduled; the rest already were." |
| Action errors (`action-error.ts`) | server message as the toast headline | MOVE | Headline says what happened; server message becomes the toast description |
| Schedule dialog description | "Choose the draft, the account and the exact time. This prepares a review; nothing publishes until you approve it." | COMPRESS (kept: public publishing) | "Nothing publishes until you approve it." |
| Schedule dialog notes | voice note, permission note, stale drafts, update waiting (2 variants), editor-blocked paragraph, account not ready paragraph, passed time, gap, fold explanation | COMPRESS / REMOVE | "No voice profile yet. Check the wording." + link · "Only approvers can schedule posts." · "N drafts use an older voice and can't be scheduled." · "Uses the updated version in your current voice." · "An editor needs to … first." · "Not ready to post (state). Open Channels" (replaces the platform-support line instead of stacking) · "Pick a future time." · "Clocks skip this time. Pick another." · fold explanation removed (label kept) |
| Schedule dialog unknowns checkbox | "Confirm the N unknowns stay out of the draft (required before review)" | COMPRESS | "Leave out the N unknown details (required)" |
| Schedule dialog placeholders | "Describe the image for people who cannot see it"; "No drafts yet — add candidates from Ideas" | COMPRESS | "Hands on piano keys under a warm light"; "No drafts yet" |
| Schedule dialog toasts | "Review prepared. Approve it in the Queue to schedule."; server error as headline; DST paragraph | COMPRESS | "Ready for review"; "Couldn't prepare this post" + detail; "This time happens twice that day. Pick one, then try again." |
| Schedule dialog rights checkbox | "I have the rights to publish this text … on this account." | KEEP (legal consent) | unchanged |
| Drafts tab column header | "Drafts N" + "Candidates you added" repeated under the "Drafts N" tab | REMOVE (visual) | Header kept for screen readers only when the column is the page |
| Drafts empty | "No drafts waiting" + 2-sentence description + "Draft a post" | COMPRESS | "No drafts yet" + **Create post** |
| Draft chips | lowercase "source retracted", "update proposed", "earlier voice", "needs review", "failed"… with long titles | COMPRESS | "Source withdrawn", "Update ready", "Older voice", "Needs review", "Failed" (title "Couldn't publish this post")… short titles |
| Draft card meta | "for Oct 1, 2026, 9:00 AM" / "scheduled for …" | COMPRESS | "posts in 3 days" (relative); exact in title |
| Column footers | "Kept, not scheduled. Edit a draft to bring it back." etc. | COMPRESS | "Edit a draft to bring it back." / "Not approved in time…" / "Ended; nothing is retried." |
| Board column meta | provider hints/empties ("Approved; the worker publishes and the provider confirms", "No provider-confirmed posts yet.") | COMPRESS | "Approved and waiting for its time", "Nothing published yet."; titles use `STATUS` |
| Edit draft dialog | "Your words, your call. Edits stay in the draft history; PostRiff learns…" + "Draft updated. Schedule it to review the exact text." | REMOVE / COMPRESS | sr-only description; toast "Draft saved"; error "Couldn't save the draft" + detail |
| Set aside dialog | 2-sentence description with Memory page; blocking paragraph; "Draft set aside. Edit it to use it again." | COMPRESS (kept: nothing deleted) | "It moves to Set aside until someone edits it. Nothing is deleted." · "Its post is scheduled. Cancel it in the Queue first." · toast "Set aside" |
| Draft detail sheet | "Text · revision N", "Exact text · revision N", "Digest", "Chosen as … (zone)", "Revision N · date", "Open the draft it came from", long review footnotes | COMPRESS / REMOVE | "Text", "Exact text", digest removed, zone in title, relative dates with exact in title, "Open draft", one-line footnotes |
| Draft detail description | "Draft · English · Drafts" (column repeats context) | COMPRESS | Kind · language, plus the footer group only when relevant |
| Calendar header | "Approved and pending publications at their exact times, in your time zone." | REMOVE | Title only |
| Calendar info panel | 4 long sections | COMPRESS | 3 short sections |
| Calendar status chips | 15 status chips, most showing 0 | REMOVE (structure) | Only states present in the period (or selected); row hidden when none |
| Calendar status labels | "Needs approval", "Review expired", "Published and verified", "Marked completed by you", "Accepted; checking result", "Canceled" | COMPRESS | "Needs review", "Expired", "Published", "Marked done", "Checking result", "Cancelled" (the `STATUS` words) |
| Calendar live note | "Checking for updates every 15 seconds while a post is going out" | COMPRESS / MOVE | "Live" (interval in the title) |
| Calendar popover notes | expired / stale / assisted / manual ("not verified by the provider API") / fixture / uncertain / held paragraphs; "Receipt: <id>" | COMPRESS / REMOVE | One short line each ("Not approved in time. Schedule the draft again."…); failed leads with **Couldn't publish this post** and its link reads **Try again**; receipt ID removed (it is in the job details) |
| Calendar empty | "Nothing scheduled yet" + 2-sentence essay + "Go to Ideas" + "Connect a channel" | COMPRESS | **Nothing scheduled** + one CTA: Connect account (no accounts) or **Create post** (no drafts) |
| Calendar misc | "New post", "Open the queue", "The workspace could not be read." | COMPRESS | "Create post", "Open Queue", fallback detail removed |
| Ideas header | "Capture a thought, paste text or add a link. Approve the facts…" | REMOVE | Title + counts |
| Ideas reminders | "Web research is switched off on this deployment" + description | REMOVE | Hidden: the capability is unavailable everywhere, so it is not mentioned |
| Ideas reminders | "Web research is off for this workspace" + 2 sentences; "Set up your voice first" + sentence; "No writing batches left this period" + sentence | COMPRESS | "Web research is off" + "Drafts use only the sources you add." · "Set up your voice to schedule drafts" · "No writing batches left" + "Resets …" |
| Ideas info panel | "Leaving this server" section, "Switched off on this deployment…", long cost line | COMPRESS | "Privacy" (kept: what a cloud model reads, and that local routes read without the switch), web research section hidden when unavailable, short cost line |
| Ideas errors / permission | "Your sources could not be loaded." + Retry; "You need the edit permission to add sources." + sentence | COMPRESS | "Couldn't load your sources" + Try again; "Only editors can add sources." |
| Capture card | "Saving keeps it here. Nothing is drafted, sent to a model or published until you ask." | REMOVE (defensive) | Heading only |
| Capture card helpers | text placeholder teaches facts; "Title (optional) · Pasted source"; "Saved as an unverified reference: the page itself is not read when you save."; file label sentence; footer "Draft now opens a conversation · model · for dest · N writing batches left" | COMPRESS / MOVE | "Paste notes, an excerpt or a transcript"; "Title (optional)"; "Saved as a reference; the page isn't read."; ".txt or .md, up to 20 KB"; footer "model · destination" (`sm+`), batches in the title |
| Capture card toasts | long file errors; "That source is already here. It is open for review." | COMPRESS | "Only .txt and .md files", "X is over 20 KB", "X isn't plain text", "Already saved; opened it." |
| Source list | empty-state essay; "The other filters still hold your sources."; row metadata (cloud, host, used in) | COMPRESS / MOVE | "Nothing captured yet"; no filter description; cloud, host and "Used in N" are `md+` |
| Source inspector cloud switch | "· no cloud model on this deployment"; 2-line explanation under the switch | COMPRESS / MOVE | "· not available yet"; one visible line ("Cloud models may / don't read its approved facts."), the rest in an InfoTip (privacy kept) |
| Source inspector public use | "Approved for the current facts" / "Needed before a draft from it can be scheduled" / long notes | COMPRESS | "Approved" / "Needs review" (reason in the title); "Facts changed since the last approval."; "Covers saved facts only." |
| Source inspector public-use confirm | alert dialog | KEEP (public publishing), COMPRESS | "Drafts may publish rewritten versions of these N facts… Changing the facts needs a new approval." |
| Source inspector reminders & toasts | 5 reminder variants (2 repeat the select); success toasts for switch, policy, public use | REMOVE / COMPRESS | 3 reminders that add a fact; no success toasts where the control shows the state; "Source withdrawn" + impact as the detail |
| Source inspector misc | "Read time not recorded", "No draft is blocked by it.", "Not used in any draft yet." | REMOVE / COMPRESS | Omitted when empty; "Not used yet" |
| Library header | "Images for your posts. Private to this workspace; each one is stored with its hash…" | REMOVE | Title + Upload images |
| Library storage state | "Private media storage is not configured for this deployment" + server text | COMPRESS | "Media uploads aren't available yet." (inline, no detail) |
| Library upload blocker | "Uploads stopped because the workspace was unavailable" / "The workspace refused the upload" | COMPRESS | "Couldn't upload" + short detail |
| Library empty | "No images yet" + 3-sentence spec + Upload + "or drop files anywhere on this page" + "Open Ideas" | COMPRESS | "No images yet" + **Upload images** (drop hint in the title); non-editors: "Only editors can upload images." |
| Library footer notes | 3 paragraphs (no timestamps, "Used" definition, plan storage "not measured yet") | REMOVE / MOVE | Removed; "Used" definition moved to the info panel |
| Library search / count | "Hash or size, e.g. 1080x1350"; "N images · 3 MB (2 without a size)" | COMPRESS | Placeholder "1080x1350" (label keeps context); bytes `md+`, unknown count in the title |
| Library no-match | explanatory descriptions | REMOVE | Title + Clear search / Show all |
| Upload tray badges | waiting, reading, sending, uploaded, failed, not sent | COMPRESS | Waiting, Reading, Uploading, Uploaded, Failed, Not sent |
| Delete image dialog | "Its bytes are removed from private storage. Posts that already published keep what…" | COMPRESS (kept: destructive) | "This permanently deletes the image. Scheduled posts using it will need a new review; published posts aren't affected." |
| Library toasts | "Image deleted."; "Hash copied." | REMOVE / COMPRESS | No delete toast (card leaves); "Copied" / "Couldn't copy"; delete error "Couldn't delete this image" + detail |
| Asset detail | "Provenance", "JPEG, re-encoded on upload with metadata removed", Decoder row, hash explainer paragraph, "Counts posts in every state…", "Every post with an image also needs alt text…", "Use in a post opens scheduling… hash starts with…", footer "Copy hash" | COMPRESS / REMOVE | "Details", "JPEG · metadata removed", Decoder and explainers removed, footer Copy hash removed (each hash row keeps its copy button) |
| Asset detail uses | "waiting for approval", "provider accepted", "Review · publish time Oct 1…" | COMPRESS | `STATUS` words; relative time with exact in the title |
| Asset detail errors | "The image file is not in private storage"; "Private media storage is not configured" | COMPRESS | "Image file missing"; "Previews aren't available yet" |
| Expanded preview dialog | default intro "How X's post might sit inside Y. Switch apps to compare." | REMOVE | Title only (callers can still pass a description); "Illustrative layout, not a published post." kept |
| Asset picker | "The Library has no images yet." / "N images in the Library" | COMPRESS | "No images yet" / "N images" |

## Structural changes

- **Queue first run:** a centred teaching panel with three step cards and two or three CTAs became one `StateMessage` ("Nothing scheduled") with one context-aware CTA. It keeps both tour anchors (`queue-approvals`, `queue-list`).
- **Shared job status words:** added `features/queue/job-status.ts` (`jobStatus`). It maps `lib/jobs` groups onto `STATUS` (Scheduled, Publishing, Published, Failed, Needs review…). The Queue rows, job sheet, "already scheduled" list and Drafts cards all use it. Filters, calendar kinds and library uses now use the same words.
- **Errors:** `reportActionError` and `useActError` now show what happened as the headline ("Couldn't cancel this post", "Couldn't approve this post"). The server's own text moves into the toast description. Failed jobs lead with "Couldn't publish this post" in the row, sheet and calendar popover. The sheet offers **Try again** (the existing Prepare again action).
- **Duplicate data removed:** the Provider table column, the job sheet's Verification and Reference rows (the receipt shows them; its post ID now has a copy button through a new optional `referenceAction` prop), the asset detail's footer Copy hash, the review digest in cards and details, and the Drafts column header that repeated the Drafts tab.
- **Dates:** one representation on cards and rows. Relative by default (countdowns for scheduled posts), with the exact time in `title` and, in job rows, in sr-only text.
- **Calendar legend:** status chips render only for states present in the period (or selected). Previously 15 chips showed, mostly zeros. The row hides when empty.
- **Mobile:** below `md` the Queue hides language, media and review times, the disclosure detail, attempts and the last event line. It also hides source-list cloud, host and usage metadata, library byte totals, and the capture and inspector model lines.
- **Toasts:** removed success toasts where the UI already shows the result: cancel, full batch approve, source policy, cloud switch, public use approval, image delete. The remaining ones are "Saved"-length.
- **Library:** removed the three footnote paragraphs and the unused `useUsage` read that only fed the "storage not measured" note. The empty state has one CTA.
- **Ideas:** the "Web research is switched off on this deployment" reminder and info section are hidden when research is unavailable. The cloud-switch explanation moved into an InfoTip, with one visible line kept.

## Intentionally kept (and why)

- Rights confirmation checkbox in Schedule (legal consent) and "Nothing publishes until you approve it." (public publishing).
- Approve-many dialog, public-use alert dialog and delete-image dialog: consequential or public actions. The copy is shorter, but they still say what they do and that it is all-or-nothing, permanent or public.
- "Approve & schedule" and "Hold to cancel" labels, plus the irreversibility note on hold-to-cancel.
- "Result not confirmed" as its own label, not folded into Publishing: it is an important error and must never look like progress. `tests/publishing-status.test.mjs` also asserts it.
- The Privacy section in the Ideas info panel: it explains what a cloud model can read.
- Hash rows (Stored and Source hash with copy) in asset details, and the Approval ID in job details: these are detail surfaces people open on purpose.
