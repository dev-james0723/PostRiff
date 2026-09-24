/**
 * Execution registry: what the workspace can actually do with each Content Library choice.
 *
 * The library's 31 editorial types and 20 native formats are a planning vocabulary (DNA v8 §3.4).
 * The runtime speaks a smaller one: the sixteen content types of `src/postriff_phase2/content_types.py`
 * (`CORE_TYPES` + the `pack.creator` starter pack) and its ten format families. Every editorial type
 * maps onto the backend type whose meaning matches (many library types share one backend type, the
 * way Quick Starts already do). A native format maps onto one of the ten formats when the runtime can
 * draft that thing; otherwise it is `planning-only`: the choice is kept and shown honestly, never
 * coerced into text (prompt §6). `note` is the sentence the composer shows next to the choice.
 *
 * `taxonomy.test.cjs` checks the backend mirrors below against the Python source, so a catalog change
 * fails a test here instead of a request in production.
 */

export interface BackendContentType {
  id: string;
  label: string;
  description: string;
  /** In the backend's order; the first one is what `p2_content_select` picks when no format is sent. */
  recommendedFormatIds: string[];
}

/** Mirror of `CORE_TYPES` + `CREATOR_TYPES` in `src/postriff_phase2/content_types.py`. */
export const BACKEND_CONTENT_TYPES: BackendContentType[] = [
  { id: 'postriff:update', label: 'Update', description: 'Share what changed and what it means.', recommendedFormatIds: ['short_text', 'image_caption'] },
  { id: 'postriff:teach', label: 'Practical tip', description: 'Teach one useful method or lesson.', recommendedFormatIds: ['short_text', 'carousel', 'short_video'] },
  { id: 'postriff:story', label: 'Story', description: 'Tell a concrete moment and its meaning.', recommendedFormatIds: ['image_caption', 'short_text', 'short_video'] },
  { id: 'postriff:promote', label: 'Offer or announcement', description: 'Explain an available offer, event, or release.', recommendedFormatIds: ['image_caption', 'short_text'] },
  { id: 'postriff:engage', label: 'Question or discussion', description: 'Invite a specific, useful response.', recommendedFormatIds: ['community_post', 'poll', 'short_text'] },
  {
    id: 'pack.creator:quick_thought_quote',
    label: 'Quick thought / Original quote',
    description: 'Express one concise observation, tension, question, realization, or owned line.',
    recommendedFormatIds: ['short_text', 'quote_card', 'image_caption', 'community_post']
  },
  {
    id: 'pack.creator:personal_reflection',
    label: 'Personal reflection / Life moment',
    description: 'Tell a true personal moment without pretending complete resolution.',
    recommendedFormatIds: ['image_caption', 'short_text', 'short_video', 'story']
  },
  {
    id: 'pack.creator:article_news_commentary',
    label: 'Article/news summary + my view',
    description: 'Explain what happened, why it matters, and your view or open question.',
    recommendedFormatIds: ['short_text', 'article', 'carousel', 'image_caption']
  },
  { id: 'pack.creator:deep_point_of_view', label: 'Deep point of view', description: 'Develop a defensible thesis with evidence and counterpoint.', recommendedFormatIds: ['article', 'carousel', 'long_video'] },
  {
    id: 'pack.creator:building_in_public',
    label: 'Building in public',
    description: 'Share progress, decisions, experiments, failures, and tradeoffs truthfully.',
    recommendedFormatIds: ['image_caption', 'carousel', 'short_video', 'short_text']
  },
  {
    id: 'pack.creator:tutorial_how_to',
    label: 'Tutorial / How-to / Use case',
    description: 'Teach a tested workflow, feature, practice, or repeatable method.',
    recommendedFormatIds: ['carousel', 'short_video', 'long_video', 'article']
  },
  {
    id: 'pack.creator:product_feature_launch',
    label: 'Product / Feature launch',
    description: 'Explain why a release exists, what is available, and the evidence.',
    recommendedFormatIds: ['image_caption', 'carousel', 'short_video', 'short_text']
  },
  {
    id: 'pack.creator:music_performance_teaching',
    label: 'Music / Performance / Teaching',
    description: 'Share practice, interpretation, performance, teaching, or musical meaning.',
    recommendedFormatIds: ['short_video', 'long_video', 'image_caption', 'article']
  },
  {
    id: 'pack.creator:youtube_derivative',
    label: 'YouTube extension',
    description: 'Extend a long video into native entry points and follow-up discussion.',
    recommendedFormatIds: ['community_post', 'short_video', 'quote_card', 'short_text']
  },
  {
    id: 'pack.creator:community_q_and_a',
    label: 'Community Q&A / Discussion',
    description: 'Answer a real question, seek feedback, or open a useful discussion.',
    recommendedFormatIds: ['community_post', 'poll', 'short_text', 'short_video']
  },
  {
    id: 'pack.creator:event_service_institutional_update',
    label: 'Event / Service / Institutional update',
    description: 'Communicate a confirmed event, service, collaboration, or institutional update.',
    recommendedFormatIds: ['image_caption', 'short_text', 'story', 'community_post']
  }
];

/** Mirror of `FORMATS` in `src/postriff_phase2/content_types.py`, in the backend's order. */
export const BACKEND_FORMATS: { id: string; label: string }[] = [
  { id: 'short_text', label: 'Short text' },
  { id: 'image_caption', label: 'Image + caption' },
  { id: 'quote_card', label: 'Quote card' },
  { id: 'carousel', label: 'Carousel' },
  { id: 'article', label: 'Article' },
  { id: 'short_video', label: 'Short video' },
  { id: 'long_video', label: 'Long video' },
  { id: 'story', label: 'Story' },
  { id: 'community_post', label: 'Community Post' },
  { id: 'poll', label: 'Poll' }
];

export const BACKEND_CONTENT_TYPE_IDS = BACKEND_CONTENT_TYPES.map((item) => item.id);
export const BACKEND_FORMAT_IDS = BACKEND_FORMATS.map((item) => item.id);
export const BACKEND_CONTENT_TYPE_BY_ID: Record<string, BackendContentType> = Object.fromEntries(BACKEND_CONTENT_TYPES.map((item) => [item.id, item]));
export const BACKEND_FORMAT_LABELS: Record<string, string> = Object.fromEntries(BACKEND_FORMATS.map((item) => [item.id, item.label]));

/** The starter pack that carries the `pack.creator:*` types; installed once per workspace before selecting one. */
export const CREATOR_PACK = { packId: 'pack.creator', version: '1.0.0' } as const;

export type Execution = 'mapped' | 'planning-only';

export interface ExecutionMapping {
  /** Backend content type an editorial type drafts as. */
  contentTypeId?: string;
  /** Backend format family a native format drafts as; absent when planning-only. */
  formatId?: string;
  execution: Execution;
  /** Why this mapping, in words the composer can show. */
  note: string;
}

/** The label shown on a planning-only native format wherever it appears. */
export const PLANNING_ONLY_LABEL = 'Planning only · export or manual posting';

const mapped = (target: { contentTypeId: string } | { formatId: string }, note: string): ExecutionMapping => ({ ...target, execution: 'mapped', note });
const planningOnly = (note: string): ExecutionMapping => ({ execution: 'planning-only', note });

export const EXECUTION: Record<string, ExecutionMapping> = {
  /* ---- editorial types → backend content types ---- */
  status_update: mapped({ contentTypeId: 'postriff:update' }, 'Drafts as an Update: what is happening and what it means. The result-state check asks for the real state of things.'),
  announcement: mapped({ contentTypeId: 'postriff:promote' }, 'Drafts as an Offer or announcement: the message, who it is for and what is available. The availability check keeps dates and claims honest.'),
  news_curation: mapped(
    { contentTypeId: 'pack.creator:article_news_commentary' },
    'Drafts as an Article/news summary + my view: each story stays separate from your note, with citations and fresh sources.'
  ),
  opinion_commentary: mapped({ contentTypeId: 'pack.creator:deep_point_of_view' }, 'Drafts as a Deep point of view: a claim you can defend, your reasons and the strongest counterpoint.'),
  quote: mapped({ contentTypeId: 'pack.creator:quick_thought_quote' }, 'Drafts as a Quick thought / Original quote: one owned line, attributed when it is not yours.'),
  question_prompt: mapped({ contentTypeId: 'postriff:engage' }, 'Drafts as a Question or discussion: one open question that invites a specific, useful response.'),
  poll_quiz: mapped({ contentTypeId: 'postriff:engage' }, 'Drafts as a Question or discussion with choices. Pair it with the Poll format to get selectable answers.'),
  how_to: mapped({ contentTypeId: 'pack.creator:tutorial_how_to' }, 'Drafts as a Tutorial / How-to: tested steps in order, what you need first and the mistake to avoid.'),
  educational_explainer: mapped({ contentTypeId: 'postriff:teach' }, 'Drafts as a Practical tip: one idea made easier to understand, taught the way you actually explain it.'),
  list_checklist: mapped({ contentTypeId: 'postriff:teach' }, 'Drafts as a Practical tip organised into items; a carousel gives each item its own slide.'),
  review_comparison: mapped({ contentTypeId: 'pack.creator:deep_point_of_view' }, 'Drafts as a Deep point of view: the differences that matter, with evidence for the verdict and the case against it.'),
  resource_roundup: mapped({ contentTypeId: 'pack.creator:article_news_commentary' }, 'Drafts as an Article/news summary + my view for each resource: what it is, why it is worth your reader’s time, with links cited.'),
  product_service_showcase: mapped({ contentTypeId: 'postriff:promote' }, 'Drafts as an Offer or announcement: what you offer, who it helps and what is available today, with claims backed.'),
  product_update: mapped({ contentTypeId: 'postriff:update' }, 'Drafts as an Update: what changed and why it matters, stated as it is today rather than as a promise.'),
  launch_release: mapped({ contentTypeId: 'pack.creator:product_feature_launch' }, 'Drafts as a Product / Feature launch: why it exists, who it is for, what is available now and how to try it.'),
  promotion_offer: mapped({ contentTypeId: 'postriff:promote' }, 'Drafts as an Offer or announcement: the offer, its benefit, the conditions and where it is available.'),
  event_live: mapped({ contentTypeId: 'pack.creator:event_service_institutional_update' }, 'Drafts as an Event / Service / Institutional update: a confirmed date, place and how to join; live coverage follows the same facts.'),
  behind_the_scenes: mapped({ contentTypeId: 'pack.creator:building_in_public' }, 'Drafts as Building in public: the process, decisions and dead ends behind the finished work, told truthfully.'),
  personal_lifestyle: mapped({ contentTypeId: 'pack.creator:personal_reflection' }, 'Drafts as a Personal reflection / Life moment: a true glimpse of daily life that does not need a lesson at the end.'),
  milestone: mapped({ contentTypeId: 'postriff:story' }, 'Drafts as a Story: the moment reached and what it means. Numbers in a milestone must be the real ones.'),
  ugc_testimonial: mapped(
    { contentTypeId: 'pack.creator:quick_thought_quote' },
    'Drafts as a Quote: someone else’s words about your work, attributed and shared with their permission, without adding claims they did not make.'
  ),
  case_study: mapped({ contentTypeId: 'pack.creator:building_in_public' }, 'Drafts as Building in public: the challenge, what was done and the result, with evidence for the result and nothing confidential.'),
  qa_faq: mapped({ contentTypeId: 'pack.creator:community_q_and_a' }, 'Drafts as a Community Q&A: a real question answered plainly, saying what you would do and where you are unsure.'),
  community_announcement: mapped(
    { contentTypeId: 'pack.creator:event_service_institutional_update' },
    'Drafts as an Institutional update for your group: what changes, from when, and where to ask; the community-post format fits a shared space.'
  ),
  cause_advocacy: mapped({ contentTypeId: 'pack.creator:deep_point_of_view' }, 'Drafts as a Deep point of view: the cause, its context and supporting facts, with the strongest objection answered.'),
  contest_challenge: mapped({ contentTypeId: 'postriff:promote' }, 'Drafts as an Offer or announcement: the challenge, how to take part, who is eligible and until when.'),
  job_recruitment: mapped({ contentTypeId: 'pack.creator:event_service_institutional_update' }, 'Drafts as an Institutional update: the role, who it suits, what is confirmed and how to apply.'),
  article_blog_newsletter: mapped({ contentTypeId: 'pack.creator:deep_point_of_view' }, 'Drafts as a Deep point of view at article length: one idea developed with evidence and editorial depth.'),
  recap_followup: mapped({ contentTypeId: 'postriff:update' }, 'Drafts as an Update: the key moments as they happened and what comes next.'),
  reaction_reply: mapped(
    { contentTypeId: 'pack.creator:article_news_commentary' },
    'Drafts as an Article/news summary + my view: what the other contribution said, kept separate from your response, quoted briefly.'
  ),
  live_ama: mapped({ contentTypeId: 'pack.creator:community_q_and_a' }, 'Drafts as a Community Q&A: the invitation for questions and the answers you give; the live session itself happens in the app.'),

  /* ---- native formats → backend format families ---- */
  text: mapped({ formatId: 'short_text' }, 'Drafts as Short text.'),
  long_text: mapped({ formatId: 'article' }, 'Drafts in the Article family, the runtime’s longer writing with distinct sections.'),
  thread: planningOnly('The workspace catalog has no thread format yet. The Thread intent still drafts the connected sequence as text; you split and post the chain yourself.'),
  image_caption: mapped({ formatId: 'image_caption' }, 'Drafts as Image + caption.'),
  quote_card: mapped({ formatId: 'quote_card' }, 'Drafts as a Quote card.'),
  carousel: mapped({ formatId: 'carousel' }, 'Drafts as a Carousel, one idea per slide.'),
  link_preview: mapped({ formatId: 'short_text' }, 'Drafts as Short text with the link; the preview card is rendered by the platform, not by the draft.'),
  native_article: mapped({ formatId: 'article' }, 'Drafts as an Article.'),
  document: mapped({ formatId: 'carousel' }, 'Drafts as a Carousel (one page per slide); assembling and uploading the PDF or document is done by hand.'),
  short_vertical_video: mapped({ formatId: 'short_video' }, 'Drafts as a Short video script: hook, beats and caption.'),
  long_video: mapped({ formatId: 'long_video' }, 'Drafts as a Long video script and its description.'),
  livestream: planningOnly('The runtime writes and schedules posts; it does not run a live broadcast. Plan the stream here and draft its announcement and recap as posts.'),
  story: mapped({ formatId: 'story' }, 'Drafts as a Story sequence.'),
  poll: mapped({ formatId: 'poll' }, 'Drafts as a Poll: the question and its selectable answers.'),
  quiz: planningOnly('The catalog has a poll format but no quiz with a correct answer. Plan the questions here and build the quiz in the app’s own sticker or quiz tool.'),
  audio: planningOnly('No audio format in the runtime. Draft the accompanying text here; record and post the audio in the app itself.'),
  broadcast_message: mapped({ formatId: 'community_post' }, 'Drafts as a Community post for a channel you run; sending it happens in the messaging app.'),
  community_message: mapped({ formatId: 'community_post' }, 'Drafts as a Community post for a group or forum.'),
  product_catalog: planningOnly('A catalogue is built in the shop or commerce tool; the runtime has no product format. Plan the collection here and draft each product’s caption separately.'),
  local_business_update: mapped(
    { formatId: 'image_caption' },
    'Drafts as Image + caption: the text and an optional photo of a Google Business Profile post; the button and its link are set when you post.'
  )
};

/** The execution mapping for a taxonomy id, or undefined for an id the registry does not know. */
export function executionFor(id: string | null | undefined): ExecutionMapping | undefined {
  return id ? EXECUTION[id] : undefined;
}

export function isPlanningOnly(id: string | null | undefined): boolean {
  return executionFor(id)?.execution === 'planning-only';
}
