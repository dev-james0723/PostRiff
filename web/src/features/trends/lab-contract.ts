import type { LabRun, TrendOpportunity } from '@/lib/coworker/trend-types';
export interface LabDraft {
  id: string;
  revision: number;
  platform: string;
  text: string;
  dirty: boolean;
}
export interface ApplyLabEdit {
  text: string;
  expected_revision: number;
  run_id: string;
  edit_id: string;
}
export function labMatches(run: LabRun, draft: LabDraft, opportunity: TrendOpportunity) {
  return (
    !draft.dirty &&
    run.draft_id === draft.id &&
    run.draft_revision === draft.revision &&
    run.opportunity_id === opportunity.id &&
    run.opportunity_revision === opportunity.revision &&
    run.context_revision === opportunity.context_revision &&
    opportunity.context_digest === opportunity.context_revision &&
    run.trust_receipt_id === opportunity.trust_receipt_id &&
    Date.parse(run.expires_at) > Date.now() &&
    Date.parse(opportunity.expires_at) > Date.now() &&
    opportunity.verification_state === 'verified'
  );
}
export function applyExactEdit(text: string, before: string, after: string): string | null {
  const at = text.indexOf(before);
  return before && at >= 0 && text.indexOf(before, at + 1) < 0
    ? text.slice(0, at) + after + text.slice(at + before.length)
    : null;
}
