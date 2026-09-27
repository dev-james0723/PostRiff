'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Band } from '@/features/workspace/rafii-parts';
import { useCreateOpportunity, useDecideOpportunity } from '@/lib/coworker/hooks';
import { errorMessage } from '@/lib/coworker/api';
import type { Opportunity } from '@/lib/coworker/types';

const OBJECTIVE: Record<string, string> = {
  reach: 'Reach',
  shareability: 'Shares',
  conversation: 'Conversation',
  follower_conversion: 'Followers',
  authority: 'Authority'
};
function date(value: unknown) {
  if (typeof value !== 'number' && typeof value !== 'string') return 'Unknown';
  const d = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isFinite(d.getTime()) ? d.toLocaleString() : 'Unknown';
}
function link(value?: string) {
  try {
    const u = new URL(value || '');
    return ['http:', 'https:'].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
}

/** Semantic disclosure + visible actions work with keyboard, touch and reduced motion. */
export function OpportunityFlipper({ items, canEdit }: { items: Opportunity[]; canEdit: boolean }) {
  return (
    <section aria-label='Opportunity Flipper' className='flex flex-col gap-3'>
      <p className='text-muted-foreground text-sm'>
        {items.length
          ? `${items.length} opportunit${items.length === 1 ? 'y' : 'ies'} worth your attention`
          : 'No evidence-backed opportunities yet. Fewer is fine.'}
      </p>
      {items.map((item) => (
        <FlipperCard key={item.id} item={item} canEdit={canEdit} />
      ))}
    </section>
  );
}

function FlipperCard({ item, canEdit }: { item: Opportunity; canEdit: boolean }) {
  const create = useCreateOpportunity();
  const decide = useDecideOpportunity();
  const router = useRouter();
  const plans = item.executionPlans || [];
  const [planId, setPlanId] = useState(plans[0]?.id || '');
  const pending = create.isPending || decide.isPending;
  const action =
    item.actionType === 'act_now' ? 'Act now' : item.actionType === 'skip' ? 'Skip' : 'Watch';
  async function make(outcomeJobId?: string, selectedPlanId = planId) {
    try {
      const result = await create.mutateAsync({
        id: item.id,
        planId: selectedPlanId,
        outcomeJobId
      });
      if (!result.verified)
        return toast.warning('Could not confirm creation. Refresh before trying again.');
      router.push(result.href);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }
  async function decision(value: 'watch' | 'dismiss') {
    try {
      const result = await decide.mutateAsync({ id: item.id, decision: value });
      if (!result.verified) return toast.warning('Could not confirm the decision.');
      toast.success(value === 'watch' ? 'Watching for more evidence.' : 'Skipped.');
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }
  return (
    <Band className='gap-3' as='section'>
      <div className='flex flex-wrap justify-between gap-2'>
        <h3 className='text-foreground font-medium'>{item.title}</h3>
        <span className='text-sm'>
          {action} · {item.stage?.replaceAll('_', ' ')}
        </span>
      </div>
      <p className='text-sm'>
        Best suited for: {OBJECTIVE[item.primaryObjective || ''] || 'Objective not selected'}
      </p>
      <p className='text-muted-foreground text-sm'>
        {item.independentCreators ?? 0} known independent creators · {item.sourceCount ?? 0} sources
      </p>
      <p className='text-sm'>{item.actionReason}</p>
      <p className='text-muted-foreground text-sm'>{item.growthRationale}</p>
      <details className='text-sm'>
        <summary className='rafii-focus min-h-11 cursor-pointer py-3'>
          Evidence and limitations
        </summary>
        <div className='flex flex-col gap-3 py-2'>
          <p>{item.stageBasis}</p>
          <p>
            Saturation: {item.saturation?.replaceAll('_', ' ') || 'Unknown'}. Expires:{' '}
            {date(item.expiresAt)}.
          </p>
          <ul className='flex flex-col gap-3'>
            {item.evidence.map((s, i) => {
              const p = (s.provenance || {}) as Record<string, unknown>;
              return (
                <li key={i}>
                  <a
                    href={link(s.url)}
                    target='_blank'
                    rel='noopener noreferrer'
                    className='rafii-focus underline break-all'
                  >
                    Source {i + 1}
                    <span className='sr-only'> (opens in new tab)</span>
                  </a>
                  <p>{s.snippet}</p>
                  <p className='text-muted-foreground'>
                    Published: {date(p.publishedAt)} · Retrieved: {date(p.retrievedAt)}
                  </p>
                </li>
              );
            })}
          </ul>
          {item.normalizedEvidence?.map((m, i) => <p key={i}>{m.provider} · {m.window} · {m.metric}: {m.value.toLocaleString()}; own-account median {m.baseline.toLocaleString()} from {m.samples} comparable posts ({m.lift.toFixed(1)}×). Observed association only.</p>)}
          <ul className='list-disc pl-5'>
            {item.unknowns?.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          {plans.map((p) => (
            <div key={p.id}>
              <p className='font-medium'>
                {p.platform}: {p.format.replaceAll('_', ' ')}
              </p>
              <p>{p.hookStrategy}</p>
              <p>{p.reason}</p>
              <p>
                Original assets only.{' '}
                {p.retentionHypothesis ? `Retention hypothesis: ${p.retentionHypothesis}` : ''}
              </p>
            </div>
          ))}
          {item.outcomes?.map((o) => (
            <div key={`${o.jobId}-${o.window}`}>
              <p className='font-medium'>
                {o.window}: {o.state.replaceAll('_', ' ')}
              </p>
              <p>
                {o.value === null
                  ? 'Outcome unavailable'
                  : `${o.metric}: ${o.value.toLocaleString()} · ${o.samples} comparable posts`}
              </p>
              <p>
                Next: {o.nextAction.replaceAll('_', ' ')}. {o.reason}
              </p>
              <p>Business return: {o.businessReturn}.</p>
            </div>
          ))}
          {canEdit &&
            item.outcomes
              ?.filter(
                (o) =>
                  o.state === 'double_down_candidate' &&
                  !item.outcomes?.some(
                    (later) =>
                      later.jobId === o.jobId &&
                      later.window === '7d' &&
                      later.value !== null &&
                      o.window !== '7d'
                  )
              )
              .map((o) => (
                <Button
                  key={`followup-${o.jobId}-${o.window}`}
                  disabled={pending}
                  onClick={() => void make(o.jobId, o.executionPlanId)}
                >
                  Prepare sequel from {o.window} evidence
                </Button>
              ))}
        </div>
      </details>
      {canEdit && (
        <div className='flex flex-wrap items-center gap-2'>
          {item.status !== 'acted' && item.actionType !== 'skip' && plans.length > 0 && (
            <>
              <label className='sr-only' htmlFor={`plan-${item.id}`}>
                Destination for {item.title}
              </label>
              <select
                id={`plan-${item.id}`}
                value={planId}
                onChange={(e) => setPlanId(e.target.value)}
                className='bg-background text-foreground rafii-focus min-h-11 max-w-full rounded-md border px-3 text-base'
              >
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.platform} · {p.format.replaceAll('_', ' ')}
                  </option>
                ))}
              </select>
              <Button disabled={pending} onClick={() => void make()}>
                Make post
              </Button>
            </>
          )}
          <Button
            variant='quiet'
            disabled={pending || item.status === 'watching'}
            onClick={() => void decision('watch')}
          >
            Watch
          </Button>
          <Button variant='quiet' disabled={pending} onClick={() => void decision('dismiss')}>
            Skip
          </Button>
          {!plans.length && item.actionType !== 'skip' && (
            <p className='text-muted-foreground text-sm'>
              Connect a supported account to prepare a post.
            </p>
          )}
        </div>
      )}
    </Band>
  );
}
