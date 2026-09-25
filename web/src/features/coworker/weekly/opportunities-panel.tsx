'use client';

import { useId, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Band, FIELD_CLASS, Panel } from '@/features/workspace/rafii-parts';
import { errorMessage } from '@/lib/coworker/api';
import { useDecideOpportunity, useListening, useSaveWatchlist } from '@/lib/coworker/hooks';
import type { Opportunity } from '@/lib/coworker/types';
import { cn } from '@/lib/utils';
import { humanize } from '../present';
import { QueryProblem, ToneChip } from '../parts';

function freshness(item: Opportunity, now: number): string {
  const created = item.createdAt ?? null;
  const days = typeof item.ageDays === 'number' ? item.ageDays : created ? Math.max(0, Math.floor((now - created) / 86400)) : null;
  const age = days === null ? 'Age unknown' : days === 0 ? 'Found today' : days === 1 ? 'Found yesterday' : `Found ${days} days ago`;
  const left = Math.ceil((item.expiresAt - now) / 86400);
  return `${age} · ${left > 0 ? `relevant for ${left} more day${left === 1 ? '' : 's'}` : 'expired'}`;
}

function safeExternal(url: string | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : null;
  } catch {
    return null;
  }
}

/**
 * Social listening → action (coworker spec §12): each opportunity says why it matters, where it came from, how
 * fresh it is and how sure Rafii is. Acting on one only records the decision; drafting starts in Ideas.
 */
export function OpportunitiesPanel({ canEdit }: { canEdit: boolean }) {
  const listening = useListening();
  const decide = useDecideOpportunity();
  const follow = useSaveWatchlist();
  const [query, setQuery] = useState('');
  const [goal, setGoal] = useState('');
  const [acted, setActed] = useState<string | null>(null);
  const uid = useId();

  if (listening.isPending) return <StateMessage kind='loading' title='Loading opportunities…' />;
  if (listening.isError) return <QueryProblem error={listening.error} onRetry={() => void listening.refetch()} what='Listening' />;
  const data = listening.data;
  const now = data.now || Date.now() / 1000;
  const open = data.opportunities.filter((o) => o.status === 'open');
  const decided = data.opportunities.filter((o) => o.status !== 'open');

  async function onDecide(item: Opportunity, decision: 'act' | 'dismiss') {
    try {
      const result = await decide.mutateAsync({ id: item.id, decision });
      if (!result.verified) return toast.warning('Rafii could not confirm that decision. Refresh to see its state.');
      if (decision === 'act') setActed(item.id);
      toast.success(decision === 'act' ? 'Marked to act on. Start the post in Ideas.' : 'Dismissed.');
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  async function onFollow(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length < 3) return toast.error('Say what to watch: a topic, product or question.');
    try {
      const result = await follow.mutateAsync({ query: query.trim(), goal: goal.trim() });
      if (!result.verified) return toast.warning('Rafii could not confirm the topic was saved.');
      setQuery('');
      setGoal('');
      toast.success('Following. Rafii checks it about once a day.');
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <div className='flex flex-col gap-4'>
      <Panel title='Opportunities' titleId='opportunities-heading' description={data.coverage}>
        {open.length === 0 ? (
          <StateMessage kind='empty' layout='inline' title='No open opportunities.' description={data.watchlists.length ? 'Rafii will list fresh, relevant items from the topics you follow.' : 'Follow a topic below to start.'} />
        ) : (
          <ul className='flex flex-col gap-2' aria-labelledby='opportunities-heading'>
            {open.map((item) => {
              const source = safeExternal(item.url ?? item.evidence[0]?.url);
              return (
                <Band as='li' key={item.id} className='gap-2'>
                  <div className='flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between'>
                    <p className='text-foreground text-sm font-medium'>{item.title}</p>
                    <ToneChip tone={item.confidence === 'high' ? 'success' : 'neutral'} icon='sparkles' className='self-start'>
                      {humanize(item.confidence)} confidence
                    </ToneChip>
                  </div>
                  <p className='text-muted-foreground text-sm'>
                    <span className='text-foreground'>Why: </span>
                    {item.why}
                  </p>
                  {item.evidence[0]?.snippet && <blockquote className='text-muted-foreground border-foreground/20 border-l-2 pl-3 text-sm'>{item.evidence[0].snippet}</blockquote>}
                  <p className='text-muted-foreground text-xs'>
                    {freshness(item, now)}
                    {source && (
                      <>
                        {' · '}
                        <a href={source} target='_blank' rel='noopener noreferrer' className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
                          Source<span className='sr-only'> (opens in a new tab)</span>
                        </a>
                      </>
                    )}
                  </p>
                  <p className='text-muted-foreground text-xs'>Suggested: {item.proposedAction}</p>
                  {canEdit && (
                    <div className='flex flex-wrap gap-2 pt-1'>
                      <Button variant='action' size='control' disabled={decide.isPending} onClick={() => void onDecide(item, 'act')}>
                        Act on it
                      </Button>
                      <Button variant='quiet' size='control' disabled={decide.isPending} onClick={() => void onDecide(item, 'dismiss')}>
                        Dismiss
                      </Button>
                    </div>
                  )}
                </Band>
              );
            })}
          </ul>
        )}
        {acted && (
          <p role='status' className='text-foreground text-sm'>
            Marked to act on.{' '}
            <Link href='/app/ideas?new=1' className='rafii-focus rounded-sm underline underline-offset-4'>
              Start a post in Ideas
            </Link>
          </p>
        )}
        {decided.length > 0 && <p className='text-muted-foreground text-xs'>{decided.length} decided earlier (acted on or dismissed).</p>}
      </Panel>

      {canEdit && (
        <Panel title='Follow a topic' titleId='follow-heading' description='Public web results only, with the owner’s research consent. Nothing is posted or replied to.'>
          <form onSubmit={(event) => void onFollow(event)} className='grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end'>
            <div className='flex flex-col gap-2 text-sm'>
              <label htmlFor={`${uid}-topic`} className='text-foreground font-medium'>
                Topic
              </label>
              <Input id={`${uid}-topic`} value={query} maxLength={200} onChange={(e) => setQuery(e.target.value)} className={FIELD_CLASS} placeholder='New bakeries in our neighbourhood' />
            </div>
            <div className='flex flex-col gap-2 text-sm'>
              <label htmlFor={`${uid}-goal`} className='text-foreground font-medium'>
                Why it matters (optional)
              </label>
              <Input id={`${uid}-goal`} value={goal} maxLength={200} onChange={(e) => setGoal(e.target.value)} className={FIELD_CLASS} placeholder='Find partners for the autumn launch' />
            </div>
            <Button type='submit' variant='glass' size='control' disabled={follow.isPending} className={cn('w-fit')}>
              Follow
            </Button>
          </form>
          {data.watchlists.length > 0 && (
            <ul className='flex flex-wrap gap-2' aria-label='Topics you follow'>
              {data.watchlists.map((wl) => (
                <li key={wl.id} className='rafii-quiet text-foreground inline-flex min-h-8 items-center rounded-full px-3 text-xs'>
                  {wl.query}
                  {!wl.active && <span className='text-muted-foreground'> · paused</span>}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}
      <Link href='/app/inbox' className={cn(buttonVariants({ variant: 'quiet', size: 'control' }), 'w-fit')}>
        Replies and mentions are in Inbox
      </Link>
    </div>
  );
}

