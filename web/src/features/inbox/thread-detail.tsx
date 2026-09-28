'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { MessageBubble, MessageBubbleContent } from '@/components/agents/message-bubble';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import type { ChannelView, EngagementTriage, Thread } from '@/lib/api/types';
import { formatDateTime, relativeTime } from '@/lib/time';
import { STATUS } from '@/lib/status-labels';
import { cn } from '@/lib/utils';
import { InboxLevelBadge } from './level-badge';
import { authorLabel, isAnswered, originLabel, providerName, replyStatusView, threadPermalink, threadTime, type ReplyRecord } from './model';
import { permissionSentence, ReplyComposer, type ComposerState } from './reply-composer';

/** A state row that sits where the composer would (quiet reading surface, DNA §20.1). */
const COMPOSER_STATE = 'rafii-quiet rounded-[var(--rafii-radius-control)] px-3';

/** Title and one meta line for a comment, shared by the side pane and the sheet. */
export function threadHeadline(thread: Thread, channel: ChannelView | undefined) {
  const time = threadTime(thread);
  const platform = providerName(thread.provider, channel);
  return {
    title: authorLabel(thread.author),
    // One date form: relative. The platform is carried by the icon beside it.
    meta: `${channel?.account ?? platform} · ${relativeTime(time.at)}`,
    exactTime: formatDateTime(time.at),
    platform
  };
}

export function ThreadHeading({ thread, channel }: { thread: Thread; channel: ChannelView | undefined }) {
  const headline = threadHeadline(thread, channel);
  return (
    <div className='flex min-w-0 items-center gap-2.5'>
      <ChannelIcon platform={headline.platform} name={headline.platform} />
      <div className='min-w-0'>
        <p className='text-foreground truncate font-medium'>{headline.title}</p>
        <p className='text-muted-foreground truncate text-xs' title={headline.exactTime}>
          {headline.meta}
        </p>
      </div>
    </div>
  );
}

export function ThreadDetail({
  thread,
  channel,
  replies,
  freshReplyIds,
  composer,
  onComposerChange,
  onApproved,
  triage,
  replySendingEnabled,
  canEdit,
  canReply
}: {
  thread: Thread;
  channel: ChannelView | undefined;
  replies: ReplyRecord[];
  freshReplyIds: ReadonlySet<string>;
  composer: ComposerState;
  onComposerChange: (patch: Partial<ComposerState>) => void;
  onApproved: (reply: ReplyRecord) => void;
  triage?: EngagementTriage['items'][number];
  replySendingEnabled: boolean;
  canEdit: boolean;
  canReply: boolean;
}) {
  const [writeAnother, setWriteAnother] = useState(false);
  const platform = providerName(thread.provider, channel);
  const permalink = threadPermalink(thread);
  const accountLabel = channel?.account ?? 'this account';
  const answered = replies.some(isAnswered);
  const latestAnswered = replies.findLast(isAnswered);

  let composerArea;
  if (thread.tombstoned) {
    composerArea = (
      <StateMessage
        kind='stale'
        layout='inline'
        title='Replying is closed.'
        className={COMPOSER_STATE}
      />
    );
  } else if (thread.replyLevel !== 'Direct') {
    // Reply grant shown honestly: the verified level and the platform's own reply path. Evidence lives on the coverage chips.
    composerArea = (
      <div data-tour='inbox-composer'>
        <StateMessage
          kind='unsupported'
          layout='inline'
          title={
            <span className='inline-flex flex-wrap items-center gap-1.5'>
              Can&apos;t reply from Rafii <InboxLevelBadge level={thread.replyLevel} />
            </span>
          }
          action={
            permalink ? (
              <a href={permalink} target='_blank' rel='noreferrer' className={cn(buttonVariants({ variant: 'glass', size: 'control' }), 'gap-2')}>
                Reply on {platform}
                <Icons.externalLink className='size-4' aria-hidden />
              </a>
            ) : undefined
          }
          className={COMPOSER_STATE}
        />
      </div>
    );
  } else if (!canEdit && !canReply) {
    composerArea = (
      <div data-tour='inbox-composer'>
        <StateMessage kind='permission' layout='inline' title={STATUS.readOnly} description={permissionSentence(false, false)} className={COMPOSER_STATE} />
      </div>
    );
  } else if (answered && !writeAnother) {
    composerArea = (
      <div className='rafii-quiet flex flex-wrap items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2.5 text-sm' data-tour='inbox-composer'>
        <span className='text-muted-foreground inline-flex items-center gap-2'>
          <Icons.check className='size-4 shrink-0' aria-hidden />
          {latestAnswered ? replyStatusView(latestAnswered.status).label : 'Reply approved'}
        </span>
        {latestAnswered?.status === 'approved' && latestAnswered.requiresReconfirmation && replySendingEnabled && canReply && (
          <Button variant='glass' size='control' onClick={() => {
            onComposerChange({ text: latestAnswered.text, draft: { draftId: latestAnswered.draftId, text: latestAnswered.text, origin: latestAnswered.origin ?? 'manual', label: latestAnswered.label ?? 'Saved reply' } });
            setWriteAnother(true);
          }}>
            Review this reply again
          </Button>
        )}
        {canEdit && latestAnswered?.status === 'verified' && (
          <Button variant='glass' size='control' onClick={() => setWriteAnother(true)}>
            Write another
          </Button>
        )}
      </div>
    );
  } else {
    composerArea = (
      <ReplyComposer
        thread={thread}
        accountLabel={accountLabel}
        platform={platform}
        permalink={permalink}
        state={composer}
        onChange={onComposerChange}
        onApproved={(reply) => {
          setWriteAnother(false);
          onApproved(reply);
        }}
        canEdit={canEdit}
        canReply={canReply}
        disableSuggestion={triage?.category === 'spam' || triage?.category === 'abusive'}
      />
    );
  }

  return (
    <div className='flex flex-col gap-5'>
      <div className='flex flex-col gap-2'>
        {triage && <p className='text-muted-foreground text-sm' aria-label='Engagement Copilot assessment'>
          {triage.priority.replaceAll('_', ' ')} · {triage.category.replaceAll('_', ' ')} · {triage.why}
        </p>}
        {thread.tombstoned && (
          <AnimatedBadge size='sm' status='neutral' className='rafii-quiet w-fit border-0'>
            No longer on {platform}
          </AnimatedBadge>
        )}
        <MessageBubble align='start' variant='soft'>
          <MessageBubbleContent className='break-words whitespace-pre-wrap'>{thread.text || 'No text'}</MessageBubbleContent>
        </MessageBubble>
        <div className='text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs'>
          {/* When PostRiff cannot reply, the reply state below carries the same link as "Reply on …". */}
          {permalink && (thread.tombstoned || thread.replyLevel === 'Direct') && (
            <a
              href={permalink}
              target='_blank'
              rel='noreferrer'
              title={`Post ${thread.providerPostId}`}
              className='rafii-focus hover:text-foreground inline-flex items-center gap-1 rounded-sm underline underline-offset-2'
            >
              Open on {platform}
              <Icons.externalLink className='size-3' aria-hidden />
            </a>
          )}
        </div>
      </div>

      {replies.length > 0 && (
        <section aria-label='Replies' className='flex flex-col gap-3' data-tour='inbox-replies'>
          {replies.map((reply) => {
            const status = replyStatusView(reply.status);
            return (
              <div key={reply.draftId} className='flex flex-col items-end gap-1'>
                <MessageBubble align='end' variant='tint' animateIn={freshReplyIds.has(reply.draftId)}>
                  <MessageBubbleContent className='break-words whitespace-pre-wrap'>{reply.text || 'No text'}</MessageBubbleContent>
                </MessageBubble>
                <div className='text-muted-foreground flex flex-wrap items-center justify-end gap-1.5 text-xs'>
                  <AnimatedBadge size='sm' status={status.badge} contentKey={reply.status} className='rafii-quiet border-0'>
                    {status.label}
                  </AnimatedBadge>
                  <span>{originLabel(reply.origin, reply.label)}</span>
                  {reply.updatedAt ? <span>· {relativeTime(reply.updatedAt)}</span> : null}
                </div>
                {reply.events && reply.events.length > 0 && <ol className='text-muted-foreground text-xs' aria-label='Reply receipt timeline'>
                  {reply.events.map((event, index) => <li key={`${event.state}-${event.at}-${index}`}>
                    {event.state.replaceAll('_', ' ')} · {formatDateTime(event.at)}{event.message ? ` · ${event.message}` : ''}
                  </li>)}
                </ol>}
                {reply.providerReference && <span className='text-muted-foreground flex items-center gap-1 text-xs'>
                  Provider reply ID: {reply.providerReference}
                  <Button variant='quiet' size='icon-sm' aria-label='Copy provider reply ID' onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(reply.providerReference!);
                      toast.success('Reply ID copied.');
                    } catch {
                      toast.error("Couldn't copy the reply ID.");
                    }
                  }}><Icons.copy className='size-3.5' /></Button>
                </span>}
              </div>
            );
          })}
        </section>
      )}

      {composerArea}
    </div>
  );
}

/** Shown in the side pane before a comment is picked, or when the linked one is not in the list. */
export function NoThreadSelected({ missing, onClear }: { missing: boolean; onClear: () => void }) {
  return (
    <div className='text-muted-foreground flex h-full min-h-48 flex-col items-center justify-center gap-3 p-6 text-center text-sm'>
      {missing ? (
        <StateMessage
          kind='stale'
          layout='inline'
          title="This comment isn't available."
          action={
            <Button variant='glass' size='control' onClick={onClear}>
              Close
            </Button>
          }
          className='max-w-sm'
        />
      ) : (
        <>
          <span aria-hidden className='rafii-glass flex size-11 items-center justify-center rounded-full'>
            <Icons.messageCircle className='size-5' />
          </span>
          <p>Pick a comment.</p>
        </>
      )}
    </div>
  );
}
