---
name: postriff-discoverability
description: Plan and validate search, AI-answer, local, and platform-native discoverability for a workspace's content after a CanonicalBrief exists. Use for article SEO, topic clusters, metadata, schema, YouTube search packaging, local visibility, and per-platform discovery hints; do not use to promise virality, keyword-stuff captions, or publish.
license: MIT
metadata:
  status: project-local-not-globally-installed
  inspired-by: AgriciDaniel/claude-seo and AgriciDaniel/codex-seo
  project-contract: postriff-social-media-suite-design-revision-10
---

# PostRiff discoverability

Make the creator's real ideas easier to find without replacing their voice with search-engine copy or generic engagement tactics. This skill produces a reviewable `DiscoverabilityBrief`; it owns no account, crawler installation, credential, scheduling, publishing, or live-site mutation.

## Required inputs

Load, in order:

1. The active `CanonicalBrief` and its exact `story_version`.
2. The PostRiff Content Engine and selected brand identity.
3. Current source-log or claim records for factual content.
4. Requested markets, languages, destinations, and native formats.
5. The owned property, article, video, business location, or social account being optimized, when one exists.
6. Current first-party performance/search data only when access is already authorized.

If the creator's point of view, factual basis, target market, or destination is missing, return a missing-input record. Do not invent experience, expertise, audience demand, search volume, ranking, product results, or business-location facts.

## Route to the relevant reference

- Read [references/discoverability-brief-contract.md](references/discoverability-brief-contract.md) before producing or validating a brief.
- Read [references/platform-discovery-guidance.md](references/platform-discovery-guidance.md) only for the selected destination families and markets.

## Select the discovery mode

Use one or more modes, but keep their evidence and success metrics separate:

- `owned_search`: website, blog, article, product page, note, Naver Blog, Zhihu article, or another indexable property.
- `youtube_search`: title, description, chapters, transcript concepts, thumbnail promise, and query-to-video fit.
- `local_search`: an exact verified business location, venue, event, or Google Business Profile the workspace actually controls.
- `ai_answer_visibility`: answer-first structure, entity clarity, attribution, passage citability, and appropriate structured data for an owned page.
- `social_discovery`: platform-native topic language, hook clarity, media-text alignment, accessibility, community context, and retention/share intent.

Never describe social discovery as SEO when the platform primarily ranks through recommendation, relationships, watch behavior, or community response. Search optimization can improve findability; it cannot guarantee popularity.

## Workflow

### 1. Define the discovery job

State the intended audience, market, language, destination, user need, content lifecycle, and desired action. Separate timely discovery from durable search value. A breaking-news response and an evergreen article may share evidence but require different titles, freshness language, and update policies.

### 2. Build an evidence-backed intent map

Identify:

- the primary audience question;
- adjacent questions worth answering;
- search or platform vocabulary supported by current evidence;
- relevant entities and relationships;
- the best content format for the intent;
- uncertainties and data gaps.

Use current primary or authoritative sources for unstable claims. Trend tools, autocomplete, competitor pages, public posts, and third-party SEO data are discovery signals only. Record provider, query, market, language, retrieval time, data window, and limitations. Do not infer demand from repeated headlines or fabricate numerical volume.

### 3. Protect the canonical meaning

The `CanonicalBrief` remains authoritative for the creator's thesis, voice, factual qualifications, and sensitivity. Suggest discoverability improvements around that meaning. Do not silently change the creator's position, add unsupported claims, manufacture authority, or flatten a reflective idea into listicle language.

Prefer one clear subject and a coherent entity vocabulary over repeated exact-match phrases. Every localized variant must preserve attribution, uncertainty, and claim strength while using native audience language.

### 4. Design the content architecture

For owned or long-form content, recommend only what the destination can support:

- thesis-led title and search-intent alternative;
- concise answer or event summary near the beginning;
- logical question/section hierarchy;
- supporting evidence and source notes;
- internal links to genuinely related work;
- descriptive URL, metadata, image/alt-text, and update note;
- structured-data candidates such as Article, Organization, LocalBusiness, Product, Event, FAQ, VideoObject, or Breadcrumb only when the visible page supports them;
- canonical, locale, and hreflang guidance only for real equivalent pages.

Schema is a factual representation of visible content, not a ranking trick. Never create fake reviews, ratings, authorship, FAQs, events, availability, or organization relationships.

### 5. Produce platform-native discovery hints

Generate hints, not final platform copy. Each hint should identify the audience vocabulary, opening job, searchable/contextual fields, media relationship, and metric to observe. Do not paste one keyword set or hashtag block across destinations.

For recommendation-led platforms, prioritize viewer/reader fit, clarity, retention, saves/shares, and native community value. For knowledge communities, current rules and usefulness outrank campaign reach. For regional platforms, use locally researched vocabulary and editorial structure rather than translated Google keywords.

### 6. Define measurement and learning

Choose metrics that match the mode:

- owned search: impressions, qualified clicks, query/page fit, index coverage, and useful conversions;
- YouTube: search impressions where available, click-through, watch time, completion, and downstream engagement;
- local: accurate discovery actions, calls/directions/site visits where available, and location relevance;
- AI-answer visibility: observed citations/mentions with dated evidence, not assumed exposure;
- social discovery: qualified reach, watch time, completion, saves, shares, profile visits, link clicks, and useful replies.

Do not treat one spike, vanity impressions, or an unaudited third-party score as proof. Record the measurement window and distinguish correlation from causation.

## Output

Return:

1. One structured `DiscoverabilityBrief` tied to the campaign and canonical-brief version.
2. A short explanation of the chosen discovery modes.
3. Owned-content architecture and metadata candidates when relevant.
4. Per-platform discovery hints for selected targets only.
5. Evidence, assumptions, missing data, and claims that must not be strengthened.
6. A measurement plan with baseline and review window.
7. `validation_state: candidate_ready | needs_data | blocked` and explicit `not_done` items.

`candidate_ready` means the local brief is coherent and evidence-linked. It does not mean ranked, indexed, viral, approved, uploaded, published, or verified live.

## Hard boundaries

- Do not install or invoke an upstream SEO bundle automatically.
- Do not request or read Search Console, Analytics, provider, or platform credentials unless a separate approved setup workflow supplies an opaque connection.
- Do not edit a live website, business listing, video, or social post.
- Do not buy backlinks, create fake reviews, manufacture engagement, impersonate users, or recommend deceptive traffic tactics.
- Do not promise rankings, virality, follower growth, citations, or revenue.
- Do not let SEO scores, competitor patterns, or third-party prompts override the creator's voice, source standards, privacy rules, or exact publishing approval.

