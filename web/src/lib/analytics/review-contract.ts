import { z } from 'zod';
import { trendLearningSchema } from '../coworker/trend-types';

export const REVIEW_SCHEMA_VERSION = '1.0' as const;
const id = z.string().min(1).max(128);
const instant = z.iso.datetime();
const timezone = z.string().min(1).max(80).refine((value) => {
  try { return Boolean(new Intl.DateTimeFormat('en', { timeZone: value }).resolvedOptions().timeZone); } catch { return false; }
}, 'Choose an IANA timezone');
export const nativeValueSchema = z.number().finite().nonnegative().nullable();
export const publicationPeriodSchema = z.object({ start: instant, end: instant, timezone }).strict().refine((p) => p.start < p.end, 'End must follow start');
export const relativeDateRuleSchema = z.object({ kind: z.enum(['this_week', 'last_week', 'this_month', 'last_month']), timezone }).strict();
export const nativeMetricSchema = z.object({ provider: z.string().min(1), nativeName: id, definitionVersion: id, unit: z.literal('count') }).strict();
export const tagSelectionSchema = z.object({ tagId: id, kind: z.enum(['theme', 'campaign', 'series']), classificationVersion: z.number().int().nonnegative() }).strict();
export const comparisonSchema = z.discriminatedUnion('kind', [z.object({ kind: z.literal('none') }).strict(), z.object({ kind: z.literal('previous_period'), publicationPeriod: publicationPeriodSchema }).strict()]);
export const comparisonInputSchema = z.union([comparisonSchema, z.object({kind:z.literal('previous_period'),relativeToPublicationPeriod:z.literal(true)}).strict()]);
const inputFields = {
  schemaVersion: z.literal('1.0').optional(), workspaceId: id.optional(), channelIds: z.array(id).max(8),
  publicationPeriod: publicationPeriodSchema.optional(), relativeDateRule: relativeDateRuleSchema.optional(),
  horizon: z.enum(['1h', '24h', '7d']).optional(), language: z.string().max(40).nullable().optional(), formatIds: z.array(id).max(12).optional(),
  tagSelection: z.array(tagSelectionSchema).max(30).optional(), nativeMetric: z.array(nativeMetricSchema).max(48).optional(),
  comparison: comparisonInputSchema.optional(), cutoffAt: instant.optional(), scopeKind: z.literal('published_content_cohort').optional(),
  aggregation: z.enum(['median', 'mean']).optional(), attributionState: z.literal('unknown').optional()
};
export const reviewContextInputSchema = z.object(inputFields).strict().refine((v) => Boolean(v.publicationPeriod) !== Boolean(v.relativeDateRule), 'Choose one date scope');
export const reviewContextSchema = z.object({ ...inputFields, schemaVersion: z.literal('1.0'), workspaceId: id,
  publicationPeriod: publicationPeriodSchema, providers: z.array(id), horizon: z.enum(['1h', '24h', '7d']),
  language: z.string().nullable(), formatIds: z.array(id), tagSelection: z.array(tagSelectionSchema), nativeMetric: z.array(nativeMetricSchema),
  comparison: comparisonSchema, cutoffAt: instant, aggregation: z.enum(['median', 'mean']), scopeKind: z.literal('published_content_cohort'),
  attributionState: z.literal('unknown'), contextRevision: z.number().int().nonnegative(), contextDigest: id, rightsEpoch: id
}).strict();
export const publicationBindingSchema = z.object({ workspaceId: id, jobId: id, connectionId: id, provider: id, nativePostId: id, manifestDigest: id, publicationAt: instant }).strict();
export const metricEvidenceSchema = z.object({ ...nativeMetricSchema.shape, observationId: id.nullable(), publicationBinding: publicationBindingSchema,
  value: nativeValueSchema, valueState: z.enum(['measured', 'missing', 'unsupported', 'invalid']), reason: z.string().nullable(),
  collectionState: id, accessState: z.enum(['allowed', 'not_authorized', 'disconnected', 'revoked']), freshnessState: z.enum(['current', 'stale', 'unknown']),
  freshnessPolicyVersion: id, readOffset: z.string().nullable(), observedAt: instant.nullable(), ingestedAt: instant.nullable(),
  nativeWindow: z.literal('cumulative_at_observation'), sourceRef: z.url().nullable(), displayPermission: z.enum(['allowed', 'restricted']),
  periodSide: z.enum(['current', 'baseline']), lastAttemptState: z.string().nullable(), language: z.string().nullable(), formatId: z.string().nullable(), eligible: z.boolean()
}).strict().superRefine((e, ctx) => {
  if (e.value === null && !e.reason) ctx.addIssue({ code: 'custom', message: 'Missing values require a reason' });
  if (e.accessState !== 'allowed' && (e.value !== null || e.sourceRef !== null)) ctx.addIssue({ code: 'custom', message: 'Restricted evidence cannot expose values or sources' });
});
export const reviewCohortSchema = z.object({ provider: id, connectionId: id, language: z.string().nullable(), formatId: z.string().nullable(), nativeName: id, definitionVersion: id, unit: id, horizon: z.enum(['1h', '24h', '7d']) }).strict();
export const reviewGroupSchema = z.object({ cohort: reviewCohortSchema, sampleSize: z.number().int().nonnegative(), baselineSampleSize: z.number().int().nonnegative(), value: nativeValueSchema, baselineValue: nativeValueSchema, aggregation: z.enum(['median', 'mean']), minimumSample: z.literal(3), evidenceIds: z.array(id) }).strict();
export const reviewComparisonSchema = z.object({ cohort: reviewCohortSchema, current: nativeValueSchema, baseline: nativeValueSchema, relativeChange: z.number().finite().nullable(), reason: z.string().nullable(), sampleSize: z.number().int().nonnegative(), baselineSampleSize: z.number().int().nonnegative(), causal: z.literal(false), aggregation: z.enum(['median', 'mean']) }).strict();
export const reviewCoverageSchema = z.object({ eligible: z.number().int().nonnegative(), publications: z.number().int().nonnegative(), measured: z.number().int().nonnegative(), missing: z.number().int().nonnegative(), excludedByReason: z.record(z.string(), z.number().int().nonnegative()), earliestAvailableAt: instant.nullable(), collectionStartAt: instant.nullable(), lastSuccessfulRead: instant.nullable(), cutoffAt: instant, truncated: z.boolean(), maximumPosts: z.literal(300), historyLimitations: z.array(z.string()) }).strict();
export const reviewNextStepSchema = z.object({ kind:z.enum(['experiment','propose','collect']), existingExperimentId:id.nullable(), hypothesisId:id.optional(), href:z.enum(['/app/growth','/app/weekly']), label:z.string().max(240) }).strict();
export const reviewTakeawaySchema = z.object({ id,contextDigest:id,basisDigest:id,status:z.literal('observation'),actualPeriod:publicationPeriodSchema,nativeMetric:nativeMetricSchema,sampleSize:z.number().int().nonnegative(),coverage:reviewCoverageSchema,supportBindings:z.array(metricEvidenceSchema),counterEvidenceBindings:z.array(metricEvidenceSchema),limitations:z.array(z.string()),statement:z.string().max(1000),nextStep:reviewNextStepSchema,expiresAt:instant,causal:z.literal(false) }).strict();
// The canonical Trends service owns validation of receipt bindings. This adapter
// only displays its current-rights projection and never accepts client lineage.
export const reviewTrendProvenanceSchema = z.object({ jobId:id,receiptBindings:z.array(z.record(z.string(),z.unknown())).max(20),publication:z.record(z.string(),z.unknown()).nullable(),verifiedNativeIdentity:z.object({jobId:id,connectionId:id,nativePostId:id}).strict(),status:z.literal('verified_publication'),horizon:z.enum(['1h','24h','7d']),causal:z.literal(false) }).strict();
export const reviewReuseSchema = z.object({contentId:id,jobId:id,provider:id,connectionId:id,nativePostId:id,text:z.string(),revision:z.union([z.number().int(),id]),manifestDigest:id,publicationAt:instant.nullable(),language:z.string().nullable(),formatId:z.string().nullable(),state:z.literal('content_only'),rights:z.literal('allowed'),lastReviewedAt:instant,knownMetricHorizons:z.array(z.string()),nextStep:z.object({href:z.literal('/app/weekly'),label:z.string()}).strict()}).strict();
export const reviewPersonalizationSchema = z.object({status:z.literal('method_unavailable'),methodVersion:z.null(),accuracy:z.null(),period:publicationPeriodSchema,timezone, sampleSize:z.number().int().nonnegative(),variables:z.array(z.enum(['timing','format','frequency'])),reason:z.string(),nextStep:z.string()}).strict();
export const reviewProjectionSchema = z.object({ schemaVersion: z.literal('1.0'), resolvedContext: reviewContextSchema, contextDigest: id, basisDigest: id,
  nativeResults: z.array(metricEvidenceSchema), groups: z.array(reviewGroupSchema), comparisons: z.array(reviewComparisonSchema), coverage: reviewCoverageSchema,
  limitations: z.array(z.string()), workspaceRevision: z.number().int().nonnegative().nullable(), postTracking: z.unknown().optional(),
  takeaways:z.array(reviewTakeawaySchema).max(3),trendProvenance:z.array(reviewTrendProvenanceSchema),trendLearning:trendLearningSchema.nullable(),reuseCandidates:z.array(reviewReuseSchema).max(30),personalization:reviewPersonalizationSchema
}).strict();
export const savedReviewViewSchema = z.object({id,workspaceId:id,schemaVersion:z.literal('1.0'),name:z.string(),owner:id,revision:z.number().int().positive(),filterDefinition:reviewContextInputSchema,status:z.enum(['active','archived']),classificationVersion:z.number().int().nonnegative(),createdAt:instant,updatedAt:instant,resolvedContext:reviewContextSchema.nullable().optional(),blockedReason:z.string().nullable().optional()}).strict();
export const classificationTagSchema = z.object({tagId:id,kind:z.enum(['theme','campaign','series']),label:z.string().max(120)}).strict();
export const contentClassificationSchema = z.object({version:z.number().int().positive(),jobId:id,tags:z.array(id),source:z.enum(['human','ai_suggestion']),approvedBy:id,approvedAt:instant,manifestDigest:id,affectedPublications:z.literal(1),status:z.literal('approved')}).strict();
export const reviewViewsSchema = z.object({schemaVersion:z.literal('1.0'),views:z.array(savedReviewViewSchema),tags:z.array(classificationTagSchema),classifications:z.record(z.string(),contentClassificationSchema),suggestions:z.array(z.object({id,jobId:id,tags:z.array(classificationTagSchema),status:z.literal('suggested'),manifestDigest:id}).strict()),snapshots:z.array(z.object({snapshotId:id,version:z.number().int().positive(),generatedAt:instant}).strict()),classificationVersion:z.number().int().nonnegative(),workspaceRevision:z.number().int().nonnegative()}).strict();
export const reviewSnapshotSchema = z.object({snapshotId:id,schemaVersion:z.literal('1.0'),version:z.number().int().positive(),generatedAt:instant,createdBy:id,frequency:z.enum(['weekly','monthly']),resolvedContext:reviewContextSchema,contextDigest:id,basisDigest:id,sourceSha:z.string().regex(/^[a-f0-9]{40}$/),nativeResults:z.array(metricEvidenceSchema),coverage:reviewCoverageSchema,groups:z.array(reviewGroupSchema),comparisons:z.array(reviewComparisonSchema),observationBindings:z.array(metricEvidenceSchema),workProof:z.record(z.string(),z.unknown()),timeBack:z.object({value:nativeValueSchema,unit:z.literal('seconds'),state:z.enum(['unavailable','estimated']),estimationMethodVersion:id,inputs:z.array(z.unknown())}).strict(),takeaways:z.array(reviewTakeawaySchema).max(3),humanNotes:z.array(z.string().max(4000)).max(12),limitations:z.array(z.string()),classificationVersion:z.number().int().nonnegative(),sourceMethodVersions:z.array(id),rightsEpoch:id,rendererVersion:id,changeReason:z.string(),payloadDigest:id,trendProvenance:z.array(reviewTrendProvenanceSchema),trendLearning:trendLearningSchema.nullable()}).strict();
export const reviewExportSchema = z.object({snapshotId:id,version:z.number().int().positive(),payloadDigest:id,rendererVersion:id,contentType:z.string(),filename:z.string(),content:z.string(),rendering:z.enum(['browser_print_pdf','download'])}).strict();

export type ReviewInput = z.infer<typeof reviewContextInputSchema>;
export type ReviewContext = z.infer<typeof reviewContextSchema>;
export type MetricEvidence = z.infer<typeof metricEvidenceSchema>;
export type ReviewProjection = z.infer<typeof reviewProjectionSchema>;
export type SavedReviewView = z.infer<typeof savedReviewViewSchema>;
export type ReviewSnapshot = z.infer<typeof reviewSnapshotSchema>;
export type ReviewViews = z.infer<typeof reviewViewsSchema>;
export type ClassificationTag = z.infer<typeof classificationTagSchema>;
export const REVIEW_STATE_LABELS: Record<string, string> = {
  loading: 'Loading the current scope', no_account: 'No connected account', not_authorized: 'Analytics permission is unavailable',
  unsupported: 'This platform does not provide this metric', disabled: 'Collection is off in this workspace', unscheduled: 'No read scheduled for this window',
  pending_horizon: 'Waiting for the post-age window', scheduled: 'Read scheduled', pending: 'Waiting for a reading', measured: 'Native measurement',
  measured_zero: 'Measured zero', partial: 'Partial coverage', unavailable: 'No qualified reading', stale: 'Earlier reading; a later attempt failed',
  disconnected: 'Account disconnected', expired: 'Source or result expired', deleted: 'Source unavailable', revoked: 'Current source permission revoked',
  insufficient_sample: 'Too few comparable posts', legacy_period_unavailable: 'Legacy evidence period unavailable', method_unavailable: 'No qualified personalization method',
  incompatible_readings: 'Numerator and denominator readings differ', error: 'Unable to read this scope'
};
export function reviewDisplayState(e: Pick<MetricEvidence, 'accessState' | 'valueState' | 'value' | 'freshnessState' | 'collectionState'>): string {
  if (e.accessState !== 'allowed') return e.accessState;
  if (e.freshnessState === 'stale') return 'stale';
  if (e.valueState === 'measured') return e.value === 0 ? 'measured_zero' : 'measured';
  const collection = e.collectionState === 'rights_unavailable' ? 'not_authorized' : e.collectionState;
  return collection in REVIEW_STATE_LABELS ? collection : 'unavailable';
}
