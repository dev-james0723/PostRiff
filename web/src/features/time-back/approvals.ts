import type { SnapshotState } from '@/lib/api/types';

/**
 * Approvals a person made, as stable marks: publish jobs they approved (not ones an automation created under their
 * standing authority) and automation posts they approved by hand. Comparing two readings tells the app that a post
 * approval just happened, wherever it was made (Queue, batch approval, a plan card, the site agent).
 */
export function approvalMarks(state: SnapshotState | undefined, userId: string | undefined): Set<string> {
  const marks = new Set<string>();
  if (!state || !userId) return marks;
  for (const job of state.phase2?.jobs ?? []) {
    const automation = (job as { automation?: { approvedVia?: string } }).automation;
    if (job.approvedBy === userId && automation?.approvedVia !== 'owner_preauthorization') marks.add(`job:${job.id}`);
  }
  for (const occurrence of state.raffi?.campaignPlanning?.occurrences ?? []) {
    for (const item of occurrence.items ?? []) {
      if (item.state === 'approved' && item.approvedVia === 'human' && item.decision?.decision === 'approve' && item.decision.by === userId) {
        marks.add(`item:${occurrence.id}|${item.key}`);
      }
    }
  }
  return marks;
}

/** How many marks are new since the previous reading. The first reading is a baseline, never an approval. */
export function newApprovals(previous: Set<string> | null, next: Set<string>): number {
  if (previous === null) return 0;
  let count = 0;
  for (const mark of next) if (!previous.has(mark)) count += 1;
  return count;
}
