'use client';

import { useState } from 'react';
import { MessageBubble, MessageBubbleContent } from '@/components/agents/message-bubble';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Button } from '@/components/ui/button';
import type { ChannelView, Thread } from '@/lib/api/types';
import { formatDateTime, relativeTime } from '@/lib/time';
import { InboxLevelBadge } from './level-badge';
import { authorLabel, isAnswered, originLabel, providerName, replyStatusView, threadPermalink, threadTime, type ReplyRecord } from './model';
import { permissionSentence, ReplyComposer, type ComposerState } from './reply-composer';

/** Title and one meta line for a comment, shared by the side pane and the sheet. */
export function threadHeadline(thread: Thread, channel: ChannelView | undefined) {
  const time = threadTime(thread);
  const platform = providerName(thread.provider, channel);
  return {
    title: authorLabel(thread.author),
    meta: `${channel?.account ?? platform} · ${platform} · ${time.firstSeen ? 'first seen ' : ''}${formatDateTime(time.at)}`,
    platform
  };
}

export function ThreadHeading({ thread, channel }: { thread: Thread; channel: ChannelView | undefined }) {
  const headline = threadHeadline(thread, channel);
  return (
    <div className='flex min-w-0 items-center gap-2'>
      <ChannelIcon platform={headline.platform} name={headline.platform} />
      <div className='min-w-0'>
        <p className='truncate font-medium'>{headline.title}</p>
        <p className='text-muted-foreground truncate text-xs'>{headline.meta}</p>
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
  canEdit: boolean;
  canReply: boolean;
}) {
  const [writeAnother, setWriteAnother] = useState(false);
  const platform = providerName(thread.provider, channel);
  const permalink = threadPermalink(thread);
  const accountLabel = channel?.account ?? 'this account';
  const answered = replies.some(isAnswered);
  const replyCapability = channel?.capabilities.reply;

  let composerArea;
  if (thread.tombstoned) {
    composerArea = (
      <p className='text-muted-foreground text-sm'>
        {platform} no longer returns this comment, so replying from here is closed.
      </p>
    );
  } else if (thread.replyLevel !== 'Direct') {
    composerArea = (
      <div className='bg-muted/40 flex flex-col gap-2 rounded-lg border p-3 text-sm' data-tour='inbox-composer'>
        <p className='flex flex-wrap items-center gap-1.5'>
          Replies are <InboxLevelBadge level={thread.replyLevel} /> for {accountLabel}, so PostRiff cannot reply here.
        </p>
        {replyCapability?.evidence?.trim() && <p className='text-muted-foreground text-xs'>{replyCapability.evidence}</p>}
        {permalink && (
          <a href={permalink} target='_blank' rel='noreferrer' className='w-fit text-sm font-medium underline underline-offset-2'>
            Reply on {platform} ↗
          </a>
        )}
      </div>
    );
  } else if (!canEdit && !canReply) {
    composerArea = (
      <p className='text-muted-foreground text-sm' data-tour='inbox-composer'>
        {permissionSentence(false, false)}
      </p>
    );
  } else if (answered && !writeAnother) {
    composerArea = (
      <div className='flex flex-wrap items-center gap-2 text-sm' data-tour='inbox-composer'>
        <span className='text-muted-foreground'>This comment already has an approved reply.</span>
        {canEdit && (
          <Button variant='outline' size='sm' onClick={() => setWriteAnother(true)}>
            Write another reply
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
      />
    );
  }

  return (
    <div className='flex flex-col gap-5'>
      <div className='flex flex-col gap-2'>
        {thread.tombstoned && (
          <AnimatedBadge size='sm' status='neutral' className='w-fit'>
            No longer returned by {platform}
          </AnimatedBadge>
        )}
        <MessageBubble align='start' variant='soft'>
          <MessageBubbleContent className='break-words whitespace-pre-wrap'>{thread.text || 'No text returned'}</MessageBubbleContent>
        </MessageBubble>
        <div className='text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs'>
          <span>On post {thread.providerPostId}</span>
          {/* When PostRiff cannot reply, the reply card below carries the same link as "Reply on …". */}
          {permalink && (thread.tombstoned || thread.replyLevel === 'Direct') && (
            <a href={permalink} target='_blank' rel='noreferrer' className='hover:text-foreground inline-flex items-center gap-1 underline underline-offset-2'>
              Open on {platform} ↗
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
                  <MessageBubbleContent className='break-words whitespace-pre-wrap'>{reply.text || 'No text returned'}</MessageBubbleContent>
                </MessageBubble>
                <div className='text-muted-foreground flex flex-wrap items-center justify-end gap-1.5 text-xs'>
                  <AnimatedBadge size='sm' status={status.badge} contentKey={reply.status}>
                    {status.label}
                  </AnimatedBadge>
                  <span>{originLabel(reply.origin, reply.label)}</span>
                  {reply.updatedAt ? <span>· {relativeTime(reply.updatedAt)}</span> : null}
                </div>
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
    <div className='text-muted-foreground flex h-full min-h-48 flex-col items-center justify-center gap-2 p-6 text-center text-sm'>
      <Icons.messageCircle className='size-6' />
      {missing ? (
        <>
          <p>This comment is not in the list the server returned.</p>
          <Button variant='outline' size='sm' onClick={onClear}>
            Close it
          </Button>
        </>
      ) : (
        <p>Pick a comment to read it and reply.</p>
      )}
    </div>
  );
}
