'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { formatDateTime } from '@/lib/time';
import type { CreativePerformance } from '@/lib/api/creative-video';

const emptyStates = {
  unrendered: 'This revision has no saved MP4.',
  asset_unavailable: 'The exported video is unavailable in this workspace.',
  unlinked: 'No verified published post is linked to this export.'
};

export function PerformanceReadings({ data }: { data: CreativePerformance }) {
  if (data.state !== 'linked') return <StateMessage kind='empty' title={emptyStates[data.state]} />;
  return <div className='grid gap-4'>{data.posts.map(post => (
    <Surface key={post.jobId} as='section' material='quiet' padding='md'>
      <h2 className='text-lg font-medium'>{post.provider}</h2>
      <p className='break-all text-sm text-muted-foreground'>Post {post.providerPostId} · Verified {formatDateTime(post.verifiedAt)}</p>
      {post.metrics.length ? <dl className='mt-4 grid gap-3 sm:grid-cols-2'>
        {post.metrics.map(metric => <div key={JSON.stringify([metric.name, metric.definitionVersion, metric.readOffset, metric.periodStart, metric.periodEnd, metric.observedAt])}
          className='rounded-lg border p-3'>
          <dt className='font-medium'>{metric.name.replaceAll('_', ' ')}</dt>
          <dd className='mt-1 text-lg tabular-nums'>{metric.availability === 'available' && metric.value !== null
            ? `${metric.value.toLocaleString(undefined, { maximumFractionDigits: 9 })} ${metric.unit}` : 'Unavailable'}</dd>
          <dd className='mt-1 text-xs text-muted-foreground'>{metric.source === 'youtube_analytics' ? 'YouTube Analytics' : 'Provider insights'} · {metric.definitionVersion} · Observed {formatDateTime(metric.observedAt)}</dd>
          <dd className='text-xs text-muted-foreground'>{metric.periodStart != null || metric.periodEnd != null
            ? `Observation window: ${metric.periodStart == null ? 'unknown start' : formatDateTime(metric.periodStart)} – ${metric.periodEnd == null ? 'unknown end' : formatDateTime(metric.periodEnd)}`
            : 'Observation window unavailable'}{metric.readOffset ? ` · ${metric.readOffset}` : ''}</dd>
        </div>)}
      </dl> : <p className='mt-3 text-sm'>No platform readings have been recorded for this post.</p>}
    </Surface>))}</div>;
}

export function VideoPerformance({ projectId, revision }: { projectId: string; revision: number }) {
  const { api, workspaceId } = useWorkspaceApi();
  const readable = checkAccess(useWorkspaceAccess(), { permission: 'read' });
  const result = useQuery({
    queryKey: ['creative-video-performance', workspaceId, projectId, revision],
    queryFn: () => api.creativeVideoPerformance(workspaceId, projectId, revision),
    enabled: readable && Boolean(workspaceId), retry: false, gcTime: 0
  });
  if (!readable) return <PageContainer access={false} />;
  return <PageContainer pageTitle='Video performance' pageDescription={`Published posts and platform observations for revision ${revision}.`}
    pageHeaderAction={<Link href={`/app/creative?project=${encodeURIComponent(projectId)}&revision=${revision}`}
      className='rafii-focus rounded-sm text-sm underline underline-offset-4'>Open saved revision</Link>}>
    {result.isError ? <StateMessage kind='error' title='The performance records could not be loaded'
      description={result.error.message} action={<Button variant='glass' onClick={() => void result.refetch()}>Try again</Button>} /> :
      result.data ? <PerformanceReadings data={result.data} /> : <StateMessage kind='loading' title='Looking up published posts…' />}
    <Link href='/app/growth' className='rafii-focus w-fit rounded-sm text-sm underline underline-offset-4'>Open Growth Studio</Link>
  </PageContainer>;
}
