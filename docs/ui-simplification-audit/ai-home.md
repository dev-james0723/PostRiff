# Raffi AI (Home, chat, composer, voice, images, planning, overview): copy and density audit

Routes: `/app` (Home), `/app/agent/[id]` (chat), `/app/overview`. Source: `web/src/features/agent/**`, `web/src/features/overview/**`, `web/src/components/agents/**`.

| Screen/component | Current copy (short) | Class | New copy / action |
|---|---|---|---|
| Home hero | Eyebrow "A little idea. A bigger reach." | REMOVE | Nothing; the heading carries the page |
| Home hero | "What's the idea, James?" | KEEP | Unchanged (asserted by tests) |
| Home hero | "Give it a thought. Rafii drafts one version per destination, in your voice, for your review." | REMOVE | The composer shows this in use |
| Composer placeholder | "Drop a thought, a link, or a beautifully messy idea…" | COMPRESS | "Launch post for my new course" (shows the input) |
| Composer placeholder (template) | "<Template>: replace the brackets and send." | COMPRESS | "<Template>…" |
| Composer topline | Eyebrow "A new draft" + "Expand writing space" | REMOVE / COMPRESS | Button "Expand" (accessible name "Expand writing space") |
| Composer counter | "123 / 20,000" always shown | MOVE | Only shown past 80% of the limit |
| Composer help | "Writing your drafts. Nothing publishes without your approval." | COMPRESS | "Writing your drafts…" |
| Composer help | "Start with an idea. We'll take it from there." / "Choose at least one destination." | COMPRESS | "Add an idea to start." / "Choose a channel." |
| Composer help | "3 drafts · one per destination and language · ⌘↵ to send" | COMPRESS | "3 drafts · ⌘↵ to send" |
| Composer help | "Image generation is not available on this route." | COMPRESS | "Image generation isn't available yet." (API detail wins when present) |
| Composer image toggle | Title "Checking the managed image route…" | COMPRESS | "Checking…"; label stays **Generate image** (Example E) |
| Composer consent | "Use this text to draft with" / "My own writing (may be quoted publicly)" | KEEP | Consent wording, unchanged |
| Composer assurance | "Your approval. Always. Nothing publishes here." | REMOVE | Defensive; approval is enforced by the Queue |
| Composer (read-only) | "You need the edit permission to draft in this workspace." | COMPRESS | StateMessage "Viewing only." + "Ask an owner for edit access." |
| Model setting | "Claude Code · sonnet · High reasoning" | COMPRESS | "Claude Code · sonnet · High"; "High reasoning" in tooltip |
| Starting points | "A little nudge?" + "Behind the scenes / Something I learned / Research a topic / Plan the week" | REMOVE / COMPRESS | Example requests: "A behind-the-scenes post", "What I learned this week", "Research posting cadence", "Plan this week's posts" |
| Quick starts | "More kinds of post" + "Eleven kinds people actually publish. Pick one, replace the brackets, send." | COMPRESS | "More kinds of post" |
| Quick start cards | Title + explanation + "Usually: …" | MOVE | Title + 2-line explanation; "Usually" in tooltip |
| Template row | "Selects the "X" content type and its checks for this draft." | REMOVE | Badge + Clear (aria "Clear template") |
| Status links | "Voice · rev 3" / "not set up" | COMPRESS | "Voice · Active" (`STATUS.active`, revision in tooltip) / "Not set up" |
| Status links | "Rafii noticed 2 · review" | COMPRESS | "2 to review" (accessible name keeps the full sentence) |
| Recent conversations | "No conversations yet. Your first message starts one." | COMPRESS | "No conversations yet." |
| Recent conversations | Relative time | KEEP | Exact date/time in tooltip |
| Home info popover | 3 paragraphs (destinations, proposals, sources) | COMPRESS | "One draft per account" / "You approve everything" / "Only the sources you pick", one short line each |
| Platform-only dialog | "No account is connected yet, so drafts are written per platform. Connect an account to choose real destinations." | COMPRESS | "No accounts connected. Drafts only." |
| Platform-only dialog row | "No account connected · drafts only" | COMPRESS | "Drafts only" |
| Voice dialog | Intro "Which writing the drafts should sound like. Nothing here changes your languages, model or destinations." | REMOVE | Title only |
| Voice dialog | Neutral: "Clear and natural. Writes from your idea and sources without your writing samples." | COMPRESS | "Clear and natural. Doesn't use your writing samples." |
| Voice dialog | Personalized: "Uses the 3 writing samples you approved for X." / "No writing samples are approved for X yet. Add and allow samples on the Brand page." | COMPRESS (consent kept) | "Uses 3 samples you approved for X." / "No samples approved for X yet." |
| Voice dialog | "Voice profile revision 3 is active for approvals." | MOVE | Tooltip on "Manage voice and samples" |
| Expanded idea dialog | "Stretch out. Everything you type here is already in the composer." / "Use this draft" | REMOVE / COMPRESS | No intro / "Done" |
| Context pocket | Intro "Choose which of your usable sources the next drafts may read. Public quoting is decided per source, never here." | COMPRESS | "Pick what the next drafts may read." |
| Context pocket | Empty "No usable sources yet." + "Add a note below, or bring sources in on the Ideas page." | COMPRESS | "No sources yet" (Add a note is right below) |
| Context pocket row | Source kind + policy | COMPRESS | Policy only ("May be quoted publicly" etc., privacy kept); kind in tooltip; "Policy not set" becomes "Quoting not set" |
| Context pocket note | Placeholder "A brand detail, an idea, something to remember…" | COMPRESS | "The course launches on 3 March" |
| Context pocket note | "Saved as a private source. Public quoting stays off until you decide it on the Ideas page." | COMPRESS (privacy kept) | "Saved privately. Never quoted publicly unless you allow it." |
| Context pocket link | "Manage sources, facts and quoting permissions" | COMPRESS | "Manage sources" |
| Idle preview | Eyebrow "03 / The idea splits" + "One thought. Everywhere, still you." | REMOVE | Visually hidden heading "Preview" |
| Idle preview | "Swipe left or right, or tap a destination. An illustrative layout: no account is contacted and nothing is published." | COMPRESS | "Preview only" |
| Idle preview caption | "English · iPhone preview · sample text" | COMPRESS | "English · Sample" |
| Idle preview empty | "Choose where this idea should go." + "Pick accounts in the channel picker and the preview follows." | COMPRESS | "Choose a channel" |
| Results header | Eyebrow "The idea splits" + "Your idea, unfolded." | COMPRESS | "Drafts" |
| Results status | "Nothing was drafted." above "The drafts could not be started." | REMOVE (duplicate) | Only the error: "Couldn't start the drafts" + Try again |
| Results | "App-layout mockup, not a screenshot or a published post." | REMOVE | Expand button only |
| Results editor | "Updates live" | REMOVE | State shown only when it changes: "Edited · not saved" / "Saved" |
| Results loading | "Shaping your drafts" + "One draft per destination. This is a real run; cancel any time." | COMPRESS | "Writing your drafts…" (Cancel button already present) |
| Results failure | "The run did not complete." + "Draft again" | COMPRESS | "Couldn't finish the drafts" + "Try again" |
| Results saved | "Open drafts" + "Review in Queue" | REMOVE (duplicate) | One link: "Open drafts" |
| Results saved | "Captions saved as generated." | REMOVE | Status line already says saved |
| Results pending | "One account already had an unscheduled draft in this language, so this version waits on it as a proposed update." | COMPRESS | "One account already had a draft here, so this one waits as a proposed update." |
| Automations card | Eyebrow "On repeat" + "Drafts that prepare themselves" + paragraph | COMPRESS / MOVE | Heading "Automations" + InfoTip "Drafts on a schedule. You still approve every draft." |
| Automations empty | "No automations yet." + "A weekly tip, a monthly recap, a countdown…" | COMPRESS | "No automations yet" + New automation |
| Suggestions card | Eyebrow "Evidence first" + "Rafii suggestions" + "Each suggestion names the workspace evidence behind it." | COMPRESS | "3 ideas for you" (Example D) / "Suggestions" |
| Suggestion row | Reason + "campaign ab12cd34 · rev 1" + "Open for review" / "Dismiss" | MOVE / COMPRESS | Reason (from API) + **Review** / Dismiss in one row; evidence ids in tooltip |
| Suggestions empty | "No suggestions right now." + "No current evidence in this workspace supports one." | COMPRESS | "No suggestions right now" |
| Chat header | Eyebrow "Conversation" above the title | REMOVE | Title only |
| Chat plan badge | "Plan awaiting your approval" | COMPRESS | `STATUS.needsReview` "Needs review" |
| Chat model badge | Model id always visible | MOVE | Hidden below `md` |
| Chat queued | "Waiting for Claude Code on this machine…" | COMPRESS | "Waiting for Claude Code…" |
| Chat failure | "The run did not complete." | COMPRESS | "Couldn't finish the drafts" + run error as detail |
| Chat no-plan note | "No times were named, so nothing is scheduled. Say when each post should go out, or schedule a draft in the Queue." | COMPRESS | "Not scheduled. Say when, or schedule in the Queue." |
| Chat composer placeholder | "Ask for another angle, a shorter version, or a different time…" / "Describe the image you want to generate…" | COMPRESS | "Make it shorter and post Tuesday at 9" / "A grand piano on an empty stage, warm light" |
| Chat composer hint | "⌘↵ to send · channels and times you name in the message win over the chips" | COMPRESS | "⌘↵ to send" (the rule moved to the Home info popover) |
| Chat composer hint (image) | "Uses the managed image route and one media credit · independent of the writing model" | COMPRESS (charge kept) | "Uses 1 media credit" |
| Chat inspector | "An illustrative layout, not a published post." / empty-state paragraphs | REMOVE | "Nothing to preview yet" / "No sources yet" |
| Chat sidebar | Absolute date per conversation | COMPRESS | Relative time; exact date in tooltip |
| Composer voice toggle | "Writing like me" / "Neutral voice" | KEEP | Asserted by tests; tooltips shortened |
| Composer language notes | "…isn't tuned yet. PostRiff still writes it; check the wording before you post." etc. | COMPRESS | "…has no region. Pick one." / "…isn't tuned yet. Check the wording." / "+2 more" |
| Activity strip | Five always-visible lines: detected intent, skills, memory, "N approved sources read; nothing else from your workspace", run time · model id · cost | MOVE | Visible: warnings + "Done in 12s · $0.02" + **Details**. Intent, destinations, skills, memory, sources, model and raw event log inside Details |
| Activity strip cost | "your subscription paid (CLI reported $0.003) · PostRiff $0" | COMPRESS (money kept) | "Billed to your subscription · $0 here"; CLI figure in Details |
| Plan card header | Eyebrow "Schedule plan" + "2 posts, each its own job." + "UTC · nothing publishes until you approve" | COMPRESS | "2 posts to schedule" + time zone |
| Plan card job badge | Raw job state ("provider accepted") | COMPRESS | Shared `jobBadge` vocabulary from `lib/jobs` (label + tooltip) |
| Plan card | "Scheduling needs an active voice profile, so every post is checked against whose words it carries." + "Set up your voice" | COMPRESS | "Set up your voice to schedule." + "Set up voice" |
| Plan card | "Approval binds the exact text, media, account and time of each row." | COMPRESS (publishing kept) | "You approve the exact text, media, account and time." |
| Plan card | Rights and unknowns acknowledgements | KEEP | Legal wording unchanged |
| Plan card buttons | "Just save drafts" / "Review & approve all 2" / "Ask an approver to schedule" | COMPRESS | "Save as drafts" / "Approve & schedule 2" / "Needs an approver" |
| Plan card done | "2 posts approved and waiting for their time. 1 row still unscheduled." | COMPRESS | "2 scheduled · 1 not scheduled" |
| Plan card toasts | "2 posts scheduled. See them in the Queue and Calendar." / "2 candidates saved as drafts. Nothing is scheduled." | REMOVE / COMPRESS | No toast (the done row shows it) / "2 saved as drafts" |
| Plan steps | "Save the candidates as drafts" / "Prepare the exact Instagram review" / "Adding the candidates to your drafts…" | COMPRESS | "Save drafts" / "Prepare Instagram" / "Saving drafts…" |
| Image card | "Generating your image…" / "Generated image candidate" / "Preparing image generation…" | COMPRESS | "Generating image…" / "Generated image" / "Preparing…" |
| Image card error | "The candidate was saved, but its private preview could not be loaded." | COMPRESS | "Saved, but the preview couldn't load." |
| Learn my voice panel | "First review the retrieved posts. Retaining samples, allowing analysis, approving the Writing DNA profile, and allowing future generation are separate decisions. Nothing in this workflow publishes." | COMPRESS (consent kept) | "You decide each step separately: keeping samples, analysis, the profile, and use in drafts." |
| Learn my voice panel | "An owner must authorize social-post retrieval and sample use. No posts were read for this request." | COMPRESS (privacy kept) | "Only an owner can import posts. Nothing was read." |
| Learn my voice panel | "Writing DNA revision 3 is approved. Individual samples still need generation permission for the exact writer you choose." | COMPRESS | "Writing DNA approved. Each sample still needs permission for the model you draft with." |
| Learn my voice panel | "Close sample review" | COMPRESS | "Close" (accessible name kept) |
| Voice interview | "Answers are saved in this workspace conversation. No model is called. Your current voice stays active until an owner approves the proposal." | COMPRESS | "Saved in this chat without an AI call. Your voice changes only when an owner approves." |
| Model dialog | Eyebrow "Your creative engine" | COMPRESS | "Model" |
| Model dialog | "Runs on the machine that serves the API" / "Runs through the workspace" | MOVE | InfoTip beside API/CLI switch |
| Model dialog row | "Anthropic · Claude Code · CLI subscription" + "Ready" | MOVE | Billing only ("CLI subscription", "Workspace usage"); provider and route in row tooltip; "Unavailable · reason" only when unavailable |
| Model dialog | "The API host has not reported a CLI for this provider. Models below show their own availability." | COMPRESS | "No CLI found." |
| Model dialog | "No models are configured" + "Add a provider or sign in to a CLI on the machine that serves the API, then rescan." | COMPRESS | "No models available" + "Set up models" link |
| Model dialog | CLI card "Installed · 1.2.3 · Signed in · host" | COMPRESS | "Installed · Signed in"; version and host in tooltip |
| Model dialog | Reasoning summary "Effective for Claude Code · sonnet: xhigh" + "… has no reasoning setting; your preference is kept for other models." | MOVE | Summary in tooltip on "Reasoning"; visible line only "This model has no reasoning setting." when it applies |
| Model dialog footer | "Models & providers ↗" | COMPRESS | "Manage models ↗" |
| Language dialog | Intro, "Choose first. Apply when you're ready.", empty-state paragraph | REMOVE | Title and controls only |
| Language dialog | "Settings only. Future drafts use these languages; existing drafts are not translated or regenerated." | COMPRESS | "Applies to new drafts only." |
| Language dialog shared hint | "One shared choice. Individual settings stay as they are until you apply." | COMPRESS | "Applies to every channel." / "Each channel keeps its own." |
| Content library | "App fit is a suggestion, not publishing support…", "Subtle animation in thumbnails" | REMOVE | Footer note covers it: "Changes this draft only. Your channels stay the same." |
| Content library | "Curated fit suggestions, not a popularity ranking. Research measures format use or engagement, not which topic wins." | COMPRESS | "Curated suggestions, not a ranking." |
| Content library evidence | Research snapshot paragraph (API support, account eligibility…) | COMPRESS | "Research snapshot: …. No live analytics. Xiaohongshu pairings are unverified suggestions. Doesn't check platform support or account eligibility." |
| Overview header | "What is scheduled, what needs you, and how much of your plan is left." | REMOVE | Title only |
| Overview stats | Four cards with label, value, hint and footer sentence ("Approved posts the worker will publish", "Confirmed by the provider; unverified jobs remain in sending", "Overage: stop — nothing is charged silently") | COMPRESS | One stat strip: **4** Scheduled · **12** Published · 30 days · **8** Writing batches left · **3** Channels connected; one short qualifier each ("1 sending now", "Resets in 5 days", "No overage charges", "2 Direct · 1 Assisted · 0 Local") |
| Overview stats error | "Unavailable" + "Could not read the workspace" + Retry | COMPRESS | "Unavailable" + Retry (reason kept for screen readers) |
| Overview info popover | 4 paragraphs | COMPRESS | 3 short lines |
| Next up | "Approved posts only, shown in your time zone (X)." | MOVE | Time zone in the time's tooltip; "approved only" in info popover |
| Next up empty | "Nothing approved is waiting." + "Approve a draft in the Queue and its slot appears here." + "Open the Queue" | COMPRESS | "Nothing scheduled" + "Open Queue" |
| Next up badges | "2 sending now" / "1 failed in the last 24 hours" / "publish" label | COMPRESS | "2 publishing" / "1 failed" (24-hour window for screen readers) / level badge only |
| Needs your attention | "Things only you can decide. Empty is good." | REMOVE | Title only |
| Attention row | "Needs owner · you can do this" | REMOVE (when you can act) | Shown only when you can't: "Needs owner · ask an owner or admin" |
| Attention all clear | "All clear" + "No approvals waiting and every connection is healthy." | COMPRESS | "All clear" |
| Attention partial | "Could not read part of the workspace" + "Some reminders may be missing: channels could not be read." | COMPRESS | "Some reminders may be missing" + "Couldn't load channels." + Retry |
| Publishing activity | "Posts the provider confirmed, by day: 12 in this range. Hover a day; click two days to total the span." | COMPRESS | "12 published" beside the title |
| Channels card | "What each connection can really do today." + "Publish: 2 Direct · 1 Assisted · 0 Local" | REMOVE (duplicate of stat strip) | Title + list |
| Channels card | "No channels connected yet." + "Connecting an account lets you schedule and publish." | COMPRESS | "No channels connected" + "Connect a channel" |
| Getting started | "Four steps from a blank workspace to your first scheduled post." + a detail sentence per step | REMOVE / MOVE | "Get set up · 1 of 4 done"; step detail in tooltip |
| Recent activity | "Content-free audit trail of what happened in this workspace." / empty paragraph | REMOVE | Title / "No activity yet" |
| Recent activity | "Connection declined at the provider" / "The full log is open to admins; ask one if you need it." | COMPRESS | "Connection declined" / "Ask an admin for the full log." |
| Error toasts (Home/chat/plan) | "The content type could not be selected.", "The message could not be sent.", "The plan could not be approved." | COMPRESS | "Couldn't select that content type.", "Couldn't send your message.", "Couldn't approve the plan." (API message still wins) |

## Structural changes

- **Home**: dropped the hero eyebrow and subtitle. Starting points are now example requests with no "A little nudge?" prefix. The composer topline is a single Expand control. The assurance line under the consent row is gone. The character counter only appears near the limit. Quick-start cards are shorter.
- **Home idle preview**: the eyebrow, the two-line marketing heading and the disclaimer paragraph are gone. The phone deck is the content, with a visually hidden heading.
- **Home results**: one status line instead of a status line plus a duplicate error. One "Open drafts" link instead of two. No mockup disclaimer. No "Updates live" or "Captions saved as generated" filler.
- **Planning strip** (`raffi-planner.tsx`): each card has one heading, with no eyebrow and no explanatory paragraph. Automation approval is behind an InfoTip. Suggestions are compact rows (reason + Review + Dismiss). The heading counts them ("3 ideas for you"). Evidence ids are in a tooltip instead of a line under every item.
- **Activity strip**: went from five always-visible lines to a status + cost line (warnings still visible) with a **Details** disclosure. Intent, destinations, skills, memory, sources read, model id and the raw event log are all inside it.
- **Plan card**: shorter header. Job states use the shared `jobBadge` vocabulary. The success toast is gone because the card's done row already shows it. The primary button says what it does ("Approve & schedule 2").
- **Model dialog**: provider, route, version and host moved into tooltips. Billing class stays visible. The mode explanation moved into an InfoTip. The reasoning summary is a tooltip.
- **Overview**: the four stat cards became one stat strip (`<dl>`). The page description is gone. The duplicate publish-level counts came off the Channels card. Panel descriptions were removed from Next up, Needs your attention, Channels, Getting started and Recent activity. Attention rows show "who can act" only when it isn't you. Empty states are a title plus one action.
- **Statuses**: added `STATUS.active` for the voice link, `STATUS.needsReview` for a plan awaiting approval, `STATUS.scheduled` for the plan done row, and `STATUS.publishing` / `STATUS.failed` in Next up and the activity strip.

## Intentionally kept verbose

- Consent: "Use this text to draft with" and "My own writing (may be quoted publicly)". Plan card rights acknowledgement: "I have the rights to publish these texts (and any image) on the selected accounts." Unknowns and warnings acknowledgements. Voice-sample consent wording ("samples you approved for <model>"), the Learn-my-voice separate-decisions line, and the owner-only import line. These are legal consent, privacy and public-publishing wording, shortened but kept unambiguous.
- Money: the activity-strip cost, "Uses 1 media credit", the billing class in model rows, and "No overage charges" on Overview.
- The model dialog's segmented control aria-label "…: not applied by this provider" and `reasoning-map.ts` summaries. Both are asserted by tests (`rafii-workflow.cjs`, `reasoning-map.test.cjs`), and the summaries are now only in a tooltip.
