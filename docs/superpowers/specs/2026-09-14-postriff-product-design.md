# PostRiff Product and Experience Design Specification

**Status:** Design candidate for review. No Studio code, channel connection, schedule, publication, or reply was changed by this document.

**Date:** 2026-09-14

**Product name:** PostRiff

**Working promise:** One idea. Each channel, in its own voice.

## 1. Executive decision

PostRiff should have exactly six primary destinations:

1. Dashboard
2. Ideas
3. Scheduling
4. Channels
5. Analytics
6. Audience

`Settings`, `Activity`, `Backups`, app status, and help remain available from the account/utility menu, but they are not primary tabs. `Templates` becomes a contextual tool inside Ideas. `Delivery` becomes the publish state inside Scheduling. The permanent right-side Codex handoff rail is removed.

The product's center is the Ideas workspace: a persistent, Codex-like conversation that can read attached sources, route through the relevant social skills, create a canonical content brief, generate channel-native post variants and media, and present an interactive publish composer. The agent may propose a publish or reply, but PostRiff—not the conversational agent—owns preflight, exact approval, provider execution, and receipts.

This preserves the existing safety boundary while making it largely invisible during ordinary creative work.

## 2. Assumptions resolved for this candidate

- The dangling “6th tab” in the request is interpreted as the sixth named destination, Audience. No seventh primary tab is proposed.
- “Global channels” means a saved, user-editable channel group, not every connected account by default.
- Reasoning and access are shown as friendly task controls, not raw command-line flags.
- Generating an image is a creative action. Publishing, scheduling, sending a reply, deleting/hiding a comment, or changing a connection is a separate external action.
- PostRiff remains local-first and uses the installed, version-qualified Codex CLI/runtime through its backend.
- Platform capabilities remain partial. A connected identity is not automatically publish-ready, analytics-ready, or comment-ready.

## 3. Evidence from the current Studio and live Buffer audit

### Current Studio friction

The current local Studio was inspected in Chrome at `127.0.0.1:4310`. The main navigation currently exposes Drafts, Calendar, Delivery, Channels, Templates, Activity, and Settings. A permanent Guided drafting/Codex handoff rail competes with the page content. The Channels view leads with a large catalog and long setup explanations, and its detail dialog surfaces identifiers, permission state, routes, and other operator-level information before the user needs them.

The code mirrors this density: most page composition is compressed into `studio/web/src/App.tsx`, while the agent experience is a guided intake panel rather than a full conversation. The current Codex bridge is deliberately content-only, ephemeral, read-only, and configured without browser, web, image generation, or tool use. This is a safe foundation, but not yet the requested Ideas agent.

### Buffer patterns worth borrowing

The open Buffer workspace was inspected live in Chrome, including Home, Create/Ideas, the post composer, AI Assistant, Publish list, weekly calendar, Community, and Insights preview.

Borrow:

- Channel selection at the top of the composer.
- One shared draft with channel-specific customizations.
- A persistent post-preview surface beside the editor.
- Save, schedule, and publish actions in one predictable footer.
- List/calendar scheduling views, filters, and draft recovery.
- A unified comment inbox with post context.
- Lightweight top-level analytics followed by per-post detail.

Adapt:

- Buffer's one-shot AI prompt becomes a persistent task conversation with sources, skills, runs, artifacts, and resumable history.
- The composer becomes the reviewable output of a canonical brief and explicit per-platform transformations.
- Media guidance becomes a small preflight system with severity and one-click repairs.
- Channel selection supports saved groups such as Global channels, but always expands to an exact account list before approval.

Avoid:

- A large template catalog as a primary destination.
- Dense, always-visible instructions.
- Treating a generic AI suggestion as equivalent to source-aware research.
- Showing unavailable analytics as zero.
- Letting a conversational request bypass account, content, schedule, or reply approval.

## 4. Product principles

### 4.1 One obvious next action

Each page has one dominant action. Secondary actions remain visible but visually quiet.

| Destination | Dominant action |
|---|---|
| Dashboard | Create with PostRiff |
| Ideas | Send task |
| Scheduling | Create or schedule post |
| Channels | Connect a channel |
| Analytics | Inspect a post or change comparison |
| Audience | Reply |

### 4.2 Progressive disclosure

Normal language comes first. Platform IDs, OAuth scopes, runtime versions, route details, format codes, raw manifests, and hashes live under `Advanced`. An error initially states what happened, what the user can do, and what was not changed.

### 4.3 One canonical idea, native outputs

PostRiff stores the source, verified facts, user viewpoint, audience, goal, and constraints once. It then produces platform-native variants; it does not merely copy the same text into every network.

### 4.4 Preview is not publication

Draft, preview, approval, scheduled, publishing, published, failed, and verified are distinct states. UI labels and receipts must never collapse them.

### 4.5 Safety without ceremony

Routine drafting should feel fluid. Friction appears only when an action crosses a meaningful boundary: external research, workspace mutation, paid generation, schedule creation, publication, reply, moderation, or connection change.

## 5. Information architecture

### Desktop shell

```text
┌──────────────┬──────────────────────────────────────────────────────────┐
│ PostRiff     │ Page title                         Search    + Create    │
│              ├──────────────────────────────────────────────────────────┤
│ Dashboard    │                                                          │
│ Ideas        │                     Page content                         │
│ Scheduling   │                                                          │
│ Channels     │                                                          │
│ Analytics    │                                                          │
│ Audience     │                                                          │
│              │                                                          │
│ Account  •   │                                                          │
└──────────────┴──────────────────────────────────────────────────────────┘
```

The sidebar is collapsible. Collapsed mode retains recognizable platform-neutral icons and accessible labels. The account menu contains Settings, Activity and receipts, Backups/export, Help, and app/runtime status.

### Responsive shell

On narrow screens, show Dashboard, Ideas, Scheduling, and Audience in a bottom navigation bar, plus `More` for Channels and Analytics. All six destinations still exist; the responsive shell simply prevents six crowded tap targets.

### Migration from current navigation

| Current area | PostRiff destination | Treatment |
|---|---|---|
| Drafts | Ideas | Draft library becomes a left drawer inside Ideas |
| Guided drafting | Ideas | Replaced by persistent chat |
| Templates | Ideas | Attachment/command menu and starter suggestions |
| Calendar | Scheduling | One of three views |
| Delivery | Scheduling | Status, approvals, receipts, and exceptions |
| Channels | Channels | Simplified; advanced setup is collapsed |
| Activity | Account menu | Timeline and receipts |
| Settings | Account menu | Workspace preferences |

## 6. Primary end-to-end workflow

```text
Prompt or source
      ↓
Research + skill routing
      ↓
Canonical brief
      ↓
Channel-native variants + media candidates
      ↓
Live preview + preflight
      ↓
Save draft ── or ── Schedule/Publish proposal
                             ↓
                   Exact action approval
                             ↓
                 Provider execution + receipt
                             ↓
                     Analytics + Audience
```

The user can enter the flow from Ideas, the global Create button, a scheduled item, a comment thread, or an analytics post detail. Every entry point resolves to the same content/variant model.

## 7. Dashboard

### Purpose

Answer three questions in under ten seconds:

1. What needs my attention?
2. What is going out next?
3. What is working?

### Layout

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Good morning. What would you like to create?       [Create with PostRiff]
├────────────────────────────┬─────────────────────────────────────────┤
│ Needs attention            │ Up next                                 │
│ 4 comments need replies    │ Today 2:30 PM • Instagram              │
│ 1 channel needs reconnect  │ Tomorrow 9:00 AM • Global group        │
├────────────────────────────┼─────────────────────────────────────────┤
│ Performance pulse          │ Recent work                             │
│ Reach ↑ 12%                │ Classical music article • In review    │
│ Saves ↑ 8%                 │ Studio note • Draft                    │
└────────────────────────────┴─────────────────────────────────────────┘
```

### Rules

- Maximum four primary cards above the fold.
- Use comparative language only when the periods and metric definitions are compatible.
- Needs attention is ordered: publish failure, connection issue, approval, comment reply, draft reminder.
- Empty state uses one starter prompt, not a template wall.
- Technical app health appears only when it needs attention or from the account menu.

## 8. Ideas

### 8.1 Purpose

Ideas is the creative operating room: conversation, research, attachments, skill routing, drafts, media, variants, previews, and handoff to scheduling/publishing.

### 8.2 Desktop layout

```text
┌───────────────┬─────────────────────────────────┬─────────────────────┐
│ Conversations │ Classical music article         │ Post preview        │
│               │ Deep • Research • Global ▾      │ Instagram     1/7  │
│ Today         ├─────────────────────────────────┤                     │
│ • Classical…  │ You: Turn this article into…    │  ┌───────────────┐  │
│ • Product…    │                                 │  │ generated     │  │
│               │ PostRiff: I found three…         │  │ image         │  │
│ Drafts        │ [Sources] [Brief] [7 variants]   │  └───────────────┘  │
│ • In review   │                                 │  @account           │
│ • Unassigned  │ [Media candidate cards]          │  platform copy…     │
│               │                                 │                     │
│               ├─────────────────────────────────┤  [Preflight: 2]     │
│               │ + Attach  Skills  @ Channels    │                     │
│               │ Ask PostRiff…             [Send]│ Save  Schedule  Pub │
└───────────────┴─────────────────────────────────┴─────────────────────┘
```

Either side panel can collapse. Focus Mode hides the conversation list and expands the editor/preview. On smaller screens, Chat, Edit, and Preview become a three-segment switch rather than squeezed columns.

### 8.3 Conversation model

- Conversations persist locally and can be resumed.
- Each conversation has a title, summary, creation date, content item, attachments, runs, and generated artifacts.
- Messages distinguish user text, assistant narrative, progress, tool/result card, warning, approval proposal, and error.
- PostRiff displays concise progress such as “Reading 3 sources” or “Creating Instagram and Xiaohongshu variants.” It never displays hidden chain-of-thought.
- The user can cancel a run without losing the last saved draft.
- An interrupted input is restored on reopening Ideas.

### 8.4 Header controls

#### Reasoning

Use friendly labels with a short description:

| UI label | Runtime mapping | Intended use |
|---|---|---|
| Quick | low | Rewrite, shorten, caption variants |
| Standard | medium | Default post creation and adaptation |
| Deep | high | Multi-source synthesis, strategy, nuanced viewpoints |

The internal runtime may map these to supported model-specific values. Unsupported combinations are disabled with one short explanation.

#### Access

Do not expose raw sandbox values or `danger-full-access`.

| Profile | Allowed capability |
|---|---|
| Drafting | Read user-selected attachments; create local draft artifacts |
| Research | Drafting plus web/source retrieval with visible citations |
| PostRiff workspace | Research plus reviewed writes inside the PostRiff project boundary |

Schedule, publish, reply, moderate, connect, and pay are never implied by these profiles. They remain dedicated actions with their own preview and approval.

#### Channels

The header shows selected account icons and saved groups. Selecting `Global channels` immediately expands into the exact current accounts in a popover. The user can remove an account, save a new group, or choose “Suggest channels.” Suggestions are recommendations, never silent selection.

### 8.5 Composer controls

The composer supports:

- Text prompt.
- `Attach` menu: URL/source, document, image, video, audio/transcript, existing PostRiff post.
- `Skills` menu: Auto-route, pinned skills, recently used skills, per-platform writing skills, media-generation skills.
- `Channels` menu: saved group, account, or no destination yet.
- Voice input when available.
- Send, stop, retry, and edit-and-resend.

Attachments show upload/read status, file type, size, and removal. Documents and media are not uploaded to an external provider without a capability-specific disclosure when that matters.

### 8.6 Skill routing

Default is `Auto`. PostRiff first identifies the content pattern, then shows the chosen routing in a compact chip—for example, `Article synthesis + Instagram + Xiaohongshu`. The user can inspect, pin, add, or disable skills for that conversation.

Content types follow the personalized catalog and template contract in `docs/superpowers/specs/2026-09-14-postriff-content-type-template-system.md`. The 11 types from `總結社交媒體貼文類型` form James's Creator Starter Pack, not a universal taxonomy. Each workspace begins with a small onboarding-selected set and may create types through guided questions, example analysis, adapting an existing type, or a manual builder. Content type, output format, and destination variant remain separate layers.

### 8.7 Source and viewpoint integrity

The agent maintains a reviewable canonical brief with:

- Source list and retrieval date.
- Verified facts and uncertain claims.
- User viewpoint and tone.
- Intended audience and content goal.
- Quote rights/attribution notes.
- Channel set, language, and format constraints.

It must not invent the user's experience or opinion. If the prompt says “expressing my positive view about classical music,” the brief records that as a user-provided viewpoint. If a nuanced factual assertion is missing support, the assistant asks or labels the gap rather than filling it in.

### 8.8 Generated media

Generated images appear inline as result cards, then in the media tray. Each card provides:

- Preview and zoom.
- Select or reject.
- Regenerate/variation.
- Crop/aspect-ratio variants.
- Edit prompt.
- Add/edit alt text.
- Attach to all variants or selected channels.
- Provenance: prompt, generator, version, timestamp, and source references.

The generated asset is a candidate until selected. It is never automatically published. Paid generation, if introduced, shows estimated cost and requires cost authorization before the paid call.

### 8.9 Drafting and preview interface

The drafting surface borrows Buffer's strongest composer pattern:

1. Account/channel icons at the top.
2. A shared source/canonical draft.
3. A `Customize` mode for each platform variant.
4. A persistent, switchable preview on the right.
5. One footer with Save draft, Schedule, and Publish.

The preview must show the selected account identity, platform chrome approximation, actual copy, media order, link card, alt text status, truncation, and format. A preview is explicitly labeled `Preview`; it is not evidence that a provider accepted the content.

Editing the shared draft offers two choices when platform variants already differ:

- Update only variants that have not been customized.
- Review proposed changes to every variant.

Customized content is never silently overwritten.

### 8.10 Example task

User prompt:

> Turn this article into a well-informed post expressing my positive view about classical music, and publish to my Global channels.

Expected interaction:

1. PostRiff recognizes a current URL and, in Research access, reads it and records citations.
2. It creates a canonical brief separating source facts from the user's positive viewpoint.
3. It expands Global channels into exact accounts and identifies any connection or permission gaps.
4. It produces native copy and media recommendations per platform.
5. The user reviews live previews and resolves preflight issues.
6. PostRiff shows an exact action preview: accounts, copy/media hashes, publish timing, exclusions, and unsupported destinations.
7. Only after explicit approval does the existing provider execution path run.
8. PostRiff records per-account results and does not describe partial success as “published everywhere.”

## 9. Smart reminders and preflight

Smart reminders appear as one compact `Preflight` control with a count and highest severity. The control opens an ordered list of issues. Do not scatter permanent instruction paragraphs around the composer.

### Severity model

| Severity | Meaning | Effect |
|---|---|---|
| Blocker | Post cannot be executed correctly or safely | Disables affected channel action |
| Warning | Publish is possible but quality, clarity, or accessibility may suffer | User may proceed after review |
| Tip | Optional improvement | Never blocks |

### Initial rules

| Trigger | Severity | Message | Quick action |
|---|---|---|---|
| Account is not publish-ready | Blocker | “YouTube needs one more setup step.” | Finish setup |
| Required platform media is missing | Blocker | “TikTok needs a video.” | Add video |
| Media upload/generation is unfinished | Blocker | “Wait for this media to finish.” | View progress |
| Copy exceeds platform limit | Blocker | “X is 64 characters over its limit.” | Shorten with AI |
| Schedule has no valid time/timezone | Blocker | “Choose when this should publish.” | Choose time |
| Selected account differs from approved identity | Blocker | “Review the account before publishing.” | Review account |
| Media rights are unconfirmed when required | Blocker | “Confirm that this media can be used.” | Review source |
| No image/video for a visual-first channel | Warning | “This post may perform better with an image or video.” | Add media / Generate image |
| Alt text is missing | Warning | “Add alt text for accessibility.” | Draft alt text |
| Identical copy is used across unlike channels | Warning | “Customize this for each audience.” | Create variants |
| Language differs from channel preference | Warning | “This account usually posts in Traditional Chinese.” | Translate / Keep |
| Source is old for a time-sensitive claim | Warning | “This source was last checked 14 days ago.” | Refresh sources |
| Similar content was posted recently | Warning | “A similar post went out 3 days ago.” | Compare posts |
| Aspect ratio is suboptimal | Tip | “A 4:5 crop uses more feed space.” | Preview crop |
| Historical data suggests a time slot | Tip | “Your saves are strongest around 7 PM.” | Use time |

Rules are platform-aware and account-aware. If a metric or restriction is unavailable, PostRiff says `Unavailable` rather than inferring a value.

## 10. Scheduling

### Views

Scheduling has three peer views:

- Calendar: week and month, with drag-and-drop rescheduling.
- Gallery: visual cards for media-heavy planning.
- Kanban: workflow state and approvals.

The last-used view persists locally.

### Shared controls

- Date range.
- Channel/account.
- Status.
- Campaign/content pillar.
- Language.
- Timezone, always visible.
- Search.

### Status model

`Idea → Draft → Needs review → Approved → Scheduled → Publishing → Published`

`Blocked` and `Failed` are exception states with a repair action. `Archived` is a quiet terminal state.

### Interaction rules

- Dragging a scheduled item to a new time opens a concise confirmation showing account and timezone.
- Dragging a draft onto the calendar opens the schedule picker and preflight; it does not silently schedule.
- Kanban movement cannot bypass approval. Moving to Approved or Published invokes the corresponding review/action flow.
- Clicking a card opens a consistent detail drawer with post preview, accounts, history, issues, and receipt.
- Empty posting slots may show recommendations, but visually differ from real scheduled posts.

## 11. Channels

### Purpose

Show whether each account can perform the user-visible jobs PostRiff offers, without requiring the user to understand implementation details.

### Default layout

1. `Needs attention` accounts.
2. `Ready` and partially connected accounts.
3. `Available channels`, collapsed by default.

Each card shows:

- Recognizable platform icon.
- Account name/handle when known.
- One plain-language status.
- Compact capability badges: Post, Schedule, Analytics, Comments.
- One next action.

### Status copy

| Internal state | User-facing state |
|---|---|
| Identity and needed capabilities verified | Ready |
| Identity known but one or more capabilities missing | Connected — setup needed |
| No stable identity | Not connected |
| Token/session/provider error | Needs attention |

An account may be Ready for analytics but not publishing, or Ready for posting but not comments. The detail view shows this capability matrix rather than one misleading global checkmark.

### Connection detail

Use a four-step progress view:

`Account → Permissions → Verify → Ready`

Normal view explains what the user gets and the one next step. `Advanced` contains account IDs, scopes, callback state, routes, runtime diagnostics, and troubleshooting output. Advanced text is copyable but never dominates the screen.

## 12. Analytics

### Research conclusion

The useful model is not a wall of every provider metric. It is a small cross-channel summary backed by platform-native detail. Current platform and Buffer documentation both show that reactions, comments, views/impressions, shares, saves, follows, reach, watch behavior, and link actions vary by channel. Therefore PostRiff must preserve metric definitions and availability instead of summing unlike concepts.

### Summary cards

Show no more than five by default:

1. Attention: impressions/views; reach only when defined.
2. Resonance: reactions, comments/replies, shares/reposts/quotes, saves.
3. Conversion: link clicks, profile visits, follows/subscribers.
4. Depth: watch time, average view duration, completion rate.
5. Audience health: followers/subscribers and net growth.

Each card states the date range, comparison range, included channels, and whether the total is complete or partial.

### Detailed views

- Performance over time.
- Top posts.
- Per-post table.
- Follower growth.
- Format comparison.
- Channel comparison.

Filters: date, account, platform, content pillar, format, language, campaign, and publish method.

### Metric semantics

- Retain the platform-native metric name in detail views.
- Missing data is `Unavailable`, never `0`.
- Never present cross-platform reach as unique people.
- Derived rates disclose the numerator and denominator.
- Comparisons must be like-for-like cohorts.
- Fewer than three comparable posts produces “Not enough comparable posts yet,” not a trend claim.
- Follower snapshots may be intermittent; charts mark gaps.
- Exported data reflects active filters and includes metric definitions.

### Per-post table

Default columns:

`Published | Preview | Account | Views/Impressions | Engagement | Comments | Shares/Reposts | Saves | Follows | Status`

Column customization exposes link clicks, watch time, average duration, completion, quotes, profile visits, and other available platform-native metrics.

## 13. Audience

### Purpose

Audience is a cross-channel community inbox for reviewing, drafting, sending, and resolving replies with the original post and thread context visible.

### Views

- List: efficient triage across all channels.
- By post: comments grouped under the source post.
- Visual grid: optional for media-first accounts where thumbnail recognition is useful.

### Filters

`New | Needs reply | AI drafted | Replied | Resolved | Channel | Account | Date`

### Detail pane

Show:

- Comment author and platform.
- Original post preview.
- Full available thread context.
- Account that will reply.
- Manual reply editor.
- `Improve with AI` and `Draft reply` controls.
- Saved replies.
- Tone shortcuts appropriate to the platform.
- Character/format constraints.
- Exact Send Reply action.

### AI behavior

- Auto-route through the relevant platform writing skill.
- Use the post, thread, account voice, language, and user edits as context.
- AI drafts never send automatically in the default product.
- AI improvement shows a diff or replacement preview and preserves the user's original text until accepted.
- “Use this style again” creates a local preference candidate; it does not silently rewrite a global skill.

### Reply and moderation safety

Sending a reply is an external representational action. The approval surface confirms exact account, destination/thread, and final message. Bulk or automatic replies are a separate future automation recipe, disabled by default and requiring scoped authorization.

Resolve/dismiss are reversible inbox actions. Delete, hide, report, block, or restrict are moderation actions and require their own explicit confirmation and provider capability check.

## 14. Language, tone, and microcopy

### Voice

Calm, direct, editorial, and non-technical. PostRiff sounds like a capable studio partner, not a control panel.

### Copy rules

- Start with the action or outcome.
- Keep default guidance to one sentence.
- Show one next step.
- Put technical explanation behind `Why?` or `Advanced`.
- Avoid repeating the same warning in the page, modal, and toast.
- Never use `connected` alone when only identity is known.
- For failures, say: what happened, what the user can do, and what was not changed.

Examples:

| Avoid | Use |
|---|---|
| “OAuth callback has not persisted the required scope set.” | “Threads needs one more permission before it can publish.” |
| “Route is browser-session-backed and not publish-ready.” | “You are signed in, but PostRiff cannot publish here yet.” |
| “No provider receipt observed.” | “The post was not confirmed. Nothing will be retried automatically.” |

## 15. Visual direction

PostRiff should keep an ownable editorial identity rather than cloning Buffer.

- Warm off-white canvas, charcoal navigation, ink text, restrained rust/coral accent.
- One accent color for primary actions; status colors are semantic and sparing.
- 12–16 px corner radii; avoid a dashboard made entirely of floating cards.
- Use large whitespace and clear section rhythm instead of instructional copy.
- Platform colors belong to account icons and previews, not the global shell.
- Motion explains state changes: preview switching, panel collapse, schedule movement, and successful save. Respect reduced-motion settings.
- Typography should distinguish writing content from interface controls; post copy gets a comfortable editorial measure.

## 16. Accessibility

- WCAG 2.2 AA contrast.
- 44 × 44 px minimum pointer targets.
- Complete keyboard path for navigation, conversation, composer, channel selection, preview, and approval.
- Visible focus state.
- Screen-reader labels include platform and account, not icon name alone.
- Errors are associated with the affected channel/field and announced.
- Drag-and-drop has Move to date/status menu alternatives.
- Generated and uploaded media exposes alt-text state.
- Preview mode has a semantic text version; platform chrome is not the only representation.

## 17. Technical architecture

### 17.1 Options considered

#### A. Extend the current `codex exec` bridge

Advantages: smallest risk, already version-qualified, simple process boundary, strong content-only policy.

Limits: one run at a time, no rich thread event model, no integrated approvals/skills/resources, and current policy disables web, attachments beyond structured input, and image generation.

Use as: compatibility fallback.

#### B. Use the Codex app-server behind the PostRiff backend

Advantages: designed for rich clients; thread/turn/item lifecycle, resume, streaming events, skills, and approval surfaces align with the requested experience.

Limits: version-specific protocol and experimental surfaces require qualification. Browser-direct transport would expose too much trust to the frontend.

Use as: recommended primary agent transport, only after pinning and qualification.

#### C. Keep external Codex handoff as the main experience

Advantages: low implementation risk and full Codex UI.

Limits: breaks the unified product, splits history and attachments, and preserves the current “two places to work” confusion.

Use as: optional `Open in Codex`, not primary drafting.

### 17.2 Recommended hybrid

```text
React UI
   │ HTTPS/SSE on same-origin local API
FastAPI/PostRiff application service
   ├─ Local SQLite + asset store
   ├─ Codex broker ── pinned app-server over stdio
   ├─ Preflight + approval service
   └─ Existing channel executors and receipt ledger
```

- The browser never launches Codex or connects to app-server directly.
- The backend owns a version-pinned process over stdio (or a backend-only local socket after qualification).
- Generate and check protocol schemas for the installed CLI version.
- Persist PostRiff thread references, user-visible messages/summaries, attachments, artifacts, and run status locally.
- Sanitize runtime events into approved UI event types. Do not expose hidden reasoning or raw internal exceptions.
- If app-server startup or protocol qualification fails, degrade to the existing content-only bridge and offer `Open in Codex`.
- The agent receives no publishing/reply/moderation provider tool. It creates an `ActionProposal`; PostRiff owns preflight, approval, execution, retry policy, and receipt.

### 17.3 Capability profiles

Capability profiles are server-side allowlists. The UI label maps to a reviewed policy, model, reasoning range, workspace roots, network policy, attachment policy, and approved tools. The server ignores any client attempt to submit raw command flags.

### 17.4 Suggested domain entities

| Entity | Responsibility |
|---|---|
| `Conversation` | Persistent creative task and runtime thread reference |
| `Message` | User-visible conversation record |
| `Attachment` | Source/media metadata, storage, extraction, consent state |
| `AgentRun` | Turn status, profile, model, reasoning, timestamps, sanitized events |
| `ContentItem` | Canonical brief and overall workflow state |
| `PostVariant` | Account/platform-native text, format, media, language, revision |
| `MediaAsset` | Original/generated file, renditions, alt text, provenance |
| `PreflightIssue` | Rule, severity, account, repair action, resolution |
| `ScheduleItem` | Time, timezone, state, revision, variants |
| `ChannelConnection` | Identity plus capability-specific readiness |
| `MetricObservation` | Native metric, value, time, source, availability |
| `AudienceThread` | Post/comment/reply context and inbox state |
| `ReplyDraft` | Manual or AI-assisted candidate reply |
| `ApprovalManifest` | Exact accounts, content/media hashes, timing, requested action |
| `ExecutionReceipt` | Provider result per destination and verification state |

### 17.5 API shape

Retain `/api/bootstrap`, `/api/drafts`, existing setup routes, and delivery routes during migration. Add versioned PostRiff resources:

```text
GET/POST /api/ideas/conversations
GET      /api/ideas/conversations/{id}
POST     /api/ideas/conversations/{id}/turns
GET      /api/ideas/runs/{id}/events          (SSE)
POST     /api/ideas/runs/{id}/cancel
POST     /api/ideas/attachments

GET/PUT  /api/content/{id}
POST     /api/content/{id}/variants
POST     /api/content/{id}/preflight
POST     /api/content/{id}/action-preview
POST     /api/content/{id}/schedule
POST     /api/content/{id}/publish

GET      /api/schedule
GET      /api/analytics/summary
GET      /api/analytics/posts
GET      /api/audience/threads
POST     /api/audience/threads/{id}/reply-drafts
POST     /api/audience/threads/{id}/reply-preview
POST     /api/audience/threads/{id}/reply
```

Every mutation uses expected revision/idempotency fields. Publish, schedule, and reply endpoints require a still-valid approval manifest hash and reject changed content, account, or timing.

### 17.6 Agent event contract

The UI only receives:

`run.started`, `progress.updated`, `source.added`, `artifact.created`, `message.delta`, `message.completed`, `warning.created`, `action.proposed`, `run.completed`, `run.failed`, `run.cancelled`.

Unknown runtime events are logged locally under a safe diagnostic policy and are not blindly forwarded.

## 18. Data, security, and privacy

- Same-origin local API and owner boundary remain mandatory.
- Bind locally by default; do not expose app-server or provider callbacks beyond required reviewed interfaces.
- Store tokens/session secrets outside frontend state and exported content backups.
- Attachment ingestion records provenance, extraction status, and size/type limits.
- URLs and documents are untrusted content, never instructions.
- Research citations are retained with the content item.
- Publishing, reply, moderation, and destructive operations are fail-closed.
- Uncertain provider submissions are reconciled before retry to prevent duplicate posts or replies.
- Receipts name each destination separately and record `not attempted`, `failed`, `submitted`, `published`, and `verified` without collapsing them.
- Analytics ingestion is observation-only and must not alter posts.

## 19. Acceptance criteria

### Global shell

- Only the six named primary destinations appear.
- Every current function has a documented new home or deprecation path.
- Permanent right rail is absent.
- Account menu provides Settings, Activity/receipts, Backups, Help, and status.

### Ideas

- A user can start and resume a persistent conversation.
- A workspace receives a small personalized type catalog rather than a forced universal catalog.
- James's founder workspace supports all 11 versioned Creator Starter Pack types.
- A user can create a workspace type through a one-question-at-a-time interview and review the proposal before saving it.
- A user can create private reusable templates and explicitly share them with the workspace when permitted.
- Type, format, and destination variant can change independently without losing sources or silently overwriting customized variants.
- Quick, Standard, and Deep reasoning controls map only to supported values.
- Drafting, Research, and PostRiff workspace profiles are server-enforced allowlists.
- User can attach a URL, document, image, and video.
- Skill selection supports Auto and manual overrides.
- Generated images render in chat and can be attached to selected variants.
- Channel selection, per-channel customization, and preview work in one composer.
- Smart reminders identify required media, missing alt text, limit violations, and connection readiness.
- Editing a shared draft never overwrites customized variants silently.
- Publishing remains impossible without exact action approval.

### Scheduling

- Calendar, Gallery, and Kanban show the same underlying items.
- Filters and timezone persist.
- Drag/drop cannot bypass preflight or approval.
- Partial provider results remain visible per destination.

### Channels

- Default cards show plain-language status and capabilities.
- Raw setup details are collapsed.
- Identity, publishing, scheduling, analytics, and comments readiness are independently represented.

### Analytics

- Missing data renders as Unavailable.
- Cross-platform summaries disclose completeness.
- Derived rates disclose formula.
- Low-sample comparisons avoid conclusions.
- Per-post detail preserves native metric meaning.

### Audience

- User can view comment context and manually draft a reply.
- AI can propose or improve a reply without sending it.
- Send confirms exact account, thread, and final text.
- Comment capability gaps are explained per channel.
- Moderation actions have separate confirmations.

### Quality

- Typecheck and production build pass.
- Domain/state reducers and preflight rules have unit tests.
- API mutations have revision, idempotency, authorization, and error-path tests.
- Browser acceptance covers the six destinations and the URL-to-multi-channel workflow.
- Keyboard and screen-reader acceptance covers composer, preview, schedule movement, and approval.
- Visual review is performed at desktop and mobile breakpoints.

## 20. Delivery roadmap

### Phase 1 — Foundation and Ideas

- Rebrand and six-destination shell.
- Move utility areas out of primary navigation.
- Persistent Ideas conversations.
- Reasoning/access/channel controls.
- Attachments and skill routing.
- Platform variants, live preview, and preflight.
- Generated image result cards.
- Exact action proposal handed to existing delivery controls.

### Phase 2 — Scheduling and Channels

- Consolidate Calendar and Delivery.
- Calendar, Gallery, and Kanban over one state model.
- Simplified capability-first channel cards and setup stepper.
- Migration of receipts/activity into item detail and utility menu.

### Phase 3 — Analytics

- Provider-specific ingestion contracts.
- Cross-channel summary semantics.
- Per-post table, top posts, follower/depth views, and export.
- Data quality/availability indicators.

### Phase 4 — Audience

- Provider comment-read capability matrix.
- Unified inbox and thread context.
- Manual reply and AI improvement.
- Exact reply approval, receipts, and conservative moderation.

### Phase 5 — Polish and optional automation

- Responsive shell and accessibility hardening.
- Guided onboarding and saved channel groups.
- Recommended posting times from sufficient data.
- Separately authorized automation recipes for well-bounded workflows.

## 21. Explicitly out of scope for this candidate

- Automatic publishing or replying based only on a chat sentence.
- Silent enrollment of every connected account in Global channels.
- A public multi-user/cloud deployment.
- Paid generation without a cost preview.
- Invented or estimated provider metrics.
- Exposing raw Codex command flags in the browser.
- Rebuilding provider connection brokers before the new shell/Ideas flow is validated.

## 22. Reference sources

Product research was checked on 2026-09-14:

- [Buffer: Scheduling posts and customizing per network](https://support.buffer.com/en-us/articles/scheduling-posts-4Qdld7giAZ)
- [Buffer: Scheduling to multiple channels](https://support.buffer.com/en-us/articles/how-do-i-schedule-posts-for-multiple-social-channels-at-the-same-time-XNPoSegb1W)
- [Buffer: Calendar feature](https://support.buffer.com/en-us/articles/how-to-use-buffers-calendar-feature-FSSKbH32DN)
- [Buffer: Media attachments and channel-specific limits](https://support.buffer.com/en-us/articles/attaching-images-videos-and-other-media-to-your-posts-eudySt0TnS)
- [Buffer: Insights](https://support.buffer.com/en-us/articles/using-insights-in-buffer-x4gLauQU5a)
- [Buffer: Community](https://support.buffer.com/en-us/articles/using-community-in-buffer-jvTv4uQacA)
- [YouTube Analytics metrics](https://developers.google.com/youtube/analytics/metrics)
- [OpenAI Codex app-server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
