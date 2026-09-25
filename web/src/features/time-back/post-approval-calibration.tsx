'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { useMe, useSnapshot, useTimeSavings } from '@/lib/api/hooks';
import type { TimeSavingsTaskKind } from '@/lib/api/types';
import { useWorkspace } from '@/lib/workspace/provider';
import { approvalMarks, newApprovals } from './approvals';
import { CalibrationPrompt } from './calibration-prompt';

/** What an approval completes; a publication counts later, when the platform confirms it. */
const AFTER_APPROVAL: TimeSavingsTaskKind[] = ['draft', 'adapt'];

/**
 * The calibration question right after the person approves a post, wherever they approved it. Optional and
 * rate-limited exactly as on Analytics: the server's `due` list decides (that kind completed in the last week, fewer
 * than three answers, no own setting, nothing answered or dismissed in 30 days). One question per approval; an answer
 * or "Not now" closes it, and it never stands in the way of publishing.
 */
export function PostApprovalCalibration() {
  const { workspaceId } = useWorkspace();
  const snapshot = useSnapshot();
  const me = useMe();
  const pathname = usePathname();
  const client = useQueryClient();
  const seen = useRef<Set<string> | null>(null);
  const [armed, setArmed] = useState(false);
  const userId = me.data?.userId;

  useEffect(() => {
    seen.current = null;
    setArmed(false);
  }, [workspaceId, userId]);

  useEffect(() => {
    if (!snapshot.data || !userId) return;
    const marks = approvalMarks(snapshot.data.state, userId);
    const fresh = newApprovals(seen.current, marks);
    seen.current = marks;
    if (fresh > 0) {
      setArmed(true);
      void client.invalidateQueries({ queryKey: ['time-savings', workspaceId] });
    }
  }, [snapshot.data, userId, client, workspaceId]);

  const summary = useTimeSavings('30d', { enabled: armed });
  const kind = summary.data?.calibration.due.find((due) => AFTER_APPROVAL.includes(due));
  // Analytics asks the same question in its own section.
  if (!armed || !kind || pathname?.startsWith('/app/analytics')) return null;
  return (
    <aside aria-label='A quick question about time back' data-time-back-after-approval className='fixed inset-x-4 top-20 z-40 mx-auto max-w-md md:inset-x-auto md:right-6 md:mx-0 md:w-[26rem]'>
      <CalibrationPrompt key={kind} kind={kind} material='elevated' onSettled={() => setArmed(false)} />
    </aside>
  );
}
