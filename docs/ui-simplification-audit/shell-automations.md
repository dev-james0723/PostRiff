# App shell, shared components and Automations: copy and information-density audit

Sources: `web/src/components/{layout,kbar,rafii}/*`, `web/src/config/nav-config.ts`, `web/src/hooks/use-breadcrumbs.tsx`, `web/src/app/{global-error,not-found}.tsx`, `web/src/features/automations/*`

## App shell

| Screen/component | Current copy (short) | Class | New copy / action |
|---|---|---|---|
| Sidebar nav | "Models & providers" | COMPRESS | **Models** ("provider" is implementation language); breadcrumb matches |
| Sidebar nav | "API & integrations", "Usage & plan", "Privacy & data", "Audit log" | KEEP | Unchanged (page titles, tours and tests use them; see requests below) |
| Account menu | Avatar + name + email repeated at the top of the menu | REMOVE | Shown only on the icon rail, where the trigger is just the avatar |
| Workspace switcher | "You join other workspaces by invitation." | REMOVE | Removed |
| Workspace switcher | Subtitle "Workspace" when no role is known | REMOVE | Role only when known |
| Notifications popover | "Needs your attention" | COMPRESS | **Needs attention** |
| Notifications popover | "Loading current status…" | COMPRESS | **Loading…** |
| Notifications popover | "Some status is unavailable." / "Open the Overview to retry." | COMPRESS | **Some updates couldn't load.** / "Open Overview to try again." |
| Notifications popover | "Nothing needs your attention right now." | COMPRESS | **All caught up** |
| Live island panel | "Waiting for approval" | COMPRESS | **To approve** (matches the pill's "N to approve") |
| Live island panel | "Failed in the last 24 h" | COMPRESS | **Failed (24 h)** |
| Live island panel | "Nothing waiting, publishing or scheduled." | COMPRESS | **Nothing scheduled** |
| App gate: API down | "PostRiff is temporarily unavailable" + raw error or "The API did not respond. Please try again in a moment." | COMPRESS + MOVE | **Couldn't reach Rafii** · "Check your connection and try again." · **Try again**; raw error under **Details** |
| App gate: workspace error | "Your workspace could not be loaded" + raw error + **Retry** | COMPRESS + MOVE | **Couldn't load your workspace** · **Try again** / Sign out; raw error under **Details** |
| App gate: dev mode | "Local dev workspace" + paragraph | KEEP | Dev-only, allowed as is |
| Page access fallback | "You do not have access to this page." / "Ask a workspace owner or admin for the permission this page needs." | COMPRESS | **No access** / "Ask a workspace owner or admin for access." |
| Info sidebar | Eyebrow "About this page" above the help title | REMOVE | Title only |
| Info sidebar fallback | Two long help sentences | COMPRESS | "Open the ? menu in the header for the tour and tips for this page." / "Press ⌘K (Ctrl+K) and type any page or action." |
| Info sidebar empty | "No content available" | COMPRESS | **No help for this page yet** |
| Shortcuts dialog | "Navigation shortcuts follow your current workspace permissions. Type letter sequences outside text fields." | COMPRESS | "Type letter pairs outside text fields." |
| Command palette | Subtitle "Go to X" under every page | REMOVE | Removed (the section is already "Navigation") |
| Command palette | "A two-minute walk through the app" / "Show the welcome and page tips again" | COMPRESS | "Two minutes" / "Show tips again" |
| Command palette | "No results found." | COMPRESS | **No results** |
| Filter panel (shared) | Eyebrow "Refine your view" + title "Filters & display" | REMOVE + COMPRESS | Title **Filters**; eyebrow only when a page passes one |
| Global error | "Rafii hit an unexpected error. Check your activity before retrying any publication." | COMPRESS | "If you were publishing, check your posts before trying again." (the double-publish warning stays) |
| 404 | "This page does not exist" + two sentences | COMPRESS | **Page not found** · "The link may be out of date." |

## Automations

| Screen/component | Current copy (short) | Class | New copy / action |
|---|---|---|---|
| Page header | Eyebrow "Create" + description "Rafii prepares drafts on your schedule… Every draft waits for your review." | REMOVE | Title **Automations** + **New automation** |
| Page header action | "New automation" shown next to the empty state's identical button | MOVE | Header action appears only once automations exist |
| Summary | Four glass tiles, each with a sub-sentence ("All running", "Waiting for the owner", "From 2 runs not opened yet"…) | REMOVE (structure) | One quiet strip: Active · Needs you · To review · Next run · Spent this month · Monthly limit (with InfoTip) · Usage link; zero counts hidden |
| Budget panel | "Spent this month: $X. Active automations can spend at most $Y in a month (a countdown counts in full)." | MOVE | Folded into the summary strip; the countdown rule moved to an InfoTip |
| Empty state | "No automations yet" + "Tell Rafii what to prepare, when and for which accounts…" | COMPRESS | **No automations yet** · **New automation** |
| Briefs section | "Briefs without a schedule" + explanation paragraph · "Schedule it" | COMPRESS | **Unscheduled briefs** · **Schedule** (accessible name includes the brief); audience hidden on mobile |
| Card facts | Where · What · Writer (+ spend) · Publishing (+ detail) · Each run · Research and writing · Next run (+ ceiling) | MOVE | Visible: Where · What · Next run · Budget (per-run limit, monthly ceiling, spent) · Publishing (label + InfoTip). Writer, stage rules and research moved into **Details** |
| Card policy paragraph | "Nothing publishes without an approval: each post waits until someone who can approve posts approves that exact draft." (repeats the Publishing fact) | REMOVE | Publishing fact + InfoTip; waiting posts become a **N to approve** chip in the header |
| Card held-back list | "{platform} held back for your approval: {reason}" | COMPRESS | "{platform} held for approval: {reason}" |
| Card status details | "Waiting for the workspace owner to activate it.", "Paused: none of its accounts is connected. Edit it to choose new destinations.", "It resumes on its own then. An owner can resume it sooner." | COMPRESS | "An owner activates it.", "No connected accounts. Edit it to choose new ones.", "Resumes on its own. An owner can resume it sooner." |
| Card email switch | "Email me when its drafts are ready" | COMPRESS | "Email me when drafts are ready" (accessible name keeps the automation name) |
| Run history row | "Following up a Threads post from …: 12 replies vs a typical 3." / "…: no longer connected." | COMPRESS | "After a strong Threads post: 12 replies vs 3 typical." / "…: disconnected." |
| Run text (`runText`) | "Writing now", "The writer was unavailable, so no drafts were made.", "The run was more than a day late, so it was skipped." | COMPRESS | "Drafting", "Writer unavailable, so no drafts.", "Over a day late, so skipped." |
| Trigger summary | "When you add a new idea or link to Ideas · …" / "After a post gets more replies or comments than usual (last 7 days) · …" | COMPRESS | "New idea or link in Ideas · …" / "After a strong post (last 7 days) · …" |
| Ceiling text | "up to 5 runs a month · at most $0.50 a month" | KEEP | Money wording unchanged |
| Toasts | "Automation active. Each post waits for your approval.", "Automation paused.", "Automation resumed.", "Marked as seen.", "You will get an email…" | REMOVE | Silent: the card's chip or switch shows the result |
| Toasts | "Automation cancelled. No further drafts will be prepared." / builder save toasts | COMPRESS | "Automation cancelled" / "Saved as draft" / "Automation active" (the card moves or the dialog closes) |
| Cancel confirm | Eyebrow + "No further drafts will be prepared. Drafts it already made stay… cannot be restarted; create a new one instead." | COMPRESS | "No more drafts will be prepared, and it can't be restarted. Drafts it already made stay." Kept as a confirmation (irreversible) |
| Pause | No confirmation | KEEP | Harmless and reversible |
| Auto-publish confirm | Long intro; "You can pause or change it at any time. Editing it returns it to draft until an owner activates it again." | COMPRESS | Intro keeps what is held back and why; footnote "Pause it any time. Editing returns it to draft." Consent checkboxes unchanged |
| Builder header | Eyebrow "Automations" + "Rafii prepares drafts on your schedule. Nothing publishes: every draft waits for your review." | REMOVE | **New automation** / **Edit automation**; workflow automations show only the policy label |
| Builder: What | Hints under Name, brief, voice switch, content type, event fields, sources | REMOVE / MOVE | Name: none. Brief: InfoTip ("read as text, not settings"). Voice: InfoTip. Content type: label only. Event date/venue: hint only when missing ("Needed to activate."). Sources: "Only ticked sources are read." Recent posts: "Reads up to 10 posts from the 31 days before each run." |
| Builder: When | Paragraphs on triggers, strong posts, daily limit, missed runs, fixed schedules | COMPRESS / MOVE | One short line each; strong-post method in an InfoTip; the late-run rule moved to the info sidebar |
| Builder: Where | "Each account gets its own draft in each of its languages…" | REMOVE | The "N drafts each run" count shows it |
| Builder: Where | "No longer connected: remove it or reconnect it on Channels." | COMPRESS | "Disconnected. Remove it or reconnect on Channels." (`STATUS.disconnected`) |
| Builder: Review | "The brief and the ticked sources are sent to this writer's provider on every run." | COMPRESS | "Each run sends the brief and ticked sources to this cloud writer." (privacy fact kept, "provider" removed) |
| Builder: Review | "Charges come from your workspace credits, the same as drafting on Home." | COMPRESS | "Paid from workspace credits." |
| Builder: Review | Closing paragraph "Activating lets Rafii prepare drafts… Every draft still needs your review and approval…" | COMPRESS | "Every draft waits for your approval before anything is published." / "Saves a draft. An owner activates it." + "Editing anything but the name returns it to draft." |
| Builder: Review | Auto-publish hint repeating the policy detail | REMOVE | Policy detail shown once above |
| Run item lines | "Approve before X to publish then. Nothing publishes without an approval.", "Scheduled for X.", "Publishing now.", "Skipped." | COMPRESS / REMOVE | "Approve by X to publish.", "Publishes X."; lines that repeat the status chip are dropped, and so is the empty paragraph |
| Run decision dialog | Long intros, "…facts fingerprint…", done toasts with sentences | COMPRESS | "…Rafii rechecks the account first and won't post if anything changed.", "This browser can't verify the sources for this approval.", toasts "Approved" / "Changes requested" / "Rejected". Exact-text and consent content unchanged |
| Policy words (`workflow.ts`) | "…Silence never approves." / "Rafii prepares drafts; nothing is published. Schedule the ones you like yourself." | COMPRESS | "Nothing publishes until someone approves that exact draft." / "Nothing is published. Schedule the drafts you like yourself." |
| Chat automation card | Pause toast; "Automation cancelled. Nothing more will be drafted."; "An owner of this workspace turns it on in Automations." | REMOVE / COMPRESS | No pause toast; "Automation cancelled"; "An owner turns it on in Automations." |
| Lifecycle labels (`automation-lifecycle.ts`) | "Ready for review", "Changes requested", "Account disconnected"… | KEEP | Must match `tests/fixtures/automation_lifecycle.json` and `lifecycle.py` (server parity); see note |

## Structural changes

- Automations: the four summary tiles and the budget panel became one quiet summary strip, with zero counts hidden.
- Automation card: the facts went from seven to five (Where, What, Next run, Budget, Publishing). Writer, stage rules and research moved into a **Details** collapsible. The policy paragraph that repeated the Publishing fact is gone, and waiting approvals show as a header chip.
- Automations header: the "New automation" button hides while the empty state carries the same action.
- Builder: explanations under controls became InfoTips (brief, voice, strong post) or were dropped, and the header intro is gone. The shared `Field` gained an optional `tip`.
- App gate: errors lead with what happened and what to do. Raw error text sits in a **Details** disclosure in the action row.
- The page and shell loading skeletons dropped the description placeholder line, so there is no layout jump for pages without descriptions.
- FilterPanel (shared): the eyebrow renders only when a caller passes one, and the default title is now "Filters". The API is unchanged.
- Account menu: the profile header repeats only on the icon rail.

## Note on lifecycle labels

`LABELS` in `automation-lifecycle.ts` is asserted deep-equal against the shared fixture that `lifecycle.py` also reads. It can't import `STATUS` either, because the node:test loader has no path aliases. The shared words already match `STATUS` (Approved, Scheduled, Publishing, Published, Failed, Changes requested). "Ready for review" versus `STATUS.needsReview` ("Needs review") would need a server and fixture change.
