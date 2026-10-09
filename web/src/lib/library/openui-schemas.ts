/**
 * Props schemas for the Library's OpenUI task components (UI spec §7–8; A067–A070). One source for the descriptors
 * (features/library/intelligence/openui/descriptors.ts), the deterministic fallback and the tests.
 *
 * Rules every schema follows:
 *   - z.strictObject with a STABLE key order: OpenUI props are positional, required first, optional last;
 *   - identities are server-issued AssetRefs / SourceRefs and ActionEnvelopes (without an idempotency key: the host adds
 *     a fresh one per user activation), never URLs, HTML, SQL or scripts;
 *   - display text is plain text: links, markup and script schemes are refused, not escaped and shown.
 *
 * Imports only zod, so web/tests/library-intelligence-openui.test.cjs can transpile it on its own.
 */
import { z } from 'zod';

export const LIBRARY_OPENUI_VERSION = 'rafii-library-ui/1.0.0';

const KEY = /^[0-9a-f]{32}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const ACTION_ID = /^[A-Za-z0-9_.:-]{1,80}$/;
/** Links, script schemes and markup. Display text never carries them. */
const UNSAFE_TEXT = /(?:[a-z][a-z0-9+.-]*:\/\/|\b(?:javascript|vbscript|data):|<\s*\/?\s*[a-z!?])/i;
/** The server's own payload rule (`contracts._reject_unsafe`), applied before anything is sent. */
const UNSAFE_PAYLOAD = /(<\s*script|javascript:|\bselect\b[^\n]{0,40}\bfrom\b|\bdrop\s+table\b|https?:\/\/)/i;

export function isSafeText(value: string): boolean {
  return !UNSAFE_TEXT.test(value);
}

function strings(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') out.push(value);
  else if (Array.isArray(value)) for (const item of value) strings(item, out);
  else if (value && typeof value === 'object') for (const [key, item] of Object.entries(value)) {
    out.push(key);
    strings(item, out);
  }
  return out;
}

export function isSafePayload(value: unknown): boolean {
  try {
    if (JSON.stringify(value).length > 20000) return false;
  } catch {
    return false;
  }
  return strings(value).every((text) => !UNSAFE_PAYLOAD.test(text));
}

const text = (max: number) => z.string().max(max).refine(isSafeText, 'Plain text only');
const title = text(160).min(1);
const count = z.number().int().nonnegative();

export const assetKeySchema = z.string().regex(KEY);

export const AssetRefSchema = z.strictObject({
  assetId: assetKeySchema,
  versionId: z.union([assetKeySchema, z.literal('')]),
  sha256: z.union([z.string().regex(SHA256), z.literal('')])
});

export const LocatorSchema = z.discriminatedUnion('kind', [
  z.strictObject({ kind: z.literal('page'), page: z.number().int().min(1), section: text(200).optional(), textStart: count.optional(), textEnd: count.optional() }),
  z.strictObject({ kind: z.literal('time'), startMs: count, endMs: count }),
  z.strictObject({ kind: z.literal('text'), start: count, end: count }),
  z.strictObject({ kind: z.literal('slide'), slide: z.number().int().min(1) }),
  z.strictObject({ kind: z.literal('sheet'), sheetName: text(120), cellRange: z.string().regex(/^[A-Za-z]{1,3}\d{1,7}(?::[A-Za-z]{1,3}\d{1,7})?$/) }),
  z.strictObject({
    kind: z.literal('imageRegion'),
    frameTimeMs: count.optional(),
    x: z.number().min(0).max(1),
    y: z.number().min(0).max(1),
    width: z.number().min(0).max(1),
    height: z.number().min(0).max(1)
  })
]);

export const SourceRefSchema = z.strictObject({
  assetRef: AssetRefSchema,
  segmentId: assetKeySchema.optional(),
  locator: LocatorSchema.optional(),
  quoteHash: z.string().regex(SHA256).optional()
});

export const LIBRARY_ACTION_TYPES = [
  'collection.save',
  'collection.override',
  'collection.undo',
  'collection.preview',
  'sources.select',
  'source_pack.create',
  'source_pack.attach',
  'version.link',
  'version.accept_replacement',
  'annotation.correct',
  'suggestion.set_state',
  'moment.save',
  'voice.approve_span',
  'voice.revoke',
  'metadata.update'
] as const;

/** Server reads (no write, no activation needed; bounded by the read budget). */
export const READ_ONLY_ACTION_TYPES: readonly string[] = ['collection.preview', 'sources.select'];

/** Host-only actions: they change what the person sees or selects, never the server. */
export const HOST_ACTIONS = ['library.select', 'library.open'] as const;

/** A server-issued action as it arrives in a task result: the host adds the idempotency key on a person's click. */
export const IssuedEnvelopeSchema = z.strictObject({
  actionId: z.string().regex(ACTION_ID),
  uiInstanceId: z.string().regex(ACTION_ID),
  actionType: z.enum(LIBRARY_ACTION_TYPES),
  targetRefs: z.array(AssetRefSchema).max(200),
  expectedRevision: count.nullable(),
  payload: z.record(z.string(), z.unknown()).refine(isSafePayload, 'The action carries links, markup or code')
});

/** A button the server offers: its words and its effect come from the server, never from generated text. */
export const ProposedActionSchema = z.strictObject({
  label: text(60).min(1),
  effect: text(240),
  envelope: IssuedEnvelopeSchema
});

const kinds = z.enum(['image', 'video', 'audio', 'document', 'file']);
const titledSource = z.strictObject({ sourceRef: SourceRefSchema, title });
const member = z.strictObject({ assetRef: AssetRefSchema, title });

function actionsOf(allowed: readonly string[], max: number) {
  return z
    .array(ProposedActionSchema)
    .max(max)
    .refine((actions) => actions.every((action) => allowed.includes(action.envelope.actionType)), 'An action this component cannot offer');
}

export const AssetCandidateCardSchema = z.strictObject({
  assetRef: AssetRefSchema,
  title,
  kind: kinds,
  mime: z.string().max(120).regex(/^[a-z0-9.+-]+\/[a-z0-9.+-]+$/i),
  snippet: text(600).optional(),
  locatorLabel: text(80).optional(),
  matchReasons: z.array(text(60)).max(8).optional()
});

export const SourceCitationSchema = z.strictObject({
  sourceRef: SourceRefSchema,
  title,
  support: z.enum(['supported', 'conflicting', 'insufficient']),
  quote: text(600).optional(),
  locatorLabel: text(80).optional()
});

export const SourceScopeSchema = z.strictObject({
  kind: z.enum(['workspace', 'collection', 'selection']),
  selectedCount: count,
  description: text(160).optional(),
  collectionName: text(80).optional(),
  accessibleCount: count.optional(),
  pendingCount: count.optional()
});

const versionSide = z.strictObject({
  ref: AssetRefSchema.refine((ref) => ref.versionId !== '', 'A comparison names each version'),
  versionNo: z.number().int().min(1),
  createdAt: z.number().nonnegative(),
  current: z.boolean(),
  approved: z.boolean().nullable()
});

export const VersionComparisonSchema = z
  .strictObject({
    title,
    before: versionSide,
    after: versionSide,
    differences: z.array(z.strictObject({ field: text(60).min(1), before: text(300), after: text(300) })).max(50),
    affectedDrafts: count,
    actions: actionsOf(['version.accept_replacement', 'version.link'], 4)
  })
  .refine((value) => value.before.ref.versionId !== value.after.ref.versionId, 'Compare two different versions');

export const CollectionProposalSchema = z.strictObject({
  name: text(80).min(1),
  ruleSummary: text(400),
  before: z.array(member).max(200),
  after: z.array(member).max(200),
  effect: text(240),
  actions: actionsOf(['collection.save', 'collection.override', 'collection.undo'], 4),
  collectionId: assetKeySchema.optional()
});

/** Words in a source-pack action that would approve something only a person can approve. */
const APPROVING = /approv|rights|fact|public/i;

/** Rights are a constraint to check: nothing in a pack may call them cleared. */
const CLEARED = /\b(?:cleared|clearance|all clear|rights[- ]free|copyright[- ]free)\b/i;
const notCleared = (max: number) => text(max).refine((value) => !CLEARED.test(value), 'Rights are never “cleared”');

export const SourcePackReviewSchema = z.strictObject({
  packId: assetKeySchema,
  revision: count,
  goal: text(300),
  evidence: z
    .array(
      z.strictObject({
        sourceRef: SourceRefSchema,
        title,
        rationale: text(400),
        /** A rights code (approved_public | needs_review | internal | unknown); shown in fixed words, anything else reads unknown. */
        rights: notCleared(120),
        locatorLabel: text(80).optional(),
        warnings: z.array(notCleared(240)).max(6).optional()
      })
    )
    .max(50),
  style: z
    .array(
      z.strictObject({
        sourceRef: SourceRefSchema,
        title,
        rationale: text(400),
        locatorLabel: text(80).optional(),
        polarity: z.enum(['positive', 'negative']).optional(),
        sampleId: z.string().regex(ACTION_ID).optional()
      })
    )
    .max(20),
  gaps: z.array(notCleared(200)).max(20),
  rightsWarnings: z.array(notCleared(240)).max(20),
  actions: actionsOf(['source_pack.create', 'source_pack.attach'], 3).refine(
    (actions) => actions.every((action) => !strings(action.envelope.payload).some((key) => APPROVING.test(key))),
    'A source pack cannot approve facts or rights'
  )
});

export const DraftWorkspaceSchema = z.strictObject({
  title,
  body: text(20000),
  sources: z.array(titledSource).max(50),
  draftId: assetKeySchema.optional(),
  actions: actionsOf(['source_pack.attach'], 3).optional()
});

const capabilityName = z.enum(['preview', 'extract', 'transcribe', 'visual', 'embed_text', 'embed_visual', 'understand']);
const capabilityState = z.enum(['not_requested', 'queued', 'processing', 'ready', 'partial', 'unsupported', 'failed', 'cancelled', 'blocked_permission', 'blocked_budget']);

export const ProcessingStatusSchema = z.strictObject({
  assetRef: AssetRefSchema,
  title,
  capabilities: z
    .array(
      z.strictObject({
        capability: capabilityName,
        state: capabilityState,
        progress: z.strictObject({ done: count, total: count }).nullable().optional(),
        retryable: z.boolean().optional(),
        detail: text(200).optional()
      })
    )
    .max(10)
});

export const SuggestionReviewSchema = z.strictObject({
  suggestionId: assetKeySchema,
  category: z.enum(['outdated_source', 'unused_relevant', 'missing_input', 'failed_processing', 'organization', 'permission', 'source_integrity']),
  reason: text(400).min(1),
  state: z.enum(['new', 'seen', 'dismissed', 'snoozed', 'applied', 'expired', 'suppressed']),
  critical: z.boolean(),
  candidates: z.array(titledSource).max(20),
  affected: z.array(z.strictObject({ kind: text(40), label: text(120) })).max(20),
  actions: actionsOf(['suggestion.set_state'], 4)
});

/** The versioned allowlist: component name → schema and the action ids it may raise. Nothing else renders. */
export const LIBRARY_OPENUI_SCHEMAS = {
  AssetCandidateCard: { schema: AssetCandidateCardSchema, actions: ['library.select', 'library.open'] },
  SourceCitation: { schema: SourceCitationSchema, actions: ['library.open'] },
  SourceScope: { schema: SourceScopeSchema, actions: [] },
  VersionComparison: { schema: VersionComparisonSchema, actions: ['library.open', 'version.accept_replacement', 'version.link'] },
  CollectionProposal: { schema: CollectionProposalSchema, actions: ['collection.save', 'collection.override', 'collection.undo'] },
  SourcePackReview: { schema: SourcePackReviewSchema, actions: ['library.open', 'source_pack.create', 'source_pack.attach'] },
  DraftWorkspace: { schema: DraftWorkspaceSchema, actions: ['library.open', 'source_pack.attach'] },
  ProcessingStatus: { schema: ProcessingStatusSchema, actions: ['library.open'] },
  SuggestionReview: { schema: SuggestionReviewSchema, actions: ['library.open', 'suggestion.set_state'] }
} as const;

export type LibraryOpenUiName = keyof typeof LIBRARY_OPENUI_SCHEMAS;
export const LIBRARY_OPENUI_NAMES = Object.keys(LIBRARY_OPENUI_SCHEMAS) as LibraryOpenUiName[];

export type AssetCandidateCardProps = z.infer<typeof AssetCandidateCardSchema>;
export type SourceCitationProps = z.infer<typeof SourceCitationSchema>;
export type SourceScopeProps = z.infer<typeof SourceScopeSchema>;
export type VersionComparisonProps = z.infer<typeof VersionComparisonSchema>;
export type CollectionProposalProps = z.infer<typeof CollectionProposalSchema>;
export type SourcePackReviewProps = z.infer<typeof SourcePackReviewSchema>;
export type DraftWorkspaceProps = z.infer<typeof DraftWorkspaceSchema>;
export type ProcessingStatusProps = z.infer<typeof ProcessingStatusSchema>;
export type SuggestionReviewProps = z.infer<typeof SuggestionReviewSchema>;
export type ProposedAction = z.infer<typeof ProposedActionSchema>;
export type IssuedEnvelope = z.infer<typeof IssuedEnvelopeSchema>;
export type LibraryAssetRef = z.infer<typeof AssetRefSchema>;
export type LibraryLocator = z.infer<typeof LocatorSchema>;

/**
 * Validate one component's props. Unknown names return null (rejected, never rendered); invalid props return the
 * first problem in words, without echoing the offending value.
 */
export function parseLibraryProps(name: string, props: unknown): { ok: true; props: Record<string, unknown> } | { ok: false; error: string } | null {
  if (!Object.prototype.hasOwnProperty.call(LIBRARY_OPENUI_SCHEMAS, name)) return null;
  const entry = LIBRARY_OPENUI_SCHEMAS[name as LibraryOpenUiName];
  const parsed = entry.schema.safeParse(props);
  if (parsed.success) return { ok: true, props: parsed.data as Record<string, unknown> };
  const issue = parsed.error.issues[0];
  return { ok: false, error: `${name}: ${issue ? `${issue.path.join('.') || 'props'} — ${issue.message}` : 'invalid props'}` };
}
