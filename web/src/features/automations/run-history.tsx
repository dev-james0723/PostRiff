'use client';

/**
 * One run of a Raffi workflow automation (orchestration §2–§3): its lifecycle status, when it drafts, is reviewed and
 * publishes, what research found, and each destination's post with its own state, reason and time. Items waiting for
 * a decision offer Approve / Request changes / Reject to people who can approve posts; the decision itself happens in
 * `RunDecisionDialog`. Older runs (no lifecycle) keep the hub's original row.
 */
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/queue/status-chip';
import type { RecurringOccurrence, RunItem } from '@/lib/api/types';
import { attention, decisionsFor, label, status, tone } from '@/lib/automation-lifecycle';
import { languageLabel } from '@/lib/locales';
import type { RunDecision } from './run-decision';
import { runLabel } from './schedule';
import { itemName, researchOutcome, runPlan, safeUrl } from './workflow';

/** A v3 run: it carries a generation stage or per-destination items. */
export const isWorkflowRun = (run: Pick<RecurringOccurrence, 'lifecycle' | 'items'>): boolean => Boolean(run.lifecycle || run.items?.length);

/** Posts waiting for an approval before their publish time (drafts-only posts have no publish time and never wait). */
export function awaitingApproval(run: Pick<RecurringOccurrence, 'items'>): RunItem[] {
  return (run.items ?? []).filter((item) => decisionsFor(item).approve && Boolean(item.publishAt));
}

/** The run's status for the chip: lifecycle label and tone, with attention raised to a warning. */
export function runStatus(run: RecurringOccurrence): { label: string; tone: ReturnType<typeof tone>; attention: boolean } {
  const shown = status(run);
  const needs = attention(run);
  const base = tone(shown);
  return { label: label(shown), tone: needs && (base === 'info' || base === 'neutral') ? 'warning' : base, attention: needs };
}

/** What happens next for one item, in a few words; empty when the status chip already says it all. */
function itemLine(item: RunItem, policy: string | undefined, timeZone: string): string {
  const when = item.publishAt ? runLabel(item.publishAt * 1000, timeZone) : null;
  switch (item.state) {
    case 'ready_for_review':
      if (!when) return 'Draft only.';
      return policy === 'auto' ? `Held for your approval. Approve by ${when} to publish.` : `Approve by ${when} to publish.`;
    case 'needs_revision':
      return when ? `Won’t publish at ${when} unless a new version is approved.` : '';
    case 'approved':
      return when ? `Publishes ${when} after a final account check.` : '';
    case 'scheduled':
      return when ? `Publishes ${when}.` : '';
    case 'published':
      return when ? `Planned for ${when}.` : '';
    case 'rejected':
      return 'Won’t be published.';
    case 'approval_expired':
      return when ? `Not approved by ${when}, so not published.` : 'Not approved in time, so not published.';
    case 'platform_disconnected':
      return 'Reconnect the account to publish.';
    default:
      return '';
  }
}

export interface RunDetailProps {
  run: RecurringOccurrence;
  timeZone: string;
  canApprove: boolean;
  busy: boolean;
  onDecide: (run: RecurringOccurrence, item: RunItem, decision: RunDecision) => void;
  onOpenRun?: (runId: string, conversationId: string) => void;
}

export function RunDetail({ run, timeZone, canApprove, busy, onDecide, onOpenRun }: RunDetailProps) {
  const shown = runStatus(run);
  const plan = runPlan(run, timeZone);
  const research = researchOutcome(run.research);
  const items = run.items ?? [];
  const policy = run.policy;
  const quote = run.research?.quote;
  const link = research?.kind === 'chosen' ? safeUrl(research.url) : null;

  return (
    <div className='rafii-quiet flex flex-col gap-2.5 rounded-[var(--rafii-radius-control)] px-3 py-2.5 text-sm' data-automation-run={run.id}>
      <div className='flex flex-wrap items-center gap-x-3 gap-y-1'>
        <span className='min-w-[9.5rem]'>{runLabel((run.anchorAt ?? run.scheduledFor) * 1000, timeZone)}</span>
        <StatusChip tone={shown.tone}>{shown.label}</StatusChip>
        {shown.attention && <span className='text-muted-foreground text-xs'>Needs you</span>}
        {run.conversationId && onOpenRun && (
          <Button variant='quiet' size='sm' className='min-h-11 sm:ml-auto' onClick={() => onOpenRun(run.id, run.conversationId!)}>
            Open drafts
          </Button>
        )}
      </div>

      {plan.length > 0 && (
        <ol className='text-muted-foreground flex flex-wrap gap-x-3 gap-y-0.5 text-xs' aria-label='Plan for this run'>
          {plan.map((row) => (
            <li key={row.step}>
              <span className='text-foreground'>{row.label}</span> {row.when}
            </li>
          ))}
        </ol>
      )}

      {research && (
        <p className='text-muted-foreground min-w-0 text-xs break-words'>
          {research.kind === 'chosen' ? (
            <>
              Source:{' '}
              {link ? (
                <a href={link} target='_blank' rel='noopener noreferrer' className='rafii-focus text-foreground rounded-sm underline underline-offset-2'>
                  {research.title}
                </a>
              ) : (
                <span className='text-foreground'>{research.title}</span>
              )}{' '}
              ({research.host})
            </>
          ) : (
            research.text
          )}
          {quote && ` Quote by ${quote.author} (${quote.verified ? 'attribution checked' : 'attribution not verified'}).`}
        </p>
      )}
      {!research && run.lifecycle === 'skipped' && run.reason && <p className='text-muted-foreground text-xs'>{run.reason}</p>}

      {items.length > 0 && (
        <ul className='flex flex-col gap-2' aria-label='Posts in this run'>
          {items.map((item) => {
            const allowed = decisionsFor(item);
            const canApproveItem = allowed.approve && Boolean(item.publishAt);
            const showActions = canApprove && (canApproveItem || allowed.revise || allowed.reject);
            const cannotPublish = item.capability && !item.capability.publish && policy !== 'drafts';
            const name = itemName(item);
            return (
              <li key={item.key} className='border-border/60 flex flex-col gap-1.5 border-t pt-2 first:border-t-0 first:pt-0'>
                <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
                  <ChannelIcon platform={item.platform} size='sm' className='rounded-md' />
                  <span className='min-w-0 font-medium break-words'>{name}</span>
                  <span className='text-muted-foreground text-xs'>{languageLabel(item.language)}</span>
                  <StatusChip tone={tone(item.state)} className='ml-auto'>
                    {label(item.state)}
                  </StatusChip>
                </div>
                {(() => {
                  const line = [
                    itemLine(item, policy, timeZone),
                    item.reason,
                    item.state === 'failed' && !item.reason ? item.lastError : null,
                    item.approvedVia === 'owner_preauthorization' && ['approved', 'scheduled', 'publishing', 'published'].includes(item.state) ? 'Approved by the owner’s standing permission.' : null,
                    item.decision?.note ? `Note: “${item.decision.note}”` : null,
                    cannotPublish ? `Drafts only: ${item.capability!.reason || `can’t publish to ${item.platform} yet.`}` : null
                  ].filter(Boolean).join(' ');
                  return line ? <p className='text-muted-foreground text-xs leading-relaxed break-words'>{line}</p> : null;
                })()}
                {showActions && (
                  <div className='flex flex-wrap gap-2'>
                    {canApproveItem && (
                      <Button variant='action' size='sm' className='min-h-11' disabled={busy} onClick={() => onDecide(run, item, 'approve')} aria-label={`Approve the ${name} post`}>
                        <Icons.check />
                        Approve
                      </Button>
                    )}
                    {allowed.revise && (
                      <Button variant='glass' size='sm' className='min-h-11' disabled={busy} onClick={() => onDecide(run, item, 'revise')} aria-label={`Request changes to the ${name} post`}>
                        <Icons.edit />
                        Request changes
                      </Button>
                    )}
                    {allowed.reject && (
                      <Button variant='quiet' size='sm' className='min-h-11' disabled={busy} onClick={() => onDecide(run, item, 'reject')} aria-label={`Reject the ${name} post`}>
                        Reject
                      </Button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
