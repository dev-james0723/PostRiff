/**
 * Plain-language presentation for the coworker screens: slot and week states, quality findings, the week's single
 * next action. Pure (no imports) so node's test runner can load it directly (`web/tests/coworker-present.test.mjs`).
 *
 * Honesty rules: "scheduled" and "published" appear only when the API status says so (the server reads them
 * back from Queue jobs); an accepted post is described as waiting in Queue, never as scheduled.
 */

export type SlotGroup = 'ready' | 'blocked' | 'working' | 'handed' | 'skipped';
export type Tone = 'neutral' | 'attention' | 'success';

export interface SlotStatusMeta {
  label: string;
  group: SlotGroup;
  tone: Tone;
  /** An icon name from `@/components/icons` (kept as a string so this file stays import-free). */
  icon: string;
  hint: string;
}

const SLOT: Record<string, SlotStatusMeta> = {
  planned: { label: 'Waiting to be drafted', group: 'working', tone: 'neutral', icon: 'circleDashed', hint: 'Rafii drafts it when the week is prepared.' },
  drafted: { label: 'Being checked', group: 'working', tone: 'neutral', icon: 'hourglass', hint: 'Drafted; the quality checks have not finished.' },
  ready: { label: 'Ready', group: 'ready', tone: 'success', icon: 'circleCheck', hint: 'Drafted and checked. Accept it, redo it or skip it.' },
  needs_revision: { label: 'Needs revision', group: 'ready', tone: 'attention', icon: 'warning', hint: 'The meaning check found something your sources do not support.' },
  needs_input: { label: 'Needs your input', group: 'blocked', tone: 'attention', icon: 'messageCircle', hint: 'Rafii needs a short answer from you before it can write this.' },
  needs_source: { label: 'Needs a source', group: 'blocked', tone: 'attention', icon: 'page', hint: 'No approved source covers this post yet.' },
  needs_asset: { label: 'Needs an image', group: 'blocked', tone: 'attention', icon: 'media', hint: 'The text is ready; this platform needs an image. A creative brief is attached.' },
  channel_unavailable: { label: 'Account unavailable', group: 'blocked', tone: 'attention', icon: 'broadcast', hint: 'This account cannot post until it is reconnected.' },
  accepted: { label: 'Accepted · confirm in Queue', group: 'handed', tone: 'neutral', icon: 'check', hint: 'In Queue → Drafts. Confirm and approve it there; nothing is scheduled yet.' },
  in_queue: { label: 'In Queue for approval', group: 'handed', tone: 'neutral', icon: 'listDetails', hint: 'Waiting for someone with approval rights in Queue.' },
  approved: { label: 'Approved', group: 'handed', tone: 'success', icon: 'circleCheck', hint: 'Approved in Queue; not scheduled until a publishing job exists.' },
  scheduled: { label: 'Scheduled', group: 'handed', tone: 'success', icon: 'calendarEvent', hint: 'Queue has a publishing job for it.' },
  published: { label: 'Published', group: 'handed', tone: 'success', icon: 'badgeCheck', hint: 'The platform confirmed the post.' },
  failed: { label: 'Did not publish', group: 'blocked', tone: 'attention', icon: 'circleX', hint: 'The publishing job failed or is held. The draft is kept.' },
  rejected: { label: 'Skipped', group: 'skipped', tone: 'neutral', icon: 'slash', hint: 'Not part of this week.' },
  approval_expired: { label: 'Approval expired', group: 'blocked', tone: 'attention', icon: 'clock', hint: 'The approval went stale before its time. Choose a new time in Queue.' }
};

export function slotStatus(status: string): SlotStatusMeta {
  return SLOT[status] ?? { label: humanize(status), group: 'working', tone: 'neutral', icon: 'circle', hint: '' };
}

const WEEK: Record<string, string> = {
  planned: 'Planned',
  researching: 'Researching',
  generating: 'Drafting',
  quality_check: 'Checking quality',
  ready_for_review: 'Ready for review',
  approved: 'Approved in Queue',
  scheduled: 'Scheduled',
  needs_input: 'Waiting for your input',
  needs_source: 'Waiting for a source',
  needs_asset: 'Waiting for an image',
  channel_unavailable: 'An account is unavailable',
  approval_expired: 'An approval expired'
};

export function weekStateLabel(state: string): string {
  return WEEK[state] ?? humanize(state);
}

export function humanize(value: string | null | undefined): string {
  const text = String(value ?? '').replace(/[_.-]+/g, ' ').trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
}

/* ---------- quality findings in plain language ---------- */

const MEANING: Record<string, string> = {
  number_added: 'a number that is not in your sources',
  number_changed: 'a number that differs from your sources',
  date_changed: 'a date that differs from your sources',
  name_added: 'a name that is not in your sources',
  name_changed: 'a name from your sources is missing',
  negation_lost: 'a “not” from the source was dropped',
  hedge_removed: 'the source’s uncertainty was dropped',
  certainty_added: 'it sounds more certain than the source',
  attribution_lost: 'a source attribution was dropped',
  scope_changed: 'a qualifier changed (some/all, only/every)',
  status_changed: 'something planned now reads as done',
  causal_added: 'a cause-and-effect claim that is not in the source',
  anecdote_added: 'a personal story that is not in your sources',
  feeling_added: 'a feeling that is not in your sources',
  brand_term_changed: 'an approved brand term was changed'
};

const STYLE: Record<string, string> = {
  synthetic_cluster: 'several stock phrases that can read as machine-written',
  dash_density: 'many dashes (a clue only; keep the ones you mean)',
  script_mixed: 'Simplified and Traditional characters are mixed'
};

export interface PlainFinding {
  kind: 'meaning' | 'unchecked' | 'style' | 'length' | 'language' | 'voice';
  /** Blocking findings stop "ready": only meaning findings do. */
  blocking: boolean;
  text: string;
  detail?: string;
}

interface FindingLike {
  code?: string;
  detail?: string;
}

interface QualityLike {
  meaning?: FindingLike[] | null;
  /** What the meaning check compared the draft with; 'none' means names, numbers and dates were not checked. */
  meaningBasis?: 'approved_facts' | 'your_answer' | 'none' | null;
  style?: FindingLike[] | null;
  lint?: FindingLike[] | null;
  voiceFit?: { differs?: { trait?: string; evidence?: string }[] | null; unavailable?: string } | null;
}

export function plainFindings(quality: QualityLike | null | undefined, platform?: string): PlainFinding[] {
  if (!quality) return [];
  const out: PlainFinding[] = [];
  for (const f of quality.meaning ?? []) {
    out.push({ kind: 'meaning', blocking: true, text: `Meaning check: ${MEANING[f.code ?? ''] ?? humanize(f.code).toLowerCase()}`, detail: f.detail });
  }
  if (quality.meaningBasis === 'none') {
    out.push({ kind: 'unchecked', blocking: false, text: 'Facts not checked: this post had no approved source', detail: 'Check any names, numbers and dates yourself before you accept it.' });
  }
  for (const f of quality.style ?? []) {
    out.push({ kind: 'style', blocking: false, text: `Style: ${STYLE[f.code ?? ''] ?? humanize(f.code).toLowerCase()}`, detail: f.detail });
  }
  for (const f of quality.lint ?? []) {
    if (f.code === 'too_long') out.push({ kind: 'length', blocking: false, text: `Too long for ${platform ?? 'this platform'}`, detail: f.detail });
    else out.push({ kind: 'language', blocking: false, text: 'Language note', detail: f.detail });
  }
  for (const d of quality.voiceFit?.differs ?? []) {
    out.push({ kind: 'voice', blocking: false, text: `Voice fit: ${d.trait ? humanize(d.trait).toLowerCase() : 'a trait'} differs from how you usually write`, detail: d.evidence });
  }
  return out;
}

/* ---------- the week at a glance ---------- */

interface SlotLike {
  id: string;
  status: string;
}

export interface WeekSummary {
  ready: number;
  needsRevision: number;
  blocked: number;
  waiting: number;
  handed: number;
  skipped: number;
  total: number;
}

export function summarizeSlots(slots: SlotLike[]): WeekSummary {
  const summary: WeekSummary = { ready: 0, needsRevision: 0, blocked: 0, waiting: 0, handed: 0, skipped: 0, total: slots.length };
  for (const slot of slots) {
    const group = slotStatus(slot.status).group;
    if (slot.status === 'needs_revision') summary.needsRevision += 1;
    else if (group === 'ready') summary.ready += 1;
    else if (group === 'blocked') summary.blocked += 1;
    else if (group === 'working') summary.waiting += 1;
    else if (group === 'handed') summary.handed += 1;
    else summary.skipped += 1;
  }
  return summary;
}

export type NextActionKind = 'setup' | 'prepare' | 'continue' | 'answer' | 'review' | 'queue' | 'source' | 'asset' | 'reconnect' | 'none';

export interface NextAction {
  kind: NextActionKind;
  label: string;
  why: string;
  /** The slot to focus, when the action is about one post. */
  slotId?: string;
}

/** Week states in which the server no longer drafts waiting posts (it only reads Queue back). */
export const REVIEW_STATES = ['ready_for_review', 'approved', 'scheduled'];

/** A waiting post the server will not draft: the rest of its week is already in review. */
export function isStalled(slotStatus: string, weekState: string | null | undefined): boolean {
  return slotStatus === 'planned' && REVIEW_STATES.includes(weekState ?? '');
}

/** The single most useful next step for this week, in a fixed order: answers unblock drafting before review. */
export function nextAction(input: { hasRecipe: boolean; canSetUp: boolean; week: { slots: SlotLike[]; state?: string } | null }): NextAction {
  if (!input.hasRecipe) {
    return input.canSetUp
      ? { kind: 'setup', label: 'Set up your week', why: 'Tell Rafii which accounts, how often and what for. Nothing is drafted until you prepare a week.' }
      : { kind: 'none', label: 'No weekly plan yet', why: 'An owner sets up the weekly plan.' };
  }
  if (!input.week) return { kind: 'prepare', label: 'Prepare next week now', why: 'Rafii plans next week and drafts what it can. Nothing is scheduled.' };
  const slots = input.week.slots;
  const first = (status: string) => slots.find((s) => s.status === status);
  const count = (status: string) => slots.filter((s) => s.status === status).length;
  const question = first('needs_input');
  if (question) return { kind: 'answer', label: count('needs_input') > 1 ? `Answer ${count('needs_input')} questions` : 'Answer 1 question', why: 'Rafii can’t write these posts without you.', slotId: question.id };
  const planned = REVIEW_STATES.includes(input.week.state ?? '') ? 0 : count('planned');
  if (planned > 0) return { kind: 'continue', label: planned > 1 ? `Draft ${planned} waiting posts` : 'Draft 1 waiting post', why: 'These posts are planned but not drafted yet.' };
  const reviewable = slots.filter((s) => s.status === 'ready' || s.status === 'needs_revision');
  if (reviewable.length) return { kind: 'review', label: reviewable.length > 1 ? `Review ${reviewable.length} posts` : 'Review 1 post', why: 'Accept what’s right; redo or skip the rest.', slotId: reviewable[0].id };
  const accepted = count('accepted');
  if (accepted) return { kind: 'queue', label: 'Confirm in Queue → Drafts', why: `${accepted} accepted post${accepted > 1 ? 's wait' : ' waits'} in Queue. Nothing is scheduled until it is approved there.` };
  const source = first('needs_source');
  if (source) return { kind: 'source', label: 'Add a source', why: 'Some posts need an approved source before Rafii can write them.', slotId: source.id };
  const asset = first('needs_asset');
  if (asset) return { kind: 'asset', label: 'Add an image', why: 'A creative brief is ready for the posts that need an image.', slotId: asset.id };
  const channel = first('channel_unavailable');
  if (channel) return { kind: 'reconnect', label: 'Reconnect the account', why: 'Posts for that account are paused until it is reconnected.', slotId: channel.id };
  return { kind: 'none', label: 'Nothing needs you this week', why: 'Everything is drafted, handed to Queue or skipped.' };
}

/* ---------- dates ---------- */

/** "Monday 28 Sep" for an ISO date, read as a calendar date (no time-zone shift). */
export function dayLabel(isoDate: string, locale = 'en-GB'): string {
  const date = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDate;
  return new Intl.DateTimeFormat(locale, { weekday: 'long', day: 'numeric', month: 'short', timeZone: 'UTC' }).format(date);
}

/** "09:00" from the slot's local "YYYY-MM-DDTHH:MM". */
export function timeLabel(localTime: string | null | undefined): string {
  const match = /T(\d{2}:\d{2})/.exec(localTime ?? '');
  return match ? match[1] : '';
}

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const;
