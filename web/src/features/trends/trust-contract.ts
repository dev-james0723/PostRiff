import type { Trend, TrendFlags } from '@/lib/coworker/trend-types';
export const blockedVerification = (state: string) =>
  ['inputs_deleted', 'inputs_expired', 'policy_revoked', 'mismatch', 'method_unavailable'].includes(
    state
  );
export function publicStage(trend: Trend, flags: TrendFlags): string | null {
  return flags.RAFII_TREND_STAGE_CLAIMS_ENABLED === true &&
    flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED === true &&
    trend.verification_state === 'verified' &&
    Boolean(trend.trust_receipt_id) &&
    Date.parse(trend.expires_at) > Date.now() &&
    trend.inferred.data_state === 'qualified' &&
    trend.inferred.calibration_state === 'qualified'
    ? trend.inferred.stage
    : null;
}
