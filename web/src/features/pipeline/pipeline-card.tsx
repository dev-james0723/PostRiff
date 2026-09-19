'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion } from 'motion/react';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from '@/components/motion/context-menu';
import { JobCancelHold } from '@/components/jobs/job-cancel-hold';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { COLUMN_META, reviewExpired, toEpoch, type BoardCard, type CardChip, type ChipTone, type PipelineJob } from './board';
import { isCancellable, jobBadge, stateWords, type JobBadge } from './job-state';

export interface CardPermissions {
  canEdit: boolean;
  canApprove: boolean;
  /** A sample workspace: the API refuses every change, so no control that changes anything is offered. */
  readOnly: boolean;
}

export interface CardActions {
  open: (card: BoardCard) => void;
  edit: (variantId: string) => void;
  schedule: (variantId: string) => void;
  setAside: (variantId: string) => void;
  cancel: (job: PipelineJob) => void;
}

export type ScheduleGate = { allowed: true } | { allowed: false; reason: string; title: string };

/**
 * Whether this person can take this draft through Schedule…. The dialog may send `accept_update` and
 * `p2_variant_review` (edit class) before `p2_review` (approve class, `permissions.py`), so a draft that needs
 * either first step asks for both permissions; otherwise approve alone is enough. Checked up front so nobody is
 * left with half a change after a 403.
 */
export function scheduleGate(card: BoardCard, permissions: CardPermissions): ScheduleGate {
  const variant = card.variant;
  const needsEditStep = Boolean(variant?.needsReview) || Boolean(variant?.unknowns.length) || Boolean(card.draft?.voiceStale || card.draft?.updateRequired);
  if (!permissions.canApprove) {
    return { allowed: false, reason: 'Needs an approver to schedule', title: 'Scheduling prepares an exact review, which needs the approve permission.' };
  }
  if (needsEditStep && !permissions.canEdit) {
    return {
      allowed: false,
      reason: 'Needs an editor to prepare',
      title: (card.draft?.voiceStale || card.draft?.updateRequired) ? 'A current voice revision must be prepared first, which needs the edit permission.' : 'The unknown details must be confirmed first, which needs the edit permission.'
    };
  }
  return { allowed: true };
}

/** Set aside is an edit; the API refuses it (409) while a job for the draft is not cancelled or failed. */
export const canSetAside = (card: BoardCard, permissions: CardPermissions) =>
  !permissions.readOnly && permissions.canEdit && card.kind === 'draft' && Boolean(card.draft) && !card.draft?.setAside && !card.draft?.setAsideBlocked;

export const TONE_STATUS: Record<ChipTone, AnimatedBadgeStatus> = { neutral: 'neutral', info: 'info', warning: 'warning', danger: 'danger', success: 'success' };

const TONE_TEXT: Record<ChipTone, string> = {
  neutral: 'text-muted-foreground',
  info: 'text-primary',
  warning: 'text-amber-600 dark:text-amber-400',
  danger: 'text-destructive',
  success: 'text-emerald-600 dark:text-emerald-400'
};

/** What a revision's origin means, in plain words (`domain.py` and `ideas.py` origins). */
export const REVISION_ORIGIN: Record<string, string> = {
  'ideas-candidate': 'Written',
  fixture: 'Written',
  'author-edit': 'Edited',
  'chosen-opening': 'Opening chosen',
  'accepted-fixture-replacement': 'Update accepted'
};

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success('Copied to clipboard.');
  } catch {
    toast.error('Could not copy the text.');
  }
}

/** The card's one status badge: the job's state, the review's state, or the draft's first situation. */
export function cardBadge(card: BoardCard, now: number): JobBadge | null {
  if (card.job) return jobBadge(card.job);
  if (card.review) {
    return reviewExpired(card.review, now)
      ? { status: 'danger', label: 'expired', pulse: false, title: 'The approval deadline passed, so it can no longer be approved. Schedule… the draft again.' }
      : { status: 'warning', label: 'needs approval', pulse: false, title: 'Approve this exact review in the Queue.' };
  }
  const first = card.chips[0];
  if (card.kind === 'draft' && first) return { status: TONE_STATUS[first.tone], label: first.label, pulse: false, title: first.title };
  return null;
}

/** Chips that are not already the badge. */
function extraChips(card: BoardCard): CardChip[] {
  if (card.kind === 'draft') return card.chips.slice(1);
  if (card.kind === 'review') return [];
  return card.chips;
}

/** One short line of when: only from fields the snapshot actually carries. */
export function cardWhen(card: BoardCard): string | null {
  if (card.kind === 'source') {
    const at = toEpoch(card.source?.createdAt);
    return at ? `added ${relativeTime(at)}` : null;
  }
  if (card.kind === 'draft') {
    const last = card.variant?.revisions?.at(-1);
    const at = toEpoch(last?.at);
    if (!at) return null;
    return `${(REVISION_ORIGIN[last?.origin ?? ''] ?? 'Written').toLowerCase()} ${relativeTime(at)}`;
  }
  if (card.kind === 'review') {
    const at = toEpoch(card.review?.manifest.timing.utc);
    return at ? `for ${formatDateTime(at)}` : null;
  }
  const job = card.job;
  if (!job) return null;
  if (card.jobGroup === 'waiting') {
    const at = toEpoch(job.manifest.timing.utc);
    return at ? `scheduled for ${formatDateTime(at)}` : null;
  }
  if (card.jobGroup === 'verified' && job.verification?.at) return `verified ${relativeTime(job.verification.at)}`;
  const last = job.events.at(-1);
  return last ? `${stateWords(last.state)} ${relativeTime(last.at)}` : null;
}

const LINK_CLASS = 'text-foreground decoration-muted-foreground/50 hover:decoration-foreground rounded-sm font-medium underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring/50';

function TextButton({ children, onClick, className }: { children: ReactNode; onClick: () => void; className?: string }) {
  return (
    <button type='button' onClick={onClick} className={cn(LINK_CLASS, className)}>
      {children}
    </button>
  );
}

function CardActionsRow({
  card,
  permissions,
  actions,
  cancelPending,
  holdEpoch
}: {
  card: BoardCard;
  permissions: CardPermissions;
  actions: CardActions;
  cancelPending: boolean;
  holdEpoch: number;
}) {
  const { canEdit, canApprove, readOnly } = permissions;
  const items: ReactNode[] = [];

  if (card.kind === 'draft' && card.draft && card.variant && !readOnly) {
    const variantId = card.variant.id;
    if (card.draft.setAside) {
      if (canEdit) items.push(<TextButton key='restore' onClick={() => actions.edit(variantId)}>Edit to restore</TextButton>);
    } else {
      if (canEdit) items.push(<TextButton key='edit' onClick={() => actions.edit(variantId)}>Edit</TextButton>);
      if (card.draft.schedulable) {
        const gate = scheduleGate(card, permissions);
        items.push(
          gate.allowed ? (
            <TextButton key='schedule' onClick={() => actions.schedule(variantId)}>
              Schedule…
            </TextButton>
          ) : (
            <span key='schedule' className='text-muted-foreground' title={gate.title}>
              {gate.reason}
            </span>
          )
        );
      } else if ((card.draft.retracted || card.draft.voiceStale) && canEdit) {
        // Creating starts in the Home composer.
        items.push(
          <Link key='again' href='/app' className={LINK_CLASS}>
            Draft again
          </Link>
        );
      }
      if (canSetAside(card, permissions)) items.push(<TextButton key='aside' onClick={() => actions.setAside(variantId)} className='text-muted-foreground'>Set aside…</TextButton>);
    }
  }

  // A sample workspace refuses approvals too, so it offers no way there. An expired review is refused as well
  // (`store.py` approve checks `expiresAt`); its draft is back in Drafts for a new Schedule….
  if (card.kind === 'review' && !readOnly) {
    items.push(
      card.footer ? (
        <span key='queue' className='text-muted-foreground' title='The approval deadline passed. Schedule… the draft again to prepare a new review.'>
          Can no longer be approved
        </span>
      ) : canApprove ? (
        <Link key='queue' href='/app/queue' className={LINK_CLASS}>
          Approve in the Queue
        </Link>
      ) : (
        <span key='queue' className='text-muted-foreground'>
          An approver must approve
        </span>
      )
    );
  }

  if (card.kind === 'job' && card.job && !readOnly && canApprove) {
    const job = card.job;
    if (isCancellable(job)) {
      items.push(
        <JobCancelHold key={`cancel-${job.id}`} job={job} allowed={canApprove} pending={cancelPending} epoch={holdEpoch} onCancel={actions.cancel} />
      );
      if (card.jobGroup === 'held') items.push(<span key='then' className='text-muted-foreground'>then schedule the draft again</span>);
    }
  }

  if (items.length === 0) return null;
  return (
    // The row is outside the card's long-press: holding "Hold to cancel" on a touch screen must not open the menu.
    <div
      className='relative z-10 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs'
      onPointerDown={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.stopPropagation()}
    >
      {items}
    </div>
  );
}

export function PipelineCard({
  card,
  now,
  permissions,
  actions,
  cancelPending,
  holdEpoch,
  lift,
  menu
}: {
  card: BoardCard;
  now: number;
  permissions: CardPermissions;
  actions: CardActions;
  cancelPending: boolean;
  holdEpoch: number;
  /** Hover lift, only on devices with a real hover and without reduced motion. */
  lift: boolean;
  /**
   * The right-click menu, only where there is a real pointer. On touch a long press would fight the page's scroll,
   * and every action is already in the card's row and its details.
   */
  menu: boolean;
}) {
  const router = useRouter();
  const badge = cardBadge(card, now);
  const chips = extraChips(card);
  const when = cardWhen(card);
  const { canEdit, readOnly } = permissions;
  const variant = card.variant;
  const column = COLUMN_META[card.column];
  const gate = card.kind === 'draft' ? scheduleGate(card, permissions) : null;
  const showsAccount = card.kind === 'review' || card.kind === 'job';
  const meta = [showsAccount ? card.platform : null, card.language, when].filter(Boolean).join(' · ');

  return (
    <ContextMenu>
      <ContextMenuTrigger disabled={!menu}>
        <motion.article
          whileHover={lift ? { y: -2 } : undefined}
          transition={{ duration: 0.18, ease: EASE_OUT }}
          className='bg-card relative flex min-w-0 flex-col gap-1 rounded-lg border p-3 text-sm shadow-xs'
          data-testid='pipeline-card'
          data-card-kind={card.kind}
          data-card-key={card.key}
        >
          {/* In a narrow column the badge wraps under the title instead of cutting either one short. */}
          <div className='flex min-w-0 flex-wrap items-center justify-between gap-x-2 gap-y-1'>
            <span className='flex min-w-0 grow basis-28 items-center gap-1.5 font-medium'>
              {card.platform ? (
                <ChannelIcon platform={card.platform} name={card.platform} size='xs' />
              ) : (
                <Icons.page className='text-muted-foreground size-4 shrink-0' aria-hidden />
              )}
              {/* The title is the card's one open control; its hit area covers the card behind the action row. */}
              <button
                type='button'
                onClick={() => actions.open(card)}
                data-card-open=''
                className='min-w-0 truncate rounded-sm text-left outline-none after:absolute after:inset-0 after:rounded-lg focus-visible:after:ring-2 focus-visible:after:ring-ring/50'
                aria-label={`Open details: ${card.title}`}
              >
                {card.title}
              </button>
            </span>
            {badge && (
              <AnimatedBadge size='sm' status={badge.status} pulse={badge.pulse} title={badge.title} contentKey={badge.label} className='max-w-full'>
                {badge.label}
              </AnimatedBadge>
            )}
          </div>
          {meta && <p className='text-muted-foreground truncate text-[11px]'>{meta}</p>}
          <p className='text-muted-foreground line-clamp-3 text-xs break-words whitespace-pre-wrap'>{card.body}</p>
          {chips.length > 0 && (
            <ul className='relative flex flex-wrap gap-1' aria-label='Situation'>
              {chips.map((chip) => (
                <li key={chip.label} title={chip.title} className={cn('bg-muted/60 rounded-full px-1.5 py-0.5 text-[11px] leading-none font-medium', TONE_TEXT[chip.tone])}>
                  {chip.label}
                </li>
              ))}
            </ul>
          )}
          {card.tag && <p className='relative line-clamp-2 text-xs text-amber-600 dark:text-amber-400'>{card.tag}</p>}
          <CardActionsRow card={card} permissions={permissions} actions={actions} cancelPending={cancelPending} holdEpoch={holdEpoch} />
        </motion.article>
      </ContextMenuTrigger>
      <ContextMenuContent ariaLabel={`Actions for ${card.title}`}>
        <ContextMenuItem onSelect={() => actions.open(card)}>
          <Icons.listDetails className='text-muted-foreground size-4' aria-hidden />
          Open details
        </ContextMenuItem>
        {card.kind === 'draft' && card.draft && variant && !readOnly && canEdit && (
          <ContextMenuItem onSelect={() => actions.edit(variant.id)}>
            <Icons.edit className='text-muted-foreground size-4' aria-hidden />
            {card.draft.setAside ? 'Edit to restore' : 'Edit draft'}
          </ContextMenuItem>
        )}
        {card.kind === 'draft' && card.draft?.schedulable && variant && !readOnly && gate?.allowed && (
          <ContextMenuItem onSelect={() => actions.schedule(variant.id)}>
            <Icons.calendarEvent className='text-muted-foreground size-4' aria-hidden />
            Schedule…
          </ContextMenuItem>
        )}
        {variant && canSetAside(card, permissions) && (
          <ContextMenuItem onSelect={() => actions.setAside(variant.id)}>
            <Icons.eyeOff className='text-muted-foreground size-4' aria-hidden />
            Set aside…
          </ContextMenuItem>
        )}
        <ContextMenuItem onSelect={() => void copyText(card.body)}>
          <Icons.copy className='text-muted-foreground size-4' aria-hidden />
          Copy text
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={() => router.push(column.href)}>
          <Icons.arrowRight className='text-muted-foreground size-4' aria-hidden />
          {column.cta}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
