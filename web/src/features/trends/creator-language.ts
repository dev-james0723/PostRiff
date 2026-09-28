import type { Coverage, Trend, TrendFlags } from '@/lib/coworker/trend-types';
import { publicStage } from './trust-contract';

/** Copy only: these mappings never create a new lifecycle state, score, or measurement. */
const stageLabels: Record<NonNullable<Trend['inferred']['stage']>, string> = {
  emerging: 'Emerging',
  rising: 'Picking up',
  breaking: 'Breaking out',
  hot: 'Active conversation',
  peaking: 'Peaking',
  saturated: 'Crowded conversation',
  declining: 'Cooling',
  evergreen: 'Steady interest'
};
export function creatorStage(trend: Trend, flags: TrendFlags) {
  const stage = publicStage(trend, flags) as keyof typeof stageLabels | null;
  return stage ? stageLabels[stage] : 'Still taking shape';
}
export function creatorMomentum(trend: Trend) {
  const value = trend.calculated.velocity?.value;
  const supported =
    trend.verification_state === 'verified' &&
    Boolean(trend.trust_receipt_id) &&
    Date.parse(trend.expires_at) > Date.now() &&
    trend.inferred.data_state === 'qualified';
  if (!supported || value === null || value === undefined)
    return {
      label: 'Direction isn’t clear yet',
      symbol: '—',
      detail: 'There isn’t a reliable comparison for this period yet.'
    };
  if (value > 0)
    return {
      label: 'Activity is increasing',
      symbol: '↑',
      detail: 'The measured rate rose in this sample.'
    };
  if (value < 0)
    return {
      label: 'Activity is easing',
      symbol: '↓',
      detail: 'The measured rate fell in this sample.'
    };
  return {
    label: 'The rate is unchanged',
    symbol: '→',
    detail: 'No change in the measured rate for this sample.'
  };
}
export function creatorConfidence(trend: Trend) {
  if (
    trend.verification_state !== 'verified' ||
    !trend.trust_receipt_id ||
    Date.parse(trend.expires_at) <= Date.now() ||
    trend.inferred.confidence === 'unknown'
  )
    return {
      label: 'Not clear yet',
      detail: 'There isn’t enough checked evidence to judge this signal.'
    };
  if (
    trend.inferred.confidence === 'qualified' &&
    trend.inferred.data_state === 'qualified' &&
    trend.inferred.calibration_state === 'qualified'
  )
    return {
      label: 'Supported by evidence',
      detail: 'The available evidence meets the checks for this conversation.'
    };
  return {
    label: 'Still forming',
    detail: 'Rafii is still checking how reliable this signal is.'
  };
}
export const platformLabel = (platform: string) =>
  ({
    bluesky: 'Bluesky',
    mastodon: 'Mastodon',
    reddit: 'Reddit',
    x: 'X',
    threads: 'Threads',
    tiktok: 'TikTok',
    instagram: 'Instagram',
    youtube: 'YouTube',
    linkedin: 'LinkedIn'
  })[platform.toLowerCase()] ?? platform;
export const sourceStatus = (state: Coverage['availability']) =>
  ({
    available: 'Available',
    stale: 'Needs an update',
    unavailable: 'Unavailable',
    not_applicable: 'Not included'
  })[state];
export const sourceOverview = (coverage: Coverage) => {
  const missing = coverage.sources
    .filter((s) => s.availability === 'unavailable')
    .map((s) => platformLabel(s.platform));
  return missing.length
    ? `${missing.join(', ')} data isn’t available for this conversation.`
    : 'Based on the sources available here.';
};
