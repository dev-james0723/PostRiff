'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { useChannels, useSnapshot } from '@/lib/api/hooks';
import { cn } from '@/lib/utils';

interface Step {
  id: string;
  title: string;
  detail: string;
  href: string;
  done: boolean;
}

/**
 * First-run checklist: voice → channel → draft → first approval. Every step reads real workspace
 * state (nothing is ticked by a click) and the card disappears once all four are done.
 */
export function GettingStarted() {
  const snapshot = useSnapshot();
  const channels = useChannels();
  if (snapshot.isLoading || !snapshot.data || channels.isLoading) return null;
  const state = snapshot.data.state;
  const steps: Step[] = [
    { id: 'voice', title: 'Set your voice', detail: 'What you are building, who it is for, and a tone.', href: '/app/workspace/brand', done: Boolean(state.speaker?.activeRevision) },
    { id: 'channel', title: 'Connect a channel', detail: 'LinkedIn, Instagram or Threads — your account, your consent.', href: '/app/channels', done: (channels.data?.channels.length ?? 0) > 0 },
    { id: 'draft', title: 'Draft your first post', detail: 'Start from a sentence or a link in Ideas.', href: '/app/ideas', done: (state.variants ?? []).length > 0 },
    { id: 'approve', title: 'Approve and schedule it', detail: 'Pick the account and time, then approve the exact text.', href: '/app/pipeline', done: (state.phase2?.jobs.length ?? 0) > 0 }
  ];
  const done = steps.filter((s) => s.done).length;
  if (done === steps.length) return null;
  const next = steps.find((s) => !s.done);

  return (
    <Card data-testid='getting-started'>
      <CardHeader>
        <CardTitle className='flex items-center justify-between gap-3 text-base'>
          <span>Get set up</span>
          <span className='text-muted-foreground text-xs font-normal'>
            {done} of {steps.length} done
          </span>
        </CardTitle>
        <CardDescription>Four steps from a blank workspace to your first scheduled post.</CardDescription>
        <Progress value={(done / steps.length) * 100} aria-label={`${done} of ${steps.length} steps done`} />
      </CardHeader>
      <CardContent>
        <ol className='grid gap-2 sm:grid-cols-2 xl:grid-cols-4'>
          {steps.map((step, index) => (
            <li key={step.id}>
              <Link
                href={step.href}
                aria-current={next?.id === step.id ? 'step' : undefined}
                className={cn('hover:bg-muted/60 flex h-full items-start gap-3 rounded-lg border p-3 text-sm transition-colors', step.done && 'opacity-70', next?.id === step.id && 'border-primary')}
              >
                <span className={cn('mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border text-xs', step.done && 'border-emerald-600 bg-emerald-600 text-white')}>
                  {step.done ? <Icons.check className='size-3' /> : index + 1}
                </span>
                <span className='min-w-0'>
                  <span className={cn('block font-medium', step.done && 'line-through')}>{step.title}</span>
                  <span className='text-muted-foreground block text-xs'>{step.detail}</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
