/**
 * Data views of the journey read bindings (lane E). Every journey component receives a `UiQueryResultV1` envelope from a
 * `Query(...)` reference and safe-parses `data` with the view of its binding before it shows anything.
 *
 * Rules these views encode:
 *   - Unknown is not zero: counts and values that may be unknown are `number | null`; components print null as Unknown or
 *     Unavailable, never 0.
 *   - Times are ISO instants plus the zone they are shown in; local wall-clock strings always travel with their zone.
 *   - Refs are opaque `<type>:<id>` strings. No URL to private bytes appears in a view: previews load from refs.
 *   - A view that fails to parse is shown as "can't show this data", never patched up with defaults.
 */
import { z } from 'zod';
import { uiQueryResultSchema, type DataState, type UiQueryResultV1 } from '@/lib/agent-runtime/ui-contracts';

export const REF_PATTERN = /^[a-z][a-z_]{1,19}:[A-Za-z0-9_.:-]{1,128}$/;
const ref = z.string().regex(REF_PATTERN);
const iso = z.string().max(40);
const text = (max: number) => z.string().max(max);
/** A count that may be unknown. */
const count = z.number().int().nonnegative().nullable();
const range = z.object({ period: text(40), start: iso.nullable(), end: iso.nullable(), zone: text(64) });
const edge = z.object({ relation: text(60), ref, title: text(200).nullable(), via: text(60).nullable() });

// --- J01 drafts --------------------------------------------------------------------------------------------------------
const draftRow = z.object({
  ref,
  platform: text(40),
  language: text(40).nullable(),
  account: text(120).nullable(),
  revision: z.number().int().nonnegative(),
  characters: z.number().int().nonnegative(),
  limit: z.number().int().positive().nullable(),
  overLimit: z.boolean(),
  needsReview: z.boolean(),
  hasProposedUpdate: z.boolean(),
  committed: z.boolean(),
  jobState: text(40).nullable(),
  sourceCount: count,
  warningsCount: count,
  unknownsCount: count,
  writerModel: text(80).nullable(),
  voiceMode: z.enum(['neutral', 'personalized']).nullable(),
  createdAt: iso.nullable(),
  excerpt: text(400),
});
const scheduledJob = z.object({ ref, state: text(40), local: text(40).nullable(), zone: text(64).nullable() });
const draftDetail = draftRow.extend({
  text: text(20000),
  textTruncated: z.boolean(),
  unknowns: z.array(text(240)).max(20),
  warnings: z.array(text(240)).max(20),
  setAside: z.boolean(),
  blockedByRetraction: z.boolean(),
  scheduled: z.array(scheduledJob).max(5),
});

// --- J02 calendar ------------------------------------------------------------------------------------------------------
export const CALENDAR_STATUSES = ['scheduled', 'awaiting_approval', 'in_flight', 'failed_held_uncertain', 'published', 'verified', 'unknown'] as const;
const calendarEntry = z.object({
  ref,
  kind: z.enum(['job', 'review', 'planned']),
  state: text(40),
  status: z.enum(CALENDAR_STATUSES),
  platform: text(40).nullable(),
  account: text(120).nullable(),
  atUtc: iso.nullable(),
  local: text(40).nullable(),
  zone: text(64).nullable(),
  title: text(200).nullable(),
  fromAutomation: z.boolean(),
});
const observation = z.object({ kind: text(40), refs: z.array(ref).max(10), rule: text(200), text: text(240) });
const queueItem = z.object({
  ref,
  state: text(40),
  status: z.enum(CALENDAR_STATUSES),
  platform: text(40).nullable(),
  account: text(120).nullable(),
  local: text(40).nullable(),
  zone: text(64).nullable(),
  reason: text(240).nullable(),
});
const statusCounts = z.record(z.string(), z.number().int().nonnegative());

// --- J03 library -------------------------------------------------------------------------------------------------------
export const PREVIEW_KINDS = ['image', 'video_poster', 'pdf_page', 'document_cover', 'audio_cover', 'file_cover', 'server_page'] as const;
const libraryRow = z.object({
  ref,
  kind: z.enum(['image', 'video', 'audio', 'document', 'file']),
  title: text(240),
  mime: text(120).nullable(),
  extension: text(16).nullable(),
  bytes: z.number().int().nonnegative().nullable(),
  createdAt: iso.nullable(),
  processing: text(40).nullable(),
  indexingStatus: text(40).nullable(),
  transcriptionStatus: text(40).nullable(),
  tags: z.array(text(60)).max(40),
  collections: z.array(text(120)).max(40),
  hasSource: z.boolean(),
  sourceRef: ref.nullable(),
  duplicateOf: ref.nullable(),
  previewKind: z.enum(PREVIEW_KINDS).nullable(),
});

// --- J04 voice ---------------------------------------------------------------------------------------------------------
export const EXCLUSION_REASONS = ['revoked', 'not_selected', 'purpose_not_granted', 'route_not_granted'] as const;
export const EVIDENCE_LEVELS = ['supported', 'limited', 'conflicting', 'insufficient'] as const;
const voiceSample = z.object({
  ref,
  title: text(200).nullable(),
  platform: text(40).nullable(),
  language: text(40).nullable(),
  label: text(40).nullable(),
  origin: text(40),
  active: z.boolean(),
  selected: z.boolean(),
  revision: z.number().int().nonnegative(),
  eligible: z.boolean().nullable(),
  exclusionReason: z.enum(EXCLUSION_REASONS).nullable(),
  grants: z.array(z.object({ purpose: text(40), route: text(120) })).max(20),
  publishedAt: iso.nullable(),
  partialCoverage: z.boolean(),
});

// --- J05 campaigns -----------------------------------------------------------------------------------------------------
const campaignSummary = z.object({
  ref,
  goal: text(1200),
  status: text(40),
  missingFacts: z.array(text(60)).max(20),
  itemCount: count,
  automationCount: count,
  updatedAt: iso.nullable(),
});
const localTime = z.object({ utc: iso.nullable(), local: text(40).nullable(), zone: text(64).nullable() });
const automationRow = z.object({
  ref,
  name: text(120),
  status: z.enum(['draft', 'active', 'paused', 'cancelled']),
  schedule: text(200).nullable(),
  zone: text(64).nullable(),
  policy: text(40).nullable(),
  platforms: z.array(text(40)).max(20),
  nextRun: localTime.nullable(),
  nextPublish: localTime.nullable(),
});
export const TASK_STEP_STATES = ['planned', 'running', 'done', 'needs_user', 'blocked', 'failed', 'canceled'] as const;

// --- J06 analytics -----------------------------------------------------------------------------------------------------
export const AVAILABILITY = ['available', 'unavailable', 'suppressed', 'not_supported'] as const;
const metricReading = z.object({
  value: z.number().nullable(),
  availability: z.enum(AVAILABILITY),
  unit: text(20),
  observedAt: iso.nullable(),
  readOffset: text(20).nullable(),
});

// --- J09 founder -------------------------------------------------------------------------------------------------------
const founderState = z.enum(['available', 'partial', 'unavailable', 'empty']);

export const VIEWS = {
  draftList: z.object({ items: z.array(draftRow).max(100), total: count }),
  draftCompare: z.object({ drafts: z.array(draftDetail).min(1).max(4) }),
  draftDetail,
  draftEvidence: z.object({
    draftRef: ref,
    edges: z.array(edge).max(60),
    sources: z
      .array(z.object({ ref, title: text(200).nullable(), kind: text(40), host: text(120).nullable(), approvedFacts: count, policy: text(40).nullable() }))
      .max(40),
    voice: z
      .object({ findings: z.array(z.object({ basis: z.enum(['measured', 'heuristic', 'needs_writer']), label: text(120), detail: text(240).nullable() })).max(20) })
      .nullable(),
  }),
  calendarAgenda: z.object({
    range,
    entries: z.array(calendarEntry).max(100),
    total: count,
    statusCounts,
    unknownStates: z.array(text(40)).max(20),
    observations: z.array(observation).max(30),
  }),
  queueStatus: z.object({
    statusCounts,
    unknownStates: z.array(text(40)).max(20),
    draftsUnscheduled: count,
    attention: z.array(queueItem).max(20),
    waiting: z.array(queueItem).max(20),
    upcoming: z.array(queueItem).max(20),
  }),
  slotCheck: z.object({
    targetRef: ref,
    local: text(40),
    zone: text(64),
    valid: z.boolean(),
    utc: iso.nullable(),
    problem: z.object({ code: text(60), message: text(240) }).nullable(),
    collisions: z.array(z.object({ ref, local: text(40).nullable(), zone: text(64).nullable(), account: text(120).nullable(), minutesApart: z.number() })).max(20),
    rule: text(200),
  }),
  librarySearch: z.object({ items: z.array(libraryRow).max(100), query: text(120), kind: text(20), total: count }),
  libraryItem: libraryRow.extend({
    excerpt: text(2000).nullable(),
    chunkCount: count,
    extraction: text(40).nullable(),
    canUseAsSource: z.boolean(),
  }),
  lineage: z.object({ ref, edges: z.array(edge).max(60) }),
  libraryCollections: z.object({ collections: z.array(z.object({ id: text(64), name: text(120), count })).max(100) }),
  voiceSources: z.object({ purpose: text(40).nullable(), route: text(120).nullable(), samples: z.array(voiceSample).max(100) }),
  voiceProfile: z.object({
    active: z.object({ revision: z.number().int().nonnegative(), approvedAt: iso.nullable(), reason: text(240).nullable(), stale: z.boolean() }).nullable(),
    proposed: z
      .object({
        status: z.enum(['proposed', 'stale']),
        method: z.enum(['local-rules', 'ai']),
        proposedAt: iso.nullable(),
        sampleCount: count,
        dimensions: z.array(z.object({ id: text(60), observation: text(240), evidenceLevel: z.enum(EVIDENCE_LEVELS), supportCount: count })).max(30),
        unknowns: z.array(text(240)).max(20),
      })
      .nullable(),
    draftsOnVoice: count,
    boundJobs: count,
  }),
  voicePreferences: z.object({
    learned: z
      .array(z.object({ ref, statement: text(400), scope: text(80).nullable(), status: z.enum(['active', 'paused', 'retired']), evidenceState: text(60).nullable(), since: iso.nullable() }))
      .max(100),
    pending: z
      .array(z.object({ ref, statement: text(400), why: text(400).nullable(), source: text(40).nullable(), expiresAt: iso.nullable(), evidence: z.array(text(240)).max(10) }))
      .max(20),
  }),
  voiceLearningStatus: z.object({
    enabled: z.boolean(),
    cloudMemory: z.boolean(),
    cloudExtraction: z.boolean(),
    extractor: z.object({ kind: text(20), allowed: z.boolean() }).nullable(),
    pendingEvents: count,
    pendingProposals: count,
    newestProposalAt: iso.nullable(),
  }),
  campaignList: z.object({ items: z.array(campaignSummary).max(100), total: count }),
  campaignDetail: campaignSummary.extend({
    audience: text(800).nullable(),
    facts: z.array(z.object({ key: text(60), value: text(160).nullable() })).max(30),
    items: z
      .array(z.object({ ref, kind: z.enum(['draft', 'post', 'asset']), title: text(200).nullable(), addedAt: iso.nullable(), state: text(40).nullable(), needsReview: z.boolean() }))
      .max(200),
    automations: z.array(z.object({ ref, name: text(120), status: text(40), schedule: text(200).nullable(), nextRun: localTime.nullable() })).max(20),
  }),
  campaignTimeline: z.object({
    range,
    events: z
      .array(z.object({ ref, kind: z.enum(['run', 'post', 'review', 'item']), at: iso.nullable(), local: text(40).nullable(), zone: text(64).nullable(), state: text(40).nullable(), title: text(200).nullable() }))
      .max(200),
  }),
  taskProgress: z.object({
    taskRef: ref.nullable(),
    steps: z
      .array(z.object({ id: text(60), label: text(200), state: z.enum(TASK_STEP_STATES), dependsOn: z.array(text(60)).max(10), verified: z.boolean(), reason: text(240).nullable() }))
      .max(30),
  }),
  analyticsPosts: z.object({
    range,
    posts: z
      .array(z.object({ ref, platform: text(40), account: text(120).nullable(), publishedAt: iso.nullable(), title: text(200).nullable(), metrics: z.record(z.string(), metricReading) }))
      .max(100),
    total: count,
    definitionVersion: text(40),
    rules: z.array(text(200)).max(10),
  }),
  analyticsSeries: z.object({
    metric: text(40),
    unit: text(20),
    bucket: z.enum(['day', 'week']),
    range,
    points: z.array(z.object({ start: iso, label: text(40), value: z.number().nullable(), posts: count })).max(400),
    rule: text(200),
    definitionVersion: text(40),
  }),
  analyticsCompare: z.object({
    metric: text(40),
    unit: text(20),
    outcome: z.enum(['no_data', 'insufficient_sample', 'observation_only']),
    sampleSize: count,
    measured: count,
    missing: count,
    minimum: z.number().int().positive(),
    mean: text(60).nullable(),
    rule: text(200),
    causalityEstablished: z.literal(false),
  }),
  analyticsCoverage: z.object({
    state: z.enum(['unavailable', 'pending', 'partial', 'ready']),
    connections: z
      .array(z.object({ ref, platform: text(40), account: text(120).nullable(), level: text(40), analytics: text(60), note: text(240).nullable() }))
      .max(50),
    note: text(240).nullable(),
  }),
  researchState: z.object({ web: z.boolean(), enabled: z.boolean(), hosted: z.boolean(), decidedAt: iso.nullable(), canDecide: z.boolean() }),
  researchResults: z.object({
    state: z.enum(['available', 'empty', 'off', 'unavailable']),
    query: text(400).nullable(),
    pages: z
      .array(z.object({ ref, title: text(240), url: text(2000), host: text(200), published: iso.nullable(), fetchedAt: iso.nullable(), facts: z.array(text(500)).max(12), saved: z.boolean() }))
      .max(12),
    warnings: z.array(text(240)).max(10),
  }),
  automationList: z.object({ items: z.array(automationRow).max(50) }),
  automationDetail: automationRow.extend({ upcoming: z.array(localTime).max(14), needs: z.array(text(240)).max(10) }),
  automationRuns: z.object({
    automationRef: ref,
    runs: z
      .array(z.object({ ref, scheduledFor: localTime, stage: text(40), status: text(40), items: z.array(z.object({ state: text(40), reason: text(240).nullable() })).max(20), completedAt: iso.nullable() }))
      .max(50),
  }),
  connectionsStatus: z.object({
    accounts: z
      .array(
        z.object({
          ref,
          platform: text(40),
          account: text(120).nullable(),
          state: text(40),
          revoked: z.boolean(),
          canPublish: z.boolean().nullable(),
          reason: text(240).nullable(),
          guide: text(40).nullable(),
          href: text(200).nullable(),
        }),
      )
      .max(50),
    attention: z.enum(['available', 'unavailable']),
  }),
  founderMetrics: z.object({
    range,
    metrics: z
      .array(
        z.object({
          id: text(60),
          label: text(120),
          unit: text(20),
          currency: text(8).nullable(),
          dataState: founderState,
          reason: text(120).nullable(),
          value: z.number().nullable(),
          points: z.array(z.object({ start: iso, value: z.number().nullable() })).max(400),
          coverage: z.object({ known: count, total: count, note: text(240).nullable() }).nullable(),
          receiptIds: z.array(text(80)).max(20),
        }),
      )
      .max(6),
  }),
  founderCosts: z.object({
    dimension: text(20),
    range,
    state: founderState,
    reason: text(120).nullable(),
    rows: z.array(z.object({ key: text(80), label: text(120), costUsdMicro: z.number().nullable(), calls: count, unknownCalls: count })).max(100),
    unknownCostCalls: count,
    receiptIds: z.array(text(80)).max(20),
  }),
  founderReliability: z.object({
    range,
    indicators: z.array(z.object({ id: text(60), label: text(120), value: z.number().nullable(), unit: text(20), dataState: founderState, reason: text(120).nullable() })).max(20),
    incidents: z.array(z.object({ ref, title: text(200), severity: text(20), status: text(20), openedAt: iso.nullable() })).max(20),
    sources: z.array(z.object({ id: text(60), label: text(120), state: text(40), asOf: iso.nullable() })).max(30),
  }),
  founderSupport: z.object({
    counts: statusCounts,
    tickets: z.array(z.object({ ref, subject: text(200).nullable(), status: text(40), ageHours: z.number().nonnegative().nullable(), customer: text(80).nullable() })).max(50),
  }),
} as const;

export type ViewId = keyof typeof VIEWS;
export type ViewData<V extends ViewId> = z.infer<(typeof VIEWS)[V]>;

/** What a journey component can show for one query reference. */
export type QueryRead<T> =
  | { kind: 'loading' }
  | { kind: 'denied' | 'unavailable'; result: UiQueryResultV1 }
  | { kind: 'empty'; result: UiQueryResultV1; data: T | null }
  | { kind: 'invalid' }
  | { kind: 'data'; state: Extract<DataState, 'available' | 'partial' | 'stale'>; result: UiQueryResultV1; data: T };

/**
 * Read a `Query(...)` value (null until the bridge answers) as one of the states above. The envelope and the data are
 * both validated; nothing is defaulted. `loading` from the server is still loading; `denied`/`unavailable` carry their
 * warnings so the component can name the reason.
 */
export function readQuery<V extends ViewId>(value: unknown, view: V): QueryRead<ViewData<V>> {
  if (value === null || value === undefined) return { kind: 'loading' };
  const envelope = uiQueryResultSchema.safeParse(value);
  if (!envelope.success) return { kind: 'invalid' };
  const result = envelope.data;
  if (result.state === 'loading') return { kind: 'loading' };
  if (result.state === 'denied' || result.state === 'unavailable') return { kind: result.state, result };
  const schema: z.ZodType = VIEWS[view];
  const parsed = schema.safeParse(result.data);
  if (result.state === 'empty') return { kind: 'empty', result, data: parsed.success ? (parsed.data as ViewData<V>) : null };
  if (!parsed.success) return { kind: 'invalid' };
  return { kind: 'data', state: result.state, result, data: parsed.data as ViewData<V> };
}
