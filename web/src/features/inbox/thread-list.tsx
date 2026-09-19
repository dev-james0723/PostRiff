'use client';

import { LayoutGroup, motion, useReducedMotion } from 'motion/react';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import type { ChannelView, Thread } from '@/lib/api/types';
import { EASE_OUT, SPRING_LAYOUT } from '@/lib/ease';
import { relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { authorLabel, providerName, replyStatusShort, replyStatusView, threadTime, type ReplyRecord } from './model';

/**
 * Rows enter 30ms apart. The last delay plus the entrance stays within the 300ms budget
 * (motion system §5): 3 × 30ms + 200ms = 290ms, so rows past the fourth enter together.
 */
const STAGGER = 0.03;
const STAGGER_CAP = 3;
const ENTER_DURATION = 0.2;

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
  const reduce = useReducedMotion();
  return (
    <LayoutGroup id='inbox-threads'>
      <ul className='flex flex-col gap-1' aria-label='Comments'>
        {threads.map((thread, index) => {
          const channel = channelsById.get(thread.connectionId);
          const selected = thread.threadId === selectedId;
          const time = threadTime(thread);
          const reply = latestReply(thread);
          return (
            <motion.li
              key={thread.threadId}
              className='relative'
              // Rows glide when a filter reorders them, so badges inside (which animate their own layout) move with their row.
              layout={reduce ? false : 'position'}
              initial={reduce ? false : { opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: ENTER_DURATION, ease: EASE_OUT, delay: Math.min(index, STAGGER_CAP) * STAGGER, layout: SPRING_LAYOUT }}
            >
              {selected && (
                <motion.span
                  layoutId='inbox-selected-thread'
                  aria-hidden
                  className='bg-accent absolute inset-0 rounded-lg'
                  transition={reduce ? { duration: 0 } : SPRING_LAYOUT}
                />
              )}
              <button
                type='button'
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(thread.threadId)}
                className={cn(
                  'relative flex w-full flex-col gap-1 rounded-lg px-3 py-2.5 text-left outline-none transition-colors',
                  'focus-visible:ring-ring/50 focus-visible:ring-2',
                  !selected && 'hover:bg-muted/60'
                )}
              >
                <span className='flex min-w-0 items-center gap-2'>
                  <ChannelIcon platform={channel?.platform ?? thread.provider} name={thread.provider} size='xs' />
                  <span className='truncate text-sm font-medium'>{authorLabel(thread.author)}</span>
                  {thread.tombstoned && (
                    <AnimatedBadge size='sm' status='neutral' showIcon={false}>
                      No longer returned
                    </AnimatedBadge>
                  )}
                  {reply && (
                    <AnimatedBadge
                      size='sm'
                      status={replyStatusView(reply.status).badge}
                      showIcon={false}
                      className='ml-auto'
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
