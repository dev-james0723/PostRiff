'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import type { AuditEvent } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDateTime, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { describeAuditEvent, linkFor, metaRows, personOf, subjectLabel, type AuditLookup } from './audit-model';
import { PersonChip } from './audit-row';

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className='flex flex-col gap-1'>
      <dt className='text-muted-foreground text-xs'>{label}</dt>
      <dd className='min-w-0 text-sm'>{children}</dd>
    </div>
  );
}

/** Everything one event holds: the sentence, the person, the ids it points at and each detail it carries. */
export function AuditDetailSheet({
  event,
  lookup,
  now,
  onClose
}: {
  event: AuditEvent | null;
  lookup: AuditLookup;
  now: number;
  onClose: () => void;
}) {
  const isMobile = useIsMobile();
  const access = useWorkspaceAccess();

  return (
    <Sheet open={event !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side={isMobile ? 'bottom' : 'right'} className='data-[side=bottom]:max-h-[92dvh] data-[side=right]:sm:max-w-md'>
        {event && <Body event={event} lookup={lookup} now={now} canOpen={(check) => checkAccess(access, check)} />}
      </SheetContent>
    </Sheet>
  );
}

function Body({
  event,
  lookup,
  now,
  canOpen
}: {
  event: AuditEvent;
  lookup: AuditLookup;
  now: number;
  canOpen: (check: Parameters<typeof checkAccess>[1]) => boolean;
}) {
  const described = describeAuditEvent(event, lookup);
  const person = personOf(event.actor, lookup);
  const subject = subjectLabel(event);
  const rows = metaRows(event, lookup);
  const link = linkFor(event.kind);

  return (
    <>
      <SheetHeader>
        <SheetTitle className='pr-8'>{described.headline}</SheetTitle>
        <SheetDescription>
          <time dateTime={new Date(event.at * 1000).toISOString()}>{formatDateTime(event.at)}</time> · {relativeTime(event.at, now)}
        </SheetDescription>
      </SheetHeader>
      <dl className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4'>
        {described.detail && <Field label='About'>{described.detail}</Field>}
        <Field label='Who'>
          <div className='flex flex-col gap-1'>
            <PersonChip person={person} className='w-fit' />
            <span className='text-muted-foreground text-xs'>{person.explains}</span>
            {person.id && <span className='text-muted-foreground font-mono text-xs break-all select-all'>{person.id}</span>}
          </div>
        </Field>
        {subject && (
          <Field label={subject}>
            <span className='font-mono text-xs break-all select-all'>{event.subject}</span>
          </Field>
        )}
        <Field label='Details'>
          {rows.length === 0 ? (
            <span className='text-muted-foreground'>No extra details.</span>
          ) : (
            <dl className='divide-y rounded-lg border'>
              {rows.map((row) => (
                <div key={row.key} className='flex flex-col gap-0.5 px-3 py-2 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4'>
                  <dt className='text-muted-foreground shrink-0 text-xs'>{row.label}</dt>
                  <dd className='min-w-0 text-sm break-words sm:text-right'>
                    {row.block ? <pre className='bg-muted overflow-x-auto rounded p-2 text-left text-xs'>{row.value}</pre> : row.value}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </Field>
        <Field label='Event kind'>
          <code className='bg-muted rounded px-1.5 py-0.5 text-xs'>{event.kind}</code>
        </Field>
      </dl>
      <SheetFooter className='gap-3'>
        {link && canOpen(link.access) && (
          <Link href={link.href} className={cn('t-learn w-fit', buttonVariants({ variant: 'outline', size: 'sm' }))}>
            Open {link.label} <LearnMoreChevron />
          </Link>
        )}
        <p className='text-muted-foreground text-xs'>
          Events cannot be edited. They hold ids, kinds, counts and times — never post text, prompts, access tokens or email addresses.
        </p>
      </SheetFooter>
    </>
  );
}
