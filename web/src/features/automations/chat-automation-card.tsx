'use client';

/**
 * The automation Rafii set up from a chat request (Home or a conversation): what it understood, when the first
 * draft arrives, and anything still left to the owner. The status follows the workspace (a later pause or cancel
 * shows here too). Undo cancels it; Edit opens the builder in Automations. Drafts only: nothing here publishes.
 */
import { useEffect, useRef } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { StatusChip, type StatusTone } from '@/features/queue/status-chip';
import { ApiError } from '@/lib/api/client';
import type { ChatAutomation } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { languageLabel } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { useAutomations } from './use-automations';

const STATUS: Record<string, { label: string; tone: StatusTone }> = {
  active: { label: 'On', tone: 'success' },
  draft: { label: 'Waiting for you', tone: 'warning' },
  paused: { label: 'Paused', tone: 'warning' },
  cancelled: { label: 'Cancelled', tone: 'neutral' }
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className='grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3 text-sm'>
      <dt className='text-muted-foreground'>{label}</dt>
      <dd className='min-w-0'>{children}</dd>
    </div>
  );
}

export function ChatAutomationCard({
  automation,
  reply,
  onClose,
  reveal = false,
  className
}: {
  automation: ChatAutomation;
  reply?: string;
  onClose?: () => void;
  reveal?: boolean;
  className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  // Home's composer fills the first screen: bring Rafii's answer into view once, gently unless motion is reduced.
  useEffect(() => {
    if (!reveal) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    root.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
  }, [reveal]);
  const { automations, act, busy } = useAutomations();
  const access = useWorkspaceAccess();
  const isOwner = checkAccess(access, { permission: 'owner' });
  const live = automations.find((item) => item.task.id === automation.taskId)?.task;
  const status = live?.status ?? automation.status;
  const shown = STATUS[status] ?? { label: status, tone: 'neutral' as StatusTone };
  const edit = `/app/automations?edit=${encodeURIComponent(automation.taskId)}`;

  async function run(action: 'raffi_recurrence_pause' | 'raffi_recurrence_cancel', done: string) {
    try {
      await act(
        action,
        action === 'raffi_recurrence_cancel'
          ? { taskId: automation.taskId, confirmed: true }
          : { taskId: automation.taskId }
      );
      toast.success(done);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : 'That did not go through. Try again from Automations.'
      );
    }
  }

  return (
    <div ref={root} className={cn('scroll-mt-24', className)}>
      <Surface
        material='glass'
        padding='md'
        className='flex flex-col gap-4'
        data-chat-automation={automation.taskId}
      >
        {reply && (
          <p className='text-sm leading-relaxed' aria-live='polite'>
            {reply}
          </p>
        )}
        <div className='flex items-start justify-between gap-3'>
          <div className='flex min-w-0 items-start gap-3'>
            <span
              className='rafii-glass text-foreground grid size-9 shrink-0 place-items-center rounded-xl'
              aria-hidden
            >
              <Icons.bolt className='size-4' />
            </span>
            <div className='min-w-0'>
              <p className='rafii-eyebrow'>Automation</p>
              <h3 className='line-clamp-2 text-base font-medium break-words'>{automation.name}</h3>
            </div>
          </div>
          <div className='flex shrink-0 items-center gap-1'>
            <StatusChip tone={shown.tone} size='md'>
              {shown.label}
            </StatusChip>
            {onClose && (
              <Button
                type='button'
                variant='ghost'
                size='icon'
                className='size-9'
                onClick={onClose}
                aria-label='Close'
              >
                <Icons.close className='size-4' />
              </Button>
            )}
          </div>
        </div>

        <dl className='flex flex-col gap-2'>
          <Row label='When'>{automation.scheduleText}</Row>
          {automation.firstRun && status === 'active' && (
            <Row label='First draft'>{automation.firstRun}</Row>
          )}
          <Row label='Each draft'>{automation.goal}</Row>
          <Row label='For'>
            <ul className='flex flex-wrap gap-x-3 gap-y-1'>
              {automation.destinations.map((destination) => (
                <li
                  key={`${destination.platform}:${destination.channelId ?? ''}:${destination.language}`}
                  className='flex min-w-0 flex-wrap items-center gap-x-1.5'
                >
                  <ChannelIcon platform={destination.platform} size='sm' className='rounded-md' />
                  <span className='break-words'>{destination.account ?? destination.platform}</span>
                  <span className='text-muted-foreground'>
                    · {languageLabel(destination.language)}
                  </span>
                </li>
              ))}
            </ul>
          </Row>
          {automation.contentLabel && <Row label='Kind of post'>{automation.contentLabel}</Row>}
          <Row label='Voice'>
            {automation.voiceMode === 'personalized' ? 'Your voice' : 'Neutral'}
          </Row>
          {automation.sources.length > 0 && (
            <Row label='Reference'>
              {automation.sources.map((source) => source.title).join(', ')}
            </Row>
          )}
        </dl>

        {status === 'draft' && automation.needs.length > 0 && (
          <ul className='flex flex-col gap-1.5 text-sm'>
            {automation.needs.map((need) => (
              <li key={need.code} className='flex items-start gap-2'>
                <Icons.alertCircle className='mt-0.5 size-4 shrink-0' aria-hidden />
                <span>{need.text}</span>
              </li>
            ))}
          </ul>
        )}
        {automation.notes.length > 0 && (
          <ul className='text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed'>
            {automation.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}

        <div className='flex flex-wrap items-center gap-2'>
          {status === 'draft' && isOwner && (
            <Link href={edit} className={buttonVariants({ variant: 'action', size: 'sm' })}>
              Review and turn on
            </Link>
          )}
          {status === 'active' && isOwner && (
            <Button
              type='button'
              variant='quiet'
              size='sm'
              disabled={busy}
              onClick={() => run('raffi_recurrence_pause', 'Automation paused.')}
            >
              Pause
            </Button>
          )}
          {status !== 'cancelled' && (
            <Link href={edit} className={buttonVariants({ variant: 'quiet', size: 'sm' })}>
              Edit
            </Link>
          )}
          {status !== 'cancelled' && isOwner && (
            <Button
              type='button'
              variant='ghost'
              size='sm'
              disabled={busy}
              onClick={() =>
                run(
                  'raffi_recurrence_cancel',
                  'Automation cancelled. Nothing more will be drafted.'
                )
              }
            >
              Undo
            </Button>
          )}
          <Link
            href='/app/automations'
            className='text-muted-foreground hover:text-foreground rafii-focus ml-auto rounded-md text-sm underline-offset-2 hover:underline'
          >
            Open Automations
          </Link>
        </div>
        {status === 'draft' && !isOwner && (
          <p className='text-muted-foreground text-xs'>
            An owner of this workspace turns it on in Automations.
          </p>
        )}
      </Surface>
    </div>
  );
}
