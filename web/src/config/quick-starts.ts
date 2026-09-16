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
  /** The footnote: what this kind of post is, in plain words. */
  explanation: string;
  /** Starter text placed in the composer; brackets mark what the writer replaces. */
  example: string;
  /** How people usually present this kind of post. */
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
    explanation: 'One observation, contradiction or question, said once in your own words. No setup, no list, no conclusion required.',
    example: 'One thing I keep noticing: the tasks I put off are never the hard ones, they are the ones with no obvious first step. Turn this into a short post in my words.',
    usually: 'Text-only on Threads, X or Bluesky · a quote card on Instagram or 小紅書',
    platforms: ['Threads', 'LinkedIn'],
    mode: 'thread'
  },
  {
    id: 'life-moment',
    contentTypeId: 'pack.creator:personal_reflection',
    formatId: 'image_caption',
    group: 'thoughts',
    title: 'Personal reflection',
    explanation: 'A true moment from your week and what it stirred up. It does not need a lesson at the end; a precise observation is enough.',
    example: 'This morning I finally did the thing I had been avoiding for a month, and it took twenty minutes. Write a reflection on what the avoiding was really about, without tying it up too neatly.',
    usually: 'Photo + caption · plain text · a diary-style note · a short video voice-over',
    platforms: ['Instagram', 'Threads'],
    mode: 'post'
  },
  {
    id: 'news-view',
    contentTypeId: 'pack.creator:article_news_commentary',
    formatId: 'short_text',
    group: 'perspective',
    title: 'News + my view',
    explanation: 'What happened, why it matters to the people you write for, and what you think or still wonder. The source stays separate from your view.',
    example: 'I read this today: [paste the link or the key points]. First say what actually happened in two lines. Then my take: [what it changes for people like my readers, and one thing I am not sure about].',
    usually: 'A quick take or thread · a longer LinkedIn post · a carousel · a link post on Facebook',
    platforms: ['LinkedIn', 'Threads'],
    mode: 'post'
  },
  {
    id: 'point-of-view',
    contentTypeId: 'pack.creator:deep_point_of_view',
    formatId: 'article',
    group: 'perspective',
    title: 'Deep point of view',
    explanation: 'A position you can defend: the claim, your reasons and evidence, and the strongest argument against it, answered honestly.',
    example: 'My position: [one clear claim about your field]. My reasons: [two or three, with an example each]. The best argument against it: [state it fairly] and why I still hold the position. Write this as a longer piece.',
    usually: 'A long post or article · a newsletter issue · a blog on 知乎, note or Naver · a video essay',
    platforms: ['LinkedIn'],
    mode: 'post'
  },
  {
    id: 'building-in-public',
    contentTypeId: 'pack.creator:building_in_public',
    formatId: 'image_caption',
    group: 'work',
    title: 'Building in public',
    explanation: 'Progress, decisions, dead ends and what they cost. Real numbers where you have them, and no pretending a draft is a launch.',
    example: 'This week on [what you are building]: what I tried, what broke, the decision I made and why, and what comes next. Keep it plain and specific.',
    usually: 'Screenshot + note · a build log · a carousel · a short demo clip · behind-the-scenes video',
    platforms: ['LinkedIn', 'Threads'],
    mode: 'post'
  },
  {
    id: 'how-to',
    contentTypeId: 'pack.creator:tutorial_how_to',
    formatId: 'carousel',
    group: 'work',
    title: 'How-to',
    explanation: 'One repeatable method you have actually used, in numbered steps: what you need before you start, the steps, the one mistake to avoid.',
    example: 'Step by step, how I [do one specific task] using [a tool, a routine or a method]. Start with what you need before you begin, then the steps, then the mistake most people make.',
    usually: 'Step-by-step notes on 小紅書 · an Instagram carousel · a LinkedIn document · a short tutorial · a YouTube video',
    platforms: ['Instagram', 'LinkedIn'],
    mode: 'carousel'
  },
  {
    id: 'launch',
    contentTypeId: 'pack.creator:product_feature_launch',
    formatId: 'image_caption',
    group: 'work',
    title: 'Launch',
    explanation: 'Why it exists, who it is for, what is available today (and what is not yet), and how to try it. One launch becomes several posts with different jobs, not the same ad repeated.',
    example: 'We just released [the product, feature, service or offer]. Why we built it, who it is for, what is included right now, what is still coming, and how to try it. Draft the announcement first.',
    usually: 'An announcement · a demo clip · a behind-the-decision post · a getting-started guide · a reply to early feedback',
    platforms: ['LinkedIn', 'Instagram', 'Threads'],
    mode: 'schedule'
  },
  {
    id: 'craft-practice',
    contentTypeId: 'pack.creator:music_performance_teaching',
    formatId: 'image_caption',
    group: 'craft',
    title: 'Practice & performance',
    explanation: 'Something from today’s practice, session or class: what you worked on, what changed, what still feels hard. For any craft, from music to cooking to sport.',
    example: 'From today’s [practice, session, rehearsal or class]: what I was working on, the one thing that changed, and what still feels hard. Say it the way I would tell a friend, not a student.',
    usually: 'A performance or process clip · a studio photo + caption · a short lesson · a longer video · a reflective essay',
    platforms: ['Instagram', 'Threads'],
    mode: 'post'
  },
  {
    id: 'video-extension',
    contentTypeId: 'pack.creator:youtube_derivative',
    formatId: 'short_text',
    group: 'craft',
    title: 'Video extension',
    explanation: 'Turn one long video into several native entry points: the question it answers, the best moment, the making-of, the follow-up discussion.',
    example: 'My latest video is about [topic]. The core question it answers is [question]. The best moment is [quote or scene]. Draft a community post, a short teaser, and a conversation starter.',
    usually: 'A community post · a Short or Reel · a conversation post on Threads or X · a preview with the link on Facebook',
    platforms: ['Threads', 'Instagram'],
    mode: 'video'
  },
  {
    id: 'community-qa',
    contentTypeId: 'pack.creator:community_q_and_a',
    formatId: 'community_post',
    group: 'community',
    title: 'Answer a question',
    explanation: 'Answer a real question you were asked, or ask for feedback on something specific. Say what you would do, what you are unsure about, and invite better answers.',
    example: 'Someone asked me: [the question, as they asked it]. Answer it plainly, say what I would actually do and where I am unsure, and invite people with more experience to correct me.',
    usually: 'A Reddit or 知乎 answer · a forum reply · a Discord or Telegram message · a poll on YouTube or LinkedIn',
    platforms: ['Threads', 'LinkedIn'],
    mode: 'thread'
  },
  {
    id: 'event-update',
    contentTypeId: 'pack.creator:event_service_institutional_update',
    formatId: 'image_caption',
    group: 'community',
    title: 'Event or service update',
    explanation: 'A confirmed date, place, offer or collaboration with everything people need to act: who it is for, what happens, how to join, where to ask.',
    example: 'On [date] at [place] we are hosting [the event, class, opening or service]. Who it is for, what happens, how to join or book, and where to ask questions. Draft the announcement.',
    usually: 'A post on Facebook, Instagram or LinkedIn · a Google Business update · a broadcast to your community channel',
    platforms: ['LinkedIn', 'Instagram'],
    mode: 'schedule'
  }
];
