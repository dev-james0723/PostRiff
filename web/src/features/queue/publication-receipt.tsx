import type { ReactNode } from 'react';
import type { Job } from '@/lib/api/types';

function receiptUrl(job: Job) {
  if (job.state !== 'verified' || job.verification?.method !== 'provider_lookup' || !job.url) return null;
  try {
    const url = new URL(job.url);
    const routes: Record<string, [string[], RegExp]> = {
      Instagram: [['instagram.com', 'www.instagram.com'], /^\/(p|reel|tv)\/[A-Za-z0-9_-]+\/?$/],
      Threads: [['threads.net', 'www.threads.net', 'threads.com', 'www.threads.com'], /^\/@[A-Za-z0-9_.]+\/post\/[A-Za-z0-9_-]+\/?$/],
      LinkedIn: [['linkedin.com', 'www.linkedin.com'], /^\/feed\/update\/urn:li:(share|ugcPost):[0-9]+\/?$/]
    };
    if (job.manifest.platform === 'Mastodon') {
      const account = /^(\d{1,40})@([a-z0-9.-]+)$/.exec(job.manifest.providerAccountId ?? '');
      const path = /^\/(?:@[^/?#]+\/[0-9]{1,40}|users\/[^/?#]+\/statuses\/[0-9]{1,40})\/?$/;
      return account && url.protocol === 'https:' && url.hostname === account[2] && path.test(url.pathname) && url.pathname.replace(/\/$/, '').split('/').at(-1) === job.providerReference && !url.username && !url.password && !url.port && !url.search && !url.hash ? job.url : null;
    }
    const route = routes[job.manifest.platform];
    return route && url.protocol === 'https:' && route[0].includes(url.hostname) && route[1].test(url.pathname) && !url.username && !url.password && !url.port && !url.search && !url.hash ? job.url : null;
  } catch {
    return null;
  }
}

/**
 * Container creation, acceptance and a platform lookup are separate evidence. No app imports (only types): the
 * receipt also renders on its own in a test, so a caller passes controls such as a copy button in `referenceAction`.
 */
export function PublicationReceipt({ job, referenceAction }: { job: Job; referenceAction?: ReactNode }) {
  const url = receiptUrl(job);
  const verifiedAt = job.verification ? new Date(job.verification.at * 1000) : null;
  return (
    <div className='flex min-w-0 flex-col gap-2 text-sm' aria-label='Publication receipt'>
      {job.container && <p className='break-all'>Upload: {job.container} · not yet published</p>}
      {job.providerReference && (
        <p className='flex items-start gap-1 break-all'>
          <span className='min-w-0'>Post ID: {job.providerReference}</span>
          {referenceAction}
        </p>
      )}
      {job.progress && <p>Stage: {job.progress.stage.replace(/_/g, ' ')}</p>}
      {!!job.progress?.threadReferences?.length && <div aria-label='Thread publication progress'>
        <p>{job.progress.threadReferences.length} of {(job.manifest.payload.threadParts?.length ?? 0) + 1} thread post IDs saved · {job.progress.threadVerified ?? 0} read back</p>
        <ol className='list-inside list-decimal'>
          {job.progress.threadReferences.map((id) => <li className='break-all' key={id}>Post ID: {id}</li>)}
        </ol>
        {job.state !== 'verified' && <p>Accepted parts remain on Mastodon. The complete thread is not verified yet.</p>}
      </div>}
      <p>
        {job.verification && verifiedAt ? (
          <time dateTime={verifiedAt.toISOString()} title={verifiedAt.toISOString()}>
            Verified · {job.verification.method.replace(/_/g, ' ')} · {verifiedAt.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
          </time>
        ) : (
          'Not verified yet'
        )}
      </p>
      {url && <a href={url} target='_blank' rel='noreferrer' className='text-primary rounded underline underline-offset-4 outline-none focus-visible:ring-2'>Open verified post</a>}
    </div>
  );
}
