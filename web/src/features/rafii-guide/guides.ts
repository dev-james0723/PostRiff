/**
 * Rafii's guided walkthroughs (docs/design/rafii-live-agent/CONTRACTS.md, Contract 5). The guide manifest
 * (`lib/site-agent/guide-manifest.json`, twin of the API's `site_agent/guide_manifest.json`) is the allowlist the
 * server may name; the steps live here, on the web only. Every manifest id has steps and every id here is in the
 * manifest (`web/tests/rafii-guide.test.cjs`).
 *
 * A ghost cursor walks each step: it glides to the target, a ring lights it and a caption says what it is for.
 * - `point` waits for Next.
 * - `click` clicks for the person, but only an element marked `data-guide-safe` (see GUIDE_SAFE); anything else
 *   becomes `await-click`.
 * - `await-click` waits for the person's own click: every submit, approval, setting, upload and sign-in is theirs.
 * - `await-visible` waits for something to appear (an upload finishing), then points at it.
 *
 * Targets are CSS selectors tried in order, by convention `[data-tour="…"]` ids on the page. No imports, so the
 * tests can load this file with `ts.transpileModule`.
 */

export type GuideAction = 'point' | 'click' | 'await-click' | 'await-visible';
export type GuidePlacement = 'top' | 'bottom' | 'left' | 'right';

/** One step (Contract 5). */
export interface GuideStep {
  /** Selectors tried in order; the first one on screen is the target. */
  target: string[];
  /** The caption: one or two short sentences. */
  say: string;
  action: GuideAction;
  /** The page the step lives on, when it isn't the guide's page. */
  route?: string;
  /** Skipped when its target never appears (a permission hides it, or there is nothing to show yet). */
  optional?: boolean;
  placement?: GuidePlacement;
}

export interface Guide {
  id: string;
  /** Where the guide starts: the path of the manifest entry's route. */
  route: string;
  steps: GuideStep[];
  /** The closing caption after the last step. */
  done: string;
}

/**
 * `data-tour` ids whose element carries `data-guide-safe`: the only elements a `click` step may press. Each one only
 * opens a sheet or dialog, selects an option inside one, or switches a tab. `self`: the element itself is marked.
 * `tabs`: a tab list's wrapper carries `data-guide-safe="tabs"`, and only its `[role="tab"]` children count.
 * Never listed: anything that submits, publishes, approves, deletes, disconnects, pays, leaves the site or starts a
 * sign-in. The attribute sits on the same line as the element's `data-tour` (the tests check both ways).
 */
export const GUIDE_SAFE: Readonly<Record<string, 'self' | 'tabs'>> = {
  'channels-connect': 'self',
  'connect-platform': 'self',
  'queue-tabs': 'tabs',
  'queue-schedule': 'self',
  'automations-new': 'self',
  'automation-steps': 'tabs'
};

const tour = (id: string) => `[data-tour="${id}"]`;

export const GUIDES: readonly Guide[] = [
  {
    id: 'connect_account',
    route: '/app/channels',
    steps: [
      { target: [tour('channels-connect')], action: 'point', say: 'Every new account starts here, with Connect account.' },
      { target: [tour('channels-connect')], action: 'click', say: 'I’ll open it for you.' },
      {
        target: [`${tour('connect-platform')}[aria-pressed="true"]`, tour('connect-platform')],
        action: 'click',
        say: 'Pick the platform. Choose a different one here if you like.'
      },
      { target: [tour('connect-capability')], action: 'point', say: 'Choose what Rafii may do with the account. It only posts what you approve.' },
      {
        target: [tour('connect-continue')],
        action: 'await-click',
        say: 'Press Continue when you’re ready. The platform’s own sign-in comes next, and you complete it yourself.'
      },
      {
        target: [tour('connect-authorize')],
        action: 'await-click',
        optional: true,
        say: 'This opens the platform’s sign-in. Sign in and approve access there yourself; Rafii never sees your password.'
      }
    ],
    done: 'When the platform sends you back, the new account shows up on Channels.'
  },
  {
    id: 'write_first_post',
    route: '/app',
    steps: [
      { target: [tour('composer-idea'), tour('composer')], action: 'point', say: 'Start here: type your idea. A topic, a link or a few notes is enough.' },
      { target: [tour('composer-channels')], action: 'point', say: 'Choose the accounts to write for. Rafii drafts one version for each.' },
      { target: [tour('composer-settings')], action: 'point', say: 'Set the language, the writer and the writing voice here.' },
      { target: [tour('composer-generate')], action: 'await-click', say: 'When your idea is in, press Generate drafts. Nothing is posted until you approve it.' }
    ],
    done: 'Your drafts appear in a moment. Review them, then schedule the ones you like.'
  },
  {
    id: 'schedule_draft',
    route: '/app/queue',
    steps: [
      { target: [`${tour('queue-tabs')} [role="tab"][data-value="drafts"]`], action: 'click', say: 'Drafts that aren’t scheduled yet wait in the Drafts tab.' },
      { target: [tour('queue-schedule')], action: 'click', say: 'Schedule a draft opens the scheduler.' },
      { target: [tour('schedule-draft')], action: 'point', say: 'Choose the draft.' },
      { target: [tour('schedule-account')], action: 'point', say: 'Pick the account it goes to.' },
      { target: [tour('schedule-time')], action: 'point', say: 'Set the day and time. It uses your time zone.' },
      {
        target: [tour('schedule-prepare')],
        action: 'await-click',
        say: 'Confirm you have the rights, then press Prepare review. Nothing publishes until someone approves it.'
      }
    ],
    done: 'It now waits in the Queue for approval.'
  },
  {
    id: 'approve_post',
    route: '/app/queue',
    steps: [
      { target: [`${tour('queue-tabs')} [role="tab"][data-value="queue"]`], action: 'click', say: 'Posts waiting for approval are on the Queue tab.' },
      { target: [tour('queue-approvals')], action: 'point', say: 'Everything waiting for approval is listed here.' },
      { target: [tour('queue-review-card')], action: 'point', optional: true, say: 'Check the exact text, account and time. The phone shows how it will look.' },
      {
        target: [tour('queue-approve')],
        action: 'await-click',
        optional: true,
        say: 'When it’s right, approve it. You approve this exact text, media, account and time.'
      }
    ],
    done: 'Anything that needs your approval shows up here.'
  },
  {
    id: 'set_up_voice',
    route: '/app/workspace/brand',
    steps: [
      { target: [tour('voice-samples')], action: 'point', say: 'Rafii learns how you write from samples you add here.' },
      { target: [tour('voice-sample-text')], action: 'point', say: 'Paste a post or caption you wrote.' },
      { target: [tour('voice-sample-consent')], action: 'point', say: 'Tick this to confirm the writing is yours. Samples stay private.' },
      { target: [tour('voice-sample-save')], action: 'await-click', say: 'Press Retain samples to save it. Add a few more the same way.' },
      {
        target: [tour('voice-analyse')],
        action: 'point',
        optional: true,
        say: 'With a few samples in, Analyse locally proposes a voice. An owner approves it.'
      }
    ],
    done: 'Once a voice is approved, every draft is written in it.'
  },
  {
    id: 'create_automation',
    route: '/app/automations',
    steps: [
      { target: [tour('automations-new')], action: 'click', say: 'New automation opens the builder.' },
      { target: [tour('automation-goal')], action: 'point', say: 'Say what each draft should be about. Rafii writes a new one every run.' },
      { target: [`${tour('automation-steps')} [role="tab"][data-value="when"]`], action: 'click', say: 'When sets how often Rafii drafts.' },
      { target: [tour('automation-when')], action: 'point', say: 'Pick the days and the time.' },
      { target: [`${tour('automation-steps')} [role="tab"][data-value="where"]`], action: 'click', say: 'Where is for the accounts.' },
      { target: [tour('automation-where')], action: 'point', say: 'Choose the accounts or folders. Each one gets its own draft.' },
      { target: [`${tour('automation-steps')} [role="tab"][data-value="review"]`], action: 'click', say: 'Review shows the writer, the cost and who approves.' },
      {
        target: [tour('automation-save')],
        action: 'await-click',
        say: 'Save it when it looks right. Every draft waits for approval unless you allow otherwise.'
      }
    ],
    done: 'Your automation is listed here. Once it’s active, Rafii drafts at the times you picked.'
  },
  {
    id: 'upload_image',
    route: '/app/library',
    steps: [
      {
        target: [tour('library-upload')],
        action: 'await-click',
        say: 'Press Upload images and choose JPEG or PNG files. You can also drop them anywhere on this page.'
      },
      { target: [tour('library-card')], action: 'await-visible', optional: true, say: 'Uploaded images appear here, ready to attach to a post.' }
    ],
    done: 'Your images are in the Library. Attach one when you write or schedule a post.'
  },
  {
    id: 'turn_on_web_search',
    route: '/app/workspace/memory',
    steps: [
      { target: [tour('memory-access')], action: 'point', say: 'This card decides who else may read your memory files, including web research.' },
      {
        target: [`${tour('memory-access')} [role="switch"][aria-label="Let Rafii look facts up on the web"]`],
        action: 'await-click',
        optional: true,
        say: 'Turn on Web research. Only an owner can change it, and Rafii asks you to confirm first.'
      },
      { target: [tour('memory-access-confirm')], action: 'await-click', optional: true, say: 'Read what is looked up and where, then press Turn on.' }
    ],
    done: 'With web research on, Rafii can look up current facts and news for you.'
  },
  {
    id: 'choose_model',
    route: '/app/account/models',
    steps: [
      { target: [tour('models-current')], action: 'point', say: 'This is the writer your drafts use now.' },
      { target: [tour('models-managed')], action: 'point', say: 'Pick a built-in writer here. New drafts use your choice.' }
    ],
    done: 'You can come back and change the writer any time.'
  },
  {
    id: 'check_plan',
    route: '/app/account/billing',
    steps: [
      { target: [tour('billing-plan')], action: 'point', say: 'Your plan, and what changes next.' },
      { target: [tour('billing-allowances')], action: 'point', say: 'What’s left on your plan this period.' },
      { target: [tour('billing-plans')], action: 'point', optional: true, say: 'Owners can change the plan here.' }
    ],
    done: 'When the limit is reached, paid work stops and nothing extra is charged.'
  }
];

const BY_ID: Readonly<Record<string, Guide>> = Object.fromEntries(GUIDES.map((guide) => [guide.id, guide]));

export function guideFor(id: string): Guide | null {
  return Object.prototype.hasOwnProperty.call(BY_ID, id) ? BY_ID[id] : null;
}

/** The path part of a route ("/app/queue?view=drafts" → "/app/queue"). */
export function pathOf(route: string): string {
  return route.split('#')[0].split('?')[0] || '/';
}

/** The little of an element the safety check reads (a DOM element, or a fake one in tests). */
export interface SafetyElement {
  getAttribute(name: string): string | null;
  closest(selector: string): SafetyElement | null;
}

/**
 * Whether the guide may click this element for the person: it carries `data-guide-safe`, or it is a tab inside a
 * tab list marked `data-guide-safe="tabs"`. Everything else waits for the person's own click.
 */
export function isGuideSafe(el: SafetyElement | null | undefined): boolean {
  if (!el) return false;
  const own = el.getAttribute('data-guide-safe');
  if (own !== null && own !== 'tabs') return true;
  if (el.getAttribute('role') !== 'tab') return false;
  return el.closest('[data-guide-safe]')?.getAttribute('data-guide-safe') === 'tabs';
}
