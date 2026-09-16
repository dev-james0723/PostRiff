'use client';

import Link from 'next/link';
import { TodoList, type TodoItem } from '@/components/agents/todo-list';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useChannels, useSnapshot } from '@/lib/api/hooks';
import { cn } from '@/lib/utils';

interface Step {
  id: string;
  title: string;
  detail: string;
  action: string;
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
    { id: 'voice', title: 'Set your voice', detail: 'What you are building, who it is for, and a tone.', action: 'Set up', href: '/app/workspace/brand', done: Boolean(state.speaker?.activeRevision) },
    { id: 'channel', title: 'Connect a channel', detail: 'LinkedIn, Instagram or Threads — your account, your consent.', action: 'Connect', href: '/app/channels', done: (channels.data?.channels.length ?? 0) > 0 },
    { id: 'draft', title: 'Draft your first post', detail: 'Start from a sentence or a link in Ideas.', action: 'Draft', href: '/app/ideas', done: (state.variants ?? []).length > 0 },
    { id: 'approve', title: 'Approve and schedule it', detail: 'Pick the account and time, then approve the exact text.', action: 'Approve', href: '/app/pipeline', done: (state.phase2?.jobs.length ?? 0) > 0 }
  ];
  const done = steps.filter((s) => s.done).length;
  if (done === steps.length) return null;
  const next = steps.find((s) => !s.done);

  // Done steps are struck through by the list, so only open steps carry their one-line detail.
  const items: TodoItem[] = steps.map((step) => {
    const current = next?.id === step.id;
    return {
      id: step.id,
      status: step.done ? 'completed' : current ? 'in-progress' : 'pending',
      title: step.done ? (
        step.title
      ) : (
        <span className='block truncate'>
          {step.title}
          <span className='opacity-70'> · {step.detail}</span>
        </span>
      ),
      detail: (
        <Link
          href={step.href}
          aria-current={current ? 'step' : undefined}
          aria-label={`${step.done ? 'Open' : step.action}: ${step.title}`}
          className={cn(buttonVariants({ variant: 'link', size: 'xs' }), !current && 'text-muted-foreground hover:text-foreground')}
        >
          {step.done ? 'Open' : step.action}
        </Link>
      )
    };
  });

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
      </CardHeader>
      <CardContent>
        {/* The card header already names the checklist and counts it, so the list's own header stays short. */}
        <TodoList title='Steps' ariaLabel='Setup steps' items={items} defaultOpen collapseOnComplete={false} spinActive={false} className='rounded-xl' />
      </CardContent>
    </Card>
  );
}
