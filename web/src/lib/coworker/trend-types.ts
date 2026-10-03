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
export const dnaDimensionIdSchema = z.enum([
  'momentum',
  'acceleration',
  'spread',
  'audience',
  'adaptability',
  'gap'
]);
const dnaDimensionFields = {
  id: dnaDimensionIdSchema,
  display_value: text,
  layer: z.enum(['calculated', 'interpretation']),
  definition: text,
  reason: text,
  evidence_refs: strings
};
export const dnaDimensionSchema = z.union([
  z.object({
    ...dnaDimensionFields,
    state: z.enum(['Low', 'Moderate', 'High']),
    value: z.number().finite().min(0).max(1),
    null_reason: z.null()
  }),
  z.object({
    ...dnaDimensionFields,
    state: z.literal('Unknown'),
    value: z.null(),
    null_reason: text.min(1)
  })
]);
export const dnaProfileSchema = z.object({
  method_id: id,
  method_version: id,
  scale_ref: id,
  reference_population: text,
  trust_receipt_id: id,
  expires_at: iso,
  limitations: strings,
  dimensions: z
    .array(dnaDimensionSchema)
    .length(6)
    .superRefine((dimensions, ctx) => {
      const ids = dimensions.map((dimension) => dimension.id);
      if (new Set(ids).size !== ids.length)
        ctx.addIssue({ code: 'custom', message: 'Trend DNA dimensions must be unique.' });
      for (const required of dnaDimensionIdSchema.options)
        if (!ids.includes(required))
          ctx.addIssue({ code: 'custom', message: `Trend DNA dimension ${required} is required.` });
    })
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
  workspace_fit: fit.nullable(),
  /** Optional, receipt-bound display geometry. Native metrics never become chart radii client-side. */
  dna_profile: dnaProfileSchema.nullable().optional()
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
/** Bounded stored assignment counts; prevalence does not imply copying or fatigue. */
export const saturationSampleDetailsSchema = z.strictObject({
  unclassified_count: z.number().int().nonnegative(),
  classification_coverage: z.number().nullable(),
  total_patterns: z.number().int().nonnegative(),
  patterns_truncated: z.boolean(),
  patterns: z.array(z.strictObject({
    pattern_id: z.union([text, z.tuple([text, text])]),
    count: z.number().int().nonnegative(),
    classified_share: z.number(),
    unique_creator_support: z.number().int().nonnegative(),
    interval: z.strictObject({
      lower: z.number(), upper: z.number(), method: text, level: z.number()
    }).nullable()
  })).max(20),
  copy_support: z.enum(['assessed', 'unassessed']),
  redundant_count: z.number().int().nonnegative().nullable(),
  creator: z.strictObject({
    known_author_count: z.number().int().nonnegative(),
    author_coverage: z.number().nullable(),
    largest_creator_share: z.number().nullable(),
    effective_creator_count: z.number().nullable()
  }).nullable()
});
export type SaturationSampleDetails = z.infer<typeof saturationSampleDetailsSchema>;

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
      uncertainty: text,
      sample_details: saturationSampleDetailsSchema.optional()
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
        format_reason: text,
        evidence_refs: strings.optional(),
        relevance: z.object({ assessment: text, reason: text }).optional(),
        risk: z.object({ assessment: text, reason: text }).optional(),
        uncertainties: strings.optional(),
        platform_targets: strings.optional(),
        recheck_at: iso.optional()
      })
    )
    .max(3)
});
export const angleGenerationSchema = z.object({
  status: z.enum(['disabled', 'needs_facts', 'needs_review', 'cached', 'queue_full', 'budget_unavailable',
    'queued', 'leased', 'running', 'retry_wait', 'succeeded', 'failed_terminal', 'cancelled', 'outcome_unknown']),
  job_id: z.uuid().optional(),
  result_id: z.uuid().optional(),
  provider_attempts: z.number().int().nonnegative().optional(),
  existing: z.boolean().optional()
});
export type TrendOpportunity = z.infer<typeof opportunitySchema>;
/** A signed page subset authorizes reported views; delivery itself is never a view. */
export const opportunitiesResponseSchema = envelopeSchema(z.array(opportunitySchema)).extend({
  exposure_token: text.min(1).max(4096).nullable().optional()
});
export const exposureInputSchema = z.strictObject({
  event_id: z.uuid(),
  exposure_token: text.min(1).max(4096),
  opportunity_id: z.uuid(),
  opportunity_revision: z.number().int().positive(),
  trust_receipt_id: z.uuid(),
  context_digest: text.min(1),
  eligible_candidates: z
    .array(
      z.strictObject({
        opportunity_id: z.uuid(),
        revision: z.number().int().positive()
      })
    )
    .min(1)
    .max(20)
});
export const exposureSchema = z.object({
  exposure_id: z.uuid(),
  event_id: z.uuid(),
  opportunity_id: z.uuid(),
  opportunity_revision: z.number().int().positive(),
  trust_receipt_id: z.uuid(),
  context_digest: text.min(1),
  measurement: z.literal('client_reported_view'),
  eligible_candidate_count: z.number().int().min(1).max(20),
  recorded_at: iso,
  expires_at: iso,
  existing: z.boolean()
});
export const dismissOpportunityInputSchema = z.strictObject({
  revision: z.number().int().positive(),
  idempotency_key: id,
  exposure_id: z.uuid().optional()
});
export const dismissedOpportunitySchema = z.object({
  opportunity_id: z.uuid(),
  revision: z.number().int().positive(),
  state: z.literal('dismissed'),
  exposure_id: z.uuid().nullable(),
  existing: z.boolean()
});
export type ExposureInput = z.infer<typeof exposureInputSchema>;
export type TrendExposure = z.infer<typeof exposureSchema>;
export type DismissOpportunityInput = z.infer<typeof dismissOpportunityInputSchema>;

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
  idempotency_key: id,
  exposure_id: z.uuid().optional()
});
export const acceptedOpportunitySchema = z.object({
  source_id: id,
  href: text,
  verified: z.boolean(),
  existing: z.boolean()
});
export type AcceptOpportunityInput = z.infer<typeof acceptOpportunitySchema>;

/** Stored, descriptive Performance data. These choices never infer an objective from a goal. */
export const trendLearningWindowSchema = z.enum(['1h', '24h', '7d']);
export const trendLearningObjectiveSchema = z.enum([
  'reach', 'shareability', 'conversation', 'follower_conversion', 'custom_metric'
]);
const metricChoiceFields = {
  selection_digest: id,
  channel_id: id,
  provider: id,
  metric: id,
  definition_version: z.string().min(1).max(100),
  window: trendLearningWindowSchema,
  objective: trendLearningObjectiveSchema,
  denominator_metric: id.optional()
};
export const trendMetricChoiceInputSchema = z.strictObject(metricChoiceFields);
export const trendMetricChoiceSchema = z.strictObject({
  ...metricChoiceFields,
  confirmed: z.literal(true),
  selected_by: id,
  selected_at: iso,
  id
});
export const trendMetricChoiceResponseSchema = envelopeSchema(trendMetricChoiceSchema);
export const trendLearningChoiceOptionSchema = z.strictObject({
  selection_digest: id,
  source_id: id,
  source_label: text,
  channel_id: id,
  channel_label: text,
  provider: id,
  metrics: z.array(id),
  definition_version: z.string().min(1).max(100),
  windows: z.array(trendLearningWindowSchema),
  objectives: z.array(trendLearningObjectiveSchema),
  saved_choice: trendMetricChoiceSchema.nullable()
});
export const trendLearningOutcomeStateSchema = z.enum([
  'unpublished', 'invalid_publication_chronology', 'invalid_published_revision',
  'objective_unselected', 'account_unavailable', 'pending_horizon', 'delayed',
  'unavailable', 'ambiguous_native_publication', 'measured'
]);
const count = z.number().int().nonnegative();
const finite = z.number().finite();
export const trendBetaStatusSchema = z.strictObject({
  state: z.enum(['feature_off', 'workspace_not_allowlisted', 'stored_radar']),
  radar_available: z.boolean(), acquisition: z.enum(['none', 'unverified', 'active', 'degraded']),
  metric_reads_enabled: z.boolean(), follower_conversion: z.literal('unavailable')
});
export const postTrackingSchema = z.strictObject({
  enabled: z.boolean(), as_of: finite, truncated: z.boolean(),
  posts: z.array(z.strictObject({
    job_id: id, provider: text, account: id,
    horizons: z.array(z.strictObject({
      window: z.enum(['t0', '1h', '24h', '7d']),
      state: z.enum(['disabled', 'unsupported', 'disconnected', 'rights_unavailable', 'pending_horizon', 'unscheduled', 'scheduled', 'pending', 'measured', 'unavailable']),
      due_at: finite.nullable(), reason: text.nullable()
    }))
  })).max(120)
});
export const performancePostTrackingSchema = z.object({ post_tracking: postTrackingSchema.optional() });
const learningOutcomeFields = {
  job_id: id,
  treatment_state: z.enum(['unknown', 'changed', 'unchanged']),
  causal: z.literal(false).optional(),
  reason: text.optional(),
  publication: z.strictObject({
    variant_revision: z.number().int().positive(), text_digest: id,
    platform_post_id: id, published_at: finite
  }).optional(),
  angle_id: id.nullable().optional(),
  selection_digest: id.nullable().optional(),
  objective_choice_id: id.optional(),
  metric: id.optional(),
  cohort: z.strictObject({
    account: id, provider: id, language: text.nullable(), format: text.nullable(),
    window: trendLearningWindowSchema, objective: trendLearningObjectiveSchema,
    definition: id, metric: id
  }).optional(),
  features: z.strictObject({
    opening: z.enum(['question', 'statement']), length: z.enum(['short', 'long']),
    cta: z.enum(['with_cta', 'no_cta']), visual: z.enum(['with_image', 'text_only']),
    weekday: z.enum(['weekend', 'weekday']).nullable(), time: z.enum(['morning', 'later']).nullable()
  }).optional(),
  paid_promotion: z.boolean().nullable().optional(),
  attribution: z.literal('multiple_recommendations_in_one_publication').optional(),
  comparison: z.strictObject({
    relative_value: finite.nullable(), sample_count: count, reason: text.nullable(),
    evidence_ids: strings, counter_evidence_ids: strings, causal: z.literal(false)
  }).optional(),
  baseline: z.strictObject({
    count, median: finite.nullable(), mad: finite.nullable(),
    state: z.enum(['unknown', 'descriptive']), reason: text.optional(), confounders: strings.optional()
  }).optional()
};
export const trendLearningOutcomeSchema = z.union([
  z.strictObject({
    ...learningOutcomeFields, state: z.literal('measured'), value: finite.nonnegative(),
    native_values: z.record(text, finite.nonnegative()), unit: z.enum(['ratio', 'count']),
    observed_at: finite, available_at: finite, metric_receipts: strings
  }),
  z.strictObject({
    ...learningOutcomeFields,
    state: trendLearningOutcomeStateSchema.exclude(['measured']), value: z.null()
  })
]);
export const trendLearningSchema = z.strictObject({
  schema_version: z.literal('rafii.trend-learning.v1'),
  as_of: iso,
  window: trendLearningWindowSchema,
  denominator: z.strictObject({
    exposures: count, accepted: count, dismissed: count, unaccepted: count, unknown: count,
    accepted_without_exposure: count, dismissed_without_exposure: count, unknown_without_exposure: count
  }),
  coverage: z.strictObject({
    exposure_page_truncated: z.boolean(), independent_analytics_views: count,
    decisions_truncated: z.boolean(), job_history_truncated: z.boolean(),
    suppressed_in_page: z.record(text, count),
    scope: z.literal('current_permitted_retained_client_views'),
    historical_denominator_complete: z.literal(false)
  }),
  outcome_states: z.partialRecord(trendLearningOutcomeStateSchema, count),
  exposures: z.array(z.strictObject({
    exposure_id: id, opportunity_id: id, opportunity_revision: z.number().int().positive(),
    measurement: z.literal('client_reported_view'), eligible_candidate_count: count,
    candidate_scope: z.literal('returned_page'),
    decision: z.enum(['accepted', 'dismissed', 'unknown', 'unaccepted']),
    outcomes: z.array(trendLearningOutcomeSchema),
    retention_basis: z.enum(['independent_reviewed_metadata', 'current_source_dependencies']),
    source_rights_extended: z.literal(false),
    publication_coverage: z.enum(['accepted_source_unavailable', 'observed_jobs', 'not_published']).optional()
  })),
  causal: z.literal(false), durable_strategy: z.literal(false), limitations: strings,
  choice_options: z.array(trendLearningChoiceOptionSchema).max(20)
});
export const trendLearningResponseSchema = envelopeSchema(trendLearningSchema);
/** Narrow only the additive field; the existing Performance contract retains its own owner. */
export const performanceTrendLearningSchema = z.object({ trend_learning: trendLearningSchema.optional() });
export type TrendLearning = z.infer<typeof trendLearningSchema>;
export type TrendLearningChoiceOption = z.infer<typeof trendLearningChoiceOptionSchema>;
export type TrendMetricChoiceInput = z.infer<typeof trendMetricChoiceInputSchema>;

// Stored visual analysis only. These additions do not widen existing contracts.
const analysisText = z.string().min(1).max(2000);
const analysisDigest = z.string().regex(/^[a-f0-9]{64}$/);
const analysisCount = z.number().int().min(0).max(10_000);
const analysisNumber = z.number().finite().min(0).max(Number.MAX_SAFE_INTEGER);
const analysisRefs = z.array(id).max(20).refine((v) => new Set(v).size === v.length);
const analysisReasons = z.array(analysisText).max(64);
const sampleScope = z.literal('observed_comparison_sample');
const analysisCoverageSchema = coverageSchema.extend({
  scope_ref: z.string().max(2000), coverage_epoch: z.string().max(2000), scope: z.string().max(2000),
  sources: z.array(coverageSchema.shape.sources.element.extend({
    platform: id, reason: z.string().max(2000).nullable()
  }).strict()).max(1000)
}).strict();
function analysisEnvelope<T extends z.ZodType>(data: T) {
  return envelopeSchema(data).extend({
    coverage: analysisCoverageSchema, limitations: analysisReasons,
    next_cursor: z.string().max(2000).nullable()
  }).strict();
}
const whitespaceOpportunitySchema = z.strictObject({
  candidate_id: id,
  gap_type: z.enum(['unanswered_question', 'counterargument', 'practical_example',
    'language_explanation', 'platform_adaptation', 'declared_audience_need']),
  demand_evidence_refs: analysisRefs,
  supply_search_scope: z.strictObject({
    available_at: iso, expires_at: iso,
    evidence_refs: z.array(id).min(1).max(1000), frame_id: id, qualified: z.literal(true),
    retrieval_coverage: z.number().min(0.8).max(1),
    observed_units: z.number().int().min(1).max(1000),
    expected_units: z.number().int().min(1).max(1000),
    scope: sampleScope, context_complete: z.boolean()
  }),
  supporting_supply_refs: analysisRefs, opposing_supply_refs: analysisRefs,
  angle_occupancy: z.strictObject({
    supporting_count: analysisCount, opposing_count: analysisCount, scope: sampleScope
  }),
  credibility: z.strictObject({
    available_at: iso, expires_at: iso, evidence_refs: analysisRefs,
    workspace_id: id, approved: z.literal(true), approved_fact_refs: analysisRefs
  }),
  proposed_contribution: z.string().min(1).max(800),
  risks: z.array(z.string().min(1).max(400)).max(8),
  disconfirming_evidence: z.array(z.string().min(1).max(400)).max(8)
});
export const whitespaceSchema = z.strictObject({
  schema_version: z.literal('rafii.trend-whitespace-admission.v1'),
  state: z.enum(['admitted', 'review_required', 'unavailable']),
  workspace_id: id, trend_id: id, trust_receipt_id: id,
  context_digest: analysisDigest, facts_digest: analysisDigest,
  opportunities: z.array(whitespaceOpportunitySchema).max(20),
  opportunity_refs: z.array(z.strictObject({
    candidate_id: id, opportunity_id: id, revision: z.number().int().positive().max(Number.MAX_SAFE_INTEGER)
  })).max(3),
  rejected: z.array(z.strictObject({ candidate_id: id, reasons: analysisReasons })).max(20),
  gaps: z.array(z.strictObject({
    candidate_id: id, platform: id, language: id,
    observed_original_count: analysisCount, known_creator_count: analysisCount,
    state: z.enum(['review_required', 'admitted']), reasons: analysisReasons, summary: analysisText
  })).max(20),
  claim_scope: sampleScope, semantic_qualification: z.literal('unqualified'),
  expires_at: iso, truncated: z.boolean(), limitations: analysisReasons,
  source_decision_cutoff: iso, computed_at: iso
}).superRefine((value, ctx) => {
  const reject = () => ctx.addIssue({ code: 'custom', message: 'Inconsistent stored whitespace bindings' });
  const at = Date.parse;
  if (!(at(value.source_decision_cutoff) <= at(value.computed_at) && at(value.computed_at) < at(value.expires_at))) reject();
  for (const rows of [value.gaps, value.opportunities, value.rejected, value.opportunity_refs]) {
    if (new Set(rows.map((r) => r.candidate_id)).size !== rows.length) reject();
  }
  const expected = value.opportunities.length ? 'admitted' : value.gaps.length ? 'review_required' : 'unavailable';
  if (value.state !== expected) reject();
  for (const gap of value.gaps) {
    const admitted = value.opportunities.some((o) => o.candidate_id === gap.candidate_id);
    const rejected = value.rejected.find((r) => r.candidate_id === gap.candidate_id);
    if ((gap.state === 'admitted') !== admitted || (admitted && (rejected || gap.reasons.length)) ||
        (!admitted && (!rejected || !gap.reasons.length)) || gap.known_creator_count > gap.observed_original_count) reject();
  }
  for (const row of [...value.opportunities, ...value.rejected]) {
    if (!value.gaps.some((g) => g.candidate_id === row.candidate_id)) reject();
  }
  for (const ref of value.opportunity_refs) {
    if (!value.opportunities.some((o) => o.candidate_id === ref.candidate_id)) reject();
  }
  for (const o of value.opportunities) {
    const s = o.supply_search_scope, c = o.credibility;
    const refs = new Set(s.evidence_refs);
    if (s.observed_units !== refs.size || refs.size !== s.evidence_refs.length ||
        s.observed_units > s.expected_units || Math.abs(s.retrieval_coverage - s.observed_units / s.expected_units) > 1e-12 ||
        o.demand_evidence_refs.length < 2 || !c.approved_fact_refs.length || c.workspace_id !== value.workspace_id ||
        o.angle_occupancy.supporting_count !== o.supporting_supply_refs.length ||
        o.angle_occupancy.opposing_count !== o.opposing_supply_refs.length ||
        o.supporting_supply_refs.some((r) => o.opposing_supply_refs.includes(r)) ||
        [...o.demand_evidence_refs, ...o.supporting_supply_refs, ...o.opposing_supply_refs].some((r) => !refs.has(r)) ||
        c.evidence_refs.length !== o.demand_evidence_refs.length || c.evidence_refs.some((r) => !o.demand_evidence_refs.includes(r)) ||
        (o.gap_type === 'unanswered_question' && !s.context_complete)) reject();
    for (const bound of [s, c]) {
      if (at(bound.available_at) > at(value.computed_at) || at(bound.expires_at) < at(value.expires_at) ||
          at(bound.available_at) >= at(bound.expires_at)) reject();
    }
  }
});
export const whitespaceResponseSchema = analysisEnvelope(z.array(whitespaceSchema).max(20));
export type TrendWhitespace = z.infer<typeof whitespaceSchema>;

const forecastQuantilesSchema = z.strictObject({
  '0.1': analysisNumber, '0.5': analysisNumber, '0.9': analysisNumber
});
const forecastMetricSchema = z.strictObject({
  count: analysisCount, mae: analysisNumber, quantile_loss: forecastQuantilesSchema,
  interval_count: analysisCount, interval_coverage: z.number().min(0).max(1),
  sharpness: analysisNumber, nominal_coverage: z.literal(0.8)
});
export const forecastSchema = z.strictObject({
  id, revision: z.number().int().positive().max(Number.MAX_SAFE_INTEGER), expires_at: iso,
  method: z.strictObject({ method_id: z.literal('trend.forecast.admission'), version: id }),
  scope_key: z.string().min(1).max(210),
  target: z.strictObject({
    population: z.literal('observed_sample'), frame_id: id, cohort: id, metric_definition: id,
    horizon_steps: z.number().int().min(1).max(168), bin_hours: analysisNumber.min(0.001),
    supported_horizon_hours: analysisNumber
  }),
  method_bundle: z.strictObject({
    version: z.literal('forecast_v2'), feature_version: z.literal('stable_sample_bins_v1'),
    methods: z.strictObject({ last_value: z.literal('1'), seasonal_naive: z.literal('1'), local_linear_count: z.literal('1') }),
    seasonal_period: z.number().int().min(1).max(168), trend_window: z.number().int().min(6).max(168),
    embargo_hours: analysisNumber,
    residual_window: z.strictObject({ last_value: z.literal(10_000), seasonal_naive: z.literal(10_000), local_linear_count: z.literal(512) })
  }),
  issued_at: iso, training_cutoff: iso, target_start: iso, horizon_end: iso, embargo_hours: analysisNumber,
  coverage: z.literal('stable'), structural_break: z.literal(false),
  training_input_digest: analysisDigest, prediction_digest: analysisDigest,
  state: z.literal('qualified'), forecast_wording_enabled: z.literal(true),
  predictions: z.array(z.strictObject({
    method: z.literal('local_linear_count'), state: z.literal('qualified'), point: analysisNumber,
    quantiles: forecastQuantilesSchema, interval_basis: z.literal('past_rolling_residuals'),
    residual_count: z.number().int().min(5).max(512)
  })).length(1),
  uncertainty: z.literal('predictive_interval'),
  qualification: z.strictObject({
    qualification_digest: analysisDigest, report_digest: analysisDigest, dataset_digest: analysisDigest,
    evaluation_cutoff: iso, gate_digest: analysisDigest,
    gate: z.strictObject({
      preregistered_at: iso, holdout_opened_at: iso,
      dataset_digest: analysisDigest, target_digest: analysisDigest, method_digest: analysisDigest,
      report_digest: analysisDigest, evaluation_plan_digest: analysisDigest, preregistration_digest: analysisDigest,
      primary_loss: z.literal('mae'), min_episodes: z.number().int().min(2).max(1000),
      min_pairs: z.number().int().min(2).max(1000), coverage_tolerance: z.number().min(0).lt(0.8),
      reviewer: analysisText, operator_approved: z.literal(true), rights_verified: z.literal(true), reproducible: z.literal(true)
    }),
    paired_count: z.number().int().min(2).max(1000), episode_count: z.number().int().min(2).max(1000),
    better_simple_baseline: z.enum(['last_value', 'seasonal_naive']),
    improvement_interval: z.strictObject({
      lower: analysisNumber.positive(), upper: analysisNumber.positive(),
      method: z.literal('paired_episode_block_bootstrap'), confidence_level: z.literal(0.95),
      draws: z.literal(1000), seed: z.literal(0)
    }),
    metrics: z.strictObject({ last_value: forecastMetricSchema, seasonal_naive: forecastMetricSchema, local_linear_count: forecastMetricSchema })
  })
}).superRefine((value, ctx) => {
  const at = Date.parse, q = value.qualification, t = value.target;
  const quantiles = value.predictions[0].quantiles;
  const hours = t.bin_hours * t.horizon_steps;
  if (q.paired_count < q.gate.min_pairs || q.episode_count < q.gate.min_episodes || q.episode_count > q.paired_count ||
      q.gate.dataset_digest !== q.dataset_digest || q.gate.report_digest !== q.report_digest ||
      q.improvement_interval.lower > q.improvement_interval.upper ||
      quantiles['0.1'] > quantiles['0.5'] || quantiles['0.5'] > quantiles['0.9'] ||
      t.supported_horizon_hours < hours || at(value.horizon_end) - at(value.target_start) !== hours * 3_600_000 ||
      at(value.training_cutoff) !== at(value.issued_at) - value.embargo_hours * 3_600_000 ||
      value.embargo_hours !== value.method_bundle.embargo_hours ||
      !(at(q.gate.preregistered_at) < at(q.gate.holdout_opened_at) && at(q.gate.holdout_opened_at) <= at(q.evaluation_cutoff) &&
        at(q.evaluation_cutoff) <= at(value.issued_at) && at(value.issued_at) <= at(value.target_start) &&
        at(value.issued_at) < at(value.expires_at) && at(value.expires_at) <= at(value.horizon_end)) ||
      Object.values(q.metrics).some((m) => m.interval_count > m.count) ||
      q.metrics.local_linear_count.interval_count !== q.metrics.local_linear_count.count ||
      q.metrics.local_linear_count.count < q.paired_count ||
      Math.abs(q.metrics.local_linear_count.interval_coverage - 0.8) > q.gate.coverage_tolerance + 1e-12) {
    ctx.addIssue({ code: 'custom', message: 'Inconsistent qualified forecast target, calibration or timing' });
  }
});
export const forecastResponseSchema = analysisEnvelope(forecastSchema);
export type TrendForecast = z.infer<typeof forecastSchema>;
