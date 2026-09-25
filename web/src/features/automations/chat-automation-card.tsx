'use client';

/**
 * The automation Rafii set up from a chat request (Home or a conversation): what it understood, when the first
 * draft arrives, and anything still left to the owner. The status follows the workspace (a later pause or cancel
 * shows here too). Undo cancels it; Edit opens the builder in Automations. Nothing on this card publishes.
 *
 * A staged automation (orchestration §7) also shows its plan in plain words (draft, review, publish), how its posts
 * go out (automatically, after your approval, or drafts only), which platforms can publish and why not, and any
 * question Rafii still needs answered. A quick reply is sent through `onQuickReply` as the person's next message in
 * the same conversation, exactly as if they had typed it; without `onQuickReply` (an older message) no buttons show.
 * Cards from before staged automations carry none of these fields and render as they always did.
 */
import { useEffect, useId, useRef, useState } from 'react';
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
import { label, tone } from '@/lib/automation-lifecycle';
import { languageLabel } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { useAutomations } from './use-automations';
import { policyText } from './workflow';

const STATUS: Record<string, { label: string; tone: StatusTone }> = {
  active: { label: 'On', tone: 'success' },
  draft: { label: 'Waiting for you', tone: 'warning' },
  paused: { label: 'Paused', tone: 'warning' },
  cancelled: { label: 'Cancelled', tone: 'neutral' }
};

/** The question behind `pending.question`, in the person's words. */
const QUESTIONS: Record<string, string> = {
  policy: 'How should these posts go out?',
  review_time: 'When should the drafts be ready for your review?'
};

const STEP_WORDS: Record<string, string> = { generate: 'Draft', review: 'Review', publish: 'Publish' };

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
  className,
  onQuickReply
}: {
  automation: ChatAutomation;
  reply?: string;
  onClose?: () => void;
  reveal?: boolean;
  className?: string;
  /** Sends a quick reply as the next message of the same conversation. Omit it on older messages. */
  onQuickReply?: (text: string) => void | Promise<void>;
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
  const pausedUntil = status === 'paused' && live?.pausedUntil ? new Date(live.pausedUntil * 1000) : null;
  const shown = pausedUntil
    ? { label: `Paused until ${pausedUntil.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}`, tone: 'warning' as StatusTone }
    : (STATUS[status] ?? { label: status, tone: 'neutral' as StatusTone });
  const edit = `/app/automations?edit=${encodeURIComponent(automation.taskId)}`;
  const questionId = useId();
  const [replying, setReplying] = useState<string | null>(null);

  // Staged automations (orchestration §7); older cards have none of these fields.
  const policy = automation.policy !== undefined ? automation.policy : automation.workflow ? automation.workflow.policy : undefined;
  const staged = policy !== undefined || Boolean(automation.plan?.length || automation.platforms?.length);
  const publishing = staged ? policyText(policy) : null;
  const plan = (automation.plan ?? []).filter((step) => step.text || step.when);
  const platforms = policy === 'drafts' ? [] : (automation.platforms ?? []);
  // A policy question already answered (here or elsewhere) no longer asks.
  const answered = automation.pending?.question === 'policy' && Boolean(live?.workflow?.policy);
  const question = automation.pending && !answered ? (QUESTIONS[automation.pending.question] ?? null) : null;
  const replies = answered ? [] : (automation.quickReplies ?? []).filter((text) => text.trim());
  const canReply = Boolean(onQuickReply) && status !== 'cancelled';

  async function quickReply(text: string) {
    if (!onQuickReply || replying) return;
    setReplying(text);
    try {
      await onQuickReply(text);
    } finally {
      setReplying(null);
    }
  }

  async function run(action: 'raffi_recurrence_pause' | 'raffi_recurrence_cancel', done: string | null) {
    try {
      await act(
        action,
        action === 'raffi_recurrence_cancel'
          ? { taskId: automation.taskId, confirmed: true }
          : { taskId: automation.taskId }
      );
      if (done) toast.success(done);
    } catch (error) {
      toast.error(
        error instanceof ApiError
          ? error.message
          : 'Couldn’t update this automation. Try again from Automations.'
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
          {publishing && (
            <Row label='Publishing'>
              <span className='font-medium'>{publishing.label}</span>
              <span className='text-muted-foreground block text-xs leading-relaxed'>
                {publishing.detail}
              </span>
            </Row>
          )}
          {plan.length > 0 && (
            <Row label='Plan'>
              <ol className='flex flex-col gap-1'>
                {plan.map((step, index) => (
                  <li key={`${step.step}:${index}`} className='min-w-0 break-words'>
                    <span className='text-muted-foreground'>
                      {STEP_WORDS[step.step] ?? 'Then'}
                      {step.when ? ` · ${step.when}` : ''}
                    </span>
                    {step.text && <span className='block'>{step.text}</span>}
                  </li>
                ))}
              </ol>
            </Row>
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
          {platforms.length > 0 && (
            <Row label='Publishes to'>
              <ul className='flex flex-col gap-1'>
                {platforms.map((item) => (
                  <li
                    key={`${item.platform}:${item.account ?? ''}`}
                    className='flex min-w-0 items-start gap-1.5'
                  >
                    <ChannelIcon platform={item.platform} size='sm' className='mt-0.5 rounded-md' />
                    <span className='min-w-0 break-words'>
                      {item.platform}
                      {item.account ? ` (${item.account})` : ''}
                      <span className='text-muted-foreground'>
                        {item.canPublish
                          ? ' — can publish'
                          : ` — drafts only${item.reason ? `: ${item.reason}` : ''}`}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </Row>
          )}
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
        {automation.explain?.lines && automation.explain.lines.length > 0 && (
          <ul className='flex list-disc flex-col gap-1 pl-5 text-sm'>
            {automation.explain.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        {automation.runs && automation.runs.length > 0 && (
          <div className='flex flex-wrap items-center gap-1.5 text-sm'>
            <span className='text-muted-foreground'>Recent runs</span>
            {automation.runs.slice(0, 3).map((item) => (
              <StatusChip key={item.id} tone={item.attention ? 'warning' : tone(item.status)}>
                {item.label ?? label(item.status)}
              </StatusChip>
            ))}
          </div>
        )}
        {automation.notes.length > 0 && (
          <ul className='text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed'>
            {automation.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}

        {canReply && (question || replies.length > 0) && (
          <div
            role='group'
            aria-labelledby={question ? questionId : undefined}
            aria-label={question ? undefined : 'Quick replies'}
            className='flex flex-col gap-2'
          >
            {question && (
              <p id={questionId} className='text-sm font-medium'>
                {question}
              </p>
            )}
            {replies.length > 0 && (
              <div className='flex flex-wrap gap-2'>
                {replies.map((text) => (
                  <Button
                    key={text}
                    type='button'
                    variant='glass'
                    size='sm'
                    className='min-h-11 max-w-full whitespace-normal text-left'
                    disabled={replying !== null}
                    aria-label={`Reply: ${text}`}
                    onClick={() => void quickReply(text)}
                  >
                    {replying === text && <Icons.spinner className='animate-spin motion-reduce:animate-none' />}
                    {text}
                  </Button>
                ))}
              </div>
            )}
          </div>
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
              // The status chip shows the pause; no toast.
              onClick={() => run('raffi_recurrence_pause', null)}
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
                run('raffi_recurrence_cancel', 'Automation cancelled')
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
            An owner turns it on in Automations.
          </p>
        )}
      </Surface>
    </div>
  );
}
