'use client';

import { useState } from 'react';
import Link from 'next/link';
import { motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { useAudit } from '@/lib/api/hooks';
import type { AuditEvent } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { ROLE_LABELS } from '@/lib/auth/permissions';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import type { WorkspaceRole } from '@/types';
import { FLAGS, shortId } from './access-model';
import { SectionHeading, StatusChip } from './rafii-parts';

const MAX_ROWS = 10;

/** `member.*` kinds written by hosted.py: update_member, remove_member, leave_workspace. */
const KIND_LABELS: Record<string, string> = {
  'member.updated': 'Access changed',
  'member.removed': 'Removed',
  'member.left': 'Left the workspace'
};

function eventKey(event: AuditEvent, index: number) {
  return event.id ?? `${event.kind}-${event.at}-${index}`;
}

function who(userId: string | undefined, you: string | null) {
  if (!userId) return '—';
  return userId === you ? 'You' : shortId(userId);
}

function Row({ event, you, fresh }: { event: AuditEvent; you: string | null; fresh: boolean }) {
  const reduce = useReducedMotion();
  const meta = event.meta ?? {};
  const role = typeof meta.role === 'string' && meta.role in ROLE_LABELS ? ROLE_LABELS[meta.role as WorkspaceRole] : null;
  const grants = FLAGS.filter((flag) => meta[flag.key] === true);
  // Someone who left is the actor; there is no separate subject to show.
  const subject = event.kind === 'member.left' ? null : event.subject;
  return (
    <motion.li
      initial={fresh ? { opacity: 0, y: reduce ? 0 : 6 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: EASE_OUT }}
      className='flex flex-col gap-1.5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4'
    >
      <div className='flex min-w-0 flex-wrap items-center gap-1.5 text-sm'>
        <StatusChip icon={event.kind === 'member.removed' ? 'minus' : event.kind === 'member.left' ? 'logout' : 'userPen'}>{KIND_LABELS[event.kind] ?? event.kind}</StatusChip>
        {subject ? <span className='text-foreground font-mono text-xs'>{who(subject, you)}</span> : null}
        {role && <StatusChip icon={null}>{role}</StatusChip>}
        {grants.map((flag) => (
          <StatusChip key={flag.key} icon={null} className='font-normal' title={flag.label}>
            {flag.short}
          </StatusChip>
        ))}
        {event.kind === 'member.updated' && role && grants.length === 0 && <span className='text-muted-foreground text-xs'>no extra grants</span>}
      </div>
      <div className='text-muted-foreground flex shrink-0 items-center gap-2 text-xs'>
        <span>by {who(event.actor, you)}</span>
        <span aria-hidden>·</span>
        <time dateTime={new Date(event.at * 1000).toISOString()} title={formatDateTime(event.at)}>
          {relativeTime(event.at)}
        </time>
      </div>
    </motion.li>
  );
}

/**
 * The latest access changes from the workspace audit trail (`member.*` events). The audit endpoint
 * returns the most recent events only, so an empty list says how many events were searched.
 */
export function RecentAccessChanges({ you }: { you: string | null }) {
  const access = useWorkspaceAccess();
  const audit = useAudit();
  const all = audit.data?.events;
  const events = (all ?? []).filter((event) => event.kind.startsWith('member.')).slice(0, MAX_ROWS);
  const ids = events.map(eventKey);
  // Rows already on screen when the list first loads stay still; only ones that arrive later slide in.
  const [known, setKnown] = useState<Set<string> | null>(null);
  if (known === null && audit.data) setKnown(new Set(ids));


  return (
    <section className='flex flex-col gap-3' aria-labelledby='roles-recent-heading' data-tour='roles-recent'>
      <SectionHeading id='roles-recent-heading' title='Recent access changes' />
      {audit.isPending ? (
        <StateMessage kind='loading' title='Loading recent changes…' />
      ) : audit.error ? (
        <StateMessage
          kind='error'
          title='Couldn’t load recent changes.'
          action={
            <Button size='default' variant='glass' onClick={() => void audit.refetch()} disabled={audit.isFetching}>
              <Icons.refresh className={cn(audit.isFetching && 'motion-safe:animate-spin')} /> Retry
            </Button>
          }
        />
      ) : events.length === 0 ? (
        <StateMessage kind='empty' title='No recent access changes' />
      ) : (
        <Surface material='quiet' padding='none' className='py-1'>
          <ul className='flex flex-col'>
            {events.map((event, index) => {
              const key = ids[index];
              return <Row key={key} event={event} you={you} fresh={known !== null && !known.has(key)} />;
            })}
          </ul>
        </Surface>
      )}
      {checkAccess(access, { role: 'admin' }) && (
        <Link href='/app/workspace/audit' className={cn('t-learn w-fit', buttonVariants({ variant: 'quiet', size: 'default' }), '-ml-2.5')}>
          Full audit log <LearnMoreChevron />
        </Link>
      )}
    </section>
  );
}
