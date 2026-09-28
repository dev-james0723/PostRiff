import type { Trend, TrendFlags, TrendMetric, TrendOpportunity } from '@/lib/coworker/trend-types';
import { publicStage, blockedVerification } from './trust-contract';

export type Dimension = {
  id: string;
  label: string;
  shortLabel: string;
  value: string;
  known: boolean;
  layer: 'calculated' | 'interpretation';
  definition: string;
  reason: string;
  metric: TrendMetric | null;
  evidenceRefs: string[];
  // v1 has native units, but no cross-axis normalization contract. Never guess a radius.
  radius: null;
  scope: string;
};
export const formatValue = (metric: TrendMetric | undefined) =>
  metric?.value != null ? `${metric.value.toLocaleString()} ${metric.unit}` : 'Unknown';
export function currentEvidence(trend: Trend, now = Date.now()) {
  return (
    Boolean(trend.trust_receipt_id) &&
    trend.verification_state === 'verified' &&
    !blockedVerification(trend.verification_state) &&
    Date.parse(trend.expires_at) > now
  );
}
export function usableOpportunity(op: TrendOpportunity, trend: Trend, now = Date.now()) {
  return (
    currentEvidence(trend, now) &&
    op.trend_id === trend.id &&
    op.trust_receipt_id === trend.trust_receipt_id &&
    op.verification_state === 'verified' &&
    ['ready', 'accepted'].includes(op.state) &&
    Date.parse(op.expires_at) > now &&
    op.workspace_fit.sufficient
  );
}
export function trendDimensions(trend: Trend, flags: TrendFlags, now = Date.now()): Dimension[] {
  const valid = currentEvidence(trend, now);
  const measured = (
    id: string,
    label: string,
    shortLabel: string,
    metric: TrendMetric | undefined,
    definition: string,
    missing: string
  ): Dimension => ({
    id,
    label,
    shortLabel,
    value: valid ? formatValue(metric) : 'Unknown',
    known: valid && metric?.value != null,
    layer: 'calculated',
    definition,
    reason: !valid
      ? 'A current verified receipt is required.'
      : metric?.value == null
        ? metric?.null_reason || missing
        : 'Reported in its native unit; not a viral probability.',
    metric: valid ? (metric ?? null) : null,
    evidenceRefs: trend.trust_receipt_id ? [trend.trust_receipt_id] : [],
    radius: null,
    scope: trend.coverage.scope
  });
  const audience =
    valid && flags.RAFII_TREND_MODEL_ENRICHMENT_ENABLED ? trend.workspace_fit?.audience : null;
  return [
    measured(
      'momentum',
      'Momentum',
      'Momentum',
      trend.calculated.velocity,
      'Change in observed rate over time. The current contract supplies velocity in its native unit, not a normalized momentum score.',
      'Comparable velocity has not been supplied.'
    ),
    measured(
      'acceleration',
      'Acceleration',
      'Acceleration',
      trend.calculated.acceleration,
      'Change in velocity across comparable windows. Inspect the method, window and denominator.',
      'Comparable acceleration has not been supplied.'
    ),
    measured(
      'spread',
      'Cross-platform Spread',
      'Spread',
      trend.calculated.observed_platform_count,
      'Platforms with qualified independent evidence. A count of available platform rows is not this measurement.',
      'Independent corroboration has not been measured in this response.'
    ),
    {
      id: 'audience',
      label: 'Audience Fit',
      shortLabel: 'Audience fit',
      value:
        audience?.assessment && audience.assessment !== 'unknown' ? audience.assessment : 'Unknown',
      known: Boolean(audience && audience.assessment !== 'unknown'),
      layer: 'interpretation',
      definition:
        'Workspace-specific interpretation of audience relevance, not measured popularity.',
      reason: audience?.reason || 'Audience context or a supported interpretation is unavailable.',
      metric: null,
      evidenceRefs: audience?.evidence_refs ?? [],
      radius: null,
      scope: trend.coverage.scope
    },
    measured(
      'adaptability',
      'Format Adaptability',
      'Adaptability',
      undefined,
      'How the observed structure could become an original execution within your capabilities. This is not repeatable performance.',
      'No versioned format-adaptability measurement is available.'
    ),
    measured(
      'gap',
      'Opportunity Gap',
      'Gap',
      undefined,
      'Evidence of unmet demand relative to a defined supply and crowding sample.',
      'Demand, supply comparison and a qualified whitespace method are not available.'
    )
  ];
}
export function movementState(
  row: Trend['platform_states'][number],
  trend: Trend,
  flags: TrendFlags
) {
  const coverage = row.coverage;
  const stage = publicStage({ ...trend, inferred: row.inferred }, flags);
  const activity =
    coverage.availability === 'unavailable'
      ? 'Unavailable'
      : coverage.availability === 'not_applicable'
        ? 'Not included'
        : coverage.availability === 'stale'
          ? 'Needs a fresh observation'
          : row.inferred.data_state === 'collecting'
            ? 'Collecting'
            : stage
              ? stage === 'declining'
                ? 'Cooling'
                : stage[0].toUpperCase() + stage.slice(1)
              : 'Activity not established';
  return {
    activity,
    representation:
      coverage.representation === 'aggregate_only'
        ? 'Aggregate-only'
        : coverage.representation.replaceAll('_', ' '),
    completeness:
      coverage.completeness === 'partial' ||
      coverage.completeness === 'truncated' ||
      coverage.completeness === 'gap'
        ? 'Partial coverage'
        : coverage.completeness.replaceAll('_', ' '),
    // Neither low breadth nor unavailable coverage means low activity / zero observations.
    reason: row.inferred.explanation,
    stage
  };
}
export function timelineData(trend: Trend, unit: string, hours: number, platform = '') {
  if (!currentEvidence(trend) || platform) return [];
  const points = trend.observed.timeline.toSorted((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const end = Math.max(...points.map((p) => Date.parse(p.at)));
  // Do not drop intervening gaps or different-unit points and then connect across them.
  return points
    .filter((p) => Date.parse(p.at) >= end - hours * 3600000)
    .map((p) => ({
      ...p,
      value: p.unit === unit && p.state !== 'gap' ? p.value : null,
      state: p.unit === unit ? p.state : ('gap' as const),
      reason: p.unit === unit ? p.reason : 'Different measurement unit; series not comparable.'
    }));
}
export function compareDimensions(a: Dimension[], b: Dimension[]) {
  return a.map((left, i) => {
    const right = b[i];
    const comparable = Boolean(
      left.known &&
      right.known &&
      left.metric &&
      right.metric &&
      left.metric.definition_id === right.metric.definition_id &&
      left.metric.definition_version === right.metric.definition_version &&
      left.scope === right.scope &&
      left.metric.denominator === right.metric.denominator &&
      left.metric.unit === right.metric.unit &&
      left.metric.baseline_ref === right.metric.baseline_ref &&
      left.metric.window.start === right.metric.window.start &&
      left.metric.window.end === right.metric.window.end
    );
    return {
      label: left.label,
      left: left.value,
      right: right.value,
      difference: comparable
        ? `${Number((left.metric!.value! - right.metric!.value!).toPrecision(8))} ${left.metric!.unit} difference in reported values; sample scope may differ`
        : 'Separate contexts; no numeric ranking'
    };
  });
}
