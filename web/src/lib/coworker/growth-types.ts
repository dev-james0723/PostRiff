export interface GrowthGoal {
  id: string; name: string; goalType: string; primaryMetric: string;
  baselineValue: number | null; currentValue: number | null; targetValue: number;
  targetAt: number; currentValueAt: number | null; channelId: string | null;
  status: 'active' | 'paused' | 'achieved' | 'archived'; displayStatus: string;
  providerMetricDefinition: string; source: string | null; confidence: string; change: number | null;
  coverage: { status: string; reason: string; measured: number; eligible: number };
  nextAction: { label: string; href: string };
}
export interface ExperimentResult {
  samples: { variant: number; control: number }; minimumPerArm: number; causal: false;
  statistic: 'median'; missing: number; limitations: string[];
  medianVariant?: number; medianControl?: number; relativeDifference?: number;
  evidenceIds: string[]; counterEvidenceIds: string[]; supportedFactor: string | null;
  interpretation: string;
}
export interface GrowthExperiment {
  id: string; statement: string; hypothesisId: string; hypothesisRevision: number; status: string;
  cohort: { provider: string; connectionId: string; language: string; contentTypeId: string; definitionVersion: string };
  metric: string; dimension: string; controlFactor: string; variantFactor: string;
  minimumPerArm: number; windowDays: number; startedAt?: number; endAt?: number;
  decision: string | null; result: ExperimentResult | null; limitations: string[];
  publishingJobIds: string[]; sourcePostIds: string[]; expiresAt: number;
}
export interface GrowthProof {
  id: string; frequency: 'weekly' | 'monthly'; periodStart: number; periodEnd: number;
  generatedAt: number; historyCoverage: string; href: string; limitations: string[];
  counts: { preparedPosts: number; approvedPosts: number; verifiedPublishedPosts: number; campaigns: number;
    completedExperiments: number; runningExperiments: number; nextWeekPrepared: number; engagementHandled: number;
    opportunitiesActedOn: number; evidence: { jobIds: string[]; variantIds: string[]; experimentIds: string[]; campaignIds: string[] } };
  timeBack: { coverage: string; byConfidence: { confidence: string; outcomes: number; savedSeconds: number }[]; reason?: string };
  goal: GrowthGoal | null;
  learningSummary: { coverage: string; approvalRate: number | null; medianEditDistance: number | null; priorApprovalRate: number | null; priorMedianEditDistance: number | null; acceptedPreferenceLearnings: number; definition: string };
}
export interface GrowthLoopView {
  goal: GrowthGoal | null; goals: GrowthGoal[]; experiments: GrowthExperiment[]; proofs: GrowthProof[];
  weekly: { activeRecipes: number; nextAction: string; href: string }; metricOptions: Record<string, string[]>;
}
export interface GrowthWrite<T> { record: T; verified: boolean }
export interface GoalInput {
  name: string; goalType: string; primaryMetric: string; baselineValue: number | null; targetValue: number;
  targetAt: string; channelId?: string; secondaryIndicators?: string[]; idempotencyKey: string;
}
