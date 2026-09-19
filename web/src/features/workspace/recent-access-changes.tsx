'use client';

import { useState } from 'react';
import Link from 'next/link';
import { motion, useReducedMotion } from 'motion/react';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { useAudit } from '@/lib/api/hooks';
import type { AuditEvent } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { ROLE_LABELS } from '@/lib/auth/permissions';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import type { WorkspaceRole } from '@/types';
import { FLAGS, shortId } from './access-model';

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
      className='flex flex-col gap-1.5 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4'
    >
      <div className='flex min-w-0 flex-wrap items-center gap-1.5 text-sm'>
        <Badge variant='outline'>{KIND_LABELS[event.kind] ?? event.kind}</Badge>
        {subject ? <span className='font-mono text-xs'>{who(subject, you)}</span> : null}
        {role && <Badge variant='secondary'>{role}</Badge>}
        {grants.map((flag) => (
          <Badge key={flag.key} variant='secondary' className='font-normal' title={flag.label}>
            {flag.short}
          </Badge>
        ))}
        {event.kind === 'member.updated' && role && grants.length === 0 && (
          <span className='text-muted-foreground text-xs'>no extra grants</span>
        )}
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

  const searched = all?.length ?? 0;
  const empty =
    searched === 0
      ? 'Nothing has been recorded in this workspace yet.'
      : `No access changes among the ${searched === 1 ? 'latest workspace event' : `${searched} latest workspace events`}.`;

  return (
    <section className='flex flex-col gap-3' aria-labelledby='roles-recent-heading' data-tour='roles-recent'>
      <div className='flex flex-col gap-1'>
        <h3 id='roles-recent-heading' className='text-lg font-semibold'>
          Recent access changes
        </h3>
        <p className='text-muted-foreground text-sm'>Role and grant changes, removals and departures, newest first.</p>
      </div>
      <div className='rounded-lg border px-4'>
        {audit.isPending ? (
          <div className='py-3'>
            <Skeleton className='h-24 w-full' />
            <span className='sr-only'>Loading recent changes</span>
          </div>
        ) : audit.error ? (
          <div role='alert' className='flex flex-wrap items-center justify-between gap-2 py-3 text-sm'>
            <span className='text-destructive'>Recent changes could not be loaded.</span>
            <Button size='sm' variant='outline' onClick={() => void audit.refetch()} disabled={audit.isFetching}>
              Retry
            </Button>
          </div>
        ) : events.length === 0 ? (
          <p className='text-muted-foreground py-3 text-sm'>{empty}</p>
        ) : (
          <ul className='divide-y'>
            {events.map((event, index) => {
              const key = ids[index];
              return <Row key={key} event={event} you={you} fresh={known !== null && !known.has(key)} />;
            })}
          </ul>
        )}
      </div>
      {checkAccess(access, { role: 'admin' }) && (
        <Link href='/app/workspace/audit' className={cn('t-learn w-fit', buttonVariants({ variant: 'ghost', size: 'sm' }), '-ml-2.5')}>
          Full audit log <LearnMoreChevron />
        </Link>
      )}
    </section>
  );
}
