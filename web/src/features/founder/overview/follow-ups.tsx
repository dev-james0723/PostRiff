'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { founderHref } from '@/config/founder-nav';
import { founderPanelStore } from '@/features/founder/agent/store';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { formatDateTime, formatRelative, humanize } from '@/features/founder/shared/format';
import { QueryBoundary } from '@/features/founder/shared/state-fallbacks';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { founderKeys } from '@/lib/founder/api';
import type { BriefingSchedule, FounderFollowUp } from '@/lib/founder/types';
import { cn } from '@/lib/utils';

/**
 * The Overview's Follow-ups and Reports tabs (PRD §5.2 F): reminders Rafii prepared and the person confirmed, and the
 * briefing schedules. Both read the server's rows; creating one goes through Rafii (follow-ups) or Settings (reports).
 */

const STATE_STATUS: Record<string, 'success' | 'warning' | 'neutral' | 'info' | 'danger'> = {
  draft: 'neutral',
  scheduled: 'info',
  due: 'warning',
  completed: 'success',
  cancelled: 'neutral',
  missed: 'danger'
};

/** Follow-ups are prepared by Rafii and confirmed by the person; the button only opens that conversation. */
function prepareFollowUp() {
  founderPanelStore.ask('Prepare a follow-up for tomorrow at 9 AM about the item I am looking at.', { section: 'overview' });
}

export function FollowUpsPanel() {
  const { api, environment } = useFounderSession();
  const query = useQuery({ queryKey: founderKeys.followUps(environment ?? 'unknown'), queryFn: ({ signal }) => api.followUps({ signal }), retry: false });
  return (
    <Panel
      title='Follow-ups'
      titleId='founder-follow-ups-heading'
      description='Reminders Rafii prepared and you confirmed. Nothing is scheduled without your confirmation.'
      actions={
        <Button type='button' variant='glass' size='sm' onClick={prepareFollowUp} className='gap-1.5'>
          <Icons.sparkles className='size-3.5' aria-hidden /> Prepare with Rafii
        </Button>
      }
    >
      <QueryBoundary query={query} loadingTitle='Reading follow-ups…' isEmpty={(envelope) => (envelope.data.followUps ?? []).length === 0} emptyTitle='No follow-ups yet' emptyDescription='Ask Rafii to prepare one; you confirm the time before it is saved.' layout='inline'>
        {(envelope) => (
          <ul className='flex flex-col gap-1.5' aria-label='Follow-ups'>
            {(envelope.data.followUps ?? []).map((item: FounderFollowUp) => (
              <li key={item.id} className='rafii-quiet flex items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
                <span className='flex min-w-0 flex-col'>
                  <span className='truncate font-medium'>{item.title}</span>
                  <span className='text-muted-foreground text-xs'>
                    {item.dueAt ? `Due ${formatDateTime(item.dueAt)} (${item.timeZone})` : 'No time yet'} · {humanize(item.sourceType)}
                  </span>
                </span>
                <StatusChip status={STATE_STATUS[item.state] ?? 'neutral'} className='h-6 shrink-0 px-2 text-[11px]'>
                  {humanize(item.state)}
                </StatusChip>
              </li>
            ))}
          </ul>
        )}
      </QueryBoundary>
    </Panel>
  );
}

export function ReportsPanel() {
  const { api, mode, environment } = useFounderSession();
  const query = useQuery({ queryKey: founderKeys.briefingSchedules(environment ?? 'unknown'), queryFn: ({ signal }) => api.briefingSchedules({ signal }), retry: false });
  return (
    <Panel
      title='Reports'
      titleId='founder-reports-heading'
      description='Daily and weekly briefings on your schedule. Delivery follows the contact policy; real calls stay off until you switch them on.'
      actions={
        <Link href={founderHref('settings', mode, { tab: 'reports' })} className={cn(buttonVariants({ variant: 'glass', size: 'sm' }), 'gap-1.5')}>
          Manage schedules <Icons.arrowRight className='size-3.5' aria-hidden />
        </Link>
      }
    >
      <QueryBoundary query={query} loadingTitle='Reading schedules…' isEmpty={(envelope) => (envelope.data.schedules ?? []).length === 0} emptyTitle='No briefing schedule yet' emptyDescription='Add a daily or weekly briefing under Settings → Reports.' layout='inline'>
        {(envelope) => (
          <ul className='flex flex-col gap-1.5' aria-label='Briefing schedules'>
            {(envelope.data.schedules ?? []).map((schedule: BriefingSchedule) => (
              <li key={schedule.id} className='rafii-quiet flex items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
                <span className='flex min-w-0 flex-col'>
                  <span className='font-medium'>
                    {humanize(schedule.kind)} at {schedule.localTime} ({schedule.timeZone})
                  </span>
                  <span className='text-muted-foreground text-xs'>{schedule.nextAt ? `Next ${formatRelative(schedule.nextAt)}` : 'Not scheduled'}</span>
                </span>
                <StatusChip status={schedule.enabled ? 'success' : 'neutral'} className='h-6 shrink-0 px-2 text-[11px]'>
                  {schedule.enabled ? 'On' : 'Off'}
                </StatusChip>
              </li>
            ))}
          </ul>
        )}
      </QueryBoundary>
    </Panel>
  );
}
