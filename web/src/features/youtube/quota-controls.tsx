import type { YouTubeOverview } from '@/lib/youtube/types';

export function YouTubeQuotaControls({ admission }: { admission: YouTubeOverview['quota']['admission'] }) {
  if (!admission) return null;
  return (
    <section aria-label='Workspace publishing capacity' className='grid min-w-0 gap-3'>
      <h3 className='text-sm font-medium'>Workspace publishing capacity</h3>
      <div className='grid min-w-0 gap-3 sm:grid-cols-3'>
        {([['videoUploads', 'Upload starts'], ['search', 'Search requests'], ['general', 'General API units']] as const).map(([bucket, label]) => {
          const usage = admission.workspaceUsageToday[bucket];
          return (
            <div key={bucket} data-youtube-capacity={bucket} className='min-w-0 rounded-md border p-3 text-sm [overflow-wrap:anywhere]'>
              <p className='font-medium'>{label}</p>
              <p>Reserved today: {usage?.reservedUnits ?? 0} / {admission.workspaceCeilings[bucket]}</p>
              <p className='text-muted-foreground text-xs'>Rafii project ceiling: {admission.configuredProjectCeilings[bucket]} daily</p>
              <p className='text-muted-foreground text-xs'>Delayed attempts: {usage?.delayedRequests ?? 0}</p>
            </div>
          );
        })}
      </div>
      <p className='text-xs text-muted-foreground'>
        Pending workflow limit: {admission.pendingQueueLimit}. Request limit: {admission.requestsPerMinute} per minute.
        {' '}Daily reset: {new Date(admission.resetAt * 1000).toLocaleString(undefined, { timeZone: admission.resetTimeZone })} ({admission.resetTimeZone}).
      </p>
      <p className='text-xs text-muted-foreground'>
        {admission.approvedQuotaEvidence ? 'Configured ceilings are bound to recorded quota evidence.' : 'Configured ceilings use Rafii safety limits; production quota approval is unverified.'}
        {' '}These counters cover Rafii requests and do not show Google’s remaining allocation.
      </p>
    </section>
  );
}
