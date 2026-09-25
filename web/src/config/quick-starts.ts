/**
 * Quick Starts on the Home page: eleven post types anyone can start from.
 *
 * Every template maps onto a content type in the workspace catalog
 * (`src/postriff_phase2/content_types.py`, starter pack `pack.creator`), so choosing one
 * also selects that type and its preflight rules. Copy here is general-audience by rule:
 * it must read the same to a designer, a teacher, a shop owner or a developer, and never
 * carries one customer's projects, brands or sample data.
 */
export type QuickStartGroup = 'thoughts' | 'perspective' | 'work' | 'craft' | 'community';

export interface QuickStart {
  id: string;
  /** Workspace content type this template selects. */
  contentTypeId: string;
  /** One of the catalog's ten format families. */
  formatId: string;
  group: QuickStartGroup;
  title: string;
  /** The footnote: what this kind of post is, in one short sentence. */
  explanation: string;
  /** Starter text placed in the composer; brackets mark what the writer replaces. */
  example: string;
  /** How people usually present this kind of post: two or three formats. */
  usually: string;
  /** Default draft targets among the platforms the runtime can write for today. */
  platforms: ('LinkedIn' | 'Instagram' | 'Threads')[];
  /** Home intent chip to switch to. */
  mode: 'post' | 'thread' | 'carousel' | 'video' | 'research' | 'schedule';
}

export const QUICK_START_GROUPS: { id: QuickStartGroup | 'all'; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'thoughts', label: 'Thoughts & moments' },
  { id: 'perspective', label: 'News & opinion' },
  { id: 'work', label: 'Work & launches' },
  { id: 'craft', label: 'Craft & video' },
  { id: 'community', label: 'Community & events' }
];

export const QUICK_STARTS: QuickStart[] = [
  {
    id: 'quick-thought',
    contentTypeId: 'pack.creator:quick_thought_quote',
    formatId: 'short_text',
    group: 'thoughts',
    title: 'Quick thought',
    explanation: 'One observation or question, in your own words.',
    example: 'One thing I keep noticing: the tasks I put off are never the hard ones, they are the ones with no obvious first step. Turn this into a short post in my words.',
    usually: 'Text on Threads, X or Bluesky · a quote card',
    platforms: ['Threads', 'LinkedIn'],
    mode: 'thread'
  },
  {
    id: 'life-moment',
    contentTypeId: 'pack.creator:personal_reflection',
    formatId: 'image_caption',
    group: 'thoughts',
    title: 'Personal reflection',
    explanation: 'A true moment from your week and what it stirred up.',
    example: 'This morning I finally did the thing I had been avoiding for a month, and it took twenty minutes. Write a reflection on what the avoiding was really about, without tying it up too neatly.',
    usually: 'Photo + caption · a diary-style note',
    platforms: ['Instagram', 'Threads'],
    mode: 'post'
  },
  {
    id: 'news-view',
    contentTypeId: 'pack.creator:article_news_commentary',
    formatId: 'short_text',
    group: 'perspective',
    title: 'News + my view',
    explanation: 'What happened, why it matters, and what you think.',
    example: 'I read this today: [paste the link or the key points]. First say what actually happened in two lines. Then my take: [what it changes for people like my readers, and one thing I am not sure about].',
    usually: 'A quick take · a LinkedIn post · a carousel',
    platforms: ['LinkedIn', 'Threads'],
    mode: 'post'
  },
  {
    id: 'point-of-view',
    contentTypeId: 'pack.creator:deep_point_of_view',
    formatId: 'article',
    group: 'perspective',
    title: 'Deep point of view',
    explanation: 'A claim, your reasons, and the best argument against it.',
    example: 'My position: [one clear claim about your field]. My reasons: [two or three, with an example each]. The best argument against it: [state it fairly] and why I still hold the position. Write this as a longer piece.',
    usually: 'A long post or article · a newsletter',
    platforms: ['LinkedIn'],
    mode: 'post'
  },
  {
    id: 'building-in-public',
    contentTypeId: 'pack.creator:building_in_public',
    formatId: 'image_caption',
    group: 'work',
    title: 'Building in public',
    explanation: 'Progress, decisions and dead ends, with real numbers.',
    example: 'This week on [what you are building]: what I tried, what broke, the decision I made and why, and what comes next. Keep it plain and specific.',
    usually: 'Screenshot + note · a build log · a demo clip',
    platforms: ['LinkedIn', 'Threads'],
    mode: 'post'
  },
  {
    id: 'how-to',
    contentTypeId: 'pack.creator:tutorial_how_to',
    formatId: 'carousel',
    group: 'work',
    title: 'How-to',
    explanation: 'One method you’ve used, in numbered steps.',
    example: 'Step by step, how I [do one specific task] using [a tool, a routine or a method]. Start with what you need before you begin, then the steps, then the mistake most people make.',
    usually: 'A carousel · step-by-step notes · a short tutorial',
    platforms: ['Instagram', 'LinkedIn'],
    mode: 'carousel'
  },
  {
    id: 'launch',
    contentTypeId: 'pack.creator:product_feature_launch',
    formatId: 'image_caption',
    group: 'work',
    title: 'Launch',
    explanation: 'Why it exists, who it’s for and how to try it.',
    example: 'We just released [the product, feature, service or offer]. Why we built it, who it is for, what is included right now, what is still coming, and how to try it. Draft the announcement first.',
    usually: 'An announcement · a demo clip · a getting-started guide',
    platforms: ['LinkedIn', 'Instagram', 'Threads'],
    mode: 'schedule'
  },
  {
    id: 'craft-practice',
    contentTypeId: 'pack.creator:music_performance_teaching',
    formatId: 'image_caption',
    group: 'craft',
    title: 'Practice & performance',
    explanation: 'What you worked on today, what changed, what’s still hard.',
    example: 'From today’s [practice, session, rehearsal or class]: what I was working on, the one thing that changed, and what still feels hard. Say it the way I would tell a friend, not a student.',
    usually: 'A process clip · a photo + caption · a short lesson',
    platforms: ['Instagram', 'Threads'],
    mode: 'post'
  },
  {
    id: 'video-extension',
    contentTypeId: 'pack.creator:youtube_derivative',
    formatId: 'short_text',
    group: 'craft',
    title: 'Video extension',
    explanation: 'Turn one long video into several short posts.',
    example: 'My latest video is about [topic]. The core question it answers is [question]. The best moment is [quote or scene]. Draft a community post, a short teaser, and a conversation starter.',
    usually: 'A community post · a Short or Reel · a teaser',
    platforms: ['Threads', 'Instagram'],
    mode: 'video'
  },
  {
    id: 'community-qa',
    contentTypeId: 'pack.creator:community_q_and_a',
    formatId: 'community_post',
    group: 'community',
    title: 'Answer a question',
    explanation: 'Answer a real question, and say where you’re unsure.',
    example: 'Someone asked me: [the question, as they asked it]. Answer it plainly, say what I would actually do and where I am unsure, and invite people with more experience to correct me.',
    usually: 'A forum answer · a community message · a poll',
    platforms: ['Threads', 'LinkedIn'],
    mode: 'thread'
  },
  {
    id: 'event-update',
    contentTypeId: 'pack.creator:event_service_institutional_update',
    formatId: 'image_caption',
    group: 'community',
    title: 'Event or service update',
    explanation: 'A confirmed date, place or offer, with how to join.',
    example: 'On [date] at [place] we are hosting [the event, class, opening or service]. Who it is for, what happens, how to join or book, and where to ask questions. Draft the announcement.',
    usually: 'A social post · a Google Business update',
    platforms: ['LinkedIn', 'Instagram'],
    mode: 'schedule'
  }
];
