/** Trust Trend API v1. Snake_case is the wire contract; no score-based legacy Radar adapter. */
import { z } from 'zod';

const text = z.string();
const id = z.string().min(1).max(200);
const iso = z.iso.datetime({ offset: true });
const strings = z.array(text);
export const TREND_FLAGS = [
  'RAFII_TREND_INTELLIGENCE_ENABLED',
  'RAFII_TREND_RADAR_ENABLED',
  'RAFII_TREND_TRUST_RECEIPTS_ENABLED',
  'RAFII_TREND_STAGE_CLAIMS_ENABLED',
  'RAFII_TREND_CALIBRATION_ENABLED',
  'RAFII_TREND_MODEL_ENRICHMENT_ENABLED',
  'RAFII_TREND_GRAPH_GENOME_ENABLED',
  'RAFII_TREND_SATURATION_ENABLED',
  'RAFII_TREND_WHITESPACE_ENABLED',
  'RAFII_TREND_OPPORTUNITY_LAB_ENABLED',
  'RAFII_TREND_NOTIFICATIONS_ENABLED',
  'RAFII_TREND_PROVIDER_OPERATIONS_ENABLED',
  'RAFII_TREND_MULTIMODAL_ENABLED',
  'RAFII_TREND_FORECASTS_ENABLED'
] as const;
export type TrendFlag = (typeof TREND_FLAGS)[number];
export type TrendFlags = Partial<Record<TrendFlag, boolean>>;
export const coverageSchema = z.object({
  availability: z.enum(['available', 'stale', 'unavailable', 'not_applicable']),
  representation: z.enum([
    'raw_posts',
    'sampled_posts',
    'aggregate_only',
    'search_leads',
    'owned_posts',
    'trend_seeds'
  ]),
  completeness: z.enum(['complete_within_scope', 'partial', 'truncated', 'gap', 'unknown']),
  breadth: z.enum(['high', 'moderate', 'low', 'unknown']),
  scope_ref: text,
  coverage_epoch: text,
  scope: text,
  latest_successful_read: iso.nullable(),
  freshness_deadline: iso.nullable(),
  sources: z.array(
    z.object({
      platform: text,
      availability: z.enum(['available', 'stale', 'unavailable', 'not_applicable']),
      reason: text.nullable()
    })
  )
});
const metricFields = {
  unit: id,
  definition_id: id,
  definition_version: id,
  window: z.object({ start: iso, end: iso }),
  baseline_ref: text.nullable(),
  denominator: text.nullable()
};
export const metricSchema = z.union([
  z.object({ ...metricFields, value: z.number().finite(), null_reason: text.nullable() }),
  z.object({ ...metricFields, value: z.null(), null_reason: text.min(1) })
]);
const metrics = z.record(text, metricSchema);
export const verificationSchema = z.enum([
  'pending',
  'verified',
  'mismatch',
  'inputs_expired',
  'inputs_deleted',
  'policy_revoked',
  'method_unavailable'
]);
const stage = z
  .enum(['emerging', 'rising', 'breaking', 'hot', 'peaking', 'saturated', 'declining', 'evergreen'])
  .nullable();
export const inferenceSchema = z.object({
  stage,
  data_state: z.enum([
    'collecting',
    'provisional',
    'qualified',
    'stale',
    'insufficient',
    'rights_blocked',
    'retracted'
  ]),
  explanation: text,
  confidence: z.enum(['qualified', 'provisional', 'unknown']),
  calibration_state: z.enum(['qualified', 'insufficient', 'unknown']),
  evidence_refs: strings
});
export const evidenceSchema = z.discriminatedUnion('display_state', [
  z.object({
    id,
    display_state: z.literal('displayable'),
    platform: text,
    language: text,
    excerpt: text.nullable(),
    url: z.url().nullable(),
    observed_at: iso,
    expires_at: iso,
    policy_ref: id
  }),
  z.strictObject({
    id,
    display_state: z.enum(['aggregate_only', 'restricted', 'revoked', 'expired']),
    reason: text
  })
]);
const interpretation = z
  .object({
    summary: text,
    language: text,
    phrases: strings,
    alternatives: strings,
    evidence_refs: strings
  })
  .nullable();
const fitDimension = z.object({
  assessment: z.enum(['supported', 'concern', 'mixed', 'unknown']),
  reason: text,
  evidence_refs: strings
});
const fit = z.object({
  reason: text,
  sufficient: z.boolean(),
  trend_relevance: fitDimension,
  confidence: fitDimension,
  brand: fitDimension,
  audience: fitDimension,
  timing: fitDimension,
  originality: fitDimension,
  risk: fitDimension
});
export const trendSchema = z.object({
  id,
  canonical_topic: text,
  observed: z.object({
    summary: text,
    first_detected: iso.nullable(),
    latest_observed: iso.nullable(),
    metrics,
    timeline: z.array(
      z.object({
        at: iso,
        value: z.number().finite().nullable(),
        unit: text,
        state: z.enum(['complete', 'provisional', 'gap']),
        reason: text.nullable()
      })
    )
  }),
  calculated: metrics,
  inferred: inferenceSchema,
  interpretation,
  unverified_claims: strings,
  coverage: coverageSchema,
  limitations: strings,
  trust_receipt_id: id.nullable(),
  verification_state: verificationSchema,
  expires_at: iso,
  platform_states: z.array(
    z.object({ platform: text, inferred: inferenceSchema, coverage: coverageSchema })
  ),
  evidence: z.array(evidenceSchema),
  workspace_fit: fit.nullable()
});
export const receiptSchema = trendSchema.extend({
  receipt_id: id,
  method: z.object({
    id,
    version: id,
    formula: text,
    calibration_cohort: text.nullable(),
    snapshot_refs: strings
  })
});
export function envelopeSchema<T extends z.ZodType>(data: T) {
  return z.object({
    schema_version: z.literal('1.0'),
    request_id: id,
    as_of: iso,
    data,
    coverage: coverageSchema,
    limitations: strings,
    execution_state: z.enum(['stored_result', 'partial', 'collecting', 'unavailable']),
    next_cursor: text.nullable()
  });
}
export type Coverage = z.infer<typeof coverageSchema>;
export type TrendMetric = z.infer<typeof metricSchema>;
export type Trend = z.infer<typeof trendSchema>;
export type TrendReceipt = z.infer<typeof receiptSchema>;
export type TrendEvidence = z.infer<typeof evidenceSchema>;
export type TrendEnvelope<T> = {
  schema_version: '1.0';
  request_id: string;
  as_of: string;
  data: T;
  coverage: Coverage;
  limitations: string[];
  execution_state: 'stored_result' | 'partial' | 'collecting' | 'unavailable';
  next_cursor: string | null;
};

export const methodologySchema = z.object({
  method_id: id,
  version: id,
  summary: text,
  definitions: z.array(z.object({ id, version: id, unit: text, formula: text })),
  blind_spots: strings
});
export const calibrationSchema = z.object({
  state: z.enum(['qualified', 'insufficient', 'unknown']),
  cohort: text.nullable(),
  evaluated: z.number().int().nonnegative(),
  unknown_outcomes: z.number().int().nonnegative(),
  metrics,
  limitations: strings
});
export const languagePatternSchema = z.object({
  id,
  expression: text,
  language: text,
  context: text,
  meaning: text,
  uncertainty: text,
  evidence: z.array(evidenceSchema)
});
export const genomeSchema = z.object({
  version: id,
  dimensions: z.array(
    z.object({
      dimension: text,
      finding: text.nullable(),
      uncertainty: text,
      evidence_refs: strings
    })
  ),
  narrative_variants: strings
});
export const propagationSchema = z.object({
  version: id,
  scope: text,
  nodes: z.array(z.object({ id, label: text, first_seen: iso.nullable() })),
  edges: z.array(
    z.object({
      id,
      from: id,
      to: id,
      relation: text,
      basis: z.enum(['observed', 'hypothesized']),
      evidence_refs: strings,
      limitation: text
    })
  ),
  truncated: z.boolean()
});
export const saturationSchema = z.object({
  dimensions: z.array(
    z.object({
      dimension: z.enum(['topic', 'narrative', 'hook', 'format', 'creator']),
      assessment: text.nullable(),
      frame: text,
      eligible: z.number().int().nonnegative(),
      classified: z.number().int().nonnegative(),
      metric: metricSchema,
      interval: text.nullable(),
      method: text,
      uncertainty: text
    })
  )
});
export const opportunitySchema = z.object({
  id,
  revision: z.number().int().min(1),
  trend_id: id,
  trust_receipt_id: id,
  state: z.enum(['candidate', 'ready', 'accepted', 'dismissed', 'expired', 'blocked']),
  platform_targets: strings,
  context_digest: id,
  verification_state: verificationSchema,
  expires_at: iso,
  title: text,
  contribution: text,
  uncertainty: text,
  workspace_fit: fit,
  source_id: id.nullable(),
  draft_id: id.nullable(),
  context_revision: id,
  angles: z
    .array(
      z.object({
        id,
        title: text,
        contribution: text,
        factual_requirements: strings,
        format_reason: text
      })
    )
    .max(3)
});
export type TrendOpportunity = z.infer<typeof opportunitySchema>;
export const watchSchema = z.object({
  id,
  revision: z.number().int().nonnegative(),
  trend_id: id,
  platforms: strings,
  threshold: z.enum(['stage_change', 'coverage_change']),
  notification_policy: z.literal('in_app'),
  active: z.boolean()
});
export type TrendWatch = z.infer<typeof watchSchema>;
export const watchInputSchema = z.strictObject({
  trend_id: id,
  platforms: strings.min(1),
  threshold: z.enum(['stage_change', 'coverage_change']),
  notification_policy: z.literal('in_app'),
  idempotency_key: id
});
export const labInputSchema = z.strictObject({
  draft_id: id,
  draft_revision: z.number().int().nonnegative(),
  opportunity_id: id,
  opportunity_revision: z.number().int().nonnegative(),
  target_platform: id,
  idempotency_key: id
});
export const labRunSchema = z.object({
  id,
  state: z.enum(['queued', 'running', 'completed', 'stale', 'failed', 'cancelled', 'unavailable']),
  draft_id: id,
  draft_revision: z.number().int().nonnegative(),
  opportunity_id: id,
  opportunity_revision: z.number().int().nonnegative(),
  context_revision: id,
  trust_receipt_id: id,
  expires_at: iso,
  failure_reason: text.nullable(),
  diagnostics: z.array(
    z.object({
      dimension: text,
      assessment: z.enum(['supported', 'concern', 'mixed', 'unknown']),
      claim: text,
      evidence_refs: strings,
      comparison_frame: text,
      uncertainty: text,
      requires_user_fact: z.boolean(),
      suggested_edit: z.object({ id, before: text.min(1), after: text, reason: text }).nullable()
    })
  )
});
export type LabRun = z.infer<typeof labRunSchema>;
export type LabInput = z.infer<typeof labInputSchema>;
export type WatchInput = z.infer<typeof watchInputSchema>;

export const acceptOpportunitySchema = z.strictObject({
  revision: z.number().int().min(1),
  angle_id: id,
  channel_id: id,
  goal: text.min(1).max(1000),
  idempotency_key: id
});
export const acceptedOpportunitySchema = z.object({
  source_id: id,
  href: text,
  verified: z.boolean(),
  existing: z.boolean()
});
export type AcceptOpportunityInput = z.infer<typeof acceptOpportunitySchema>;
