'use client';

import { LayoutGroup, motion } from 'motion/react';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import type { ChannelView, Thread } from '@/lib/api/types';
import { SPRING_LAYOUT } from '@/lib/ease';
import { useMotionPreference } from '@/lib/rafii/motion';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { authorLabel, providerName, replyStatusShort, replyStatusView, threadTime, type ReplyRecord } from './model';

/**
 * The conversation list (DNA §21.5): one hierarchy per row — participant, snippet, account and
 * recency — with the real reply state at the trailing edge. Rows rest on the quiet list surface;
 * the selected row carries the one persistent glass lens, which glides between rows (§18.5).
 * Rows do not stagger in (§18.6); they only glide when a filter reorders them.
 */
export function ThreadList({
  threads,
  selectedId,
  onSelect,
  channelsById,
  latestReply
}: {
  threads: Thread[];
  selectedId: string | null;
  onSelect: (threadId: string) => void;
  channelsById: Map<string, ChannelView>;
  latestReply: (thread: Thread) => ReplyRecord | undefined;
}) {
  const { reduced } = useMotionPreference();
  return (
    <LayoutGroup id='inbox-threads'>
      <ul className='flex flex-col gap-1' aria-label='Comments'>
        {threads.map((thread) => {
          const channel = channelsById.get(thread.connectionId);
          const selected = thread.threadId === selectedId;
          const time = threadTime(thread);
          const reply = latestReply(thread);
          return (
            <motion.li key={thread.threadId} className='relative' layout={reduced ? false : 'position'} transition={{ layout: SPRING_LAYOUT }}>
              {selected && (
                <motion.span
                  layoutId='inbox-selected-thread'
                  aria-hidden
                  className='rafii-glass-selected absolute inset-0 rounded-[var(--rafii-radius-control)]'
                  transition={reduced ? { duration: 0 } : SPRING_LAYOUT}
                />
              )}
              <button
                type='button'
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(thread.threadId)}
                className={cn(
                  'rafii-focus relative flex min-h-14 w-full flex-col gap-1 rounded-[var(--rafii-radius-control)] px-3 py-2.5 text-left transition-colors',
                  !selected && 'hover:bg-foreground/5'
                )}
              >
                <span className='flex min-w-0 items-center gap-2'>
                  <ChannelIcon platform={channel?.platform ?? thread.provider} name={thread.provider} size='xs' />
                  <span className='text-foreground truncate text-sm font-medium'>{authorLabel(thread.author)}</span>
                  {thread.tombstoned && (
                    <AnimatedBadge size='sm' status='neutral' showIcon={false} className='rafii-quiet border-0'>
                      No longer returned
                    </AnimatedBadge>
                  )}
                  {reply && (
                    <AnimatedBadge
                      size='sm'
                      status={replyStatusView(reply.status).badge}
                      showIcon={false}
                      className='rafii-quiet ml-auto border-0'
                      contentKey={reply.status}
                      title={replyStatusView(reply.status).label}
                    >
                      {replyStatusShort(reply.status)}
                    </AnimatedBadge>
                  )}
                </span>
                <span className='text-muted-foreground line-clamp-2 text-sm break-words'>{thread.text || 'No text returned'}</span>
                <span className='text-muted-foreground truncate text-xs'>
                  {channel?.account ?? providerName(thread.provider, channel)} · {time.firstSeen ? 'first seen ' : ''}
                  {relativeTime(time.at)}
                </span>
              </button>
            </motion.li>
          );
        })}
      </ul>
    </LayoutGroup>
  );
}
