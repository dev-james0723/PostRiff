import { QUICK_STARTS } from '@/config/quick-starts';

/**
 * The tour registry. One guided "welcome" tour walks a first-time person through the
 * app across pages; every page can also register a short set of tips that the help
 * menu (and a one-time nudge) opens on that page alone.
 *
 * Copy rules: general audience only (a designer, a teacher, a shop owner or a developer
 * must all read it the same way); no claims the product cannot keep; every sentence
 * about state reads the real workspace through `TourCtx`.
 *
 * Targets are CSS selectors tried in order; the convention is a `data-tour="…"` id on
 * the element, with a structural fallback for surfaces this feature does not own.
 */

/**
 * Workspace facts a step may read. `null` means the API could not answer: the copy must then
 * say something true without the number, never treat it as zero.
 */
export interface TourCtx {
  settled: boolean;
  hasVoice: boolean | null;
  voiceRevision: number | null;
  channelCount: number | null;
  draftCount: number | null;
  jobCount: number | null;
  needsReview: number | null;
  canEdit: boolean;
  canApprove: boolean;
  assetCount: number | null;
  canManageConnections: boolean;
  canReply: boolean;
}

export type Placement = 'top' | 'bottom' | 'left' | 'right';

export interface TourStep {
  id: string;
  /** Route the target lives on. When the person is elsewhere the tour opens it first. */
  route: string;
  /** Selectors tried in order; the first match becomes the spotlight. */
  target: string[];
  title: string;
  body: string | ((ctx: TourCtx) => string);
  /** The step is skipped when this returns false. */
  when?: (ctx: TourCtx) => boolean;
  placement?: Placement;
  /** The sidebar label named while the tour opens the route ("Next stop: Channels"). */
  stop: string;
}

export interface Tour {
  id: string;
  title: string;
  /** Route the tour belongs to; the welcome tour spans several. */
  route?: string;
  steps: TourStep[];
}

const heading = (route: string) => [`[data-tour="${route}-title"]`, 'main [data-slot="heading"] h1', 'main h1', 'main h2'];

export const WELCOME_TOUR: Tour = {
  id: 'welcome',
  title: 'PostRiff in two minutes',
  // Memory has its own page tips; the welcome walk stays at the pages a first post passes through.
  steps: [
    {
      id: 'composer',
      route: '/app',
      stop: 'Home',
      target: ['[data-tour="composer"]', 'main textarea'],
      title: 'Say what you want to put out',
      body: 'Type the topic, paste a link or drop your notes. Name a channel and a time in plain words and the plan follows them.',
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'chips',
      route: '/app',
      stop: 'Home',
      target: ['[data-tour="composer-channels"]', '[data-tour="composer"]'],
      title: 'Channels you can draft for',
      body: (ctx) =>
        ctx.channelCount === null
          ? 'Each dot shows an account’s real state, read from Channels. Drafts also work for channels you have not connected yet.'
          : ctx.channelCount > 0
            ? `Each dot shows an account’s real state. ${ctx.channelCount === 1 ? 'One account is' : `${ctx.channelCount} accounts are`} connected; drafts also work for channels you have not connected yet.`
            : 'Each dot shows an account’s real state. Nothing is connected yet, and that is fine: drafts and previews work without a connection.',
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'quick-starts',
      route: '/app',
      stop: 'Home',
      target: ['[data-tour="quick-starts"]', 'main section:has(h2)'],
      title: `${QUICK_STARTS.length} kinds of post to start from`,
      body: 'Pick one, replace the brackets with your own words, send. Each one maps to a post type with its own checks.',
      placement: 'top',
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'channels',
      route: '/app/channels',
      stop: 'Channels',
      target: ['[data-tour="channels-summary"]', '[data-tour="channels-connect"]', '[data-tour="channel-card"]', ...heading('channels')],
      title: 'One card per account, one level per capability',
      body: 'Publishing, scheduling, analytics and replies are verified one by one. Green is direct through the official API after your approval; amber means PostRiff prepares the post and you finish it.'
    },
    {
      id: 'queue',
      route: '/app/queue',
      stop: 'Queue',
      target: ['[data-tour="queue-approvals"]', '[data-tour="queue-list"]', 'main [role="tablist"]', ...heading('queue')],
      title: 'Nothing publishes on its own',
      body: (ctx) =>
        ctx.needsReview === null
          ? 'Every draft waits here until you approve the exact text, media and time.'
          : ctx.needsReview > 0
            ? `Every draft waits here until you approve the exact text, media and time. ${ctx.needsReview === 1 ? 'One draft is' : `${ctx.needsReview} drafts are`} waiting for you now.`
            : 'Every draft waits here until you approve the exact text, media and time. Nothing is waiting right now; send something from Home and it lands here.'
    },
    {
      id: 'calendar',
      route: '/app/calendar',
      stop: 'Calendar',
      target: ['[data-tour="calendar-grid"]', 'main [role="tablist"]', ...heading('calendar')],
      title: 'Your week at its exact times',
      body: 'Approved and pending publications sit at the time you chose, with a phone preview of how each channel will show the post.'
    },
    {
      id: 'brand',
      route: '/app/workspace/brand',
      stop: 'Brand',
      target: ['[data-tour="voice-setup"]', ...heading('brand')],
      title: 'Your voice',
      body: (ctx) =>
        ctx.hasVoice === null
          ? 'Your voice profile lives here: what you make, who it is for, and the tone. Drafts are written from it.'
          : ctx.hasVoice
            ? `Your voice profile is active (revision ${ctx.voiceRevision ?? 1}). Drafts are written from it, and every change you approve becomes a new revision.`
            : 'A good first stop: say what you make, who it is for, and the tone. Drafts and previews work before you do; scheduling asks for an active voice profile.',
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'overview',
      route: '/app/overview',
      stop: 'Overview',
      target: ['[data-testid="getting-started"]', '[data-tour="overview-stats"]', ...heading('overview')],
      title: 'Four steps to your first scheduled post',
      body: 'Voice, a channel, a draft, an approval. Each step ticks itself from the real workspace state, never from a click.'
    },
    {
      id: 'help',
      route: '/app/overview',
      stop: 'Overview',
      target: ['[data-tour="help"]'],
      title: 'Come back any time',
      body: 'Replay this tour or open the tips for any page from the help menu. ⌘K jumps to any page by name.',
      placement: 'bottom'
    }
  ]
};

export const PAGE_TOURS: Tour[] = [
  {
    id: 'home-tips',
    title: 'Home',
    route: '/app',
    steps: WELCOME_TOUR.steps.filter((s) => s.route === '/app')
  },
  {
    id: 'ideas-tips',
    title: 'Ideas',
    route: '/app/ideas',
    steps: [
      {
        id: 'capture',
        route: '/app/ideas',
        stop: 'Ideas',
        target: ['[data-tour="ideas-capture"]', ...heading('ideas')],
        title: 'Keep what could become a post',
        body: 'Save a thought, pasted text, a link or a file. Saving drafts nothing; Draft now opens a conversation that writes from it.'
      },
      {
        id: 'filters',
        route: '/app/ideas',
        stop: 'Ideas',
        target: ['[data-tour="ideas-filters"]'],
        title: 'Everything you saved',
        body: 'Filter by kind, see which sources came from web research, and which ones you withdrew.'
      },
      {
        id: 'row',
        route: '/app/ideas',
        stop: 'Ideas',
        target: ['[data-tour="ideas-source-row"]'],
        title: 'You decide how each source is used',
        body: 'Open a source to approve the facts a draft may use, whether it can be quoted, and whether it may reach a cloud model. Drafts only read what you approved.'
      }
    ]
  },
  {
    id: 'channels-tips',
    title: 'Channels',
    route: '/app/channels',
    steps: [
      {
        id: 'connect',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="channels-connect"]', '[data-tour="channels-summary"]', ...heading('channels')],
        title: 'Connect when you need it',
        body: 'You can draft and export without connecting anything. Connect an account when you want previews, scheduling, analytics or comments for it.'
      },
      {
        id: 'card',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="channel-card"]', '[data-tour="channels-empty"]'],
        title: 'One card per account',
        body: 'Each card is one account on one platform: who it is, what PostRiff has verified, and when access runs out.'
      },
      {
        id: 'chips',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="capability-chips"]'],
        title: 'Six capabilities, verified one by one',
        body: 'Green is Direct through the official API after your approval. Amber is Assisted: PostRiff prepares the post and you finish it. Grey is not offered yet. Hover a chip to read the evidence.'
      },
      {
        id: 'filter',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="channels-filter"]'],
        title: 'Problems come first',
        body: 'Expired access, missing permissions and accounts about to expire sort to the top and appear under Needs attention, with a Reconnect button on the card.'
      },
      {
        id: 'companion',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="companion-section"]'],
        title: 'Platforms without an API',
        body: 'Some platforms offer no publishing API a small studio can use honestly. Those will run through a desktop companion on your own machine; this page says so until it exists.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'analytics-tips',
    title: 'Analytics',
    route: '/app/analytics',
    steps: [
      {
        id: 'coverage',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-coverage"]', ...heading('analytics')],
        title: 'Which accounts report numbers',
        body: 'Each connected account shows its own analytics level. Direct means PostRiff reads the provider’s official insights for posts it published. Unsupported means that provider does not offer them to this app.'
      },
      {
        id: 'freshness',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-freshness"]'],
        title: 'When these numbers were read',
        body: 'Nothing here is live and nothing is estimated. The badge tells you the state of the readings; every row carries its own time.'
      },
      {
        id: 'table',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-table"]'],
        title: 'Native names, never added together',
        body: 'Threads reports views and reposts; Instagram reports reach and saves. Columns change with the account you pick and are never summed across providers.'
      },
      {
        id: 'row',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-row"]'],
        title: 'Open a post',
        body: 'Click a post for its full text, the provider’s receipt and every reading so far.'
      },
      {
        id: 'unavailable',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-unavailable"]', '[data-tour="analytics-table"]'],
        title: 'Unavailable is not zero',
        body: 'When a provider has not reported a metric yet, the cell says so. A real zero shows as 0.'
      }
    ]
  },
  {
    id: 'queue-tips',
    title: 'Queue',
    route: '/app/queue',
    steps: [
      {
        id: 'approvals',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-approvals"]', ...heading('queue')],
        title: 'Approve the exact post',
        body: 'Each review freezes the text, media, account and minute. Approving it is the only way a post enters the queue.'
      },
      {
        id: 'list',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-list"]'],
        title: 'Where every approved post is now',
        body: 'Each approved post becomes a job here, with what the worker did and what the provider confirmed.'
      },
      {
        id: 'filters',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-filters"]', '[data-tour="queue-list"]'],
        title: 'Filter by where a job is',
        body: 'Held means something changed after approval, so the job needs a new review before it can go out.'
      },
      {
        id: 'row',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-job-row"]', '[data-tour="queue-list"]'],
        title: 'Open the receipt',
        body: 'Open a job for its full receipt: every event, every attempt and what the provider said.',
        placement: 'top'
      },
      {
        id: 'cancel', route: '/app/queue', stop: 'Queue',
        target: ['[data-tour="queue-cancel"]', '[data-tour="queue-job-row"]'],
        title: 'Cancel before submission',
        body: 'Hold Cancel to stop a waiting or held job. Once a post reaches the provider, cancellation cannot recall it.',
        when: (ctx) => ctx.canApprove && (ctx.jobCount ?? 0) > 0
      }
    ]
  },
  {
    id: 'calendar-tips',
    title: 'Calendar',
    route: '/app/calendar',
    steps: [
      {
        id: 'grid',
        route: '/app/calendar',
        stop: 'Calendar',
        target: ['[data-tour="calendar-grid"]', 'main [role="tablist"]', ...heading('calendar')],
        title: 'Month, week or day',
        body: 'Every post sits at its exact time. Open one to see the phone preview for its channel, what happens next, and the receipt once it is published.'
      },
      {
        id: 'legend',
        route: '/app/calendar',
        stop: 'Calendar',
        target: ['[data-tour="calendar-legend"]'],
        title: 'Filter by state or account',
        body: 'The chips count the posts in the period on screen. Tap one to show only that state; expired or out-of-date reviews stay visible so nothing quietly disappears.'
      },
      {
        id: 'schedule',
        route: '/app/calendar',
        stop: 'Calendar',
        target: ['[data-tour="calendar-schedule"]'],
        title: 'Add a post',
        body: 'Schedule a draft you already have, or start a new post from Home. Nothing goes out until the exact text and time are approved.'
      }
    ]
  },
  {
    id: 'overview-tips',
    title: 'Overview',
    route: '/app/overview',
    steps: [
      {
        id: 'checklist',
        route: '/app/overview',
        stop: 'Overview',
        target: ['[data-tour="getting-started"]', '[data-tour="overview-stats"]', ...heading('overview')],
        title: 'Real numbers only',
        body: 'Every count here comes from the workspace itself. The setup checklist ticks itself from what you have done, and disappears once the four steps are done.'
      },
      {
        id: 'next-up',
        route: '/app/overview',
        stop: 'Overview',
        target: ['[data-tour="overview-next-up"]'],
        title: 'What goes out next',
        body: 'The next approved post, the account it goes to, and the coming seven days in your time zone. Open a day to see it in the calendar.'
      },
      {
        id: 'attention',
        route: '/app/overview',
        stop: 'Overview',
        target: ['[data-tour="overview-attention"]'],
        title: 'What needs you',
        body: 'Expired access, drafts waiting for approval and anything that failed. When something could not be read, this card says so instead of looking all clear.'
      },
      {
        id: 'activity',
        route: '/app/overview',
        stop: 'Overview',
        target: ['[data-tour="overview-activity"]'],
        title: 'Who did what',
        body: 'Recent changes in the workspace, in plain words: connections, approvals, members and plan changes.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'brand-tips',
    title: 'Brand & voice',
    route: '/app/workspace/brand',
    steps: [
      {
        id: 'status',
        route: '/app/workspace/brand',
        stop: 'Brand',
        target: ['[data-tour="brand-status"]', '[data-tour="voice-setup"]', ...heading('brand')],
        title: 'Your voice at a glance',
        body: 'Which voice revision is active and how many drafts and scheduled posts depend on it.'
      },
      {
        id: 'setup',
        route: '/app/workspace/brand',
        stop: 'Brand',
        target: ['[data-tour="voice-setup"]'],
        title: 'What you make, for whom, in what tone',
        body: 'Describe it once. You can draft and preview before an owner approves it.'
      },
      {
        id: 'history',
        route: '/app/workspace/brand',
        stop: 'Brand',
        target: ['[data-tour="brand-history"]', '[data-tour="voice-setup"]'],
        title: 'Every revision stays listed',
        body: 'Each approved voice stays here, with what changed since the one before it.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'memory-tips',
    title: 'Memory',
    route: '/app/workspace/memory',
    steps: [
      {
        id: 'files',
        route: '/app/workspace/memory',
        stop: 'Memory',
        target: ['[data-tour="memory-files"]', ...heading('memory')],
        title: 'Files, not a black box',
        body: 'Files marked “Given to writing routes” are what a draft is written from; the rest are here for you to read.'
      },
      {
        id: 'viewer',
        route: '/app/workspace/memory',
        stop: 'Memory',
        target: ['[data-tour="memory-viewer"]', '[data-tour="memory-files"]'],
        title: 'Read exactly what is sent',
        body: 'Each file as your workspace renders it now, with a line saying which writers receive it.'
      },
      {
        id: 'access',
        route: '/app/workspace/memory',
        stop: 'Memory',
        target: ['[data-tour="memory-access"]'],
        title: 'Who reads these files',
        body: 'An owner decides, and confirms, whether a cloud model and web research may read them too.'
      },
      {
        id: 'learning',
        route: '/app/workspace/memory',
        stop: 'Memory',
        target: ['[data-tour="memory-learning"]'],
        title: 'Preferences you decide on',
        body: 'PostRiff suggests writing preferences from what you say and how you edit. Nothing changes until an owner accepts, and unanswered suggestions expire.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'inbox-tips',
    title: 'Inbox',
    route: '/app/inbox',
    steps: [
      {
        id: 'coverage',
        route: '/app/inbox',
        stop: 'Inbox',
        target: ['[data-tour="inbox-coverage"]', ...heading('inbox')],
        title: 'Which accounts can show comments',
        body: 'Each account shows whether PostRiff can read its comments and reply to them, with the evidence behind each level.'
      },
      {
        id: 'threads',
        route: '/app/inbox',
        stop: 'Inbox',
        target: ['[data-tour="inbox-threads"]', '[data-tour="inbox-empty"]'],
        title: 'Comments waiting for you',
        body: 'Pick a comment to read it in full. Unanswered lists the comments that have no approved reply yet.'
      },
      {
        id: 'reply',
        route: '/app/inbox',
        stop: 'Inbox',
        target: ['[data-tour="inbox-threads"]', '[data-tour="inbox-empty"]'],
        title: 'Replies you approve one at a time',
        body: 'Write a reply, save it, then review the exact account, comment and text before you approve it. Nothing is sent without that step.'
      }
    ]
  },
  {
    id: 'pipeline-tips',
    title: 'Pipeline',
    route: '/app/pipeline',
    steps: [
      {
        id: 'board',
        route: '/app/pipeline',
        stop: 'Pipeline',
        target: ['[data-tour="pipeline-board"]', ...heading('pipeline')],
        title: 'Left to right, nothing moves on its own',
        body: 'Work moves from sources to drafts, reviews, the queue and published posts, and only when someone acts.'
      },
      {
        id: 'drafts',
        route: '/app/pipeline',
        stop: 'Pipeline',
        target: ['[data-tour="pipeline-col-drafts"]', '[data-tour="pipeline-board"]'],
        title: 'Drafts',
        body: 'Edit a draft or choose Schedule to pick an account and a time. Drafts you set aside wait at the bottom of the column.'
      },
      {
        id: 'review',
        route: '/app/pipeline',
        stop: 'Pipeline',
        target: ['[data-tour="pipeline-col-review"]', '[data-tour="pipeline-board"]'],
        title: 'Needs approval',
        body: 'A review locks the exact text, account and time until someone who can approve confirms it.'
      },
      {
        id: 'published',
        route: '/app/pipeline',
        stop: 'Pipeline',
        target: ['[data-tour="pipeline-col-published"]', '[data-tour="pipeline-board"]'],
        title: 'Published means confirmed',
        body: 'Only posts the provider confirmed appear here. A Fixture label marks a test run, not a real post.'
      }
    ]
  },
  {
    id: 'library-tips',
    title: 'Library',
    route: '/app/library',
    steps: [
      {
        id: 'upload',
        route: '/app/library',
        stop: 'Library',
        target: ['[data-tour="library-upload"]', '[data-tour="library-empty"]', ...heading('library')],
        title: 'Add images',
        body: 'Add JPEG or PNG images. Pick several at once, or drop them anywhere on this page.',
        when: (ctx) => ctx.canEdit
      },
      {
        id: 'filter',
        route: '/app/library',
        stop: 'Library',
        target: ['[data-tour="library-filter"]', '[data-tour="library-empty"]'],
        title: 'Used and unused',
        body: 'Switch between all images, the ones no post uses yet, and the ones already in a post. The numbers are live counts.',
        when: (ctx) => (ctx.assetCount ?? 0) > 0
      },
      {
        id: 'card',
        route: '/app/library',
        stop: 'Library',
        target: ['[data-tour="library-card"]', '[data-tour="library-empty"]'],
        title: 'Open an image',
        body: 'See its size, its fingerprint and which posts use it. Right-click or long-press for quick actions.',
        when: (ctx) => (ctx.assetCount ?? 0) > 0,
        placement: 'top'
      }
    ]
  },
  {
    id: 'api-tips',
    title: 'API & integrations',
    route: '/app/account/api',
    steps: [
      {
        id: 'status',
        route: '/app/account/api',
        stop: 'API & integrations',
        target: ['[data-tour="api-status"]', ...heading('api')],
        title: 'Read from the workspace',
        body: 'Connected accounts, reviewed providers and the tool runner. Anything that cannot be read says Unavailable instead of a number.'
      },
      {
        id: 'grants',
        route: '/app/account/api',
        stop: 'API & integrations',
        target: ['[data-tour="api-grants"]'],
        title: 'What each account can do',
        body: 'Capability by capability, with the evidence. Manage the accounts themselves on Channels.'
      },
      {
        id: 'tools',
        route: '/app/account/api',
        stop: 'API & integrations',
        target: ['[data-tour="api-tools"]'],
        title: 'Tools an agent could use',
        body: 'The tools an agent could be offered, and whether they run in isolation on this deployment.'
      },
      {
        id: 'roadmap',
        route: '/app/account/api',
        stop: 'API & integrations',
        target: ['[data-tour="api-roadmap"]'],
        title: 'Not switched on yet',
        body: 'Access tokens, webhooks and a server for AI agents are planned. Tokens will read and draft, and will never approve, publish, reply or connect an account.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'billing-tips',
    title: 'Usage & plan',
    route: '/app/account/billing',
    steps: [
      {
        id: 'plan',
        route: '/app/account/billing',
        stop: 'Usage & plan',
        target: ['[data-tour="billing-plan"]', ...heading('billing')],
        title: 'Your plan',
        body: 'The plan for the workspace you have open, its status and the next date that changes something.'
      },
      {
        id: 'allowances',
        route: '/app/account/billing',
        stop: 'Usage & plan',
        target: ['[data-tour="billing-allowances"]'],
        title: 'Allowances',
        body: 'Each bar reads your real allowance. When one runs out, paid drafting stops and says so. Nothing is charged silently.'
      },
      {
        id: 'plans',
        route: '/app/account/billing',
        stop: 'Usage & plan',
        target: ['[data-tour="billing-plans"]'],
        title: 'Changing plan',
        body: 'Checkout happens with the payment provider. A subscription shows as confirmed only after the provider tells PostRiff.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'privacy-tips',
    title: 'Privacy & data',
    route: '/app/account/privacy',
    steps: [
      {
        id: 'holdings',
        route: '/app/account/privacy',
        stop: 'Privacy & data',
        target: ['[data-tour="privacy-holdings"]', ...heading('privacy')],
        title: 'What PostRiff holds',
        body: 'These counts come from your workspace. Unavailable means a number could not be read, never that it is zero.'
      },
      {
        id: 'egress',
        route: '/app/account/privacy',
        stop: 'Privacy & data',
        target: ['[data-tour="privacy-egress"]'],
        title: 'Where your content may go',
        body: 'Whether a cloud model may read your memory files, and whether drafting may look facts up on the web.'
      },
      {
        id: 'export',
        route: '/app/account/privacy',
        stop: 'Privacy & data',
        target: ['[data-tour="privacy-export"]'],
        title: 'Take everything with you',
        body: 'Download everything as one file, and keep the fingerprint shown here to check later that your copy is unchanged.'
      },
      {
        id: 'retract',
        route: '/app/account/privacy',
        stop: 'Privacy & data',
        target: ['[data-tour="privacy-retract"]'],
        title: 'Retract a source',
        body: 'Pick a source to see exactly what retracting it would change before you commit to it.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'models-tips',
    title: 'Models & providers',
    route: '/app/account/models',
    steps: [
      {
        id: 'current',
        route: '/app/account/models',
        stop: 'Models & providers',
        target: ['[data-tour="models-current"]', ...heading('models')],
        title: 'Who is writing now',
        body: 'The writer your drafts use right now in this browser, and who pays for it.'
      },
      {
        id: 'cli',
        route: '/app/account/models',
        stop: 'Models & providers',
        target: ['[data-tour="models-cli"]', '[data-tour="models-empty"]'],
        title: 'Writers you already pay for',
        body: 'A coding assistant signed in on the machine that serves PostRiff can write drafts, paid by its own subscription.'
      },
      {
        id: 'managed',
        route: '/app/account/models',
        stop: 'Models & providers',
        target: ['[data-tour="models-managed"]'],
        title: 'PostRiff writers',
        body: 'A managed model that uses writing batches, and a free preview that never calls a model.'
      },
      {
        id: 'consent',
        route: '/app/account/models',
        stop: 'Models & providers',
        target: ['[data-tour="models-consent"]'],
        title: 'What may leave the workspace',
        body: 'What a writer may read beyond your message. An owner changes this on the Memory page.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'roles-tips',
    title: 'Roles',
    route: '/app/workspace/roles',
    steps: [
      {
        id: 'you',
        route: '/app/workspace/roles',
        stop: 'Roles',
        target: ['[data-tour="roles-you"]', ...heading('roles')],
        title: 'Your access',
        body: 'Your role in this workspace and what it lets you do. If something you need is missing, it says who can give it to you.'
      },
      {
        id: 'cards',
        route: '/app/workspace/roles',
        stop: 'Roles',
        target: ['[data-tour="roles-cards"]'],
        title: 'Five roles',
        body: 'From most to least trusted. Each number is how many active members hold that role right now.'
      },
      {
        id: 'matrix',
        route: '/app/workspace/roles',
        stop: 'Roles',
        target: ['[data-tour="roles-matrix"]'],
        title: 'The rules behind every action',
        body: 'Every action is checked against these rules. A grant adds one right without changing someone’s role.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'members-tips',
    title: 'Members',
    route: '/app/workspace/members',
    steps: [
      {
        id: 'invite',
        route: '/app/workspace/members',
        stop: 'Members',
        target: ['[data-tour="members-invite"]', ...heading('members')],
        title: 'Invite someone',
        body: 'Enter an email, pick a role and any extra grants. They get a one-time link that works for 7 days.'
      },
      {
        id: 'table',
        route: '/app/workspace/members',
        stop: 'Members',
        target: ['[data-tour="members-table"]'],
        title: 'Everyone in the workspace',
        body: 'Each person with their role and grants. Changes are confirmed before anything is saved.'
      },
      {
        id: 'invitations',
        route: '/app/workspace/members',
        stop: 'Members',
        target: ['[data-tour="members-invitations"]', '[data-tour="members-table"]'],
        title: 'Invitations you sent',
        body: 'Their state, and revoking one stops its link immediately.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'audit-tips',
    title: 'Audit log',
    route: '/app/workspace/audit',
    steps: [
      {
        id: 'title',
        route: '/app/workspace/audit',
        stop: 'Audit log',
        target: ['[data-tour="audit-title"]', ...heading('audit')],
        title: 'Who did what',
        body: 'A timeline of changes in this workspace, newest first. It records who and when, never the content itself.'
      },
      {
        id: 'categories',
        route: '/app/workspace/audit',
        stop: 'Audit log',
        target: ['[data-tour="audit-categories"]', '[data-tour="audit-empty"]'],
        title: 'Filter by kind or person',
        body: 'Pick a kind or a person; the filter is kept in the address, so a link opens the same view.'
      },
      {
        id: 'coverage',
        route: '/app/workspace/audit',
        stop: 'Audit log',
        target: ['[data-tour="audit-coverage"]', '[data-tour="audit-empty"]'],
        title: 'How much you are seeing',
        body: 'This line says whether you are looking at the whole log or only the newest events.'
      }
    ]
  }
];

export const TOURS: Record<string, Tour> = Object.fromEntries([WELCOME_TOUR, ...PAGE_TOURS].map((t) => [t.id, t]));

/** The page tour for a route, if the page registered one. */
export function pageTourFor(pathname: string): Tour | null {
  return PAGE_TOURS.find((t) => t.route === pathname) ?? null;
}

/** Steps that apply to this person right now; a step whose `when` says no is left out. */
export function visibleSteps(tour: Tour, ctx: TourCtx): TourStep[] {
  return tour.steps.filter((s) => !s.when || s.when(ctx));
}

export function stepBody(step: TourStep, ctx: TourCtx): string {
  return typeof step.body === 'function' ? step.body(ctx) : step.body;
}
