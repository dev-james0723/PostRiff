# PostRiff Content-Type and Template System Specification

**Status:** Required product specification for the PostRiff Ideas rebuild. This document defines the content-type/template contract; it does not claim the interface or generation runtime is implemented.

**Date:** 2026-09-14

**Authoritative user reference:** Codex chat titled `總結社交媒體貼文類型`, thread `01a09f45-73c6-77b0-b59a-f11e908a010a`.

**Related specifications:**

- `docs/superpowers/specs/2026-09-14-postriff-product-design.md`
- `docs/superpowers/specs/2026-09-14-postriff-saas-product-architecture.md`

## 1. Decision

PostRiff must support a **personalized content-type system**, not impose one universal taxonomy on every customer.

The 11 “mother content” families identified in `總結社交媒體貼文類型` are the required **James Creator Starter Pack** and migration baseline for the founder workspace. They are not the complete or default catalog for every PostRiff customer. A restaurant, nonprofit, realtor, musician, agency, and software founder should each see a different small set of useful starting types.

Every workspace can combine four sources:

1. A small universal core supplied by PostRiff.
2. An optional industry or role starter pack.
3. AI-suggested content types derived from onboarding and actual work.
4. Workspace-created content types and reusable templates.

PostRiff must not model these as 33 unrelated platform templates. It uses three distinct layers:

```text
Content type — what the user wants to say
       ↓
Format — how the story should be expressed
       ↓
Destination variant — how a specific platform/account receives it
```

A **content type** describes the recurring editorial job: for example, teach a method, tell a customer story, announce an event, or share a personal reflection. A **template** is an editable recipe inside that type. It supplies questions, default structure, inputs, skills, formats, channel suggestions, and preflight checks. It is not frozen copy and it does not publish anything.

The Ideas experience must also let a user:

- Start blank and allow the agent to suggest a type.
- Select a type before writing.
- Change the type without losing entered material.
- Choose a recommended format or another supported format.
- Create native variants for explicit destinations.
- Create a new content type through guided questions, from a blank definition, by importing an example, or by adapting an existing type.
- Save a successful setup as a private reusable template.
- See PostRiff, starter-pack, workspace, and private-template ownership separately.
- Hide or archive irrelevant suggested types without deleting old drafts.

## 2. Why this model

James's content world is broader than promotional posts: it joins music, software building, technology, learning, personal development, community, events, and institutional work. The same idea may become an X observation, Instagram carousel, Xiaohongshu note, LinkedIn article, YouTube essay, or community poll. Other users will have different editorial jobs, vocabulary, evidence, risks, and calls to action.

The content family therefore comes first. Platform selection comes later. The catalog itself is workspace-specific and evolves with the user. This prevents the Ideas page from becoming a large catalog of duplicated platform cards and preserves PostRiff's core principle: one canonical idea, native outputs.

## 3. Catalog layers and ownership

PostRiff resolves a workspace catalog from these layers, in order:

| Layer | Purpose | Editable by customer | Default visibility |
|---|---|---|---|
| Universal core | A few broadly useful editorial jobs such as update, teach, story, promote, and engage | Can hide or adapt; cannot mutate global source | Only onboarding-relevant items |
| Starter pack | Role/industry examples such as Creator, Restaurant, Coach, Musician, SaaS, Nonprofit, or Agency | Can install, hide, duplicate, or adapt | Opt-in during onboarding |
| Workspace type | A team-defined editorial job and question flow | Yes, with workspace permission | Visible to that workspace |
| Personal template | One person's reusable defaults inside a type | Yes, by owner unless shared | Private by default |

The UI must show provenance such as `PostRiff`, `Creator starter pack`, `Your workspace`, or `Private`. Installing a pack copies references and workspace overrides; it never gives one customer another customer's data, voice, examples, or private skills.

There is no requirement that every workspace have exactly 11 active types. A new workspace should normally begin with three to six relevant types. `Browse all` may offer more packs, but the Ideas home remains quiet.

## 4. Optional content pillars

Each workspace may optionally define content pillars that organize its body of work; pillars do not replace post type. The following are James's founder-workspace pillars, not universal fields:

| Pillar ID | Label | Meaning |
|---|---|---|
| `building_in_public` | Building in public | Making products, systems, content, and a one-person operation in public |
| `learning_and_thinking` | Learning and thinking | Research, interpretation, teaching, technology, music, and intellectual exploration |
| `becoming_yourself` | Becoming yourself | Identity, growth, discipline, loneliness, creativity, meaning, and daily life |

A music practice reflection could be `personal_reflection` with the `becoming_yourself` and `learning_and_thinking` pillars. A My Best Life OS feature explanation could be `product_feature_launch` with `building_in_public`.

## 5. James Creator Starter Pack

The pack is versioned product data. These 11 entries are required for James's founder workspace and serve as a high-quality Creator starter pack. They must not be automatically installed or shown to unrelated customers.

### CT01 — Quick thought or original quote

**ID:** `quick_thought_quote`

**Label:** Quick thought / Original quote

**Purpose:** Express one concise observation, tension, question, realization, or line drawn from the user's own work.

**Useful inputs:** A thought, journal line, paragraph, article/video excerpt owned or authored by the user, or a clearly attributed quotation.

**Recommended formats:** Short text, quote card, image + caption, Community Post.

**Typical destinations:** X, Threads, Bluesky, Instagram, Xiaohongshu, YouTube Community.

**Default structure:**

1. The thought or tension.
2. One line of context when needed.
3. Optional open question; no forced call to action.

**Smart checks:** Attribution, ownership/source, accidental generic motivational language, and unsupported claim.

**Critical rule:** Quote is a format as well as a content type. PostRiff should prefer a real line from the user's source, post, talk, or reflection. It must not generate generic filler quotes merely to fill a calendar.

### CT02 — Personal reflection or life moment

**ID:** `personal_reflection`

**Label:** Personal reflection / Life moment

**Purpose:** Tell a true personal story or reflection involving growth, loneliness, changing direction, discipline, creative pressure, or an ordinary meaningful moment.

**Useful inputs:** Personal note, photo, voice note, journal passage, event, or remembered scene.

**Recommended formats:** Image + caption, short text, diary-style note, short narrated video, Story.

**Typical destinations:** Instagram, Facebook, Xiaohongshu, Threads, Bluesky, LinkedIn where professionally relevant.

**Default structure:**

1. Concrete moment.
2. Felt tension or change.
3. Present interpretation without pretending complete resolution.

**Smart checks:** Privacy, names/identities, sensitive personal detail, invented experience, and tone authenticity.

### CT03 — Article or news summary with commentary

**ID:** `article_news_commentary`

**Label:** Article/news summary + my view

**Purpose:** Explain what happened, why it matters, and the user's informed interpretation or open question.

**Useful inputs:** URL, article, announcement, paper, report, transcript, or current event plus the user's initial stance.

**Recommended formats:** Quick take, thread, article, carousel, image + caption, link post, visual explainer.

**Typical destinations:** X, LinkedIn, Instagram, Facebook, Xiaohongshu, Threads, Bluesky, Reddit when community-relevant.

**Default structure:**

1. What happened or what the source argues.
2. What is verified and what remains uncertain.
3. Why it matters to the chosen audience.
4. The user's view, implication, or unresolved question.

**Smart checks:** Source retrieval date, citation, freshness, source/POV separation, unsupported extrapolation, direct-quote length/attribution, and link preview.

**Critical rule:** The default is not a neutral summary. The PostRiff-native result is `what happened → why it matters → how I see it / what I still question`. Neutral summary remains an explicit option.

### CT04 — Deep point-of-view article

**ID:** `deep_point_of_view`

**Label:** Deep point of view

**Purpose:** Develop a defensible thesis about technology, AI and creativity, music and identity, psychology, autonomy, or life systems.

**Useful inputs:** Thesis, notes, sources, prior posts, research folder, talk, or transcript.

**Recommended formats:** Long article, essay, thread, document post, carousel, long video, podcast/video outline.

**Typical destinations:** X Articles, LinkedIn, Zhihu, note, Naver Blog, Reddit where appropriate, YouTube, Bilibili.

**Default structure:**

1. Thesis or central tension.
2. Evidence and counterpoint.
3. User's synthesis.
4. Practical or human implication.

**Smart checks:** Thesis clarity, evidence coverage, counterargument, citation, invented authority, and platform length/structure.

### CT05 — Building in public

**ID:** `building_in_public`

**Label:** Building in public

**Purpose:** Share progress, decisions, experiments, failed attempts, tradeoffs, screenshots, demos, or lessons from building products and a one-person operation.

**Useful inputs:** Changelog, screenshot, commit/receipt, decision note, failure, experiment, metric, or demo clip.

**Recommended formats:** Screenshot + explanation, build log, carousel, demo clip, behind-the-scenes short video, thread.

**Typical destinations:** X, Threads, Bluesky, LinkedIn, Instagram, YouTube Shorts/Community, Xiaohongshu.

**Default structure:**

1. What was attempted.
2. What actually happened.
3. Decision/tradeoff or lesson.
4. What comes next, clearly labeled as intention.

**Smart checks:** Local preview versus real release, result evidence, confidential identifiers, customer data, unverified completion, and accidental announcement before readiness.

### CT06 — Tutorial, how-to, or use case

**ID:** `tutorial_how_to`

**Label:** Tutorial / How-to / Use case

**Purpose:** Teach a workflow, feature, tool, music practice, creator system, or repeatable method.

**Useful inputs:** Tested steps, source material, screenshots, demo, code/tool output, lesson notes, or frequently asked question.

**Recommended formats:** Step-by-step note, carousel, document post, short tutorial video, long tutorial, screen recording.

**Typical destinations:** Xiaohongshu, Instagram, LinkedIn, YouTube, Bilibili, TikTok/Reels/Shorts, Zhihu, Reddit where relevant.

**Default structure:**

1. Outcome and intended user.
2. Requirements or starting state.
3. Ordered steps.
4. Expected result and limitations.

**Smart checks:** Whether steps were actually tested, missing prerequisites, unsafe/paid/destructive steps, outdated interfaces, platform media needs, and misleading time/result claims.

### CT07 — Product or feature launch

**ID:** `product_feature_launch`

**Label:** Product / Feature launch

**Purpose:** Explain a product, capability, release, or improvement through why it exists, how it works, evidence, onboarding, and feedback.

**Useful inputs:** Product brief, release receipt, screenshots, demo, changelog, availability, audience, and call to action.

**Recommended formats:** Launch post, carousel, demo video, build story, tutorial, FAQ, follow-up feedback post.

**Typical destinations:** LinkedIn, X, Instagram, Facebook, Threads, YouTube, TikTok, Xiaohongshu, communities where permitted.

**Default structure:**

1. Problem or reason for building.
2. What is available now.
3. Evidence/demo and limitation.
4. One clear next action.

**Smart checks:** Candidate versus launched state, live availability, pricing accuracy, product claims, destination/link, disclosure, and repeated identical promotion.

**Critical rule:** A launch is a content sequence with distinct jobs—why, behind the scenes, demo, announcement, tutorial, and feedback—not one advertisement copied repeatedly.

### CT08 — Music, performance, or teaching

**ID:** `music_performance_teaching`

**Label:** Music / Performance / Teaching

**Purpose:** Share practice, interpretation, recording, performance, teaching, repertoire, artistic process, or the human meaning of music.

**Useful inputs:** Performance clip, rehearsal photo, score/notes, teaching moment, recording, repertoire context, or reflection.

**Recommended formats:** Performance clip, rehearsal photo + caption, tutorial short, long performance/essay video, article, visual note.

**Typical destinations:** YouTube, Bilibili, Instagram, Facebook, TikTok/Reels/Shorts, Xiaohongshu, LinkedIn where professionally relevant.

**Default structure:**

1. Musical or human moment.
2. Interpretation, craft, or teaching insight.
3. What the listener/student may notice.

**Smart checks:** Music/performance rights, performer/composer credits, event accuracy, student/privacy consent, recording state, and invented interpretation history.

### CT09 — YouTube derivative content

**ID:** `youtube_derivative`

**Label:** YouTube extension

**Purpose:** Extend one long-form video into platform-native entry points, clips, questions, and follow-up discussion.

**Useful inputs:** Published or draft video, transcript, title/thumbnail candidates, chapters, clips, quotes, and central question.

**Recommended formats:** Community Post, Short/Reel/TikTok, quote card, clip, thread, image + caption, Facebook preview.

**Typical destinations:** YouTube Community/Shorts, Instagram, TikTok, X, Threads, Facebook, LinkedIn when relevant, Bilibili.

**Default structure:**

1. One self-contained question, insight, or moment.
2. Native value for the destination.
3. Optional path to the long-form video.

**Smart checks:** Source-video state, timestamp accuracy, quote/transcript fidelity, clip rights, title/link availability, and whether the derivative works without watching the full video.

### CT10 — Community Q&A or discussion

**ID:** `community_q_and_a`

**Label:** Community Q&A / Discussion

**Purpose:** Answer a real question, seek feedback, open a discussion, run a poll, or respond to a community's actual context.

**Useful inputs:** Question, comment thread, subreddit/community rules, customer feedback, poll choices, or discussion prompt.

**Recommended formats:** Answer, discussion post, poll, Community Post, AMA prompt, short response video.

**Typical destinations:** Reddit, Zhihu, Dcard, Discord, Telegram, YouTube Community, Facebook Groups, LinkedIn, Threads.

**Default structure:**

1. Acknowledge the actual question/context.
2. Give a useful answer or clear prompt.
3. Invite a specific kind of contribution without engagement bait.

**Smart checks:** Community rules, promotional tone, missing thread context, privacy, unsupported advice, poll clarity, and whether a reply is a representational external action.

### CT11 — Event, service, or institutional update

**ID:** `event_service_institutional_update`

**Label:** Event / Service / Institutional update

**Purpose:** Communicate an event, performance, collaboration, service, case, institutional milestone, or operational update.

**Useful inputs:** Confirmed event/service details, location, date/time/timezone, collaborators, registration link, availability, images, and approved institutional copy.

**Recommended formats:** Event post, announcement graphic, image + caption, LinkedIn update, Google Business update, community broadcast, reminder, recap.

**Typical destinations:** Facebook, Instagram, LinkedIn, Google Business Profile, Telegram, Discord, WhatsApp/LINE channels, websites and relevant communities.

**Default structure:**

1. What is happening and why it matters.
2. Exact who/where/when.
3. One next action.
4. Accessibility or eligibility detail where relevant.

**Smart checks:** Date/time/timezone, address/link, availability, collaborator approval, institutional identity, prices/terms, audience eligibility, and announcement versus draft state.

## 6. Required format layer

The content type does not hard-code the format. The second selector contains these format families:

| Format ID | UI label | Output contract |
|---|---|---|
| `short_text` | Short text | Concise feed post or conversational update |
| `image_caption` | Image + caption | One or more images with complementary caption |
| `quote_card` | Quote card | Attributed line plus designed visual and supporting caption |
| `carousel` | Carousel | Ordered cover/body/conclusion slides plus caption |
| `article` | Article | Structured long-form text with title/deck/body/source notes |
| `short_video` | Short video | Hook, spoken/script beats, shot/visual plan, captions, post copy |
| `long_video` | Long video | Thesis/story outline, script/chapters, packaging and derivative plan |
| `story` | Story | Ephemeral frame sequence with optional interaction element |
| `community_post` | Community Post | Platform-native community update or question |
| `poll` | Poll | Prompt, mutually clear options, duration/visibility where supported |

Provider-specific subformats—Reel, Short, Pin, document post, link post, note, thread, broadcast, or event—are destination adaptations of these families, not additional top-level content types.

## 7. Ideas-page experience

### 7.1 Entry points

The Ideas page provides one primary composer and four quiet ways to start:

```text
What do you want to make?
[ Ask PostRiff…                                      ] [Send]

Start with:  [A source]  [A post type]  [Media]  [Previous post]
For you:     Customer story · Practical tip · Behind the scenes
```

The page must not open with a universal catalog competing for attention. It shows up to four contextual suggestions based on the workspace profile, goals, recent work, selected source, and destination. `Browse post types` opens the workspace library, and `Create a type` starts the guided builder.

### 7.2 Browse library

The library supports:

- Search by label, goal, source, format, or platform.
- `For you`, `Workspace`, `Starter packs`, `Recent`, `Saved by me`, and optional pillar filters.
- Compact cards with title, one-sentence job, and two or three recommended formats.
- Clear provenance and visibility: PostRiff, installed pack, workspace, shared, or private.
- Keyboard navigation and accessible descriptions.
- No platform logos as the primary categorization.

Selecting a card closes the library and starts a content-type instance inside the current conversation. It does not create a disconnected form or a second draft system.

### 7.3 Minimal brief

The selected type provides a conversational checklist, not a mandatory long form. The agent asks at most one blocking question at a time and may draft around explicitly unknown optional fields.

Every type instance records:

- `contentTypeId` and catalog version.
- Optional content pillar(s).
- User goal and audience.
- User viewpoint/voice source.
- Source and evidence inputs.
- Selected format.
- Language(s).
- Explicit destination accounts or none yet.
- Unknowns and required reviews.

The content-type chip remains visible in the Ideas header and is editable. Changing it produces a reviewable brief transformation; it does not delete sources, prompt text, attachments, or customized variants.

### 7.4 Agent suggestion

If the user starts blank, the agent may suggest up to three content types with a short reason:

```text
This looks most like:
• Article/news summary + my view — you attached a current article and added a stance
• Deep point of view — if you want a longer thesis
• Tutorial — if the goal is to teach a repeatable method
```

The user chooses one, asks PostRiff to create a better-fitting type, or continues without a type. The agent must not silently classify a post and hide the choice.

### 7.5 Template workflow

After selecting a content type, the user can:

1. Use the system template as-is.
2. Adjust tone, language, format, channels, CTA policy, source rules, or visual direction for this post.
3. Save selected adjustments as `My template`.
4. Name and describe the private template.
5. Keep it private or share it with the workspace if permitted.

The UI distinguishes:

- **Post type:** A recurring editorial job from PostRiff, a starter pack, or the workspace.
- **System template:** Versioned neutral workflow supplied by PostRiff.
- **Workspace type:** A workspace-owned editorial job and question set.
- **My template:** User-owned configuration referencing a content type/version; private by default and shareable with permission.
- **Draft:** One content item created from a template.

Private voice examples, profile memories, credentials, and customer content never enter the system template.

### 7.6 Template card actions

System type card:

- `Use this type`
- `Preview structure`
- `See recommended formats`

Private template card:

- `Use template`
- `Edit settings`
- `Duplicate`
- `Archive`
- `Export configuration`

Archiving a private template is recoverable and does not alter existing drafts. Updating a system template creates a new version and proposes migration; it never silently changes a customer's saved template or active draft.

## 8. Create-a-type experience

Users should not need to understand schemas or prompt engineering. `Create a type` offers four paths:

1. **Answer a few questions** — recommended for most users.
2. **Use example posts** — PostRiff analyzes user-supplied examples and proposes a reusable structure.
3. **Adapt an existing type** — duplicate a PostRiff, starter-pack, or workspace type and edit it.
4. **Build manually** — an advanced path with complete control.

### 8.1 Guided interview

The agent asks one question at a time and normally finishes in three to seven answers:

1. What kind of post do you want to make repeatedly?
2. Who is it for, and what should they understand, feel, or do?
3. What source material do you usually start with?
4. What must every post include?
5. What should it avoid or never claim?
6. Which formats and destinations are common?
7. What evidence, approval, or media is required before publishing?

Questions adapt to earlier answers. A simple type can finish after three questions; sensitive or regulated use cases require explicit evidence and approval questions. Optional answers may remain unknown.

### 8.2 AI proposal and review

PostRiff converts the answers into a reviewable proposal containing:

- Name and one-sentence purpose.
- When to use and when not to use it.
- Required and optional inputs.
- Default story structure.
- Recommended formats and destinations.
- Tone/voice references without copying private data into global definitions.
- Smart reminders and blockers.
- Suggested skills by stable ID, subject to workspace availability and permission.
- Two fixture examples generated from synthetic data.

The user can edit every visible field, test the type on a sample idea, and compare the result with `Start blank`. The type is saved only after explicit confirmation. Creating it does not generate paid media, schedule, or publish.

### 8.3 Learning without silent mutation

PostRiff may notice recurring work and suggest: `You have made four posts with this structure. Save it as a type?` The user must opt in. The system may propose improvements after repeated edits, but never silently changes a workspace type, private template, active draft, or approved variant.

Type quality signals include repeated reuse, completion rate, amount of rewriting, preflight failures, and explicit user feedback. Engagement metrics may inform recommendations, but do not automatically redefine the user's editorial strategy.

### 8.4 Starter-pack onboarding

Onboarding asks about role/industry, primary goals, audience, recurring source material, preferred channels, and posting frequency. It then recommends one pack and three to six types. The user may remove any suggestion and add another before finishing.

Examples:

- Restaurant: menu spotlight, chef story, customer moment, event/promotion, behind the scenes.
- Realtor: listing story, neighborhood guide, market explanation, client education, success story.
- Nonprofit: impact story, campaign update, volunteer spotlight, event, transparent progress report.
- Coach: teaching insight, client-safe case pattern, exercise, personal reflection, offer explanation.
- SaaS team: product education, use case, release update, customer story, building in public.

These are optional packs, not hard-coded assumptions about every customer.

## 9. Platform adaptation rules

Content type guides the story; platform skills control the native expression.

Examples:

- `personal_reflection + image_caption + Instagram` prioritizes the visual moment and a caption that adds what the image cannot say.
- `personal_reflection + image_caption + Facebook` may use the same approved image but provides more context and conversational framing; it is not a copy of the Instagram caption.
- `article_news_commentary + carousel + Xiaohongshu` becomes a cover-first note in natural Simplified Chinese with a softer promotional posture.
- `article_news_commentary + short_text + X` becomes a sharp take or thread with source link and uncertainty preserved.
- `building_in_public + image_caption + LinkedIn` focuses on decision, tradeoff, and professional implication without generic founder language.
- `community_q_and_a + article + Reddit` responds to the actual community and its rules rather than dropping promotional copy.

Selecting several destinations creates independent variants linked to one canonical brief. A later canonical edit updates only non-customized variants automatically; customized variants receive an `Update available` review state.

## 10. Content-type smart reminders

In addition to platform/media preflight, content-type rules create contextual reminders:

| Content type | Required contextual checks |
|---|---|
| Quick thought/quote | Own words or clear attribution; avoid generic filler |
| Personal reflection | Privacy, invented experience, named-person consent/context |
| Article/news commentary | Source, freshness, verified facts, user viewpoint separation |
| Deep point of view | Thesis, evidence, counterpoint, unsupported authority |
| Building in public | Candidate/preview versus real result; confidential data |
| Tutorial/how-to | Steps tested, prerequisites, risk/cost, expected result |
| Product/feature launch | Availability, claim evidence, pricing/link accuracy |
| Music/performance/teaching | Music/recording rights, credits, student/privacy consent |
| YouTube extension | Source-video state, timestamps, transcript/quote fidelity |
| Community Q&A/discussion | Thread context, community rules, engagement bait, advice risk |
| Event/service/institutional | Exact date/time/timezone, place/link, identity, availability |

These reminders use Blocker, Warning, and Tip severity. They remain compact under the existing Preflight control.

## 11. Data contracts

### 11.1 Content type definition

```ts
interface ContentTypeDefinition {
  id: ContentTypeId
  version: string
  origin: 'postriff' | 'starter_pack' | 'workspace'
  originId?: string
  workspaceId?: string
  visibility: 'catalog' | 'workspace' | 'private'
  label: string
  shortLabel: string
  description: string
  defaultStructure: readonly BriefSectionDefinition[]
  recommendedFormatIds: readonly ContentFormatId[]
  recommendedPlatformIds: readonly string[]
  requiredInputKinds: readonly InputKind[]
  optionalInputKinds: readonly InputKind[]
  skillRouteIds: readonly string[]
  preflightRuleIds: readonly string[]
  createdBy?: string
  status: 'active' | 'deprecated'
}
```

### 11.2 Type identifiers and namespaces

```ts
type ContentTypeId = string

// Examples:
// postriff:teach
// pack.creator:article_news_commentary
// workspace_abc:founder_weekly_build_log
```

IDs are immutable and namespaced by origin. The 11 James/Creator IDs remain stable inside the `pack.creator` namespace; application code must not use an exhaustive union that prevents workspace-defined types.

### 11.3 Format identifiers

```ts
type ContentFormatId =
  | 'short_text'
  | 'image_caption'
  | 'quote_card'
  | 'carousel'
  | 'article'
  | 'short_video'
  | 'long_video'
  | 'story'
  | 'community_post'
  | 'poll'
```

### 11.4 Private template

```ts
interface WorkspacePostTemplate {
  id: string
  workspaceId: string
  name: string
  description: string
  contentTypeId: ContentTypeId
  contentTypeVersion: string
  ownerUserId: string
  visibility: 'private' | 'workspace'
  overrides: {
    pillarIds?: string[]
    formatId?: ContentFormatId
    languageIds?: string[]
    accountIds?: string[]
    toneProfileId?: string
    sourcePolicy?: string
    ctaPolicy?: string
    visualDirection?: string
  }
  revision: number
  archived: boolean
}
```

The server validates every enum/reference and ignores no unknown override silently.

## 12. API requirements

Local/founder form:

```text
GET      /api/content-types
GET      /api/content-formats
GET      /api/content-type-packs
POST     /api/content-type-packs/{packId}/install
POST     /api/ideas/content-types/propose
GET/POST /api/ideas/content-types
GET/PUT  /api/ideas/content-types/{contentTypeId}
POST     /api/ideas/content-types/{contentTypeId}/archive
POST     /api/ideas/content-types/{contentTypeId}/test
GET/POST /api/ideas/post-templates
GET/PUT  /api/ideas/post-templates/{templateId}
POST     /api/ideas/post-templates/{templateId}/archive
POST     /api/ideas/conversations/{conversationId}/select-content-type
POST     /api/ideas/conversations/{conversationId}/suggest-content-types
```

SaaS form places workspace-owned resources below `/api/workspaces/{workspaceId}/...` and enforces membership, permission, entitlement, revision, and tenant ownership. Global catalog and pack reads return only public product metadata.

Catalog responses include exact IDs, version, localized labels, descriptions, format recommendations, and safe UI metadata. They must not expose private skill instructions or other workspaces' configurations.

Mutations require expected revision and idempotency keys where creation could be repeated. Template use records the system-template version so a later catalog update cannot silently change the draft.

## 13. Storage and migration

Required persistent entities:

```text
content_type_definitions       global/versioned product catalog
content_type_packs             versioned pack metadata
content_type_pack_entries      types included in each pack version
workspace_content_types        workspace-created definitions and pack overrides
workspace_content_type_versions
content_format_definitions     global/versioned product catalog
workspace_post_templates       private configurations
workspace_post_template_versions
content_items                  selected type/format/pillars
content_item_versions
post_variants                  platform/account-specific outputs
```

For the current local implementation, a reviewed additive schema or versioned state migration must preserve existing drafts. Legacy items without a type remain valid as `unclassified`; the UI may offer suggestions but must not silently classify them.

The customer's local/private voice configuration remains separate from PostRiff and starter-pack catalogs. Export includes the type/template reference, visible definition, version, and private overrides but excludes secrets and hidden system instructions.

## 14. Accessibility and responsive behavior

- Every type card has a real button name, description association, and keyboard focus.
- Search/filter updates announce result count.
- Selection is not represented by color alone.
- On mobile, suggestions use a horizontal list only if every card is reachable by swipe and keyboard; `Browse all` opens a full-height sheet with a stable close action.
- The selected type, format, and destination remain understandable to a screen reader.
- Type-change consequences are described before customized variants are affected.
- Cards do not rely on dense iconography or platform logos to communicate meaning.

## 15. Acceptance criteria

### Catalog completeness

- The James founder workspace can install and use all 11 Creator pack types.
- A new unrelated workspace is not forced to install or view the Creator pack.
- Onboarding can recommend a different three-to-six-type set from role, goals, audience, sources, and channels.
- Exactly the 10 required format-family IDs are present.
- PostRiff, pack, and workspace type IDs are stable, namespaced, and localizable.
- Catalog resolution and ordering are deterministic for the same workspace state and released versions.
- The original chat title/thread reference and approved taxonomy are recorded in the specification/evidence receipt.

### Ideas UI

- User can browse workspace types, installed packs, and optional starter packs without seeing a noisy universal grid by default.
- Suggested view shows no more than four cards.
- User can start from any type and reach an editable canonical brief.
- User can start blank and accept/reject up to three agent suggestions.
- User can create a type by guided interview, example analysis, adaptation, or manual definition.
- Guided interview asks one question at a time and produces a reviewable proposal before saving.
- User can choose or change format independently of content type.
- User can change type without losing sources, attachments, or prompt text.
- Customized variants are not silently overwritten.
- Type/format controls work at desktop and 390 × 844 mobile width.

### Templates

- Every PostRiff or pack type has a neutral versioned source definition.
- A permitted user can create, test, edit, version, archive, restore, and export a workspace type.
- A user can save, reuse, edit, duplicate, archive, restore, and export a private template.
- Private templates reference a content type/version rather than copying hidden skill instructions.
- System-template upgrades never silently change saved private templates or active drafts.
- Workspace/tenant boundaries prevent cross-customer template access.
- Private templates are private by default and require explicit sharing to become workspace-visible.

### Generation and skills

- Selected type, format, source policy, user profile, language, and explicit destinations are present in the generation input snapshot.
- The relevant content and platform skills are recorded by stable ID/version.
- Outputs preserve source facts, user viewpoint, and unknowns separately.
- Each destination receives an independent native variant.
- Quote and article-summary critical rules have regression tests.
- Agent-generated type suggestions are visible recommendations, not silent state changes.

### Preflight and external actions

- Content-type reminders appear through the compact Preflight surface.
- Platform/media constraints remain independently enforced.
- Selecting or saving a template does not connect an account, schedule, publish, reply, or spend paid credits.
- Exact publication/reply approval continues to bind the resulting variant and destination.

### Validation

- Unit tests cover catalog IDs, versioning, invalid IDs, and deterministic ordering.
- Unit tests cover namespace collisions and catalog resolution across PostRiff, installed packs, workspace types, and private templates.
- State tests cover select/change/suggest content type and format independence.
- Migration tests preserve unclassified legacy drafts.
- Browser acceptance creates one founder-workspace fixture draft from each Creator pack type plus one custom type made through the guided interview.
- Tenant tests prove that workspace types, examples, and private templates do not cross workspace boundaries.
- Visual inspection covers personalized suggestions, pack library, guided type builder, proposal review, selected-type brief, and private-template save flow on desktop and mobile.

## 16. Required implementation evidence

The implementation receipt must include:

- Exact source revision or source-file hashes when Git is unavailable.
- Founder-workspace fixture showing all 11 Creator types and 10 formats.
- Unrelated-workspace fixture showing a different recommended catalog and no forced Creator pack.
- Guided-interview fixture and the reviewed custom-type proposal it produced.
- Tests and commands run.
- Desktop/mobile screenshots with human visual verdicts.
- One fixture draft per Creator pack type and one custom workspace type.
- Evidence that private templates are workspace-isolated.
- Evidence that quote attribution and article/source/POV rules are enforced.
- Explicit statement that fixture generation, preview, or local scheduling did not publish a real post.
- Any type, format, skill route, or platform capability that remains unavailable.

## 17. Out of scope

- Creating 33 separate top-level type catalogs.
- Treating James's 11-type Creator pack as a universal customer taxonomy.
- Silently inferring, installing, or modifying a customer's content strategy.
- Making every type recommend every platform.
- Sharing James's private voice/profile or private skill instances with customers.
- Allowing templates to contain credentials or direct publish permissions.
- Treating a template choice as approval to generate paid media.
- Automatically classifying or migrating existing drafts without review.
- Claiming provider support merely because the template can generate compatible copy.
