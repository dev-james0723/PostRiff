# UI simplification audit: Brand & voice, Learn my voice, Memory, members/roles/audit, onboarding, auth

Area owner: `brand-onboarding`. Spec: `docs/Raffi_UI_Simplification_Information_Density_Engineering_Spec_2026-09-24.md`.

## Structural changes

- **Brand & voice: action first.** The page used to stack a status strip, a full-width Learn my voice card, then Identity, Voice, What drafts read and Revisions as separate cards. Now it's the status strip, then a main column in this order: a waiting proposal, then setup (no voice yet) or Learn my voice, then the approved profile. What drafts read and Revisions sit in the side column.
- **Card soup merged.** Identity and Voice are now two headed sections of one quiet card (`IdentityCard`/`VoiceCard` take a `material` prop and render on `canvas` inside a shared `Surface`). Both lost their explanatory descriptions and footers.
- **Redundant signals removed.** The Voice card no longer repeats "a proposed revision is waiting". The status strip, the proposal card and the revision list already say it.
- **Status strip.** The reminder paragraph is now one line, shown only when there's something to do. The four count hints moved into `title` and `sr-only` text, so screen readers still get them. The approval date hides below `md`.
- **Learn my voice.** The privacy detail moved into an `InfoTip` in the panel header. The one-line description keeps the permission fact. The route ids and the "adapter / records read / pages" counts are gone.
- **Memory.** No page description. The file-list footer paragraph is gone. Access-card and learning-panel success toasts are removed because the switch and badge show the result. The cloud-extraction explanation moved into an `InfoTip`. Proposal decisions no longer toast because the card itself switches to the result.
- **Members.** The Ownership section heading duplicated the "Transfer ownership" panel title, so the section heading is removed. The mobile member card no longer shows "Updated". Member and invitation states read from `STATUS` (capitalised) instead of raw API words.
- **Audit log.** The page description and empty-state essays are removed. The coverage line is one sentence with the exact time in a `title`.
- **Removed dead code:** `brand/drafts-read-card.tsx` (not imported anywhere; it had stale "writing route" copy).
- **Onboarding.** Every tour step is now a short title plus at most one short sentence. All step ids and `data-tour` targets are unchanged.

## Audit table

| Screen/component | Current copy (short) | Class | New copy / action |
|---|---|---|---|
| Brand page header | "Who speaks in this workspace and how they sound… nothing here is inferred by a model." | REMOVE | Title only (`Brand & voice`) |
| Brand info panel | 6 long sections (VOICE.md/IDENTITY.md routing, package download, etc.) | COMPRESS | 4 one-sentence sections |
| Brand access fallback | "Brand & voice is set up by owners, admins and editors." + "Ask one of them…" | COMPRESS | "Only owners, admins and editors can change the voice." |
| Voice package export | success toast "Voice package downloaded." | REMOVE | Button already reads "Downloaded" |
| Sample-workspace notice | "This sample workspace is read-only" + "You can look through…" | COMPRESS | "Sample workspace: changes aren't saved." |
| Status strip reminder | 1–3 sentences in every state | COMPRESS | One line only when actionable ("A new revision is waiting for your approval.", "Redraft the 3 older drafts…", "Set up a voice so drafts sound consistent.") |
| Status strip counts | "Drafts on this voice / Written before it / Approved or scheduled posts" + hint lines | COMPRESS/MOVE | "On this voice / Older drafts / Scheduled / Learned preferences"; hints → tooltip + sr-only |
| Identity card | description + footer ("…not available on this page yet") | REMOVE | Section title + fields; merged with Voice |
| Voice card | "…Writing routes receive it as VOICE.md." + footer | COMPRESS/REMOVE | "Revision N · approved <date>" |
| Profile details | "Draft interpretation · AI analysis · model · evidence excerpts checked; needs human review" | COMPRESS | "AI analysis · model · needs your review" / "Local writing statistics (no AI)" |
| Profile details | "Starting tone / Evidence by writing dimension / Unknowns kept explicit" | COMPRESS | "Tone / Evidence / Unknowns" |
| Profile sample note | "This explicitly supplied writing example is shared through VOICE.md…" | COMPRESS | "Included in VOICE.md." |
| Proposal review | eyebrow "Draft interpretation", long description, footer about discarding | REMOVE/COMPRESS | "Drafts keep using revision N until you approve." |
| Proposal review guidance | label + placeholder + helper (3 sentences) | COMPRESS | "Your guidance (optional)" · placeholder "Plain, specific, never salesy." · "Replaces the proposed observations." |
| Proposal approve button | "Review and approve" | COMPRESS | "Approve…" (confirm dialog unchanged, consequence kept) |
| Revisions | description + empty-state description + "Not a revision until an owner approves it." | REMOVE | "No revisions yet"; proposed row chip "Needs approval" |
| Voice setup | description "Two minutes to guide…", tone paragraph | REMOVE/COMPRESS | No description; "Your preference, not a learned conclusion." |
| Voice setup placeholders | "e.g. …", "…Writing routes receive it in VOICE.md…" | COMPRESS | Example input only ("Help beginners build a daily habit", "A paragraph is enough.") |
| Provisional voice | "Review your provisional voice" + 3 variant descriptions | COMPRESS | "Review your voice" · "Proposed by AI from the samples you allowed." |
| Start-again dialog | destructive consequence | KEEP (tightened) | "This discards the proposal and clears the active voice…" |
| Learn my voice description | "Retain writing you choose… Analysis consent does not grant future generation consent." | MOVE | "Add writing you own. Each use needs your permission." + InfoTip with the consent rules |
| Owned-posts picker | two paragraphs (auto-propose authorization, read-only) | COMPRESS | "Read-only. Nothing is published or analysed." / "Rafii picked up to 10 recent posts…" |
| Owned-posts coverage | "N pages · N records read · N excluded by the adapter." | REMOVE | Coverage summary + "N skipped." only when relevant |
| Owned-posts footer | 4-sentence bounds/expiry paragraph | COMPRESS | "N selected · up to 50 at once · reload after 10 minutes" |
| Owned-posts controls | "Load my posts (read-only)", "Select visible posts (up to 50)", "Exclude from selection" | COMPRESS | "Load my posts", "Select all shown", "Deselect" |
| Authorship consent | 3 sentences | KEEP (tightened) | First sentence unchanged (legal consent, test-anchored); rest "Leave out guest, quoted or unrepresentative posts. This doesn't allow AI use." |
| Manual import | "This is labelled user-provided text…"; "Validation is atomic." | REMOVE/COMPRESS | Row chip already says "User-provided text"; "One invalid item stops the import." |
| Manual consent | "I wrote or have permission… not AI analysis or generation." | KEEP | Legal consent |
| AI analysis | heading "Ask Rafii to analyse my writing DNA", route id paragraph, 3-clause consent | COMPRESS | "AI analysis"; "The selected samples' text is sent to this model…"; consent "…for one analysis. It uses writing allowance." |
| AI unavailable | "No managed AI analysis model is configured and qualified." | COMPRESS | "AI analysis isn't available yet." · "Local analysis still works." |
| Sample row grants | "Allowed for analysis via local-rules, cloud:gateway:…" | MOVE | "Allowed for analysis." (route ids in `title`) |
| Sample row buttons | "Allow selected AI model to analyse this text", "Describe local writing statistics" | COMPRESS | "Allow AI analysis", "Analyse locally" |
| Voice toasts | "A provisional voice profile is ready for review. It is not active yet." etc. | COMPRESS | "Voice proposal ready for review.", "Sample retained. Select it to allow analysis." |
| Memory header | "Plain Markdown files behind every draft…" | REMOVE | Title only |
| Memory file list | "Given to writing routes"; footer paragraph | COMPRESS/REMOVE | "Sent to writers"; footer removed |
| What drafts read | intro sentence + long route line per file | COMPRESS | "Sent to local writers. The cloud model needs an owner's OK." |
| Who reads these files | "Writing routes on your own machine always read…" | COMPRESS | "Local writers always read these files. An owner decides who else can." |
| Cloud model access row | 2–3 sentences + "Nothing is shared until an owner turns this on." | COMPRESS | "The cloud model doesn't read VOICE.md or …. 2 private boundaries never reach it." (privacy facts kept) |
| Cloud / research confirm dialogs | consent text | KEEP (tightened) | What is sent and to whom stays explicit |
| Web research note | "Turned off on this machine (POSTRIFF_RESEARCH=0)." | COMPRESS | "Turned off on this machine." |
| Access toasts | long success toasts | REMOVE | Switch + badge show the result |
| Learned preferences | 2-sentence description + owner line; "style rev N" chip | COMPRESS/REMOVE | "Rafii suggests writing preferences from what you say and how you edit. You decide." |
| Cloud extraction band | 3-sentence paragraph | MOVE | "A cloud model may read redacted edits." + InfoTip |
| Learning stats | "Since style rev 3: 12 approved drafts, 20% of the text changed…" | COMPRESS | "12 approvals · 20% edited on average · 40% untouched" (before-comparison `md+` only) |
| Learning toasts (pause/resume/retire/settings) | 5 success toasts | REMOVE | State visible in the list and switches |
| Suggestions history | "Suggestions and decisions"; empty/footer sentences | COMPRESS | "Suggestions"; "Nothing waiting." / "No decisions yet." / "Latest 20 of 43" only when truncated |
| Proposal card | pending consequence paragraph, decided status chip, decision toast | REMOVE | Decision line "Remembered. Applies to new drafts."; expiry relative with exact date in `title` |
| Members header / invite | page description; "They get a one-time link…" | REMOVE | Title only |
| Invite result (banned hit) | "Email delivery is not configured on this deployment, so share the link directly…" | COMPRESS | "Share this link. It works once and expires <date>." / "Email sent. The link works once and expires <date>." |
| Members states | "active", "pending" (raw) | COMPRESS | `STATUS.active` / "Pending" |
| Members empty invitations | description sentence | REMOVE | "No invitations yet" |
| Ownership | section heading + "A lower-priority change kept apart…" | REMOVE | Single "Transfer ownership" panel: "Hand ownership to an active admin. Needs a recent sign-in." |
| Remove / revoke / transfer dialogs | destructive consequence | KEEP | Unchanged wording |
| Roles header | "What each role can do in this workspace, who holds it, and where you stand." | REMOVE | Title only |
| Your access | eyebrow "Where you stand"; long rules sentence | REMOVE/COMPRESS | "Only grants you hold. Nobody can change their own access." |
| Sensitive changes | 3-sentence description | COMPRESS | "These need a recent sign-in. If yours is too old, sign in again and retry." |
| Only-member empty state | role-picking essay | REMOVE | Title + "Invite someone" |
| Permission matrix legend / tooltip | long legend | COMPRESS | "✓ included · with grant can be added · — not available" |
| Access sheet | grey-out rule, must-remove alert, footer, success toast | COMPRESS | "You can only give grants you hold."; "Needs a recent sign-in."; toast only for the held-approvals consequence |
| Audit header | "Who did what in this workspace, newest first. Never the content itself." | REMOVE | Title + Refresh; privacy fact kept in info panel and detail sheet |
| Audit empty / filter empty | descriptions | REMOVE | Title + actions |
| Audit coverage | "…This page cannot load older events yet, so counts and filters cover these 500 only." | COMPRESS | "Showing the newest 500 events since 3 Sep. Older events aren't loaded." |
| Audit rows | "payment provider", "at the provider", meta "Provider" | COMPRESS | "The plan changes once payment is confirmed.", "Did not approve a connection", "Platform" |
| Audit lookup failures | "…so some channel rows name only the provider." | COMPRESS | "Couldn't load channel names." |
| Tours (all 19 tours) | 1–3 sentence bodies, "provider", "deployment" | COMPRESS | Short title + ≤1 short sentence (Channels connect step: "Connect an account" · "Connect to schedule posts and see analytics.", matching the new Channels empty state); the "this deployment" line is now "whether each runs isolated"; `Models & providers` → `Models` (nav rename) |
| Welcome dialog | "Three things worth knowing…", long points, "Take the two-minute tour" | COMPRESS | "Three things to know.", three short points, "Take the tour" ("Nothing publishes on its own" kept) |
| Tour nudges / help toast | toast descriptions | REMOVE | "Want a quick tour?", "New to Memory?", "Tips will show again" |
| Sign-in subtitle | "Welcome back. Your drafts are where you left them." | REMOVE | Title only |
| Sign-up subtitle | "14-day trial. No card. Export everything, any time." | COMPRESS | "14-day free trial. No card needed." |
| Trial plan note | "You are not charged during the trial and nothing converts automatically." | COMPRESS (money) | "No charge during the trial. You're only billed if you choose a paid plan." |
| Auth errors | "…could not be completed. Please try again." | COMPRESS | "Couldn't sign you in. Try again." |
| Terms consent | "By continuing you agree to the Terms and Privacy Policy." | KEEP | Legal consent |
| Sign-in help | 3-sentence description; recovery disclaimer | COMPRESS (security) | "…so there's no password to reset…"; "Account recovery needs an identity check and isn't guaranteed." |
| MFA | "Your account expects a second factor, but none could be listed…" | COMPRESS | "Couldn't find your second factor. Sign out and try again, or get help below." |
| Invite acceptance | title + description + signed-out paragraph | COMPRESS | "You're invited to a PostRiff workspace" · "You'll join with the role the inviter chose. You can leave any time." · security note kept in one sentence |
| Quick starts | 1–2 sentence explanations; 4–5 format "usually" lists | COMPRESS | One short sentence each; two or three formats |

## Intentionally kept verbose

- **Consent labels** (retaining own posts, manual sample authorship, one-off AI analysis, allowance use). These are legal consent and privacy wording. They're tightened but not ambiguous. The first sentence of each consent is unchanged because browser tests anchor on it.
- **Cloud model / web research rows and their confirm dialogs.** They still name exactly which files or services receive content and what never leaves (private boundaries, sources, drafts).
- **Destructive and permission dialogs** (remove member, revoke invitation, transfer ownership, change access, approve a voice revision, start voice setup again). The consequence wording is unchanged or only lightly tightened.
- **Admin-only audit detail sheet** (event kind, ids, meta rows). This is an admin surface, so technical ids stay.
