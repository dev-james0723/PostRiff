/**
 * The Pipeline board as a pure function of the workspace snapshot.
 *
 * Every active source, draft, review waiting for approval and job lands in exactly one visible place: a
 * column, or a column's footer group ("Set aside", "Expired", "Cancelled or failed"). Held, failed, cancelled,
 * expired, stale, retracted and set-aside items are shown with the reason, never dropped. Moving right is always an explicit
 * action elsewhere (Schedule… → review; approve in the Queue → job; the provider confirms → published), so
 * this module only reads.
 *
 * Fields the API sends but `lib/api/types.ts` does not declare yet (variant `revisions`/`rejected`/`feedback`,
 * source `createdAt`, review `createdAt`, job `approvedAt`/`nextAt`/`scheduleId`/`approvedBy`, manifest
 * `timing.timestamp`) are read through the narrow local types below.
 */
import type { Job, Review, SnapshotSource, SnapshotState, SnapshotVariant } from '@/lib/api/types';
import { FAILED, jobGroup, jobNote, LIVE_JOB, type JobGroup } from './job-state';

/* ---------- fields the snapshot carries beyond the shared types ---------- */

export type { VariantRevision, VariantFeedback } from '@/lib/api/types';
export type PipelineVariant = SnapshotVariant;
export type PipelineSource = SnapshotSource;
export type PipelineReview = Review;
export type PipelineJob = Job;

/* ---------- time ---------- */

/**
 * ISO strings (`domain.py` uses `now()`) and epoch seconds (`store.py` uses `clock()`) both occur in one
 * snapshot. Anything unreadable is `null`, never 0: a draft "written 56 years ago" would be a lie.
 */
export function toEpoch(value: string | number | null | undefined): number | null {
  if (value == null || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) && value > 0 ? value : null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed / 1000;
}

/** The job's due time: the worker's `nextAt`, else the approved publish time. */
export function jobDueAt(job: PipelineJob): number | null {
  const timing = job.manifest.timing as PipelineJob['manifest']['timing'] & { timestamp?: number };
  return toEpoch(job.nextAt) ?? toEpoch(timing.timestamp) ?? toEpoch(timing.utc);
}

/* ---------- cards ---------- */

export type CardKind = 'source' | 'draft' | 'review' | 'job';
export type ColumnKey = 'sources' | 'drafts' | 'review' | 'queue' | 'published';

export type ChipTone = 'neutral' | 'info' | 'warning' | 'danger' | 'success';

export interface CardChip {
  label: string;
  tone: ChipTone;
  title?: string;
}

/** How the draft's latest schedule ended, when it came back to Drafts. */
export type DraftOutcome = 'cancelled' | 'failed' | 'review expired';

export interface DraftSituation {
  setAside: boolean;
  retracted: boolean;
  needsReview: boolean;
  updateProposed: boolean;
  /** Written for an earlier voice profile with no current update: Schedule… cannot offer it. */
  voiceStale: boolean;
  updateRequired: boolean;
  outcome?: DraftOutcome;
  /** The cancelled or failed job the outcome came from. */
  outcomeJobId?: string;
  /** The expired or stale review the outcome came from (only an expired one is still a card). */
  outcomeReviewId?: string;
  /**
   * A job for this draft (any revision) is not cancelled or failed, so the API refuses set-aside with 409
   * (`store.py` variant_feedback).
   */
  setAsideBlocked: boolean;
  /** Nothing on the draft itself stops Schedule… from offering it. The API still checks everything. */
  schedulable: boolean;
}

export interface BoardCard {
  /** `${kind}:${id}`, unique across the board, so a card can glide between columns. */
  key: string;
  kind: CardKind;
  id: string;
  column: ColumnKey;
  /** Whether the card sits in the column's footer group instead of its main list. */
  footer: boolean;
  platform?: string;
  /** The API's language string as sent; a language badge component is a separate workstream. */
  language?: string;
  title: string;
  body: string;
  /** Situations in the order a person needs to know them; the first one is the card's badge. */
  chips: CardChip[];
  /** Epoch seconds the column sorts by; null when the snapshot gives none. */
  when: number | null;
  /** A warning or the job's `nextAction`; shown under the text. */
  tag?: string;
  /** The draft a review or job was made from, for "Prepare again" and the detail sheet. */
  variantId?: string;
  source?: PipelineSource;
  /** On a draft, the draft; on a review or job, the draft it was made from while that draft still exists. */
  variant?: PipelineVariant;
  review?: PipelineReview;
  job?: PipelineJob;
  draft?: DraftSituation;
  jobGroup?: JobGroup;
}

export interface BoardColumn {
  key: ColumnKey;
  title: string;
  hint: string;
  href: string;
  cta: string;
  /** What an empty column teaches (general wording, no brand). */
  empty: string;
  items: BoardCard[];
  /** A collapsible group under the column ("Set aside · N", "Expired · N", "Cancelled or failed · N"). */
  footer?: { label: string; items: BoardCard[] };
}

export interface PlatformCount {
  platform: string;
  count: number;
}

export interface Board {
  columns: BoardColumn[];
  /**
   * Drafts, reviews and jobs per platform, counted before the filter so each tab's number is what choosing
   * that tab shows (footer groups included). Sources carry no platform and stay under every tab.
   */
  platforms: PlatformCount[];
  /** Drafts, reviews and jobs across every platform: the "All" tab. */
  platformTotal: number;
  /** True when the workspace has nothing at all on the board (before any filter). */
  empty: boolean;
  /** A job is being published, reconciling soon, or due within two minutes: the page refreshes the snapshot. */
  live: boolean;
  /**
   * When the board next changes without a new snapshot, in epoch seconds: a waiting or uncertain job enters the
   * live window (its due time minus two minutes), or a review reaches its approval deadline and moves to "Expired".
   */
  wakeAt: number | null;
}

export const COLUMN_META: Record<ColumnKey, Omit<BoardColumn, 'items' | 'footer'>> = {
  sources: {
    key: 'sources',
    title: 'Sources',
    hint: 'What drafts may draw from',
    href: '/app/ideas',
    cta: 'Add a source',
    empty: 'No sources yet. Drafts can start from a sentence; sources give them facts to draw on.'
  },
  drafts: {
    key: 'drafts',
    title: 'Drafts',
    hint: 'Candidates you added',
    // Creating starts in the Home composer; Ideas holds the sources drafts draw on.
    href: '/app',
    cta: 'Draft more',
    empty: 'No drafts. Describe a post on Home and its drafts land here.'
  },
  review: {
    key: 'review',
    title: 'Needs approval',
    hint: 'Exact text, media, account and time',
    href: '/app/queue',
    cta: 'Open the Queue',
    empty: 'Nothing waiting. Schedule… on a draft prepares an exact review here.'
  },
  queue: {
    key: 'queue',
    title: 'Queue',
    hint: 'Approved; the worker publishes and the provider confirms',
    href: '/app/calendar',
    cta: 'See calendar',
    empty: 'Nothing approved yet. Approve a review in the Queue and it waits here for its time.'
  },
  published: {
    key: 'published',
    title: 'Published',
    hint: 'Confirmed by the provider',
    href: '/app/analytics',
    cta: 'See analytics',
    empty: 'No provider-confirmed posts yet.'
  }
};

export const COLUMN_ORDER: ColumnKey[] = ['sources', 'drafts', 'review', 'queue', 'published'];

/** Within the Queue column, what needs a person first. */
const JOB_GROUP_ORDER: Record<JobGroup, number> = { held: 0, uncertain: 1, other: 2, publishing: 3, waiting: 4, verified: 5, ended: 6 };

/** How far ahead a waiting job starts the live refresh. */
export const LIVE_WINDOW_SECONDS = 120;

const contentKey = (variantId: string, revision: number) => `${variantId}:${revision}`;

/**
 * Past `manifest.expiresAt` a review can no longer be approved: `store.py` approve answers 409 ("This approval is
 * stale"). Expiry alone does not change its status, which stays `needs_review` until `invalidate` finds it out
 * of date, so the board reads the deadline itself.
 */
export const reviewExpired = (review: Review, now: number) => review.status === 'needs_review' && review.manifest.expiresAt <= now;

/** A review that still stands for its draft's exact revision: waiting for approval and inside its deadline. */
const reviewPending = (review: Review, now: number) => review.status === 'needs_review' && review.manifest.expiresAt > now;

/** A job or review key per draft revision that a card on the board stands for, so the draft itself is not shown twice. */
function liveContentKeys(reviews: Review[], jobs: Job[], now: number) {
  const keys = new Set<string>();
  for (const review of reviews) if (reviewPending(review, now)) keys.add(contentKey(review.manifest.variantId, review.manifest.contentRevision));
  for (const job of jobs) if (LIVE_JOB.has(job.state)) keys.add(contentKey(job.manifest.variantId, job.manifest.contentRevision));
  return keys;
}

/** What each footer group is called in a sentence ("It is now in Queue (cancelled or failed)"). */
export const FOOTER_WORDS: Partial<Record<ColumnKey, string>> = { drafts: 'set aside', review: 'expired', queue: 'cancelled or failed' };

const lastEventAt = (job: Job) => toEpoch(job.events.at(-1)?.at);
const startedAt = (job: PipelineJob) => toEpoch(job.approvedAt) ?? toEpoch(job.events[0]?.at);

interface Sortable {
  card: BoardCard;
  index: number;
}

/** Newest first; unknown times after known ones, then later snapshot entries (appended last) first. */
const newestFirst = (a: Sortable, b: Sortable) => {
  if (a.card.when !== null && b.card.when !== null && a.card.when !== b.card.when) return b.card.when - a.card.when;
  if ((a.card.when === null) !== (b.card.when === null)) return a.card.when === null ? 1 : -1;
  return b.index - a.index;
};

/** Soonest first; unknown times last, then snapshot order. */
const soonestFirst = (a: Sortable, b: Sortable) => {
  if (a.card.when !== null && b.card.when !== null && a.card.when !== b.card.when) return a.card.when - b.card.when;
  if ((a.card.when === null) !== (b.card.when === null)) return a.card.when === null ? 1 : -1;
  return a.index - b.index;
};

const sorted = (cards: BoardCard[], compare: (a: Sortable, b: Sortable) => number) =>
  cards
    .map((card, index) => ({ card, index }))
    .toSorted(compare)
    .map((entry) => entry.card);

function sourceCard(source: PipelineSource): BoardCard {
  const facts = source.facts ?? [];
  const approved = facts.filter((f) => f.approved).length;
  const chips: CardChip[] = [];
  if (source.sourcePolicy === 'prohibited') chips.push({ label: 'not for publication', tone: 'danger', title: 'This source may not be used in publications.' });
  if (facts.length > 0) chips.push({ label: `${approved}/${facts.length} facts approved`, tone: 'neutral' });
  return {
    key: `source:${source.id}`,
    kind: 'source',
    id: source.id,
    column: 'sources',
    footer: false,
    title: source.title || source.kind,
    body: source.text,
    chips,
    when: toEpoch(source.createdAt),
    source
  };
}

function draftCard(variant: PipelineVariant, situation: DraftSituation, tag: string | undefined): BoardCard {
  const chips: CardChip[] = [];
  if (situation.retracted) chips.push({ label: 'source retracted', tone: 'danger', title: 'A source this draft drew on was withdrawn. Draft it again from current sources.' });
  if (situation.setAside) chips.push({ label: 'set aside', tone: 'neutral', title: 'Kept, not scheduled. Edit it to restore.' });
  if (situation.updateProposed) chips.push({ label: 'update proposed', tone: 'info', title: 'A regenerated version is waiting; scheduling or editing accepts it first.' });
  if (situation.voiceStale) chips.push({ label: 'earlier voice', tone: 'neutral', title: 'Written before the current voice profile, so Schedule… cannot offer it. Draft it again.' });
  if (situation.needsReview) chips.push({ label: 'needs review', tone: 'warning', title: 'Unknown details must be confirmed as excluded; Schedule… asks for that.' });
  if (situation.outcome === 'failed') chips.push({ label: 'failed', tone: 'danger', title: 'The last schedule for this draft failed.' });
  if (situation.outcome === 'cancelled') chips.push({ label: 'cancelled', tone: 'neutral', title: 'The last schedule for this draft was cancelled.' });
  if (situation.outcome === 'review expired') chips.push({ label: 'review expired', tone: 'neutral', title: 'The last review of this draft passed its approval deadline or went out of date before anyone approved it.' });
  return {
    key: `draft:${variant.id}`,
    kind: 'draft',
    id: variant.id,
    column: 'drafts',
    footer: situation.setAside,
    platform: variant.platform,
    language: variant.language,
    title: variant.platform,
    body: variant.proposedUpdate?.text ?? variant.text,
    chips,
    // Ideas candidates carry no `at` on their first revision; a later edit does.
    when: toEpoch(variant.revisions?.findLast((revision) => toEpoch(revision.at) !== null)?.at),
    tag,
    variantId: variant.id,
    variant,
    draft: situation
  };
}

function reviewCard(review: PipelineReview, now: number): BoardCard {
  const expired = reviewExpired(review, now);
  return {
    key: `review:${review.id}`,
    kind: 'review',
    id: review.id,
    column: 'review',
    // Kept with its receipt, but out of the approvable list and its count.
    footer: expired,
    platform: review.manifest.platform,
    language: review.manifest.payload.language,
    title: review.manifest.account,
    body: review.manifest.payload.text,
    chips: expired ? [{ label: 'expired', tone: 'danger', title: 'The approval deadline passed, so it can no longer be approved. Schedule… the draft again.' }] : [],
    when: toEpoch(review.manifest.timing.utc),
    variantId: review.manifest.variantId,
    review
  };
}

function jobCard(job: PipelineJob): BoardCard {
  const group = jobGroup(job.state);
  const chips: CardChip[] = [];
  if (job.manifest.execution === 'synthetic') chips.push({ label: 'Fixture', tone: 'neutral', title: 'A synthetic provider, not a real post.' });
  const column: ColumnKey = group === 'verified' ? 'published' : 'queue';
  return {
    key: `job:${job.id}`,
    kind: 'job',
    id: job.id,
    column,
    footer: group === 'ended',
    platform: job.manifest.platform,
    language: job.manifest.payload.language,
    title: job.manifest.account,
    body: job.manifest.payload.text,
    chips,
    when: group === 'verified' ? (toEpoch(job.verification?.at) ?? lastEventAt(job)) : group === 'waiting' ? toEpoch(job.manifest.timing.utc) : lastEventAt(job),
    // Held, uncertain, failed and unknown states carry a reason; "Inspect receipt" on a cancelled job does not need one.
    tag: jobNote(job) ?? undefined,
    variantId: job.manifest.variantId,
    job,
    jobGroup: group
  };
}

/** Which platform filter a card answers to; sources answer to all of them. */
export function matchesPlatform(card: BoardCard, platform: string | null) {
  return platform === null || card.platform === undefined || card.platform === platform;
}

interface Attempt {
  at: number | null;
  outcome?: DraftOutcome;
  jobId?: string;
  reviewId?: string;
}

/** The latest review or job per draft, so a draft back in Drafts can say how its last schedule ended. */
function latestAttempts(reviews: PipelineReview[], jobs: PipelineJob[], now: number) {
  const latest = new Map<string, Attempt>();
  const consider = (variantId: string, attempt: Attempt) => {
    const previous = latest.get(variantId);
    if (!previous || (attempt.at ?? 0) >= (previous.at ?? 0)) latest.set(variantId, attempt);
  };
  for (const review of reviews) {
    const ended = review.status === 'stale' || reviewExpired(review, now);
    consider(review.manifest.variantId, { at: toEpoch(review.createdAt), outcome: ended ? 'review expired' : undefined, reviewId: ended ? review.id : undefined });
  }
  // Jobs after reviews: an approval stamps the job at or after its review, so on a tie the job wins.
  for (const job of jobs) {
    const outcome: DraftOutcome | undefined = job.state === 'canceled' ? 'cancelled' : job.state === 'failed' ? 'failed' : undefined;
    consider(job.manifest.variantId, { at: startedAt(job), outcome, jobId: outcome ? job.id : undefined });
  }
  return latest;
}

/**
 * Derive the five columns. `filterPlatform` narrows what is shown; sources stay because they belong to no
 * platform. Column items and footers hold exactly what is shown; nothing is hidden behind a count.
 */
export function deriveBoard(state: SnapshotState | undefined, filterPlatform: string | null = null, now = Date.now() / 1000): Board {
  const sources = (state?.sources ?? []) as PipelineSource[];
  const variants = (state?.variants ?? []) as PipelineVariant[];
  const reviews = (state?.phase2?.reviews ?? []) as PipelineReview[];
  const jobs = (state?.phase2?.jobs ?? []) as PipelineJob[];
  const activeVoice = state?.speaker?.activeRevision ?? null;

  // A draft is represented by its review or job while one is live for this exact text revision. An expired review
  // is not: approving it is refused, so its draft comes back to Drafts where Schedule… can prepare a new one.
  const liveKeys = liveContentKeys(reviews, jobs, now);

  // `store.py` variant_feedback refuses while any job for the draft is not cancelled or failed.
  const committed = new Set(jobs.filter((job) => !FAILED.has(job.state)).map((job) => job.manifest.variantId));
  const attempts = latestAttempts(reviews, jobs, now);
  const jobsById = new Map(jobs.map((job) => [job.id, job]));
  const variantsById = new Map(variants.map((variant) => [variant.id, variant]));

  const sourceCards = sorted(sources.filter((s) => s.active).map(sourceCard), newestFirst);

  const draftCards: BoardCard[] = [];
  for (const variant of variants) {
    const live = liveKeys.has(contentKey(variant.id, variant.revision));
    if (live && !variant.proposedUpdate) continue;
    const attempt = live ? undefined : attempts.get(variant.id);
    const setAside = Boolean(variant.rejected);
    const retracted = Boolean(variant.blockedByRetraction);
    // Mirrors the Schedule dialog's own list: an update written for the current voice keeps the draft usable.
    const voiceStale = activeVoice !== null && variant.voiceRevision !== activeVoice && variant.proposedUpdate?.voiceRevision !== activeVoice;
    const outcomeJob = attempt?.jobId ? jobsById.get(attempt.jobId) : undefined;
    const situation: DraftSituation = {
      setAside,
      retracted,
      needsReview: Boolean(variant.needsReview),
      updateProposed: Boolean(variant.proposedUpdate),
      voiceStale,
      updateRequired: variant.voiceRevision !== activeVoice && variant.proposedUpdate?.voiceRevision === activeVoice,
      outcome: attempt?.outcome,
      outcomeJobId: attempt?.jobId,
      outcomeReviewId: attempt?.reviewId,
      setAsideBlocked: committed.has(variant.id),
      schedulable: !setAside && !retracted && !voiceStale
    };
    const tag = (attempt?.outcome === 'failed' && outcomeJob ? jobNote(outcomeJob) : null) ?? variant.warnings[0];
    draftCards.push(draftCard(variant, situation, tag));
  }

  const reviewCards = reviews.filter((r) => r.status === 'needs_review').map((review) => ({ ...reviewCard(review, now), variant: variantsById.get(review.manifest.variantId) }));
  const pendingReviewCards = sorted(reviewCards.filter((c) => !c.footer), soonestFirst);
  const expiredReviewCards = sorted(reviewCards.filter((c) => c.footer), newestFirst);

  const jobCards = jobs.map((job) => ({ ...jobCard(job), variant: variantsById.get(job.manifest.variantId) }));
  const queueCards = sorted(
    jobCards.filter((c) => c.column === 'queue' && !c.footer),
    (a, b) => JOB_GROUP_ORDER[a.card.jobGroup ?? 'other'] - JOB_GROUP_ORDER[b.card.jobGroup ?? 'other'] || soonestFirst(a, b)
  );
  const endedCards = sorted(jobCards.filter((c) => c.footer), newestFirst);
  const publishedCards = sorted(jobCards.filter((c) => c.column === 'published'), newestFirst);
  const drafts = sorted(draftCards, newestFirst);

  const show = (cards: BoardCard[]) => cards.filter((c) => matchesPlatform(c, filterPlatform));
  const shownDrafts = show(drafts);

  const columns: BoardColumn[] = [
    { ...COLUMN_META.sources, items: sourceCards },
    { ...COLUMN_META.drafts, items: shownDrafts.filter((c) => !c.footer), footer: { label: 'Set aside', items: shownDrafts.filter((c) => c.footer) } },
    { ...COLUMN_META.review, items: show(pendingReviewCards), footer: { label: 'Expired', items: show(expiredReviewCards) } },
    { ...COLUMN_META.queue, items: show(queueCards), footer: { label: 'Cancelled or failed', items: show(endedCards) } },
    { ...COLUMN_META.published, items: show(publishedCards) }
  ];

  const counts = new Map<string, number>();
  for (const card of [...draftCards, ...reviewCards, ...jobCards]) {
    if (card.platform) counts.set(card.platform, (counts.get(card.platform) ?? 0) + 1);
  }
  const platforms = [...counts.entries()].map(([platform, count]) => ({ platform, count })).toSorted((a, b) => a.platform.localeCompare(b.platform));

  let live = false;
  // A review leaves the approvable list at its deadline, snapshot or not.
  const wakes = reviews.filter((review) => reviewPending(review, now)).map((review) => review.manifest.expiresAt);
  for (const job of jobs) {
    const group = jobGroup(job.state);
    const due = jobDueAt(job);
    if (group === 'publishing') live = true;
    // Waiting jobs are picked up at their time; uncertain ones are rechecked at `nextAt` (a day away after five
    // checks). Either way nothing moves before then, so the page only wakes two minutes ahead.
    if (group === 'waiting' || group === 'uncertain') {
      if (due === null || due <= now + LIVE_WINDOW_SECONDS) live = true;
      else wakes.push(due - LIVE_WINDOW_SECONDS);
    }
  }

  return {
    columns,
    platforms,
    platformTotal: draftCards.length + reviewCards.length + jobCards.length,
    empty: sourceCards.length + variants.length + reviews.length + jobs.length === 0,
    live,
    wakeAt: live || wakes.length === 0 ? null : Math.min(...wakes)
  };
}

export function allCards(board: Board): BoardCard[] {
  return board.columns.flatMap((column) => [...column.items, ...(column.footer?.items ?? [])]);
}

/** Find a card again after the snapshot moved on; `null` when it is gone from the board. */
export function findCard(board: Board, key: string): BoardCard | null {
  return allCards(board).find((c) => c.key === key) ?? null;
}

/**
 * Where an item went when its card is no longer on the board: a draft that was scheduled is now its review
 * or job; an approved review is now its job; a job that ended brought its draft back. `null` when nothing
 * on the board carries it (for example a source that was retracted).
 */
export function findSuccessor(board: Board, gone: BoardCard): BoardCard | null {
  const same = findCard(board, gone.key);
  if (same) return same;
  const cards = allCards(board);
  if (!gone.variantId) return null;
  if (gone.kind === 'review' && gone.review) {
    const { variantId, contentRevision, channelId } = gone.review.manifest;
    const job = cards.find((c) => c.kind === 'job' && c.job?.manifest.variantId === variantId && c.job.manifest.contentRevision === contentRevision && c.job.manifest.channelId === channelId);
    if (job) return job;
  }
  if (gone.kind === 'draft') {
    // Right-most live place first: the draft has moved as far as its latest action took it.
    const rank: Record<ColumnKey, number> = { published: 0, queue: 1, review: 2, drafts: 3, sources: 4 };
    const moved = cards
      .filter((c) => c.kind !== 'draft' && c.variantId === gone.variantId && !c.footer)
      .toSorted((a, b) => rank[a.column] - rank[b.column] || (b.when ?? 0) - (a.when ?? 0));
    return moved[0] ?? null;
  }
  return cards.find((c) => c.kind === 'draft' && c.variantId === gone.variantId) ?? null;
}

/* ---------- invariants (a future board.test.ts asserts these return []) ---------- */

/**
 * Checks the promises above against an unfiltered board:
 * - every job appears exactly once (Queue, its footer, or Published) and in the column its state names;
 * - every `needs_review` review appears exactly once, in the "Expired" group exactly when its deadline passed, and
 *   no other review appears;
 * - every active source appears once, no inactive one appears;
 * - every variant appears in Drafts (main list or "Set aside") exactly when no pending review or live job carries
 *   its current revision or it has a proposed update, and never twice;
 * - cancelled and failed jobs sit in the Queue's footer group and nothing else does; held and failed jobs show a reason;
 * - set-aside drafts sit in the Drafts footer group and nothing else does; a retracted source is named on its drafts;
 * - no card key repeats.
 */
export function boardInvariants(state: SnapshotState | undefined, board: Board, now = Date.now() / 1000): string[] {
  const problems: string[] = [];
  const seen = new Map<string, number>();
  for (const card of allCards(board)) seen.set(card.key, (seen.get(card.key) ?? 0) + 1);
  for (const [key, n] of seen) if (n > 1) problems.push(`card ${key} appears ${n} times`);

  const jobs = (state?.phase2?.jobs ?? []) as PipelineJob[];
  const reviews = (state?.phase2?.reviews ?? []) as PipelineReview[];
  for (const job of jobs) {
    const n = seen.get(`job:${job.id}`) ?? 0;
    if (n !== 1) problems.push(`job ${job.id} (${job.state}) appears ${n} times`);
    const card = findCard(board, `job:${job.id}`);
    const expected = job.state === 'verified' ? 'published' : 'queue';
    if (card && card.column !== expected) problems.push(`job ${job.id} (${job.state}) is in ${card.column}, not ${expected}`);
    if (card && card.footer !== FAILED.has(job.state)) problems.push(`job ${job.id} (${job.state}) is ${card.footer ? '' : 'not '}in the "Cancelled or failed" group`);
    if (card && (job.state === 'held' || job.state === 'failed') && !card.tag) problems.push(`job ${job.id} (${job.state}) shows no reason`);
  }
  for (const review of reviews) {
    const n = seen.get(`review:${review.id}`) ?? 0;
    if (review.status === 'needs_review' ? n !== 1 : n !== 0) problems.push(`review ${review.id} (${review.status}) appears ${n} times`);
    const card = n === 1 ? findCard(board, `review:${review.id}`) : null;
    if (card && card.footer !== reviewExpired(review, now)) problems.push(`review ${review.id} (expired: ${reviewExpired(review, now)}) is ${card.footer ? '' : 'not '}in the "Expired" group`);
  }
  for (const source of (state?.sources ?? []) as PipelineSource[]) {
    const n = seen.get(`source:${source.id}`) ?? 0;
    if (n !== (source.active ? 1 : 0)) problems.push(`source ${source.id} (active: ${source.active}) appears ${n} times`);
  }
  const liveKeys = liveContentKeys(reviews, jobs, now);
  for (const variant of (state?.variants ?? []) as PipelineVariant[]) {
    const expected = !liveKeys.has(contentKey(variant.id, variant.revision)) || Boolean(variant.proposedUpdate) ? 1 : 0;
    const n = seen.get(`draft:${variant.id}`) ?? 0;
    if (n !== expected) problems.push(`draft ${variant.id} appears ${n} times, expected ${expected}`);
    const card = n === 1 ? findCard(board, `draft:${variant.id}`) : null;
    if (card && card.footer !== Boolean(variant.rejected)) problems.push(`draft ${variant.id} (set aside: ${Boolean(variant.rejected)}) is ${card.footer ? '' : 'not '}in the "Set aside" group`);
    if (card && variant.blockedByRetraction && !card.chips.some((chip) => chip.label === 'source retracted')) problems.push(`draft ${variant.id} is blocked by a retraction but does not say so`);
  }
  return problems;
}
