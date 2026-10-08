/**
 * Data views of the journey read bindings (lane E), one per binding name of lane D's `ui_domain` registry. Every journey
 * component receives a `UiQueryResultV1` envelope from a `Query(...)` reference and safe-parses `data` with the view of
 * the binding it expects before it shows anything.
 *
 * A view lists only the fields the component reads (zod drops the rest), each with the exact type D's handler returns.
 * Rules these views encode:
 *   - Unknown is not zero: counts and values that may be unknown are `number | null`; components print null as Unknown
 *     or Unavailable, never 0.
 *   - Times are ISO instants plus the zone they are shown in; a local wall-clock string always travels with its zone.
 *   - No view carries a URL to private bytes: previews load from asset ids through the app's own authorized routes.
 *   - A view that fails to parse is shown as "can't show this data", never patched up with defaults.
 */
import { z } from 'zod';
import { uiQueryResultSchema, type DataState, type UiQueryResultV1 } from '@/lib/agent-runtime/ui-contracts';

const text = (max: number) => z.string().max(max);
const opt = <T extends z.ZodType>(schema: T) => schema.nullable().optional();
const iso = text(40);
const id = text(160);
const ref = z.string().regex(/^[a-z][a-z_]{1,23}:[A-Za-z0-9_.:-]{1,160}$/);
/** A count that may be unknown. */
const count = z.number().int().nonnegative().nullable();
const inAppHref = z
  .string()
  .max(400)
  .refine((h) => h === '/app' || h.startsWith('/app/') || h.startsWith('/app?'), 'in-app path');

// --- J01 drafts --------------------------------------------------------------------------------------------------------
export const VOICE_MODES = ['personalized', 'neutral'] as const;
const draftRow = z.object({
  draftId: id,
  ref,
  platform: opt(text(60)),
  language: opt(text(40)),
  account: opt(text(160)),
  revision: opt(z.number().int().nonnegative()),
  characters: z.number().int().nonnegative(),
  limit: opt(z.number().int().positive()),
  overLimit: z.boolean(),
  needsReview: z.boolean(),
  hasProposedUpdate: z.boolean(),
  committed: z.boolean(),
  committedJobState: opt(text(40)),
  setAside: z.boolean(),
  sourceCount: count,
  warningsCount: count,
  unknownsCount: count,
  writerModel: opt(text(120)),
  voice: opt(z.enum(VOICE_MODES)),
  fromAutomation: opt(z.boolean()),
  createdAt: opt(iso),
  excerpt: text(400),
  href: opt(inAppHref),
});
export type DraftRow = z.infer<typeof draftRow>;

const jobView = z.object({
  jobId: opt(id),
  state: opt(text(40)),
  title: opt(text(200)),
  meaning: opt(text(400)),
  platform: opt(text(60)),
  account: opt(text(160)),
  publishAt: opt(text(40)),
  timeZone: opt(text(64)),
  demo: opt(z.boolean()),
  fromAutomation: opt(z.boolean()),
  verified: opt(z.boolean()),
});

const draftsList = z.object({ drafts: z.array(draftRow).max(100), offset: opt(z.number().int().nonnegative()), missingIds: z.array(id).max(20).optional() });
const draftRead = draftRow.extend({
  text: text(20000),
  openings: z.array(text(400)).max(3).optional(),
  unknowns: z.array(text(240)).max(10).optional(),
  warnings: z.array(text(240)).max(10).optional(),
  blockedByRetraction: opt(z.boolean()),
  proposedUpdate: opt(z.object({ characters: z.number().int().nonnegative(), baseRevision: opt(z.number().int()) })),
  scheduled: z.array(jobView).max(5).optional(),
  editable: z.boolean(),
  editBlockedReason: opt(text(240)),
  voiceSourceCount: opt(z.number().int().nonnegative()),
  revisionsCount: opt(z.number().int().nonnegative()),
});
export type DraftDetail = z.infer<typeof draftRead>;
const graphEdge = z.object({ edge: text(60), type: text(40), id: id, via: opt(text(120)), title: opt(text(200)), platform: opt(text(60)) });
const evidenceSource = z.object({
  sourceId: id,
  ref: opt(ref),
  available: z.boolean(),
  kind: opt(text(40)),
  title: opt(text(200)),
  active: opt(z.boolean()),
  retracted: opt(z.boolean()),
  approvedFacts: opt(z.number().int().nonnegative()),
  facts: opt(z.number().int().nonnegative()),
  origin: opt(text(40)),
  host: opt(text(200)),
  published: opt(text(40)),
});
const voiceFinding = z.object({ trait: text(200), verdict: z.enum(['matches', 'differs', 'unclear']), basis: text(40), evidence: opt(text(400)) });
const draftEvidence = z.object({
  draftId: id,
  edges: z.array(graphEdge).max(80),
  sources: z.array(evidenceSource).max(40),
  voiceFit: opt(z.object({ empty: opt(z.boolean()), findings: z.array(voiceFinding).max(30).optional() })),
});
const draftRevisions = z.object({
  draftId: id,
  current: opt(z.number().int()),
  revisions: z
    .array(z.object({ revision: opt(z.number().int()), origin: opt(text(40)), at: opt(iso), characters: z.number().int().nonnegative(), text: text(4000), textTruncated: z.boolean() }))
    .max(20),
});

// --- J02 calendar ------------------------------------------------------------------------------------------------------
export const CALENDAR_STATUSES = ['scheduled', 'awaiting_approval', 'in_flight', 'failed_held_uncertain', 'published', 'verified', 'planned', 'unknown'] as const;
const agendaEntry = z.object({
  kind: text(40),
  id,
  ref,
  state: opt(text(40)),
  status: text(40),
  title: opt(text(200)),
  platform: opt(text(60)),
  account: opt(text(160)),
  atUtc: opt(iso),
  local: opt(text(40)),
  timeZone: text(64),
  jobZone: opt(text(64)),
  jobLocal: opt(text(40)),
  fromAutomation: opt(z.boolean()),
  excerpt: opt(text(400)),
  href: opt(inAppHref),
});
export type AgendaEntry = z.infer<typeof agendaEntry>;
const calendarAgenda = z.object({
  range: z.object({ start: text(10), end: text(10), timeZone: text(64), startUtc: opt(iso), endUtc: opt(iso) }),
  entries: z.array(agendaEntry).max(100),
  total: count,
  statusCounts: opt(z.record(z.string(), z.number().int().nonnegative())),
  unknownStates: z.array(text(60)).max(30).optional().nullable(),
  days: z.array(z.object({ date: text(10), weekday: text(20), count: z.number().int().nonnegative() })).max(62).optional(),
  derived: opt(
    z.object({
      closeTogether: opt(z.object({ rule: text(240), pairs: z.array(z.object({ first: id, second: id, minutes: z.number() })).max(20) })),
      emptyDays: opt(z.object({ rule: text(240), days: z.array(text(10)).max(62) })),
    }),
  ),
  href: opt(inAppHref),
});
const queueItem = jobView.extend({ ref, atUtc: opt(iso) });
export type QueueItem = z.infer<typeof queueItem>;
// Attention rows (failed/held/uncertain jobs) carry no scheduled atUtc in lane D's queue_status shape.
const attentionItem = jobView.extend({ ref });
const queueStatus = z.object({
  statusCounts: opt(z.record(z.string(), z.number().int().nonnegative())),
  unknownStates: z.array(text(60)).max(30).optional().nullable(),
  draftsUnscheduled: count.optional(),
  waitingApproval: z
    .array(z.object({ reviewId: opt(id), ref, platform: opt(text(60)), account: opt(text(160)), local: opt(text(40)), timeZone: opt(text(64)), atUtc: opt(iso), expired: opt(z.boolean()) }))
    .max(100),
  upcoming: z.array(queueItem).max(100),
  attention: z.array(attentionItem).max(100),
  totals: z.object({ waitingApproval: z.number().int().nonnegative(), upcoming: z.number().int().nonnegative(), attention: z.number().int().nonnegative() }),
  href: opt(inAppHref),
});
const slotCheck = z.object({
  draftId: opt(id),
  jobId: opt(id),
  platform: opt(text(60)),
  account: opt(text(160)),
  local: text(16),
  timeZone: text(64),
  atUtc: opt(iso),
  valid: z.boolean(),
  problems: z.array(z.object({ code: text(60), message: text(400) })).max(10),
  collisions: z.array(z.object({ kind: text(40), id, ref, local: opt(text(40)), minutesApart: z.number(), status: opt(text(40)) })).max(30),
  rule: text(240),
});
const openProposals = z.object({
  proposals: z
    .array(z.object({ proposalId: id, messageId: opt(id), type: opt(text(60)), summary: z.array(text(400)).max(12), expiresAt: opt(iso), status: text(20) }))
    .max(50),
});

// --- shared: multi-step task progress (J01 J02 J05 J08) ----------------------------------------------------------------
export const STEP_STATES = ['planned', 'running', 'done', 'needs_user', 'blocked', 'failed', 'canceled'] as const;
const taskProgress = z.object({
  task: z
    .object({
      taskId: opt(id),
      title: opt(text(200)),
      status: opt(text(40)),
      steps: z
        .array(
          z.object({
            id: text(40),
            label: text(200),
            state: z.enum(STEP_STATES),
            dependsOn: z.array(text(40)).max(30).optional(),
            reason: opt(text(400)),
            verified: opt(z.boolean()),
          }),
        )
        .max(40),
    })
    .nullable(),
  summary: opt(z.object({ done: z.number().int().nonnegative(), total: z.number().int().nonnegative(), open: z.array(text(40)).max(40).optional() })),
});

// --- J03 library -------------------------------------------------------------------------------------------------------
export const PREVIEW_KINDS = ['image', 'video_poster', 'pdf_page', 'document_cover', 'server_page', 'audio_cover', 'file_cover'] as const;
const libraryRow = z.object({
  ref,
  assetId: id,
  store: z.enum(['file', 'media']),
  kind: opt(text(20)),
  title: opt(text(240)),
  mime: opt(text(120)),
  extension: opt(text(20)),
  bytes: opt(z.number().nonnegative()),
  createdAt: opt(iso),
  tags: z.array(text(80)).max(30).optional(),
  collections: z.array(text(120)).max(30).optional(),
  processing: opt(text(40)),
  indexingStatus: opt(text(40)),
  transcriptionStatus: opt(text(40)),
  hasSource: z.boolean(),
  sourceId: opt(id),
  duplicateOf: opt(id),
  extractionProblem: opt(text(40)),
  width: opt(z.number()),
  height: opt(z.number()),
  duration: opt(z.number()),
  alt: opt(text(300)),
  href: opt(inAppHref),
  previewKind: opt(z.enum(PREVIEW_KINDS)),
  previewRoute: opt(text(300)),
});
export type LibraryRow = z.infer<typeof libraryRow>;
const libraryEdge = z.object({ relation: opt(text(60)), edge: opt(text(60)), type: text(40), id, via: opt(text(160)), title: opt(text(200)) });
const librarySearch = z.object({
  items: z.array(libraryRow).max(100),
  offset: opt(z.number().int().nonnegative()),
  storage: opt(z.object({ usedBytes: opt(z.number()), limitBytes: opt(z.number()) })),
  legacyMedia: opt(z.number().int().nonnegative()),
});
const libraryItem = libraryRow.extend({
  excerpt: opt(text(2000)),
  excerptTruncated: opt(z.boolean()),
  chunkCount: opt(z.number().int().nonnegative()),
  summary: opt(text(400)),
  mediaConsent: opt(z.object({ modelMayView: opt(z.boolean()) })),
});
const libraryLineage = z.object({ assetId: id, store: text(10), edges: z.array(libraryEdge).max(80) });
const librarySelection = z.object({
  attachments: z.array(z.object({ assetId: id, role: text(20) })).max(4),
  references: z.array(z.object({ kind: text(20), id })).max(12),
  refused: z.array(z.object({ assetId: id, reason: text(40) })).max(4),
  note: opt(text(400)),
});

// --- J04 voice ---------------------------------------------------------------------------------------------------------
const voiceSample = z.object({
  sourceId: id,
  ref,
  title: opt(text(200)),
  platform: opt(text(60)),
  language: opt(text(40)),
  label: opt(text(40)),
  origin: opt(text(40)),
  active: z.boolean(),
  selected: z.boolean(),
  revision: opt(z.number().int()),
  characters: opt(z.number().int().nonnegative()),
  excerpt: opt(text(400)),
  useGrants: z.array(z.object({ purpose: opt(text(40)), route: opt(text(120)) })).max(12),
  partialCoverage: opt(z.boolean()),
  publishedAt: opt(z.union([iso, z.number()])),
  revoked: opt(z.boolean()),
});
export type VoiceSample = z.infer<typeof voiceSample>;
const voiceSources = z.object({
  samples: z.array(voiceSample).max(100),
  eligibility: opt(
    z.object({
      purpose: text(40),
      route: text(120),
      allowed: z.array(id).max(100),
      excluded: z.array(z.object({ sourceId: id, reason: text(60) })).max(100),
      rule: text(240),
    }),
  ),
});
export const EVIDENCE_LEVELS = ['supported', 'limited', 'conflicting', 'insufficient', 'strong', 'moderate', 'weak'] as const;
const voiceDimension = z.object({
  id: opt(text(80)),
  observation: text(240),
  evidenceLevel: opt(text(40)),
  support: opt(z.number().int().nonnegative()),
  counterEvidence: opt(z.number().int().nonnegative()),
  quotes: z.array(z.object({ sourceId: opt(id), text: text(240) })).max(3).optional(),
});
const voiceProfileState = z.object({
  approved: opt(
    z.object({
      revision: opt(z.number().int()),
      approvedAt: opt(z.union([iso, z.number()])),
      stale: z.boolean(),
      staleReason: opt(text(240)),
      tone: opt(text(240)),
      dimensions: z.array(voiceDimension).max(30),
      unknowns: z.array(text(200)).max(8).optional(),
    }),
  ),
  proposed: opt(
    z.object({
      status: opt(text(40)),
      method: opt(text(40)),
      route: opt(text(120)),
      model: opt(text(120)),
      proposedAt: opt(z.union([iso, z.number()])),
      proposalKey: z.string().regex(/^[0-9a-f]{24}$/),
      dimensions: z.array(voiceDimension).max(30),
      unknowns: z.array(text(200)).max(8).optional(),
      sources: opt(z.number().int().nonnegative()),
    }),
  ),
  revisions: opt(z.number().int().nonnegative()),
  derived: opt(z.object({ draftsOnVoice: z.number().int().nonnegative(), scheduledPostsOnVoice: z.number().int().nonnegative(), rule: text(400) })),
  note: opt(text(400)),
  href: opt(inAppHref),
});
const preferenceProposal = z.object({
  id,
  status: opt(text(20)),
  op: opt(text(20)),
  source: opt(text(40)),
  statement: opt(text(400)),
  why: opt(text(400)),
  scopeLabel: opt(text(160)),
  expiresAt: opt(z.union([iso, z.number()])),
});
const voicePreferences = z.object({
  pending: z.array(preferenceProposal).max(50),
  learned: z
    .array(
      z.object({
        id: opt(id),
        statement: opt(text(400)),
        scope: z.unknown().optional(),
        evidenceState: opt(text(60)),
        evidenceSummary: opt(text(240)),
        source: opt(text(40)),
        status: opt(text(20)),
        since: opt(z.union([iso, z.number()])),
      }),
    )
    .max(100),
  rule: opt(text(240)),
});
const consentSummary = z.record(z.string(), z.unknown());
const voiceConsent = z.object({
  cloudMemory: opt(consentSummary),
  samples: z.object({ total: z.number().int().nonnegative(), grantedForAnalysis: z.number().int().nonnegative(), grantedForGeneration: z.number().int().nonnegative() }),
  learning: z.object({ enabled: opt(z.boolean()), teamEdits: opt(z.boolean()), cloudExtraction: opt(z.boolean()), modelExtractionAllowed: opt(z.boolean()) }),
  media: z.object({ cloud: z.boolean() }),
  webResearch: opt(consentSummary),
  owner: z.boolean(),
  rule: text(400),
  href: opt(inAppHref),
});
const voiceLearningStatus = z.object({
  enabled: opt(z.boolean()),
  eventsWaiting: count,
  pendingProposals: count,
  newestProposalAt: opt(iso),
  extractor: opt(z.object({ kind: opt(text(20)), allowed: opt(z.boolean()) })),
  lastRun: z.null().optional(),
  lastRunNote: opt(text(400)),
  rule: text(400),
});

// --- J05 campaigns -----------------------------------------------------------------------------------------------------
const campaignAutomation = z.object({ automationId: id, name: opt(text(160)), status: opt(text(40)), schedule: opt(text(240)), policy: opt(text(40)), nextRun: opt(text(60)) });
const campaignView = z.object({
  campaignId: id,
  goal: opt(text(1200)),
  audience: opt(text(800)),
  status: opt(text(40)),
  missingFacts: z.array(text(80)).max(30).optional(),
  facts: opt(z.record(z.string(), z.string().max(200))),
  automations: z.array(campaignAutomation).max(30).optional(),
  platforms: z.array(text(60)).max(30).optional(),
  href: opt(inAppHref),
});
const campaignsList = z.object({
  campaigns: z.array(campaignView.extend({ ref, version: opt(z.number().int()), itemCount: opt(z.number().int().nonnegative()), updatedAt: opt(iso) })).max(100),
});
const campaignDetail = campaignView.extend({
  ref,
  version: z.number().int(),
  itemCount: opt(z.number().int().nonnegative()),
  draftCount: opt(z.number().int().nonnegative()),
  upcomingRuns: z.array(z.object({ runId: opt(id), status: opt(text(40)), when: opt(text(60)) })).max(10).optional(),
  derived: opt(
    z.object({
      platformsNotCovered: opt(z.object({ rule: text(240), items: z.array(text(60)).max(30) })),
      noUpcomingRun: opt(z.object({ rule: text(240), value: z.boolean() })),
      failedOrSkippedLastWeek: opt(z.object({ rule: text(240), items: z.array(z.object({ status: opt(text(40)), when: opt(text(60)) })).max(10) })),
    }),
  ),
  progress: opt(
    z.object({
      items: z.object({
        drafts: z.number().int().nonnegative(),
        draftsNeedingReview: z.number().int().nonnegative(),
        posts: z.number().int().nonnegative(),
        postsVerified: z.number().int().nonnegative(),
        postsWaiting: z.number().int().nonnegative(),
        missing: z.number().int().nonnegative(),
      }),
      runs: z.record(z.string(), z.number().int().nonnegative()),
      rule: text(240),
    }),
  ),
});
const campaignItems = z.object({
  campaignId: id,
  version: opt(z.number().int()),
  items: z
    .array(
      z.object({
        itemId: opt(id),
        kind: text(20),
        addedAt: opt(iso),
        needsReview: z.boolean(),
        ref: opt(ref),
        exists: opt(z.boolean()),
        draftId: opt(id),
        jobId: opt(id),
        assetId: opt(id),
        platform: opt(text(60)),
        state: opt(text(40)),
        excerpt: opt(text(400)),
        local: opt(text(40)),
        timeZone: opt(text(64)),
        atUtc: opt(iso),
      }),
    )
    .max(100),
});
const campaignTimeline = z.object({
  campaignId: id,
  timeZone: text(64),
  startUtc: opt(iso),
  endUtc: opt(iso),
  events: z
    .array(
      z.object({
        kind: text(20),
        ref: opt(ref),
        name: opt(text(160)),
        atUtc: opt(iso),
        local: opt(text(40)),
        status: opt(text(40)),
        platform: opt(text(60)),
        scheduleZone: opt(text(64)),
        jobZone: opt(text(64)),
      }),
    )
    .max(200),
  truncated: opt(z.boolean()),
});

// --- J06 analytics -----------------------------------------------------------------------------------------------------
export const ANALYTICS_METRICS = ['views', 'reach', 'likes', 'comments', 'replies', 'reposts', 'quotes', 'shares', 'saved'] as const;
const reading = z.object({
  value: z.number().nullable(),
  availability: text(40),
  unit: opt(text(20)),
  readOffset: opt(text(20)),
  observedAt: opt(iso),
  definitionVersion: opt(text(40)),
});
const analyticsPosts = z.object({
  posts: z
    .array(
      z.object({
        ref,
        jobId: opt(id),
        provider: opt(text(40)),
        platform: opt(text(60)),
        connectionId: opt(id),
        language: opt(text(40)),
        publishedAt: opt(iso),
        publishedLocal: opt(text(40)),
        metrics: z.record(z.string(), reading),
        rates: opt(z.record(z.string(), z.object({ value: opt(z.string()), display: opt(text(60)) }))),
      }),
    )
    .max(100),
  timeZone: text(64),
  startUtc: opt(iso),
  endUtc: opt(iso),
  definitionVersion: opt(text(40)),
  undated: opt(z.number().int().nonnegative()),
  verifiedPostsInWindow: opt(z.number().int().nonnegative()),
  postsWithReadings: opt(z.number().int().nonnegative()),
});
const analyticsCompare = z.object({
  metric: text(40),
  comparisons: z
    .array(
      z.object({
        cohort: z.record(z.string(), z.unknown()),
        interpretation: text(40),
        sampleSize: opt(z.number().int().nonnegative()),
        measured: opt(z.number().int().nonnegative()),
        missing: opt(z.number().int().nonnegative()),
        mean: opt(z.string().max(40)),
        minimum: opt(z.number().int()),
        reason: opt(text(240)),
      }),
    )
    .max(50),
  rules: opt(z.object({ minimum: opt(z.number().int()), definitionVersion: opt(text(40)), like_for_like: opt(text(240)) })),
  timeZone: opt(text(64)),
});
const analyticsSeries = z.object({
  metric: text(40),
  bucket: z.enum(['day', 'week']),
  timeZone: text(64),
  series: z
    .array(
      z.object({
        provider: opt(text(40)),
        platform: opt(text(60)),
        connectionId: opt(id),
        points: z
          .array(z.object({ bucket: text(10), posts: z.number().int().nonnegative(), measured: z.number().int().nonnegative(), total: z.number().nullable(), mean: z.union([z.string().max(40), z.number()]).nullable() }))
          .max(400),
      }),
    )
    .max(20),
  definitionVersion: opt(text(40)),
  unit: opt(text(20)),
  rule: text(240),
  undated: opt(z.number().int().nonnegative()),
});
const analyticsCoverage = z.object({
  state: z.enum(['unavailable', 'pending', 'partial', 'ready']),
  connections: z
    .array(
      z.object({
        connectionId: id,
        platform: opt(text(60)),
        account: opt(text(160)),
        level: opt(text(40)),
        direct: z.boolean(),
        providerOffersAnalytics: opt(z.boolean()),
        verifiedPosts: z.number().int().nonnegative(),
        readPosts: z.number().int().nonnegative(),
        readings: z.number().int().nonnegative(),
        lastObservedAt: opt(iso),
        enableHref: opt(inAppHref),
      }),
    )
    .max(50),
  unmatchedReadings: opt(z.number().int().nonnegative()),
  rule: text(400),
});
const postFeedback = z.object({ jobId: id, readings: z.array(z.record(z.string(), z.unknown())).max(10), minimumBaselinePosts: opt(z.number().int()), causal: z.literal(false) });

// --- J07 research ------------------------------------------------------------------------------------------------------
const researchState = z.object({
  allowed: z.boolean(),
  web: opt(z.boolean()),
  enabledOnDeployment: opt(z.boolean()),
  decidedAt: opt(z.union([iso, z.number()])),
  canTurnOn: z.boolean(),
  guide: opt(z.object({ guideId: opt(text(60)), href: opt(inAppHref), title: opt(text(200)), canOpen: opt(z.boolean()) })),
  reason: opt(text(60)),
});
const researchPage = z.object({
  index: z.number().int().nonnegative().max(11),
  title: opt(text(300)),
  host: opt(text(253)),
  url: opt(z.string().max(2000)),
  urlUnsafe: opt(z.boolean()),
  published: opt(text(60)),
  publishedLabel: text(60),
  fetchedAt: opt(z.union([text(60), z.number()])),
  facts: z.array(text(500)).max(12),
  untrusted: z.literal(true),
});
export type ResearchPage = z.infer<typeof researchPage>;
const researchResults = z.object({ pages: z.array(researchPage).max(12), recorded: opt(text(20)), searches: opt(z.number().int().nonnegative()), note: opt(text(400)) });
const researchSources = z.object({
  sources: z
    .array(
      z.object({
        sourceId: id,
        ref,
        title: opt(text(300)),
        host: opt(text(253)),
        url: opt(z.string().max(2000)),
        publishedLabel: text(60),
        fetchedAt: opt(z.union([text(60), z.number()])),
        status: opt(text(40)),
        active: z.boolean(),
        retracted: z.boolean(),
        facts: z.number().int().nonnegative(),
        approvedFacts: z.number().int().nonnegative(),
      }),
    )
    .max(100),
});

// --- J08 automations ---------------------------------------------------------------------------------------------------
const nextRun = z.object({ atUtc: opt(iso), local: opt(text(40)), offset: opt(text(10)), timeZone: opt(text(64)) });
const automationRow = z.object({
  automationId: id,
  ref,
  name: text(160),
  status: opt(text(20)),
  schedule: opt(text(240)),
  timeZone: text(64),
  policy: opt(text(40)),
  platforms: z.array(z.string().max(60).nullable()).max(30),
  nextRun: opt(nextRun),
  campaignId: opt(id),
  pausedReason: opt(text(240)),
  version: opt(z.number().int()),
  href: opt(inAppHref),
});
export type AutomationRow = z.infer<typeof automationRow>;
const automationsList = z.object({ automations: z.array(automationRow).max(100), statusCounts: opt(z.record(z.string(), z.number().int().nonnegative())) });
const automationDetail = z.object({
  taskId: opt(id),
  name: opt(text(160)),
  status: opt(text(20)),
  scheduleText: opt(text(240)),
  policy: opt(text(40)),
  platforms: z.array(z.string().max(60).nullable()).max(30).optional().nullable(),
  needs: z.array(z.union([text(240), z.record(z.string(), z.unknown())])).max(20).optional().nullable(),
  contentLabel: opt(text(160)),
  voiceMode: opt(text(40)),
  ref,
  timeZone: text(64),
  nextRun: opt(nextRun),
  upcoming: z.array(z.object({ atUtc: opt(iso), local: opt(text(40)), offset: opt(text(10)) })).max(14),
  version: opt(z.number().int()),
  pausedReason: opt(text(240)),
  history: opt(z.number().int().nonnegative()),
  href: opt(inAppHref),
});
const automationHistory = z.object({
  automationId: id,
  runs: z
    .array(
      z.object({
        runId: opt(id),
        ref,
        status: text(40),
        attention: z.boolean(),
        scheduledUtc: opt(iso),
        scheduledLocal: opt(text(40)),
        timeZone: text(64),
        completedUtc: opt(iso),
        cost: z.object({ usdMicro: z.number().int().nullable().optional(), state: z.enum(['known', 'unknown']) }),
        items: z.array(z.object({ platform: opt(text(60)), state: opt(text(40)), reason: opt(text(240)) })).max(8),
      }),
    )
    .max(100),
});
const connectionsStatus = z.object({
  accounts: z
    .array(
      z.object({
        connectionId: id,
        ref,
        platform: opt(text(60)),
        account: opt(text(160)),
        connectionState: opt(text(40)),
        demo: opt(z.boolean()),
        revoked: opt(z.boolean()),
        levels: opt(z.record(z.string(), z.string().max(40).nullable())),
        canPublish: opt(z.boolean()),
        publishReason: opt(text(400)),
        needsReconnect: z.boolean(),
      }),
    )
    .max(50),
  publishingLive: opt(z.boolean()),
  attention: z.object({ state: text(20), reason: opt(text(60)), items: z.array(z.object({ kind: opt(text(60)), severity: opt(text(20)), title: opt(text(240)), href: opt(inAppHref) })).max(20) }),
  recovery: opt(z.object({ guideId: opt(text(60)), href: opt(inAppHref) })),
  rule: opt(text(240)),
});
const recoveryGuides = z.object({
  guides: z.array(z.object({ guideId: text(60), title: opt(text(200)), summary: opt(text(400)), href: opt(inAppHref), canOpen: opt(z.boolean()), reason: opt(text(240)) })).max(20),
  pages: z.array(z.object({ label: text(80), href: inAppHref })).max(10).optional(),
});

// --- J09 founder (open shapes: the founder tools' own records) ---------------------------------------------------------
const founderRow = z.object({
  metricId: opt(text(80)),
  definitionVersion: opt(text(40)),
  dimensions: opt(z.record(z.string(), z.unknown())),
  value: z.number().nullable().optional(),
  unit: opt(text(40)),
  currency: opt(text(8)),
  dataState: opt(text(40)),
  reason: opt(text(120)),
});
const founderMetrics = z.object({
  mode: opt(text(20)),
  receiptId: opt(text(120)),
  dataState: opt(text(40)),
  rows: z.array(founderRow).max(200),
  coverage: opt(z.record(z.string(), z.unknown())),
  warnings: z.array(text(240)).max(20).optional(),
  note: opt(text(400)),
});
const founderCostRow = z.object({
  dimensions: opt(z.record(z.string(), z.unknown())),
  actualUsdMicro: z.number().nullable().optional(),
  estimatedUsdMicro: z.number().nullable().optional(),
  value: z.number().nullable().optional(),
  unit: opt(text(40)),
  currency: opt(text(8)),
  costState: opt(text(40)),
  dataState: opt(text(40)),
});
const founderCostPart = z.object({ receiptId: opt(text(120)), dataState: opt(text(40)), reason: opt(text(120)), rows: z.array(founderCostRow).max(200).optional() });
const founderCosts = z.object({
  mode: opt(text(20)),
  dimension: opt(text(40)),
  receiptId: opt(text(120)),
  dataState: opt(text(40)),
  rows: z.array(founderCostRow).max(200).optional(),
  current: opt(founderCostPart),
  previous: opt(founderCostPart),
  note: opt(text(400)),
});
const founderAttention = z.object({
  mode: opt(text(20)),
  items: z
    .array(z.object({ id: opt(text(120)), severity: opt(text(20)), title: opt(text(240)), scope: opt(text(40)), count: opt(z.number()), since: opt(z.union([iso, z.number()])), href: opt(z.string().max(400)) }))
    .max(20),
});
const founderSources = z.object({
  mode: opt(text(20)),
  sources: z.array(z.object({ sourceId: opt(text(120)), label: opt(text(160)), state: opt(text(40)), lastGoodAt: opt(z.union([iso, z.number()])), reasonCode: opt(text(120)) })).max(100),
});

/** Binding name → view of its `data`. Keys are lane D's binding names; tests keep them in sync with the catalog. */
export const VIEWS = {
  drafts_list: draftsList,
  draft_read: draftRead,
  draft_evidence: draftEvidence,
  draft_revisions: draftRevisions,
  calendar_agenda: calendarAgenda,
  queue_status: queueStatus,
  slot_check: slotCheck,
  open_proposals: openProposals,
  task_progress: taskProgress,
  library_search: librarySearch,
  library_item: libraryItem,
  library_lineage: libraryLineage,
  library_selection: librarySelection,
  voice_sources: voiceSources,
  voice_profile_state: voiceProfileState,
  voice_preferences: voicePreferences,
  voice_consent: voiceConsent,
  voice_learning_status: voiceLearningStatus,
  campaigns_list: campaignsList,
  campaign_detail: campaignDetail,
  campaign_items: campaignItems,
  campaign_timeline: campaignTimeline,
  analytics_posts: analyticsPosts,
  analytics_compare: analyticsCompare,
  analytics_series: analyticsSeries,
  analytics_coverage: analyticsCoverage,
  post_feedback: postFeedback,
  research_state: researchState,
  research_results: researchResults,
  research_sources: researchSources,
  automations_list: automationsList,
  automation_detail: automationDetail,
  automation_history: automationHistory,
  connections_status: connectionsStatus,
  recovery_guides: recoveryGuides,
  founder_metrics: founderMetrics,
  founder_costs: founderCosts,
  founder_attention: founderAttention,
  founder_sources: founderSources,
} as const;

export type BindingName = keyof typeof VIEWS;
export type ViewData<B extends BindingName> = z.infer<(typeof VIEWS)[B]>;

/** What a journey component can show for one query reference. */
export type QueryRead<T> =
  | { kind: 'loading' }
  | { kind: 'denied'; result: UiQueryResultV1 }
  | { kind: 'unavailable'; result: UiQueryResultV1 }
  | { kind: 'empty'; result: UiQueryResultV1; data: T | null }
  | { kind: 'invalid' }
  | { kind: 'data'; state: Extract<DataState, 'available' | 'partial' | 'stale'>; result: UiQueryResultV1; data: T };

/**
 * Read a `Query(...)` value (null until the bridge answers) as one of the states above. The envelope and the data are
 * both validated; nothing is defaulted. `loading` from the server is still loading; `denied`/`unavailable` carry their
 * warnings so the component can name the reason.
 */
export function readQuery<B extends BindingName>(value: unknown, binding: B): QueryRead<ViewData<B>> {
  if (value === null || value === undefined) return { kind: 'loading' };
  const envelope = uiQueryResultSchema.safeParse(value);
  if (!envelope.success) return { kind: 'invalid' };
  const result = envelope.data;
  if (result.state === 'loading') return { kind: 'loading' };
  if (result.state === 'denied') return { kind: 'denied', result };
  if (result.state === 'unavailable') return { kind: 'unavailable', result };
  const schema: z.ZodType = VIEWS[binding];
  const parsed = schema.safeParse(result.data);
  if (result.state === 'empty') return { kind: 'empty', result, data: parsed.success ? (parsed.data as ViewData<B>) : null };
  if (!parsed.success) return { kind: 'invalid' };
  return { kind: 'data', state: result.state, result, data: parsed.data as ViewData<B> };
}
