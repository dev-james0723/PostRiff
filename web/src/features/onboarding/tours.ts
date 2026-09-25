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
  isOwner: boolean;
  portalAvailable: boolean | null;
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
  title: 'Rafii in two minutes',
  // Memory has its own page tips; the welcome walk stays at the pages a first post passes through.
  steps: [
    {
      id: 'composer',
      route: '/app',
      stop: 'Home',
      target: ['[data-tour="composer"]', 'main textarea'],
      title: 'Say what you want to post',
      body: 'A topic, a link or your notes. Name a channel and time if you like.',
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'chips',
      route: '/app',
      stop: 'Home',
      target: ['[data-tour="composer-channels"]', '[data-tour="composer"]'],
      title: 'Channels',
      body: (ctx) =>
        ctx.channelCount === null || ctx.channelCount === 0
          ? 'Drafts work before you connect anything.'
          : `${ctx.channelCount === 1 ? 'One account' : `${ctx.channelCount} accounts`} connected. Drafts work for the rest too.`,
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'quick-starts',
      route: '/app',
      stop: 'Home',
      target: ['[data-tour="quick-starts"]', 'main section:has(h2)'],
      title: `${QUICK_STARTS.length} kinds of post to start from`,
      body: 'Pick one, fill in the brackets, send.',
      placement: 'top',
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'channels',
      route: '/app/channels',
      stop: 'Channels',
      target: ['[data-tour="channels-summary"]', '[data-tour="channels-connect"]', '[data-tour="channel-card"]', ...heading('channels')],
      title: 'One card per account',
      body: 'Green publishes directly after your approval; amber means you finish the post.'
    },
    {
      id: 'queue',
      route: '/app/queue',
      stop: 'Queue',
      target: ['[data-tour="queue-approvals"]', '[data-tour="queue-list"]', 'main [role="tablist"]', ...heading('queue')],
      title: 'Nothing publishes on its own',
      body: (ctx) =>
        ctx.needsReview !== null && ctx.needsReview > 0
          ? `You approve the exact text, media and time. ${ctx.needsReview === 1 ? 'One draft is' : `${ctx.needsReview} drafts are`} waiting.`
          : 'You approve the exact text, media and time first.'
    },
    {
      id: 'calendar',
      route: '/app/calendar',
      stop: 'Calendar',
      target: ['[data-tour="calendar-grid"]', 'main [role="tablist"]', ...heading('calendar')],
      title: 'Your week',
      body: 'Every post at its exact time, with a phone preview.'
    },
    {
      id: 'brand',
      route: '/app/workspace/brand',
      stop: 'Brand',
      target: ['[data-tour="voice-setup"]', ...heading('brand')],
      title: 'Your voice',
      body: (ctx) =>
        ctx.hasVoice === true
          ? `Revision ${ctx.voiceRevision ?? 1} is active. Drafts are written from it.`
          : 'Say what you make, who it’s for and the tone. Drafts are written from it.',
      when: (ctx) => ctx.canEdit
    },
    {
      id: 'overview',
      route: '/app/overview',
      stop: 'Overview',
      target: ['[data-testid="getting-started"]', '[data-tour="overview-stats"]', ...heading('overview')],
      title: 'Four steps to your first post',
      body: 'Voice, a channel, a draft, an approval. Each ticks itself off.'
    },
    {
      id: 'help',
      route: '/app/overview',
      stop: 'Overview',
      target: ['[data-tour="help"]'],
      title: 'Come back any time',
      body: 'Replay the tour or page tips from Help. ⌘K jumps to any page.',
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
        body: 'Save a thought, text, link or file. Draft now writes from it.'
      },
      {
        id: 'filters',
        route: '/app/ideas',
        stop: 'Ideas',
        target: ['[data-tour="ideas-filters"]'],
        title: 'Everything you saved',
        body: 'Filter by kind, web research or withdrawn.'
      },
      {
        id: 'row',
        route: '/app/ideas',
        stop: 'Ideas',
        target: ['[data-tour="ideas-source-row"]'],
        title: 'You decide how sources are used',
        body: 'Approve the facts a draft may use, quoting and cloud access.'
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
        title: 'Connect an account',
        body: 'Connect to schedule posts and see analytics.'
      },
      {
        id: 'card',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="channel-card"]', '[data-tour="channels-empty"]'],
        title: 'One card per account',
        body: 'Who it is, what’s verified and when access runs out.'
      },
      {
        id: 'chips',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="capability-chips"]'],
        title: 'What each account can do',
        body: 'Green is direct, amber is assisted, grey isn’t offered yet. Hover for details.'
      },
      {
        id: 'filter',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="channels-filter"]'],
        title: 'Problems come first',
        body: 'Accounts that need a reconnect sort to the top.'
      },
      {
        id: 'companion',
        route: '/app/channels',
        stop: 'Channels',
        target: ['[data-tour="companion-section"]'],
        title: 'Platforms without an API',
        body: 'Some platforms will publish through a desktop companion app, coming later.',
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
        body: 'Direct accounts report official insights; unsupported ones don’t share them.'
      },
      {
        id: 'freshness',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-freshness"]'],
        title: 'When these numbers were read',
        body: 'Numbers are read, never estimated. Each row shows its time.'
      },
      {
        id: 'table',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-table"]'],
        title: 'Native names, never added together',
        body: 'Each platform’s own metrics, never summed across platforms.'
      },
      {
        id: 'row',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-row"]'],
        title: 'Open a post',
        body: 'See its full text, receipt and every reading.'
      },
      {
        id: 'unavailable',
        route: '/app/analytics',
        stop: 'Analytics',
        target: ['[data-tour="analytics-unavailable"]', '[data-tour="analytics-table"]'],
        title: 'Unavailable is not zero',
        body: 'A missing metric says so. A real zero shows as 0.'
      }
    ]
  },
  {
    id: 'queue-tips',
    title: 'Queue',
    route: '/app/queue',
    steps: [
      {
        id: 'drafts',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-tabs"]', ...heading('queue')],
        title: 'Drafts wait here',
        body: 'Choose Schedule… on a draft to pick an account and time.'
      },
      {
        id: 'approvals',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-approvals"]', ...heading('queue')],
        title: 'Approve the exact post',
        body: 'Approval locks the text, media, account and time.'
      },
      {
        id: 'list',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-list"]'],
        title: 'Where each approved post is',
        body: 'Each approved post shows its status here.'
      },
      {
        id: 'filters',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-filters"]', '[data-tour="queue-list"]'],
        title: 'Filter by status',
        body: 'Needs action means it changed after approval.'
      },
      {
        id: 'row',
        route: '/app/queue',
        stop: 'Queue',
        target: ['[data-tour="queue-job-row"]', '[data-tour="queue-list"]'],
        title: 'Open details',
        body: 'Every event and attempt for that post.',
        placement: 'top'
      },
      {
        id: 'cancel', route: '/app/queue', stop: 'Queue',
        target: ['[data-tour="queue-cancel"]', '[data-tour="queue-job-row"]'],
        title: 'Cancel before submission',
        body: 'Hold Cancel to stop it. A post already sent can’t be recalled.',
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
        body: 'Open a post for its preview and status.'
      },
      {
        id: 'legend',
        route: '/app/calendar',
        stop: 'Calendar',
        target: ['[data-tour="calendar-legend"]'],
        title: 'Filter by state or account',
        body: 'Tap a chip to show only that state.'
      },
      {
        id: 'schedule',
        route: '/app/calendar',
        stop: 'Calendar',
        target: ['[data-tour="calendar-schedule"]'],
        title: 'Add a post',
        body: 'Schedule a draft or start one from Home.'
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
        body: 'The checklist ticks itself and hides when you’re done.'
      },
      {
        id: 'next-up',
        route: '/app/overview',
        stop: 'Overview',
        target: ['[data-tour="overview-next-up"]'],
        title: 'What goes out next',
        body: 'The next post and the coming seven days.'
      },
      {
        id: 'attention',
        route: '/app/overview',
        stop: 'Overview',
        target: ['[data-tour="overview-attention"]'],
        title: 'What needs you',
        body: 'Expired access, waiting drafts and failures.'
      },
      {
        id: 'activity',
        route: '/app/overview',
        stop: 'Overview',
        target: ['[data-tour="overview-activity"]'],
        title: 'Who did what',
        body: 'Recent changes to connections, approvals, members and plan.',
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
        body: 'The active revision and the drafts that use it.'
      },
      {
        id: 'setup',
        route: '/app/workspace/brand',
        stop: 'Brand',
        target: ['[data-tour="voice-setup"]'],
        title: 'What you make, for whom, in what tone',
        body: 'Describe it once. Drafts work before it’s approved.'
      },
      {
        id: 'proposal', route: '/app/workspace/brand', stop: 'Brand',
        target: ['[data-tour="brand-proposal"]', '[data-tour="voice-setup"]'],
        title: 'Review a new voice', body: 'Only an owner approves it.'
      },
      {
        id: 'files', route: '/app/workspace/brand', stop: 'Brand',
        target: ['[data-tour="brand-drafts-read"]'],
        title: 'What drafts read', body: 'The memory files every draft is written from.'
      },
      {
        id: 'history',
        route: '/app/workspace/brand',
        stop: 'Brand',
        target: ['[data-tour="brand-history"]', '[data-tour="voice-setup"]'],
        title: 'Every revision stays listed',
        body: 'Each approved voice, with what changed.',
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
        body: 'Files marked “Sent to writers” are what drafts are written from.'
      },
      {
        id: 'viewer',
        route: '/app/workspace/memory',
        stop: 'Memory',
        target: ['[data-tour="memory-viewer"]', '[data-tour="memory-files"]'],
        title: 'Read exactly what is sent',
        body: 'Each file as writers receive it now.'
      },
      {
        id: 'access',
        route: '/app/workspace/memory',
        stop: 'Memory',
        target: ['[data-tour="memory-access"]'],
        title: 'Who reads these files',
        body: 'An owner decides if the cloud model and web research can.'
      },
      {
        id: 'learning',
        route: '/app/workspace/memory',
        stop: 'Memory',
        target: ['[data-tour="memory-learning"]'],
        title: 'Preferences you decide on',
        body: 'Suggestions from how you edit. An owner accepts or dismisses them.',
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
        body: 'Each account shows whether its comments can appear here.'
      },
      {
        id: 'threads',
        route: '/app/inbox',
        stop: 'Inbox',
        target: ['[data-tour="inbox-threads"]', '[data-tour="inbox-empty"]'],
        title: 'Comments waiting for you',
        body: 'Unanswered lists comments without an approved reply.'
      },
      {
        id: 'reply',
        route: '/app/inbox',
        stop: 'Inbox',
        target: ['[data-tour="inbox-composer"]', '[data-tour="inbox-threads"]', '[data-tour="inbox-empty"]'],
        title: 'Approve an exact reply',
        body: 'Sending isn’t on yet; approvals are saved for later.',
        when: (ctx) => ctx.canEdit || ctx.canReply
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
        body: 'JPEG or PNG. Drop several anywhere on the page.',
        when: (ctx) => ctx.canEdit
      },
      {
        id: 'filter',
        route: '/app/library',
        stop: 'Library',
        target: ['[data-tour="library-filter"]', '[data-tour="library-empty"]'],
        title: 'Used and unused',
        body: 'Show all images, unused ones or ones in a post.',
        when: (ctx) => (ctx.assetCount ?? 0) > 0
      },
      {
        id: 'card',
        route: '/app/library',
        stop: 'Library',
        target: ['[data-tour="library-card"]', '[data-tour="library-empty"]'],
        title: 'Open an image',
        body: 'See its details and which posts use it.',
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
        body: 'Connected accounts and platforms at a glance.'
      },
      {
        id: 'grants',
        route: '/app/account/api',
        stop: 'API & integrations',
        target: ['[data-tour="api-grants"]'],
        title: 'What each account can do',
        body: 'Capability by capability. Manage accounts on Channels.'
      },
      {
        id: 'tools',
        route: '/app/account/api',
        stop: 'API & integrations',
        target: ['[data-tour="api-tools"]'],
        title: 'Tools an agent could use',
        body: 'The tools an agent could be offered, and whether each runs isolated.'
      },
      {
        id: 'tokens', route: '/app/account/api', stop: 'API & integrations', target: ['[data-tour="api-create-token"]', '[data-tour="api-tokens"]'], title: 'Tokens for your own scripts', body: 'Copy the secret once. Drafts use your writing allowance.'
      },
      {
        id: 'roadmap',
        route: '/app/account/api',
        stop: 'API & integrations',
        target: ['[data-tour="api-roadmap"]'],
        title: 'Not switched on yet',
        body: 'Webhooks and an agent server are planned. Publishing stays in the app.',
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
        body: 'Your plan and what changes next.'
      },
      {
        id: 'allowances',
        route: '/app/account/billing',
        stop: 'Usage & plan',
        target: ['[data-tour="billing-allowances"]'],
        title: 'Allowances',
        body: 'When one runs out, paid drafting stops. Nothing is charged silently.'
      },
      {
        id: 'plans',
        route: '/app/account/billing',
        stop: 'Usage & plan',
        target: ['[data-tour="billing-plans"]'],
        title: 'Changing plan',
        body: 'A new plan shows once payment is confirmed.',
        when: (ctx) => ctx.isOwner,
        placement: 'top'
      },
      {
        id: 'manage', route: '/app/account/billing', stop: 'Usage & plan',
        target: ['[data-tour="billing-manage"]'], title: 'Manage billing',
        body: 'Update payment details or your subscription.',
        when: (ctx) => ctx.isOwner && ctx.portalAvailable === true
      },
      {
        id: 'ledger', route: '/app/account/billing', stop: 'Usage & plan',
        target: ['[data-tour="billing-ledger"]', '[data-tour="billing-ledger-empty"]'], title: 'Recorded usage',
        body: 'Reserved and actual costs, listed separately.',
        when: (ctx) => ctx.isOwner
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
        title: 'Your data',
        body: 'Counts from your workspace.'
      },
      {
        id: 'egress',
        route: '/app/account/privacy',
        stop: 'Privacy & data',
        target: ['[data-tour="privacy-egress"]'],
        title: 'Where your content may go',
        body: 'Cloud model access and web research.'
      },
      {
        id: 'export',
        route: '/app/account/privacy',
        stop: 'Privacy & data',
        target: ['[data-tour="privacy-export"]'],
        title: 'Take everything with you',
        body: 'Download everything as one file.'
      },
      {
        id: 'retract',
        route: '/app/account/privacy',
        stop: 'Privacy & data',
        target: ['[data-tour="privacy-retract"]'],
        title: 'Retract a source',
        body: 'See what changes before you retract.',
        placement: 'top'
      }
    ]
  },
  {
    id: 'models-tips',
    title: 'Models',
    route: '/app/account/models',
    steps: [
      {
        id: 'current',
        route: '/app/account/models',
        stop: 'Models',
        target: ['[data-tour="models-current"]', ...heading('models')],
        title: 'Who is writing now',
        body: 'The writer your drafts use, and who pays.'
      },
      {
        id: 'cli',
        route: '/app/account/models',
        stop: 'Models',
        target: ['[data-tour="models-cli"]', '[data-tour="models-empty"]'],
        title: 'Writers you already pay for',
        body: 'A signed-in coding assistant can write drafts on its own plan.'
      },
      {
        id: 'managed',
        route: '/app/account/models',
        stop: 'Models',
        target: ['[data-tour="models-managed"]'],
        title: 'Built-in writers',
        body: 'A managed model, and a free preview.'
      },
      {
        id: 'consent',
        route: '/app/account/models',
        stop: 'Models',
        target: ['[data-tour="models-consent"]'],
        title: 'What may leave the workspace',
        body: 'What a writer may read. An owner changes it on Memory.',
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
        body: 'Your role, what it allows and how to get more.'
      },
      {
        id: 'cards',
        route: '/app/workspace/roles',
        stop: 'Roles',
        target: ['[data-tour="roles-cards"]'],
        title: 'Five roles',
        body: 'Most to least trusted, with who holds each.'
      },
      {
        id: 'matrix',
        route: '/app/workspace/roles',
        stop: 'Roles',
        target: ['[data-tour="roles-matrix"]'],
        title: 'The rules behind every action',
        body: 'A grant adds one right without changing the role.',
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
        body: 'They get a one-time link that works for 7 days.'
      },
      {
        id: 'table',
        route: '/app/workspace/members',
        stop: 'Members',
        target: ['[data-tour="members-table"]'],
        title: 'Everyone in the workspace',
        body: 'Each person’s role and grants.'
      },
      {
        id: 'invitations',
        route: '/app/workspace/members',
        stop: 'Members',
        target: ['[data-tour="members-invitations"]', '[data-tour="members-table"]'],
        title: 'Invitations you sent',
        body: 'Revoking one stops its link at once.',
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
        body: 'Who changed what, newest first. Never the content.'
      },
      {
        id: 'categories',
        route: '/app/workspace/audit',
        stop: 'Audit log',
        target: ['[data-tour="audit-categories"]', '[data-tour="audit-empty"]'],
        title: 'Filter by kind or person',
        body: 'The link keeps your filter.'
      },
      {
        id: 'coverage',
        route: '/app/workspace/audit',
        stop: 'Audit log',
        target: ['[data-tour="audit-coverage"]', '[data-tour="audit-empty"]'],
        title: 'How much you are seeing',
        body: 'Whether you see the whole log or the newest part.'
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
