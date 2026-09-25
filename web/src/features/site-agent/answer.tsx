'use client';

/**
 * Renders one Rafii answer (`body.siteAgent`) from its typed blocks (site agent spec §11.3), in the side panel and
 * in the full conversation. Nothing here invents state: a link is shown only when the route manifest allows it,
 * a citation only when the server returned one, "applied" only after the server said so.
 */
import Link from 'next/link';
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { ReviewApproveButton } from '@/components/jobs/review-approve-button';
import { useRun } from '@/features/agent/use-run';
import { keys, useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { Snapshot } from '@/lib/api/types';
import manifestJson from '@/lib/site-agent/route-manifest.json';
import { safeHref, type RouteManifest } from '@/lib/site-agent/routes';
import type { SiteAgentBlock, SiteAgentBody, SiteAgentProposalView } from '@/lib/site-agent/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { AUTOMATION_CHANGED } from './store';

const MANIFEST = manifestJson as RouteManifest;

/** Plain text with **bold** and "- " / "1. " lists; never HTML. */
export function RichText({ text, className }: { text: string; className?: string }) {
  const paragraphs = text.split(/\n{2,}/);
  return (
    <div className={cn('flex flex-col gap-2 text-sm leading-relaxed', className)}>
      {paragraphs.map((paragraph, index) => {
        const lines = paragraph.split('\n');
        const bullets = lines.every((line) => /^\s*(?:[-•]|\d+\.)\s+/.test(line));
        if (bullets && lines.length > 0) {
          const ordered = /^\s*\d+\./.test(lines[0]);
          const List = ordered ? 'ol' : 'ul';
          return (
            <List key={index} className={cn('flex flex-col gap-1 pl-5', ordered ? 'list-decimal' : 'list-disc')}>
              {lines.map((line, i) => (
                <li key={i}>{inline(line.replace(/^\s*(?:[-•]|\d+\.)\s+/, ''))}</li>
              ))}
            </List>
          );
        }
        return (
          <p key={index} className='break-words whitespace-pre-line'>
            {inline(paragraph)}
          </p>
        );
      })}
    </div>
  );
}

function inline(text: string): ReactNode {
  // **bold** and in-app links [label](/app/…) (help articles); a link the route manifest does not allow stays plain text.
  return text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\(\/[^)\s]+\))/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={i}>{part.slice(2, -2)}</strong>;
    const link = /^\[([^\]]+)\]\((\/[^)\s]+)\)$/.exec(part);
    if (link) return <SafeLink key={i} href={link[2]} className='font-medium underline underline-offset-2'>{link[1]}</SafeLink>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

function SafeLink({ href, children, className, onNavigate }: { href: string; children: ReactNode; className?: string; onNavigate?: () => void }) {
  const allowed = safeHref(MANIFEST, href);
  if (!allowed) return <span className={className}>{children}</span>;
  return (
    <Link href={allowed} className={cn('rafii-focus', className)} onClick={onNavigate}>
      {children}
    </Link>
  );
}

export interface AnswerActions {
  /** Send a follow-up or an answer to Rafii's question as the next message. */
  onAsk?: (text: string) => void;
  /** Called after a link inside the answer is followed (the phone sheet closes). */
  onNavigate?: () => void;
  messageId?: string;
  conversationId?: string | null;
  /** Latest answer: its question options and follow-ups are live; older ones are history. */
  latest?: boolean;
}

export function SiteAgentAnswer({ body, actions }: { body: SiteAgentBody; actions: AnswerActions }) {
  const blocks = body.blocks ?? [];
  return (
    <div className='flex min-w-0 flex-col gap-3'>
      {body.compound?.pending && body.compound.runId && actions.messageId && actions.conversationId && (
        <CompoundWatcher runId={body.compound.runId} messageId={actions.messageId} conversationId={actions.conversationId} />
      )}
      {blocks.map((block, index) => (
        <AnswerBlock key={`${block.type}-${index}`} block={block} actions={actions} />
      ))}
      {body.status === 'completed' && <AnswerMeta body={body} actions={actions} />}
    </div>
  );
}

function AnswerBlock({ block, actions }: { block: SiteAgentBlock; actions: AnswerActions }) {
  switch (block.type) {
    case 'text':
      return <RichText text={block.text} />;
    case 'warning':
      return (
        <p role='note' className='rafii-quiet text-muted-foreground flex items-start gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-xs leading-relaxed'>
          <Icons.info className='mt-0.5 size-3.5 shrink-0' />
          <span>{block.message}</span>
        </p>
      );
    case 'error':
      return (
        <p role='alert' className='text-destructive flex items-start gap-2 text-sm'>
          <Icons.warning className='mt-0.5 size-4 shrink-0' />
          <span>{block.message}</span>
        </p>
      );
    case 'navigation_card':
      return (
        <SafeLink
          href={block.href}
          onNavigate={actions.onNavigate}
          className='rafii-glass hover:rafii-glass-selected flex min-h-11 items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm font-medium'
        >
          <span className='min-w-0 truncate'>{block.label}</span>
          <Icons.arrowRight className='size-4 shrink-0' aria-hidden />
        </SafeLink>
      );
    case 'citation_list':
      return (
        <nav aria-label='Sources' className='flex flex-wrap items-center gap-1.5'>
          <span className='text-muted-foreground text-[11px]'>Based on</span>
          {block.citations.map((citation) => (
            <SafeLink
              key={citation.id}
              href={citation.href}
              onNavigate={actions.onNavigate}
              className='rafii-quiet text-muted-foreground hover:text-foreground inline-flex min-h-7 max-w-full items-center gap-1 rounded-full px-2.5 text-[11px]'
            >
              <Icons.page className='size-3 shrink-0' aria-hidden />
              <span className='truncate'>
                Rafii Help · {citation.title}
                {citation.section && citation.section !== 'Overview' ? ` · ${citation.section}` : ''}
              </span>
            </SafeLink>
          ))}
        </nav>
      );
    case 'diagnostic_card':
      return (
        <Surface material='glass' padding='sm' className='flex flex-col gap-2' role='group' aria-label={`${block.title}: ${block.status}`}>
          <div className='flex items-start justify-between gap-2'>
            <span className='min-w-0 text-sm font-medium break-words'>{block.title}</span>
            <span className='rafii-quiet shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium'>{block.status}</span>
          </div>
          {block.cause && <p className='text-sm leading-relaxed'>{block.cause}</p>}
          {block.evidence.length > 0 && (
            <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
              {block.evidence.map((line) => (
                <li key={line} className='break-words'>
                  {line}
                </li>
              ))}
            </ul>
          )}
          {block.steps.length > 0 && (
            <ol className='flex list-decimal flex-col gap-1 pl-5 text-sm'>
              {block.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}
          {block.links.length > 0 && (
            <div className='flex flex-wrap gap-2'>
              {block.links.map((link) => (
                <SafeLink key={link.href} href={link.href} onNavigate={actions.onNavigate} className='text-xs font-medium underline underline-offset-2'>
                  {link.label}
                </SafeLink>
              ))}
            </div>
          )}
        </Surface>
      );
    case 'question_form':
      return (
        <div className='flex flex-col gap-2'>
          <RichText text={block.prompt} />
          {block.options.length > 0 && (
            <div className='flex flex-wrap gap-2' role='group' aria-label='Choose an answer'>
              {block.options.map((option) => (
                <Button key={option} type='button' variant='glass' size='sm' className='min-h-9' disabled={!actions.latest || !actions.onAsk} onClick={() => actions.onAsk?.(option)}>
                  {option}
                </Button>
              ))}
            </div>
          )}
        </div>
      );
    case 'handoff_card':
      return (
        <Surface material='quiet' padding='sm' className='flex flex-col gap-2'>
          <span className='text-sm font-medium'>Support summary</span>
          <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
            {block.summary.map((line) => (
              <li key={line}>{line}</li>
            ))}
            <li>
              Reference: <span className='font-mono'>{block.traceId}</span>
            </li>
          </ul>
          <SafeLink href={block.href} onNavigate={actions.onNavigate} className='text-xs font-medium underline underline-offset-2'>
            Write to support from your email app
          </SafeLink>
        </Surface>
      );
    case 'proposal_diff':
      return <ProposalCard proposal={block.proposal} actions={actions} />;
    case 'result_list':
      return (
        <section aria-label={block.title} className='flex flex-col gap-1.5'>
          <span className='text-muted-foreground text-[11px] font-medium tracking-wide uppercase'>{block.title}</span>
          {block.items.length === 0 ? (
            <p className='text-muted-foreground text-sm'>{block.empty ?? 'Nothing here.'}</p>
          ) : (
            <ul className='flex flex-col gap-1'>
              {block.items.map((item, index) => {
                const inner = (
                  <>
                    <span className='min-w-0 text-sm font-medium break-words'>{item.title}</span>
                    {item.excerpt && <span className='text-muted-foreground line-clamp-2 text-xs break-words'>{item.excerpt}</span>}
                    {item.meta && <span className='text-muted-foreground text-[11px] break-words'>{item.meta}</span>}
                  </>
                );
                return (
                  <li key={`${item.kind}-${index}`}>
                    {item.href ? (
                      <SafeLink href={item.href} onNavigate={actions.onNavigate} className='rafii-quiet hover:rafii-glass flex min-h-11 flex-col justify-center rounded-[var(--rafii-radius-control)] px-3 py-2'>
                        {inner}
                      </SafeLink>
                    ) : (
                      <div className='rafii-quiet flex min-h-11 flex-col justify-center rounded-[var(--rafii-radius-control)] px-3 py-2'>{inner}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      );
    default:
      return null;
  }
}

function PlanLines({ title, plan }: { title: string; plan: SiteAgentProposalView['preview']['before'] }) {
  return (
    <div className='flex min-w-0 flex-1 flex-col gap-1'>
      <span className='text-muted-foreground text-[11px] font-medium tracking-wide uppercase'>{title}</span>
      {plan.scheduleText && <span className='text-sm'>{plan.scheduleText}</span>}
      <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
        {plan.plan.map((line, index) => (
          <li key={index}>{[line.when, line.text].filter(Boolean).join(' · ')}</li>
        ))}
        {plan.status && <li>Status: {plan.status}</li>}
      </ul>
      {plan.needs.length > 0 && (
        <ul className='flex flex-col gap-0.5 text-xs'>
          {plan.needs.map((need) => (
            <li key={need}>{need}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ProposalCard({ proposal, actions }: { proposal: SiteAgentProposalView; actions: AnswerActions }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [busy, setBusy] = useState<'apply' | 'dismiss' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [local, setLocal] = useState<SiteAgentProposalView | null>(null);
  const view = local ?? proposal;
  // Apply and Dismiss disappear once used: focus moves to the result line, so it is read out and never drops to the
  // page (where Escape would reach a dialog behind the panel).
  const result = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (local && local.status !== 'proposed') result.current?.focus({ preventScroll: true });
  }, [local]);
  const open = view.status === 'proposed' && Date.now() / 1000 < view.expiresAt;
  const target = actions.messageId && actions.conversationId ? { conversationId: actions.conversationId, messageId: actions.messageId, proposalId: view.id } : null;

  async function refresh() {
    await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    if (actions.conversationId) await client.invalidateQueries({ queryKey: keys.messages(workspaceId, actions.conversationId) });
  }

  async function apply() {
    if (!target) return;
    setBusy('apply');
    setError(null);
    const attempt = async () => {
      const snapshot = client.getQueryData<Snapshot>(keys.snapshot(workspaceId)) ?? (await api.snapshot(workspaceId));
      return api.siteAgentApplyProposal(workspaceId, { ...target, digest: view.digest, expectedRevision: snapshot.revision, timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone });
    };
    try {
      let result;
      try {
        result = await attempt();
      } catch (err) {
        // The workspace moved on for an unrelated reason: read it again and try once more (the proposal's own checks still apply).
        if (!(err instanceof ApiError && err.code === 'workspace_revision_conflict')) throw err;
        await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
        client.setQueryData(keys.snapshot(workspaceId), await api.snapshot(workspaceId));
        result = await attempt();
      }
      setLocal(result.proposal);
      await refresh();
      if (result.proposal.status === 'applied' && result.proposal.type === 'automation_change') {
        window.dispatchEvent(new CustomEvent(AUTOMATION_CHANGED, { detail: { taskId: result.proposal.taskId } }));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The change could not be applied. Nothing was changed.');
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function dismiss() {
    if (!target) return;
    setBusy('dismiss');
    setError(null);
    try {
      setLocal((await api.siteAgentDismissProposal(workspaceId, target)).proposal);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not dismiss the proposal.');
    } finally {
      setBusy(null);
    }
  }

  const scheduling = view.type === 'schedule_draft' || view.type === 'reschedule_post';
  const statusLine: Record<string, string> = {
    applied: scheduling ? 'Prepared. The exact post now waits for approval; nothing publishes until someone approves it.' : 'Applied. The automation now follows the new plan.',
    dismissed: 'Dismissed. Nothing was changed.',
    expired: 'Expired. Nothing was changed; ask again for a fresh proposal.',
    superseded: 'Not applied: the automation changed after this was proposed.',
    failed: 'Not applied.'
  };

  return (
    <Surface material='glass' padding='sm' className='flex flex-col gap-3' role='group' aria-label={`Proposed change to ${view.name}`}>
      <div className='flex items-start justify-between gap-2'>
        <div className='flex min-w-0 flex-col'>
          <span className='text-muted-foreground text-[11px] font-medium tracking-wide uppercase'>Proposed change</span>
          <span className='text-sm font-medium break-words'>{view.name}</span>
        </div>
        {view.requiredPermission === 'owner' && <span className='rafii-quiet shrink-0 rounded-full px-2 py-0.5 text-[11px]'>Owner</span>}
      </div>
      {view.summary.length > 0 && (
        <ul className='flex list-disc flex-col gap-0.5 pl-5 text-sm'>
          {view.summary.map((line) => (
            <li key={line}>{line.charAt(0).toUpperCase() + line.slice(1)}</li>
          ))}
        </ul>
      )}
      <div className='flex flex-col gap-3 @[28rem]:flex-row'>
        <PlanLines title='Now' plan={view.preview.before} />
        <PlanLines title='After' plan={view.preview.after} />
      </div>
      {scheduling && view.text && (
        <details className='rafii-quiet rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
          <summary className='rafii-focus text-muted-foreground cursor-pointer text-xs font-medium'>The exact post ({view.text.length} characters)</summary>
          <p className='mt-2 break-words whitespace-pre-wrap'>{view.text}</p>
        </details>
      )}
      {scheduling && view.needsEdit && view.status === 'proposed' && (
        <p className='text-muted-foreground text-[11px]'>Applying also changes the draft as listed above, so it needs the edit permission as well as approve.</p>
      )}
      {view.status !== 'proposed' || !open ? (
        <div className='flex flex-col gap-2'>
          <p ref={result} tabIndex={-1} role='status' className='text-sm font-medium outline-none'>
            {statusLine[view.status === 'proposed' ? 'expired' : view.status] ?? statusLine.failed}
            {view.status === 'applied' && view.result?.needs?.length ? ` ${view.result.needs.join(' ')}` : ''}
          </p>
          {view.status === 'applied' && scheduling && view.result?.reviewId && <PreparedReview reviewId={view.result.reviewId} onNavigate={actions.onNavigate} />}
        </div>
      ) : (
        <div className='flex flex-wrap items-center gap-2'>
          <Button type='button' variant='action' size='sm' className='min-h-9 px-3' disabled={busy !== null || !target} onClick={() => void apply()}>
            {busy === 'apply' ? 'Applying…' : 'Apply change'}
          </Button>
          <Button type='button' variant='quiet' size='sm' className='min-h-9 px-3' disabled={busy !== null || !target} onClick={() => void dismiss()}>
            Dismiss
          </Button>
          <span className='text-muted-foreground text-[11px]'>Nothing changes until you apply it.</span>
        </div>
      )}
      {error && (
        <p role='alert' className='text-destructive text-xs'>
          {error}
        </p>
      )}
    </Surface>
  );
}

/**
 * A compound request whose writing run was still going when Rafii answered (a local CLI writer): when the run ends,
 * ask the server to finish the steps after it (save, link, propose scheduling). The server does the work and is
 * idempotent; this only says "the run has ended" once.
 */
function CompoundWatcher({ runId, messageId, conversationId }: { runId: string; messageId: string; conversationId: string }) {
  const run = useRun(runId);
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const asked = useRef(false);
  const ended = run && !['running', 'queued'].includes(run.status);
  useEffect(() => {
    if (!ended || asked.current) return;
    asked.current = true;
    void api
      .siteAgentCompoundContinue(workspaceId, { conversationId, messageId, timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone })
      .catch(() => undefined)
      .finally(() => {
        void client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
        void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      });
  }, [ended, api, workspaceId, conversationId, messageId, client]);
  return (
    <p role='status' className='text-muted-foreground flex items-center gap-2 text-xs'>
      <Icons.spinner className='size-3.5 animate-spin motion-reduce:animate-none' aria-hidden />
      {ended ? 'The writer finished; finishing the remaining steps…' : 'The writer is working; the remaining steps run when it finishes.'}
    </p>
  );
}

/** The review a scheduling proposal prepared, with the Queue's own approve button (exact digest, approve permission). */
function PreparedReview({ reviewId, onNavigate }: { reviewId: string; onNavigate?: () => void }) {
  const snapshot = useSnapshot();
  const access = useWorkspaceAccess();
  const client = useQueryClient();
  const { workspaceId } = useWorkspaceApi();
  const review = snapshot.data?.state.phase2?.reviews.find((item) => item.id === reviewId);
  return (
    <div className='flex flex-wrap items-center gap-2'>
      {review && snapshot.data && (
        <ReviewApproveButton
          review={review}
          revision={snapshot.data.revision}
          allowed={checkAccess(access, { permission: 'approve' })}
          nowSeconds={Date.now() / 1000}
          onReload={() => void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) })}
          onOpenJob={() => undefined}
        />
      )}
      {/* The Queue's ?job= opens jobs only: an approved review links to its job, a waiting one to "Waiting for approval". */}
      <SafeLink href={review?.jobId ? `/app/queue?job=${review.jobId}` : '/app/queue'} onNavigate={onNavigate} className='text-xs font-medium underline underline-offset-2'>
        {review?.jobId ? 'Open the approved post in the Queue' : 'Open it in the Queue (Waiting for approval)'}
      </SafeLink>
    </div>
  );
}

const REASONS: { value: 'wrong' | 'unclear' | 'missing' | 'other'; label: string }[] = [
  { value: 'wrong', label: 'Wrong' },
  { value: 'unclear', label: 'Unclear' },
  { value: 'missing', label: 'Missing something' },
  { value: 'other', label: 'Other' }
];

function AnswerMeta({ body, actions }: { body: SiteAgentBody; actions: AnswerActions }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [feedback, setFeedback] = useState(body.feedback ?? null);
  const [asking, setAsking] = useState(false);
  const read = body.context?.read ?? [];
  const withheld = body.context?.withheld ?? [];

  async function rate(value: 'helpful' | 'not_helpful', reason: (typeof REASONS)[number]['value'] | null = null) {
    if (!actions.messageId) return;
    try {
      const saved = await api.siteAgentFeedback(workspaceId, { messageId: actions.messageId, value, reason });
      setFeedback(saved.feedback);
      setAsking(false);
    } catch {
      /* feedback is optional; the answer stands */
    }
  }

  return (
    <div className='flex flex-col gap-2'>
      {actions.latest && (body.followUps?.length ?? 0) > 0 && actions.onAsk && (
        <div className='flex flex-wrap gap-1.5' role='group' aria-label='Suggested follow-ups'>
          {body.followUps!.map((item) => (
            <Button key={item} type='button' variant='glass' size='sm' className='min-h-8 max-w-full truncate text-xs' onClick={() => actions.onAsk?.(item)}>
              {item}
            </Button>
          ))}
        </div>
      )}
      <details className='group text-muted-foreground text-[11px]'>
        <summary className='rafii-focus flex min-h-7 cursor-pointer list-none items-center gap-1 rounded-md select-none'>
          <Icons.chevronRight className='size-3 transition-transform group-open:rotate-90 motion-reduce:transition-none' aria-hidden />
          {body.model?.composedBy === 'model' ? 'Written by your chosen writer from what Rafii read' : 'Answered from Rafii help and your workspace'}
        </summary>
        <div className='flex flex-col gap-1 pt-1 pl-4'>
          {body.context?.route && <span>Page: {body.context.route}{body.context.entity ? ` · selected ${body.context.entity.type}` : ''}</span>}
          <span>Read: {read.length ? read.join(', ') : 'nothing from your workspace'}</span>
          <span>Did not read: {withheld.join(', ')}</span>
        </div>
      </details>
      {actions.messageId && (
        <div className='flex flex-wrap items-center gap-1'>
          {feedback ? (
            <span className='text-muted-foreground text-[11px]' role='status'>
              {feedback.value === 'helpful' ? 'Thanks — marked helpful.' : 'Thanks — noted for improving Rafii.'}
            </span>
          ) : asking ? (
            <>
              <span className='text-muted-foreground text-[11px]'>What was wrong?</span>
              {REASONS.map((reason) => (
                <Button key={reason.value} type='button' variant='quiet' size='xs' onClick={() => void rate('not_helpful', reason.value)}>
                  {reason.label}
                </Button>
              ))}
            </>
          ) : (
            <>
              <Button type='button' variant='quiet' size='xs' aria-label='This answer was helpful' onClick={() => void rate('helpful')}>
                <Icons.check className='size-3' aria-hidden /> Helpful
              </Button>
              <Button type='button' variant='quiet' size='xs' aria-label='This answer was not helpful' onClick={() => setAsking(true)}>
                <Icons.close className='size-3' aria-hidden /> Not helpful
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
