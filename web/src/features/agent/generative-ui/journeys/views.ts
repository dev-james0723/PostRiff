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
const queueStatus = z.object({
  statusCounts: opt(z.record(z.string(), z.number().int().nonnegative())),
  unknownStates: z.array(text(60)).max(30).optional().nullable(),
  draftsUnscheduled: count.optional(),
  waitingApproval: z
    .array(z.object({ reviewId: opt(id), ref, platform: opt(text(60)), account: opt(text(160)), local: opt(text(40)), timeZone: opt(text(64)), atUtc: opt(iso), expired: opt(z.boolean()) }))
    .max(100),
  upcoming: z.array(queueItem).max(100),
  attention: z.array(queueItem).max(100),
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
} as const;

export type BindingName = keyof typeof VIEWS;
export type ViewData<B extends BindingName> = z.infer<(typeof VIEWS)[B]>;

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
export function readQuery<B extends BindingName>(value: unknown, binding: B): QueryRead<ViewData<B>> {
  if (value === null || value === undefined) return { kind: 'loading' };
  const envelope = uiQueryResultSchema.safeParse(value);
  if (!envelope.success) return { kind: 'invalid' };
  const result = envelope.data;
  if (result.state === 'loading') return { kind: 'loading' };
  if (result.state === 'denied' || result.state === 'unavailable') return { kind: result.state, result };
  const schema: z.ZodType = VIEWS[binding];
  const parsed = schema.safeParse(result.data);
  if (result.state === 'empty') return { kind: 'empty', result, data: parsed.success ? (parsed.data as ViewData<B>) : null };
  if (!parsed.success) return { kind: 'invalid' };
  return { kind: 'data', state: result.state, result, data: parsed.data as ViewData<B> };
}
