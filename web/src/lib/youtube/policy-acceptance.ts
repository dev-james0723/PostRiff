import type { YouTubePolicyStatus } from './types';

export function youtubePolicyAcceptanceBody(status: YouTubePolicyStatus, displayedPolicyId: string, confirmed: boolean) {
  if (!status.ready || !status.policy || status.policy.id !== displayedPolicyId || confirmed !== true) {
    throw new Error('Review and explicitly agree to the current published YouTube policies.');
  }
  return {
    policyId: status.policy.id,
    privacyRevision: status.policy.privacy.revision,
    termsRevision: status.policy.terms.revision,
    confirmed: true as const
  };
}
