# UI simplification audit: account

Scope: `web/src/features/account/**`, `web/src/app/app/account/**` (billing excluded; the coordinator owns it).
Screens: Profile, Notifications, Privacy & data, API & integrations, Models.

| Screen/component | Current copy (short) | Class | New copy / action |
|---|---|---|---|
| API · page | "What each connected account allows, the tool registry, and expiring tokens…" | REMOVE | No description |
| API · info panel | "…the providers this deployment offers…" | COMPRESS | Tokens / Coming later / Where to look, no "deployment" |
| API · access fallback | "This page is for people who manage connections" + 2 sentences | COMPRESS | "Only people who manage connections can see this" · "Ask an owner or admin." |
| API · status strip | 3 stat tiles: "Providers that passed review", "of N providers on this deployment", runner footer | COMPRESS | One status line: "3 connected · 1 of 2 platforms approved · Tools [Isolated] [Invoke blocked]"; publish levels and review explanation in InfoTips |
| API · accounts | "Providers on this deployment" + explanation paragraph | COMPRESS/MOVE | "Available platforms" + InfoTip |
| API · accounts | "No providers are set up on this deployment." | COMPRESS | "No platforms available yet." |
| API · accounts | "Provider not set up on this deployment" / "Provider review passed/pending" | COMPRESS | "Platform not available" / "App approved" / "App review pending" (hidden below md) |
| API · accounts | "Access until 3 Oct 2026 · in 9 days" | COMPRESS | "Access expires in 9 days" (exact date in title) |
| API · accounts | Section description "What each account allows, capability by capability…" | REMOVE | — |
| API · accounts empty | "No accounts connected in this workspace" + description | COMPRESS | "No accounts connected" + Open Channels |
| API · tokens | 4-sentence description incl. "Trial plans may use tokens." | COMPRESS | "For your own scripts. Tokens can never approve or publish." |
| API · tokens | "Tokens are unavailable. No count is shown." | COMPRESS | "Couldn’t load tokens" + Try again |
| API · tokens | "N active tokens" | COMPRESS | "N active" |
| API · token row | 4 metadata lines (prefix/scope, exact expiry, last used, created by) | COMPRESS | 2 lines; relative expiry with exact date in title; last used/creator hidden below md |
| API · tokens | "Token revoked." toast | REMOVE | Row shows Revoked |
| API · tokens dialog | "This is the only reveal. Closing this dialog clears the secret…" | COMPRESS | "You won’t see it again. Closing this dialog clears it." |
| API · tokens dialog | "Create and reveal once" | COMPRESS | "Create token" |
| API · tools | "Tool registry" + "Versioned tools this deployment lists…" | COMPRESS | "Tools", no description |
| API · tools | Runner/invoke paragraphs ("Invoke is blocked on this deployment…") | MOVE | Label + badge rows; detail in InfoTips |
| API · tools | "No tools are registered for this deployment." | COMPRESS | "No tools yet" |
| API · not yet | "Not available yet" + description + 4 paragraphs | COMPRESS | "Coming later" + 4 one-line items + "Tell us what you need" |
| Models · page | Title "Models & providers" + description | COMPRESS/REMOVE | "Models" (coordinator request, matches nav); no description |
| Models · info panel | "Hosted service: On a hosted deployment a CLI will run through a desktop companion…" | COMPRESS | "Your own CLI: Running a CLI from your own computer isn’t available yet." |
| Models · no edit access | 4-sentence explanation | COMPRESS | "Ask a workspace owner for edit access." |
| Models · checked line | "List received 2 min ago. Check again refreshes the installation and sign-in checks." | COMPRESS | "Checked 2 min ago" |
| Models · Check again | Success toasts listing every CLI; "Checked. No CLI is listed for this deployment." | REMOVE | Button shows Checked; cards show the result. Error toast kept |
| Models · writing now | "No writer listed · This deployment returned no writers…" | COMPRESS | "No writer available · Drafting can’t start until one is. Try Check again." |
| Models · writing now | "Your saved choice (X) is unavailable here; using Y instead. The server says: …" | COMPRESS | "X isn’t available. Using Y." + the reason |
| Models · writing now | "Used by Home and every conversation. Saved in this browser only, so another browser…" | COMPRESS | "Used for all drafts. Saved in this browser only." |
| Models · CLI section | "Local CLI", "Found on the machine that serves the API…", 4-sentence consent paragraph | COMPRESS/MOVE | "CLI writers (n)" + InfoTip; one visible privacy line: "Claude Code and Codex send selected context to their own AI service." |
| Models · CLI empty | "No CLI writer on this deployment" + companion paragraph + 3 always-visible steps | COMPRESS/MOVE | "No CLI connected" + one line; setup steps behind "How to add a CLI" |
| Models · CLI card | Version, Signed in with, Runs on ("The machine that serves the PostRiff API…"), Who pays, Checked | MOVE | Visible: name, status, models, cost line. Version/sign-in/host moved into "Details" with the run limits; "Checked" in the subline (md+) |
| Models · CLI card | "Models · as configured for this deployment" | COMPRESS | "Models" |
| Models · CLI card | "This mark comes from a run the CLI refused. It stays until the PostRiff server restarts…" | COMPRESS | "Sign in again in Terminal. This mark clears when the app restarts." |
| Models · built-in | "PostRiff" + "Writers PostRiff runs itself…" | COMPRESS | "Built-in writers" |
| Models · built-in row | "Runs on: PostRiff’s server, through X" / "Route “x”, which this page does not describe yet" | COMPRESS | "Runs through: X" only when a service is named |
| Models · built-in row | "You can still pick it. Its drafts will not read your memory files until…" | COMPRESS | "Drafts won’t use your memory files until an owner turns on sharing in Memory." |
| Models · cost copy | "The subscription signed in to the CLI pays. PostRiff records the run with a cost of $0." etc. | COMPRESS | "Paid by the CLI’s own subscription. $0 here." / "Uses one writing batch from your plan per finished run. Failed runs don’t count." / "Free. No AI model is used." |
| Models · kind badges | "Local CLI", "PostRiff managed", "Preview · no model", "Other route" | COMPRESS | "CLI", "Managed", "Free preview", "Other" |
| Models · costs card | "How each writer is paid for" + description | COMPRESS | "Costs" |
| Models · consent card | "Off for this deployment"; "This server did not report whether a model extractor is configured." | COMPRESS | "Off"; "Simple rules read your edits. AI model use wasn’t reported." |
| Models · consent card | "These settings could not be loaded. Nothing here means they are off." | COMPRESS | "Couldn’t load these settings" + Retry |
| Notifications · page | "PostRiff sends a small number of transactional emails and nothing else. No marketing, no tracking pixels." | COMPRESS | "No marketing emails. No tracking pixels." |
| Notifications · switch | Section description + helper paragraph under the switch | MOVE | "Security alerts" / label + switch; detail in InfoTip. Moved to the top (the page’s only control) |
| Notifications · switch | Success toasts ("You will get an email when…") | REMOVE | Switch shows the state; error toast kept |
| Notifications · email list | Long "when" sentences, "Workspace owner" badge | COMPRESS | ≤6-word "when" (hidden below sm), "Owner" badge; "7-day grace" kept (money) |
| Notifications · in app | Section with paragraph + button + owner note | COMPRESS | One line "Approvals, reconnects and plan limits show on Overview." + Open Overview; owner note folded into the email list description |
| Profile · page | Description | REMOVE | — |
| Profile · identity | "Who you are, in every workspace." | REMOVE | — |
| Profile · identity | "Name updated." toast | REMOVE | Name shows the change |
| Profile · email dialog | 2 sentences | COMPRESS | "We’ll email a link to the new address and to X. It changes once the links are opened." |
| Profile · preferences | Section description, 2 helper sentences per control, 5 success toasts | REMOVE/COMPRESS | Label + control; helper only when the device zone differs; "Example: … App text stays in English."; no success toasts |
| Profile · security | Section description; 2FA text "…the API refuses sessions that have not shown one." | COMPRESS | "Every sign-in needs Face ID / Touch ID." (On since … in the badge title) |
| Profile · security | Recovery note (2 sentences) | COMPRESS | "No recovery codes. A second method is your backup." (kept: security) |
| Profile · security | Toasts: backup added, 2FA on/off, method removed, session revoked | REMOVE | Badge and lists show the result. "Signed out N other sessions" kept (count not visible otherwise) |
| Profile · sessions | "Where you are signed in" description; "Sign out all other sessions"; recent-sign-in note in confirm | COMPRESS | "Revoke any you don’t recognise."; "Sign out others"; confirm keeps device count |
| Profile · step-up dialog | "Use a code from my authenticator app instead" | COMPRESS | "Use an authenticator code instead" (matches the MFA sign-in screen) |
| Profile · activity | "Recent security activity" + 2-sentence description | COMPRESS | "Recent activity" |
| Profile · passkeys | 2-sentence description; empty-state description; "Add a passkey on this device"; add/remove toasts | COMPRESS/REMOVE | "Sign in with Face ID, Touch ID or a security key. Two-factor still applies."; "No passkeys yet"; "Add passkey" (sr-only "on this device"); no toasts |
| Profile · channels | "Every account PostRiff can reach, in every workspace…" | COMPRESS | "Across all your workspaces." |
| Profile · channels row | "connected by X · date · valid until date" | COMPRESS | Connected-by hidden below md; "valid until" removed (badge shows expiry state) |
| Profile · workspaces | Section description; 3 Owner/Staff/Members tiles with notes; role description paragraph; leave explanation | REMOVE/MOVE | Counts in the meta line (md+); role description in an InfoTip; "Transfer ownership to leave." for owners |
| Profile · invitations | Role + description line, inviter + expiry line; decline toast | COMPRESS/REMOVE | One line: role · from X · expires (md+); role description in title; no decline toast |
| Profile · account | Section description; sign-out confirmation dialog | REMOVE | Sign out runs directly (harmless; sr-only "on this device") |
| Privacy · page | "What PostRiff holds, where it goes, and what you can do about it." | REMOVE | — |
| Privacy · holdings | "What PostRiff holds" + description + 5 separate tiles with descriptive footers | COMPRESS | "Your data": one surface, 5 stats, footers only for exceptions (withdrawn, blocked, couldn’t read) |
| Privacy · sharing | "Where it goes" + nested "This workspace’s switches" section | COMPRESS | "Sharing" · "Set by the workspace owner." + Memory link; rows "Memory files for cloud AI" and "Web research" with details kept (privacy) |
| Privacy · notice | Always-visible 4 surfaces of notice text (usage, services, retention, rights) | MOVE | One "Privacy notice" section with review badge, Full policy / Deletion steps, and details behind "How your data is used and kept" |
| Privacy · actions | "Each card says what you get and what it records." | REMOVE | — |
| Privacy · export | Extra receipt paragraph; long fingerprint note; success toast | REMOVE/COMPRESS | Content list kept; note "Keep it to show later that your file is unchanged…"; no toast (button shows Downloaded + fingerprint) |
| Privacy · voice | "…to keep or to use in another tool." + 2-sentence availability note; success toast | COMPRESS/REMOVE | "Your approved voice as a zip." · "Available after you approve your voice." |
| Privacy · diagnostics | 2-sentence helper, 2-sentence dialog text, download toast | COMPRESS/REMOVE | "You see it before downloading. Nothing is sent anywhere." (consent checkbox kept) |
| Privacy · retract | 4-sentence description; toast repeating impact | COMPRESS | "Blanks a source’s text and facts. Drafts that used it are blocked until drafted again. This can’t be undone."; impact list before the hold kept; toast "Source retracted" |
| Privacy · requests | Description; "Also in your account history"; empty-state description | REMOVE/COMPRESS | "Account history"; "No requests yet" |
| Privacy · delete | "Who can delete" row; "Nothing has been handed…"/"No approved post is waiting…" filler | REMOVE | Rows show text only when something blocks or will be lost |
| Privacy · delete | Description, typed DELETE confirm, step-up | KEEP (compressed) | Kept explicit: permanent removal, receipt/trial record, cancel subscription and transfer workspaces first; DELETE typing and "Keep my account" unchanged |

## Structural changes

- **API:** three stat tiles became one status line with InfoTips. The line now sits directly above Tokens, and tokens are the page's primary action. The "Coming later" items are one-liners in a four-column grid.
- **API tools:** runner flags are label + badge rows, with the explanations in InfoTips.
- **Models / CLI card:** version, sign-in method and host moved into the "Details" collapsible, which now always shows. The visible card is name, status, models and cost.
- **Models / CLI empty state:** the setup steps are behind a native `<details>`.
- **Models / consent:** the long consent paragraph moved into an InfoTip next to the "CLI writers" heading.
- **Notifications:** the only control (security alerts) moved to the top as label + switch + InfoTip. The "In the app" section is now a single line with a link, and the link goes to `/app/overview` (the old link went to Home, which has no "Needs your attention" panel).
- **Profile / workspaces:** removed the three-tile Owner/Staff/Members grid from each workspace row. The counts are in the meta line, and the role explanation is in an InfoTip.
- **Profile / account:** removed the sign-out confirmation dialog.
- **Privacy / holdings:** five tiles are now one surface. `StatTile` gained a `bare` option for this.
- **Privacy / sharing and notice:** the nested "switches" section is flattened into "Sharing". The notice text (usage, services, retention, rights) is one collapsible "Privacy notice" section instead of two always-open sections with four surfaces.
- **Toasts:** removed about 20 success toasts where the UI already shows the result. Error toasts and consequential results are kept: account deletion, email-change confirmation, accepting an invitation, leaving a workspace, the count of other sessions signed out, source retraction, and copy-to-clipboard.
- **Kept:** all `data-tour` anchors. `privacy-notice` and `privacy-retention` now sit inside the notice section, and `privacy-egress` sits on the Sharing section.

## Intentionally kept verbose

- **Account deletion:** the description, the in-flight and waiting-post warnings, and the typed DELETE dialog. The action is destructive and touches billing.
- **2FA:** the turn-off step-up text ("Sign-ins will need only your email or Google account. All your methods are removed.") and the recovery-codes note, for security.
- **Privacy:** the sharing details (which files, which search services, private boundaries), the diagnostics content list and consent checkbox, and the retraction impact list.
- **Models:** cost lines stay one full sentence each, because they concern money.
- **API:** the "Using a token" details disclosure stays technical. It is developer-only and closed by default.
