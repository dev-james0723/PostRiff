'use client';

import Link from 'next/link';
import { TodoList, type TodoItem } from '@/components/agents/todo-list';
import { DigitSwap } from '@/components/motion/digit-swap';
import { buttonVariants } from '@/components/ui/button';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
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
 * state (nothing is ticked by a click) and the panel disappears once all four are done.
 */
export function GettingStarted() {
  const snapshot = useSnapshot();
  const channels = useChannels();
  // An unread workspace or channel list is not "not done yet", so the panel waits for both rather than guessing.
  if (!snapshot.data || snapshot.isError || !channels.data || channels.isError) return null;
  const state = snapshot.data.state;
  const sample = state.workspace?.sample === true;
  const steps: Step[] = [
    { id: 'voice', title: 'Set your voice', detail: 'What you are building, who it is for, and a tone.', action: 'Set up', href: '/app/workspace/brand', done: Boolean(state.speaker?.activeRevision) },
    { id: 'channel', title: 'Connect a channel', detail: 'Any account you own; each shows how it can publish.', action: 'Connect', href: '/app/channels', done: channels.data.channels.length > 0 },
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
    <Panel
      material='glass'
      data-testid='getting-started'
      data-tour='getting-started'
      title={
        <span className='flex flex-wrap items-center gap-2'>
          Get set up
          {sample && <StatusChip icon='lock'>Sample · read-only</StatusChip>}
        </span>
      }
      titleId='getting-started-heading'
      description='Four steps from a blank workspace to your first scheduled post.'
      actions={
        <span className='text-muted-foreground inline-flex items-center gap-1 text-xs tabular-nums'>
          <DigitSwap value={done} /> of {steps.length} done
        </span>
      }
    >
      {/* The panel header already names the checklist and counts it, so the list's own header stays short. */}
      <TodoList title='Steps' ariaLabel='Setup steps' items={items} defaultOpen collapseOnComplete={false} spinActive={false} className='rafii-quiet rounded-[var(--rafii-radius-card)] border-0' />
    </Panel>
  );
}
