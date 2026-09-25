import { STATUS } from '@/lib/status-labels';
import { jobBadge, jobGroup, type JobBadge } from './job-state';

/**
 * A job's badge in the shared status words (`STATUS`). `jobBadge` keeps the precise group (so "held" never reads as
 * "scheduled"); this only renames it for people and moves the reason into the tooltip.
 */
export function jobStatus(job: Parameters<typeof jobBadge>[0]): JobBadge {
  const badge = jobBadge(job);
  const group = jobGroup(job.state);
  if (badge.label === 'cancelling') return { ...badge, label: 'Cancelling…', title: 'Cancel requested' };
  switch (group) {
    case 'waiting':
      return { ...badge, label: STATUS.scheduled, title: 'Approved and waiting for its time' };
    case 'publishing':
      return {
        ...badge,
        label: STATUS.publishing,
        title:
          job.state === 'processing'
            ? 'Preparing media'
            : job.state === 'provider_accepted'
              ? 'Accepted by the platform; checking the result'
              : job.state === 'published'
                ? 'Checking the post is live'
                : 'Sent; waiting for the platform'
      };
    case 'uncertain':
      return {
        ...badge,
        label: 'Result not confirmed',
        title: job.cancelRequested ? 'The cancel came too late to recall it. Check the platform before trying again.' : 'The platform didn’t confirm. Check it before trying again.'
      };
    case 'held':
      return { ...badge, label: 'Needs action', title: 'Something changed after approval. Prepare it again.' };
    case 'verified':
      return { ...badge, label: STATUS.published, title: 'Live on the platform' };
    case 'ended':
      return job.state === 'failed' ? { ...badge, label: STATUS.failed, title: 'Couldn’t publish this post' } : { ...badge, label: 'Cancelled' };
    default:
      return { ...badge, label: badge.label.charAt(0).toUpperCase() + badge.label.slice(1), title: 'Open details for its events.' };
  }
}
