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
    const route = routes[job.manifest.platform];
    return route && url.protocol === 'https:' && route[0].includes(url.hostname) && route[1].test(url.pathname) && !url.username && !url.password && !url.port && !url.search && !url.hash ? job.url : null;
  } catch {
    return null;
  }
}

/** Container creation, acceptance and a provider lookup are separate evidence. */
export function PublicationReceipt({ job }: { job: Job }) {
  const url = receiptUrl(job);
  return (
    <div className='flex min-w-0 flex-col gap-2 text-sm' aria-label='Publication receipt'>
      {job.container && <p className='break-all'>Container: {job.container} · not proof of publication</p>}
      {job.providerReference && <p className='break-all'>Provider reference: {job.providerReference}</p>}
      {job.progress && <p>Stage: {job.progress.stage.replace(/_/g, ' ')}</p>}
      <p>{job.verification ? `${job.verification.method.replace(/_/g, ' ')} · ${new Date(job.verification.at * 1000).toISOString()}` : 'Publication not verified'}</p>
      {url && <a href={url} target='_blank' rel='noreferrer' className='text-primary rounded underline underline-offset-4 outline-none focus-visible:ring-2'>Open verified post</a>}
    </div>
  );
}
