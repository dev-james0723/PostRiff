'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { DraftPreview } from '@/components/application/post-preview/draft-preview';
import { ManifestPreview } from '@/components/application/post-preview/manifest-preview';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { HoldActionButton } from '@/components/motion/hold-action-button';
import { Button } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import type { SnapshotState } from '@/lib/api/types';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { COLUMN_META, findCard, findSuccessor, FOOTER_WORDS, toEpoch, type Board, type BoardCard, type PipelineSource } from './board';
import { HOLD_CANCEL_CLASS, HOLD_CANCEL_FILL, HOLD_CANCEL_WAVE, isCancellable, jobNote, stateWords } from './job-state';
import { canSetAside, cardBadge, copyText, REVISION_ORIGIN, scheduleGate, type CardActions, type CardPermissions } from './pipeline-card';
import { reasonLabel } from './set-aside-dialog';

const KIND_LABEL: Record<BoardCard['kind'], string> = { source: 'Source', draft: 'Draft', review: 'Review', job: 'Publishing job' };

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn('flex flex-col gap-1.5', className)}>
      <h3 className='text-xs font-medium tracking-wide uppercase'>{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, children, mono }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className='grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 py-1.5'>
      <dt className='text-muted-foreground text-xs'>{label}</dt>
      <dd className={cn('min-w-0 text-sm break-words', mono && 'font-mono text-xs')}>{children}</dd>
    </div>
  );
}

/** An epoch as a date and how long ago; a dash when the snapshot has none. */
function When({ at }: { at: number | null }) {
  if (!at) return <span className='text-muted-foreground'>Not recorded</span>;
  return (
    <span>
      {formatDateTime(at)} <span className='text-muted-foreground'>· {relativeTime(at)}</span>
    </span>
  );
}

function TextBlock({ text }: { text: string }) {
  return <p className='text-sm break-words whitespace-pre-wrap'>{text}</p>;
}

const linkClass = 't-learn text-foreground inline-flex items-center gap-0.5 text-sm font-medium hover:underline';

function DraftDetails({ card, board, state, onShow }: { card: BoardCard; board: Board; state: SnapshotState | undefined; onShow: (card: BoardCard) => void }) {
  const variant = card.variant;
  if (!variant || !card.draft) return null;
  const situation = card.draft;
  const channel = state?.phase2?.channels.find((c) => c.platform === variant.platform);
  const sources = (state?.sources ?? []) as PipelineSource[];
  const revisions = (variant.revisions ?? []).toReversed();
  const feedback = (variant.feedback ?? []).toReversed();
  const outcomeJob = situation.outcomeJobId ? findCard(board, `job:${situation.outcomeJobId}`) : null;
  // Only an expired review is still a card; a stale one is gone from the board.
  const outcomeReview = situation.outcomeReviewId ? findCard(board, `review:${situation.outcomeReviewId}`) : null;
  return (
    <>
      <Section title='Preview'>
        <DraftPreview platform={variant.platform} text={card.body} account={channel?.account ?? state?.speaker?.label ?? variant.platform} channelId={channel?.id} scale={0.5} className='self-center' />
        {!channel && <p className='text-muted-foreground text-xs'>No {variant.platform} channel is connected, so the preview uses the workspace’s name.</p>}
      </Section>
      <Separator />
      {variant.proposedUpdate ? (
        <>
          <Section title='Proposed update'>
            <TextBlock text={variant.proposedUpdate.text} />
            <p className='text-muted-foreground text-xs'>Scheduling or editing accepts this update first.</p>
          </Section>
          <Section title={`Current text · revision ${variant.revision}`}>
            <TextBlock text={variant.text} />
          </Section>
        </>
      ) : (
        <Section title={`Text · revision ${variant.revision}`}>
          <TextBlock text={variant.text} />
        </Section>
      )}
      {card.chips.length > 0 && (
        <Section title='Situation'>
          <ul className='flex flex-col gap-1 text-sm'>
            {card.chips.map((chip) => (
              <li key={chip.label}>
                <span className='font-medium'>{chip.label}</span>
                {chip.title && <span className='text-muted-foreground'> · {chip.title}</span>}
              </li>
            ))}
          </ul>
          {outcomeJob && (
            <Button variant='link' size='sm' className='h-auto self-start p-0' onClick={() => onShow(outcomeJob)}>
              Open the {situation.outcome} job
            </Button>
          )}
          {outcomeReview && (
            <Button variant='link' size='sm' className='h-auto self-start p-0' onClick={() => onShow(outcomeReview)}>
              Open the expired review
            </Button>
          )}
          {situation.setAsideBlocked && !situation.setAside && (
            <p className='text-muted-foreground text-xs'>A job for this draft is still waiting, held or published, so it cannot be set aside until that job is cancelled.</p>
          )}
        </Section>
      )}
      {(variant.warnings.length > 0 || variant.unknowns.length > 0) && (
        <Section title='Warnings and unknowns'>
          <ul className='flex list-disc flex-col gap-1 pl-4 text-sm'>
            {variant.warnings.map((warning) => (
              <li key={`w-${warning}`} className='text-amber-600 dark:text-amber-400'>
                {warning}
              </li>
            ))}
            {variant.unknowns.map((unknown) => (
              <li key={`u-${unknown}`}>{unknown}</li>
            ))}
          </ul>
        </Section>
      )}
      <Section title='Sources'>
        {variant.sourceIds.length === 0 ? (
          <p className='text-muted-foreground text-sm'>Written without a source.</p>
        ) : (
          <ul className='flex flex-col gap-1 text-sm'>
            {variant.sourceIds.map((id) => {
              const source = sources.find((s) => s.id === id);
              return (
                <li key={id} className='flex items-center gap-1.5'>
                  <Icons.page className='text-muted-foreground size-3.5 shrink-0' aria-hidden />
                  <span className='truncate'>{source ? source.title || source.kind : 'A source no longer in the workspace'}</span>
                  {source && !source.active && <span className='text-destructive text-xs'>retracted</span>}
                </li>
              );
            })}
          </ul>
        )}
      </Section>
      <Separator />
      <Section title='Revision history'>
        {revisions.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No revisions recorded.</p>
        ) : (
          <ol className='flex flex-col gap-2'>
            {revisions.map((revision) => {
              const at = toEpoch(revision.at);
              return (
                <li key={`${revision.revision}-${revision.origin}`} className='border-l-2 pl-3'>
                  <p className='text-sm'>
                    <span className='font-medium'>{REVISION_ORIGIN[revision.origin] ?? revision.origin.replace(/-/g, ' ')}</span>
                    <span className='text-muted-foreground'>
                      {' '}
                      · revision {revision.revision}
                      {at ? ` · ${formatDateTime(at)}` : ''}
                    </span>
                  </p>
                  <p className='text-muted-foreground line-clamp-2 text-xs whitespace-pre-wrap'>{revision.text}</p>
                </li>
              );
            })}
          </ol>
        )}
      </Section>
      {feedback.length > 0 && (
        <Section title='Set aside notes'>
          <ul className='flex flex-col gap-2'>
            {feedback.map((entry) => (
              <li key={entry.id} className='flex flex-col gap-1'>
                <span className='flex flex-wrap gap-1'>
                  {entry.reasons.map((reason) => (
                    <span key={reason} className='bg-muted rounded-full px-2 py-0.5 text-xs'>
                      {reasonLabel(reason)}
                    </span>
                  ))}
                </span>
                {entry.note && <span className='text-sm'>{entry.note}</span>}
                <span className='text-muted-foreground text-xs'>
                  Revision {entry.revision} · {formatDateTime(toEpoch(entry.at))}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}

function ManifestDetails({ card, board, onShow }: { card: BoardCard; board: Board; onShow: (card: BoardCard) => void }) {
  const manifest = card.review?.manifest ?? card.job?.manifest;
  if (!manifest) return null;
  const draft = card.variantId ? findCard(board, `draft:${card.variantId}`) : null;
  return (
    <>
      <Section title='Preview'>
        <ManifestPreview manifest={manifest} scale={0.5} className='self-center' />
      </Section>
      <Separator />
      <Section title={`Exact text · revision ${manifest.contentRevision}`}>
        <TextBlock text={manifest.payload.text} />
        {draft && (
          <Button variant='link' size='sm' className='h-auto self-start p-0' onClick={() => onShow(draft)}>
            Open the draft it came from
          </Button>
        )}
      </Section>
    </>
  );
}

function ReviewDetails({ card, permissions }: { card: BoardCard; permissions: CardPermissions }) {
  const review = card.review;
  if (!review) return null;
  const { manifest } = review;
  // The board put it in "Expired" because `store.py` approve refuses a review past `expiresAt`.
  const expired = card.footer;
  return (
    <Section title='Review'>
      <dl className='divide-y'>
        <Row label='Account'>
          {manifest.platform} · {manifest.account}
        </Row>
        <Row label='Publish at'>
          <When at={toEpoch(manifest.timing.utc)} />
          <span className='text-muted-foreground block text-xs'>
            Chosen as {manifest.timing.local.replace('T', ' ')} ({manifest.timing.timeZone})
          </span>
        </Row>
        <Row label='Prepared'>
          <When at={toEpoch(review.createdAt)} />
        </Row>
        <Row label='Approve before'>
          <When at={toEpoch(manifest.expiresAt)} />
        </Row>
        <Row label='Language'>{manifest.payload.language}</Row>
        <Row label='Media'>{manifest.media.length === 0 ? 'None' : `${manifest.media.length} attached`}</Row>
        <Row label='Digest' mono>
          {review.digest.slice(0, 8)}
        </Row>
      </dl>
      <p className={cn('text-xs', expired ? 'text-destructive' : 'text-muted-foreground')}>
        {permissions.readOnly
          ? 'This is a sample workspace, so nothing here can be approved.'
          : expired
            ? 'The approval deadline passed, so this review can no longer be approved. Schedule… the draft again to prepare a new one.'
            : permissions.canApprove
              ? 'Approval happens in the Queue, so every approval has one receipt.'
              : 'An approver approves this exact review in the Queue.'}
      </p>
      {!permissions.readOnly && !expired && (
        <Link href='/app/queue' className={linkClass}>
          {permissions.canApprove ? 'Open in Queue to approve' : 'Open in Queue'} <LearnMoreChevron />
        </Link>
      )}
    </Section>
  );
}

function JobDetails({ card }: { card: BoardCard }) {
  const job = card.job;
  if (!job) return null;
  const { manifest } = job;
  const events = job.events.toReversed();
  const note = jobNote(job);
  return (
    <>
      <Section title='Receipt'>
        <dl className='divide-y'>
          <Row label='Account'>
            {manifest.platform} · {manifest.account}
          </Row>
          <Row label='Scheduled for'>
            <When at={toEpoch(manifest.timing.utc)} />
          </Row>
          <Row label='Approved'>
            <When at={toEpoch(job.approvedAt)} />
          </Row>
          <Row label='Execution'>
            {manifest.execution === 'synthetic' ? (
              <span>
                Fixture <span className='text-muted-foreground'>· a synthetic provider, not a real post</span>
              </span>
            ) : (
              manifest.execution.replace(/[-_]/g, ' ')
            )}
          </Row>
          <Row label='Attempts'>{job.attempts.length}</Row>
          <Row label='Provider reference' mono>
            {job.providerReference || <span className='text-muted-foreground font-sans text-sm'>None yet</span>}
          </Row>
          <Row label='Provider said'>{job.providerConfirmed || <span className='text-muted-foreground'>Nothing yet</span>}</Row>
          <Row label='Verified'>
            {job.verification ? (
              <span>
                {job.verification.method.replace(/_/g, ' ')} · <When at={toEpoch(job.verification.at)} />
              </span>
            ) : (
              <span className='text-muted-foreground'>Not verified</span>
            )}
          </Row>
          {job.cancelRequested && <Row label='Cancel'>Requested</Row>}
        </dl>
        {note && (
          <p className='rounded-md bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300'>
            <span className='font-medium'>{card.jobGroup === 'held' ? 'Held because: ' : 'Next: '}</span>
            {note}
          </p>
        )}
        {job.nextAction && job.nextAction !== note && (
          <p className='text-muted-foreground text-xs'>
            The worker’s last instruction: {job.nextAction}
          </p>
        )}
      </Section>
      <Section title='Events'>
        {events.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No events recorded.</p>
        ) : (
          <ol className='flex flex-col gap-2'>
            {events.map((event, index) => (
              <li key={`${event.at}-${event.state}-${index}`} className='border-l-2 pl-3'>
                <p className='text-sm'>
                  <span className='font-medium'>{stateWords(event.state)}</span>
                  <span className='text-muted-foreground'> · {formatDateTime(toEpoch(event.at))}</span>
                </p>
                {event.message && <p className='text-muted-foreground text-xs'>{event.message}</p>}
              </li>
            ))}
          </ol>
        )}
      </Section>
    </>
  );
}

function SourceDetails({ card }: { card: BoardCard }) {
  const source = card.source;
  if (!source) return null;
  const facts = source.facts ?? [];
  return (
    <>
      <Section title='Text'>
        <TextBlock text={source.text} />
      </Section>
      <Section title='Details'>
        <dl className='divide-y'>
          <Row label='Kind'>{source.kind}</Row>
          <Row label='Visibility'>{source.visibility.replace(/-/g, ' ')}</Row>
          {source.sourcePolicy && <Row label='Use'>{source.sourcePolicy.replace(/_/g, ' ')}</Row>}
          <Row label='Added'>
            <When at={toEpoch(source.createdAt)} />
          </Row>
        </dl>
      </Section>
      <Section title={`Facts · ${facts.filter((f) => f.approved).length} of ${facts.length} approved`}>
        {facts.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No facts were extracted from this source.</p>
        ) : (
          <ul className='flex flex-col gap-1.5 text-sm'>
            {facts.map((fact) => (
              <li key={fact.id} className='flex items-start gap-2'>
                {fact.approved ? (
                  <Icons.check className='mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400' aria-label='Approved' />
                ) : (
                  <Icons.circleDashed className='text-muted-foreground mt-0.5 size-4 shrink-0' aria-label='Not approved' />
                )}
                <span>{fact.text}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Link href='/app/ideas' className={linkClass}>
        Open in Ideas <LearnMoreChevron />
      </Link>
    </>
  );
}

function SheetActions({ card, permissions, actions, cancelPending, holdEpoch }: { card: BoardCard; permissions: CardPermissions; actions: CardActions; cancelPending: boolean; holdEpoch: number }) {
  const { canEdit, canApprove, readOnly } = permissions;
  const variant = card.variant;
  const buttons: ReactNode[] = [];
  if (!readOnly && card.kind === 'job' && card.job && !canApprove && isCancellable(card.job)) {
    buttons.push(
      <span key='cancel' className='text-muted-foreground text-xs'>
        Someone who can approve may cancel this job.
      </span>
    );
  }
  if (!readOnly && card.kind === 'draft' && card.draft && variant) {
    if (canEdit) {
      buttons.push(
        <Button key='edit' variant={card.draft.setAside ? 'default' : 'outline'} size='sm' onClick={() => actions.edit(variant.id)}>
          <Icons.edit data-icon='inline-start' />
          {card.draft.setAside ? 'Edit to restore' : 'Edit'}
        </Button>
      );
    }
    const gate = scheduleGate(card, permissions);
    if (card.draft.schedulable && gate.allowed) {
      buttons.push(
        <Button key='schedule' size='sm' onClick={() => actions.schedule(variant.id)}>
          <Icons.calendarEvent data-icon='inline-start' />
          Schedule…
        </Button>
      );
    }
    if (card.draft.schedulable && !gate.allowed) {
      buttons.push(
        <span key='schedule' className='text-muted-foreground text-xs' title={gate.title}>
          {gate.reason}
        </span>
      );
    }
    if (canSetAside(card, permissions)) {
      buttons.push(
        <Button key='aside' variant='ghost' size='sm' onClick={() => actions.setAside(variant.id)}>
          <Icons.eyeOff data-icon='inline-start' />
          Set aside…
        </Button>
      );
    }
  }
  if (!readOnly && card.kind === 'job' && card.job && canApprove) {
    const job = card.job;
    if (isCancellable(job)) {
      buttons.push(
        <HoldActionButton
          key={`cancel-${holdEpoch}`}
          type='horizontal'
          holdDuration={900}
          holdingLabel='Keep holding…'
          completeLabel='Cancelling…'
          disabled={cancelPending}
          onHoldComplete={() => actions.cancel(job)}
          aria-label={`Hold to cancel the ${job.manifest.platform} post`}
          title='Press and hold (or hold Space) to cancel this post before it is submitted.'
          className={HOLD_CANCEL_CLASS}
          fillClassName={HOLD_CANCEL_FILL}
          waveClassName={HOLD_CANCEL_WAVE}
          labelClassName='text-xs'
        >
          Hold to cancel
        </HoldActionButton>
      );
    }
  }
  buttons.push(
    <Button key='copy' variant='ghost' size='sm' onClick={() => void copyText(card.body)}>
      <Icons.copy data-icon='inline-start' />
      Copy text
    </Button>
  );
  return <div className='flex flex-wrap items-center gap-2'>{buttons}</div>;
}

/**
 * Why a card is where it is, without leaving the page. `opened` is the card as it was when the sheet opened;
 * the sheet always reads the current snapshot's copy, and says where the item went if it left the board.
 */
export function DetailSheet({
  opened,
  board,
  state,
  now,
  permissions,
  actions,
  cancelPending,
  holdEpoch,
  onShow,
  onClose,
  returnFocus
}: {
  opened: BoardCard | null;
  /** The unfiltered board, so a filter change never hides the open item. */
  board: Board;
  state: SnapshotState | undefined;
  now: number;
  permissions: CardPermissions;
  actions: CardActions;
  cancelPending: boolean;
  holdEpoch: number;
  onShow: (card: BoardCard) => void;
  onClose: () => void;
  /** Where focus goes when the sheet closes: the card that opened it, found again if it re-rendered. */
  returnFocus?: () => HTMLElement | null;
}) {
  const isMobile = useIsMobile();
  const current = opened ? findCard(board, opened.key) : null;
  const successor = opened && !current ? findSuccessor(board, opened) : null;
  const card = current ?? opened;
  const badge = current ? cardBadge(current, now) : null;
  const column = card ? COLUMN_META[card.column] : null;

  return (
    <Sheet open={opened !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side={isMobile ? 'bottom' : 'right'}
        finalFocus={returnFocus ? () => returnFocus() ?? true : undefined}
        className={cn('gap-0 overflow-y-auto sm:max-w-[32rem]', isMobile && 'max-h-[85dvh] rounded-t-xl')}
      >
        {card && (
          <>
            <SheetHeader className='pr-12'>
              <SheetTitle className='flex flex-wrap items-center gap-2'>
                {card.platform ? <ChannelIcon platform={card.platform} name={card.platform} /> : <Icons.page className='text-muted-foreground size-5' aria-hidden />}
                <span className='min-w-0 break-words'>{card.title}</span>
                {badge && (
                  <AnimatedBadge size='sm' status={badge.status} pulse={badge.pulse} title={badge.title} contentKey={badge.label}>
                    {badge.label}
                  </AnimatedBadge>
                )}
              </SheetTitle>
              <SheetDescription>
                {[KIND_LABEL[card.kind], card.kind === 'draft' ? null : card.platform, card.language, current && column ? `${column.title}${card.footer ? ` · ${FOOTER_WORDS[card.column]}` : ''}` : null]
                  .filter(Boolean)
                  .join(' · ')}
              </SheetDescription>
            </SheetHeader>
            <div className='flex flex-col gap-5 px-4 pb-4'>
              {!current ? (
                <div className='flex flex-col gap-3 rounded-lg border border-dashed p-4' role='status'>
                  <p className='font-medium'>{successor ? 'This item moved' : 'This item is gone from the board'}</p>
                  <p className='text-muted-foreground text-sm'>
                    {successor
                      ? `It is now in ${COLUMN_META[successor.column].title}${successor.footer ? ` (${FOOTER_WORDS[successor.column]})` : ''}, as the ${KIND_LABEL[successor.kind].toLowerCase()}.`
                      : card.kind === 'source'
                        ? 'The source is no longer active, so it is off the board.'
                        : 'This item is no longer in the workspace.'}
                  </p>
                  {successor && (
                    <Button size='sm' className='self-start' onClick={() => onShow(successor)}>
                      Show it
                    </Button>
                  )}
                  <Separator />
                  <p className='text-muted-foreground text-xs'>As it was when you opened it:</p>
                  <p className='text-muted-foreground line-clamp-6 text-sm whitespace-pre-wrap'>{card.body}</p>
                </div>
              ) : (
                <>
                  <SheetActions card={current} permissions={permissions} actions={actions} cancelPending={cancelPending} holdEpoch={holdEpoch} />
                  {/* A job's instruction is part of its receipt below; a draft's warning or failed job reads first. */}
                  {current.tag && current.kind === 'draft' && <p className='text-sm text-amber-600 dark:text-amber-400'>{current.tag}</p>}
                  {current.kind === 'draft' && <DraftDetails card={current} board={board} state={state} onShow={onShow} />}
                  {(current.kind === 'review' || current.kind === 'job') && <ManifestDetails card={current} board={board} onShow={onShow} />}
                  {current.kind === 'review' && <ReviewDetails card={current} permissions={permissions} />}
                  {current.kind === 'job' && <JobDetails card={current} />}
                  {current.kind === 'source' && <SourceDetails card={current} />}
                </>
              )}
            </div>
            {column && current && (
              <SheetFooter className='border-t'>
                <Link href={column.href} className={linkClass}>
                  {column.cta} <LearnMoreChevron />
                </Link>
              </SheetFooter>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
