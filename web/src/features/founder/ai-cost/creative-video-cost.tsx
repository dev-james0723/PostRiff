'use client';

import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { founderFetch, signInHref } from '@/lib/founder/api';
import type { Envelope } from '@/lib/founder/types';
import { failureOf, useCapability, useFounderScope } from '../customers/kit/api';
import { count, ratio, stateLabel, usdMicro } from '../customers/kit/format';
import { Panel } from '../customers/kit/page-frame';
import { SimpleTable } from '../customers/kit/simple-table';
import { formatCredits } from '@/features/creative-video/intelligence';

interface Model { id: string; label: string; provider: string; available: boolean; paused: boolean; reason?: string | null; pricingVersion?: string | null; }
interface Usage {
  model: string; provider: string; plan: string; usageClass?: string; jobs: number; completed: number; failed: number; pendingReconciliations: number;
  estimatedUsdMicro: number | null; actualUsdMicro: number | null; reservedMilliCredits: number | null;
  consumedMilliCredits: number | null; averageLatencySeconds: number | null; accepted: number | null;
  technicalSuccessRate?: number | null; costPerAcceptedUsdMicro?: number | null;
}
interface VideoUsage { models: Model[]; rows: Usage[]; truncated?: boolean; }
const credits = (value: number | null) => value == null ? 'Unavailable' : formatCredits(value);

export function CreativeVideoCost() {
  const scope = useFounderScope();
  const mayManage = useCapability('control.settings') && scope.mode === 'live';
  const [review, setReview] = useState<Model | null>(null);
  const [notice, setNotice] = useState('');
  const read = useQuery({
    queryKey: scope.key('creative-video-usage'), enabled: scope.ready, retry: false,
    queryFn: async ({ signal }) => {
      const result = await founderFetch<Envelope<VideoUsage>>(`/usage/creative-video?mode=${scope.mode}`, { signal });
      return { ...result.data, dataState: result.dataState };
    }
  });
  const change = useMutation({
    retry: false,
    mutationFn: async (model: Model) => {
      if (!mayManage) throw new Error('A Live operator with settings access must change model availability.');
      const result = await founderFetch<Envelope<{ model: string; paused: boolean }>>('/usage/creative-video/model?mode=live',
        { method: 'POST', body: { model: model.id, paused: !model.paused } });
      return result.data;
    },
    onSuccess: async result => {
      setReview(null); setNotice(`${result.model} · ${result.paused ? 'paused' : 'pause removed'}`); await read.refetch();
    },
    onError: () => { setReview(null); void read.refetch(); }
  });
  const error = change.error ? failureOf(change.error) : null;
  return <Panel title='Video Studio' description='Model availability and usage for jobs created in the past 30 days, by provider and subscription.'>
    {read.isPending ? <StateMessage kind='loading' layout='inline' title='Loading video usage…' /> :
      read.isError ? <StateMessage kind='error' layout='inline' title='Video usage could not be loaded' description={failureOf(read.error).message}
        action={<Button variant='quiet' onClick={() => void read.refetch()}>Refresh video usage</Button>} /> :
      read.data.dataState === 'unavailable' ? <StateMessage kind='unsupported' layout='inline' title='Video usage is unavailable in this environment.' /> :
      <div className='grid min-w-0 gap-4'>
        <SimpleTable rows={read.data.models} rowKey={item => item.id} caption='Video model availability' emptyTitle='No video models reported'
          columns={[
            { key: 'model', label: 'Model', render: item => <div><p>{item.label}</p><p className='text-xs text-muted-foreground'>{item.provider}</p></div> },
            { key: 'state', label: 'Availability', render: item => <div>{item.paused ? 'Paused' : item.available ? 'Configured' : 'Unavailable'}
              {item.reason && <p className='whitespace-normal text-xs text-muted-foreground'>{item.reason}</p>}</div> },
            { key: 'price', label: 'Pricing version', render: item => item.pricingVersion || 'Unavailable' },
            { key: 'action', label: 'Routing', render: item => <Button variant='glass' size='sm' disabled={!mayManage || change.isPending}
              aria-label={`${item.paused ? 'Review resuming' : 'Review pausing'} ${item.label}`}
              onClick={() => { setNotice(''); change.reset(); setReview(item); }}>{item.paused ? 'Resume…' : 'Pause…'}</Button> }
          ]} />
        {mayManage && review && <div className='rafii-quiet grid gap-2 rounded-lg p-3 text-sm'>
          <p>{review.paused ? `Allow new quotes for ${review.label} when its provider and pricing are available?` :
            `Pause new quotes and submissions for ${review.label}? Saved operations still require reconciliation.`}</p>
          <div className='flex flex-wrap gap-2'>
            <Button size='sm' variant='action' disabled={change.isPending} onClick={() => change.mutate(review)}>{review.paused ? 'Confirm resume' : 'Confirm pause'}</Button>
            <Button size='sm' variant='quiet' disabled={change.isPending} onClick={() => setReview(null)}>Cancel</Button>
          </div>
        </div>}
        {scope.mode === 'demo' && <p className='text-sm text-muted-foreground'>Demo is read-only.</p>}
        {notice && <p role='status' className='text-sm'>{notice}</p>}
        {error && <StateMessage kind={error.status === 403 ? 'permission' : 'error'} layout='inline' title='Check the saved model setting'
          description={error.message} action={error.code === 'STEP_UP_REQUIRED' ? <a href={signInHref('/founder/ai-cost')} className='underline'>Sign in again</a> : undefined} />}
        <SimpleTable rows={read.data.rows} rowKey={row => JSON.stringify([row.provider, row.model, row.plan, row.usageClass])}
          caption='Recorded Video Studio jobs and costs' emptyTitle='No recorded scene jobs'
          columns={[
            { key: 'scope', label: 'Model / subscription', render: row => <div>{row.model}<small className='block'>{row.provider} · {stateLabel(row.plan)}</small></div> },
            { key: 'class', label: 'Usage class', render: row => row.usageClass ? stateLabel(row.usageClass) : 'Unclassified' },
            { key: 'jobs', label: 'Jobs', render: row => count(row.jobs) },
            { key: 'done', label: 'Completed / failed', render: row => `${count(row.completed)} / ${count(row.failed)}` },
            { key: 'rate', label: 'Technical success', render: row => ratio(row.technicalSuccessRate) },
            { key: 'latency', label: 'Mean latency', render: row => row.averageLatencySeconds == null ? 'Unavailable' : `${count(row.averageLatencySeconds)} s` },
            { key: 'pending', label: 'To reconcile', render: row => count(row.pendingReconciliations) },
            { key: 'estimate', label: 'Estimated cost', render: row => usdMicro(row.estimatedUsdMicro) },
            { key: 'actual', label: 'Recorded provider cost', render: row => <div>{usdMicro(row.actualUsdMicro)}
              {row.pendingReconciliations > 0 && <small className='block text-muted-foreground'>Excludes unconfirmed charges</small>}</div> },
            { key: 'reserved', label: 'Held credits', render: row => credits(row.reservedMilliCredits) },
            { key: 'consumed', label: 'Consumed credits', render: row => credits(row.consumedMilliCredits) },
            { key: 'accepted', label: 'Accepted assets', render: row => row.accepted == null ? 'Unmeasured' : count(row.accepted) },
            { key: 'perAsset', label: 'Cost per accepted asset', render: row => usdMicro(row.costPerAcceptedUsdMicro) }
          ]} />
        {read.data.truncated && <p className='text-xs text-muted-foreground'>Showing the first 200 usage groups.</p>}
      </div>}
  </Panel>;
}
