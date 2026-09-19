'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { SuccessCheck } from '@/components/ui/success-check';
import type { Member } from '@/lib/api/types';
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { cn } from '@/lib/utils';
import type { WorkspaceRole } from '@/types';
import { FLAGS, ROLES, shortId } from './access-model';

export interface MembersState {
  members: Member[] | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

function HolderRow({
  member,
  editable,
  tour,
  justSaved,
  onEdit
}: {
  member: Member;
  editable: boolean;
  tour: boolean;
  justSaved: boolean;
  onEdit: (member: Member) => void;
}) {
  // Grants change nothing for an owner (holds every right) or a viewer (cannot carry them), so only show them where they apply.
  const grants = member.role === 'viewer' || member.role === 'owner' ? [] : FLAGS.filter((flag) => member[flag.key]);
  const body = (
    <>
      <span className='bg-muted text-muted-foreground flex size-6 shrink-0 items-center justify-center rounded-full' aria-hidden>
        <Icons.user className='size-3.5' />
      </span>
      <span className='flex min-w-0 flex-1 flex-col gap-1'>
        <span className='flex flex-wrap items-center gap-1.5'>
          <span className='font-mono text-xs'>{shortId(member.userId)}</span>
          {member.you && (
            <Badge variant='outline' className='h-4 px-1.5 text-[10px]'>
              you
            </Badge>
          )}
        </span>
        {grants.length > 0 && (
          <span className='flex flex-wrap gap-1'>
            {grants.map((flag) => (
              <Badge key={flag.key} variant='secondary' className='h-4 px-1.5 text-[10px] font-normal' title={flag.label}>
                {flag.short}
              </Badge>
            ))}
          </span>
        )}
      </span>
      {justSaved && <SuccessCheck className='size-4 shrink-0 text-emerald-500' />}
      {editable && !justSaved && <Icons.chevronRight className='text-muted-foreground size-4 shrink-0' aria-hidden />}
    </>
  );
  if (!editable) {
    return <li className='flex items-start gap-2 px-1 py-1.5'>{body}</li>;
  }
  return (
    <li>
      <button
        type='button'
        onClick={() => onEdit(member)}
        data-tour={tour ? 'roles-holder' : undefined}
        aria-label={`Change access for ${shortId(member.userId)}`}
        className='hover:bg-muted/60 focus-visible:ring-ring/50 flex w-full items-start gap-2 rounded-md px-1 py-1.5 text-left transition-colors outline-none focus-visible:ring-2'
      >
        {body}
      </button>
    </li>
  );
}

function Count({ state, value }: { state: MembersState; value: number }) {
  if (state.isLoading) {
    return (
      <>
        <Skeleton className='h-6 w-8' />
        <span className='sr-only'>loading</span>
      </>
    );
  }
  // Unavailable is never shown as 0: a failed or disabled query has no count.
  if (state.error || !state.members) return <span className='text-muted-foreground text-xs'>Unavailable</span>;
  return <DigitSwap value={value} className='text-xl font-semibold tabular-nums' />;
}

/** One card per role with the people who hold it right now (active members only). */
export function RoleCards({
  state,
  canManage,
  justSaved,
  onEdit
}: {
  state: MembersState;
  canManage: boolean;
  justSaved: string | null;
  onEdit: (member: Member) => void;
}) {
  const active = (state.members ?? []).filter((member) => member.status === 'active');
  const holders = (role: WorkspaceRole) => active.filter((member) => member.role === role);
  const editable = (member: Member) => canManage && !member.you && member.role !== 'owner';
  // The tour points at the first person a manager can select, in card order.
  const firstEditable = ROLES.flatMap(holders).find(editable)?.userId ?? null;
  const alone = !state.isLoading && !state.error && state.members !== undefined && active.length === 1;

  return (
    <section className='flex flex-col gap-3' aria-labelledby='roles-cards-heading'>
      <div className='flex flex-col gap-1'>
        <h3 id='roles-cards-heading' className='text-lg font-semibold'>
          Roles
        </h3>
        <p className='text-muted-foreground text-sm'>
          Active members, by role.{canManage ? ' Select a person to change their role or grants.' : ''}
        </p>
      </div>

      {Boolean(state.error) && (
        <Alert variant='destructive'>
          <Icons.alertCircle className='size-4' />
          <AlertTitle>Members could not be loaded</AlertTitle>
          <AlertDescription className='flex flex-wrap items-center gap-2'>
            <span>{state.error instanceof Error ? state.error.message : 'The member list did not respond.'}</span>
            <Button size='sm' variant='outline' onClick={() => state.refetch()}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className='@container' data-tour='roles-cards'>
        <ul className='grid grid-cols-1 gap-3 @lg:grid-cols-2 @3xl:grid-cols-3 @5xl:grid-cols-5'>
          {ROLES.map((role) => {
            const people = holders(role);
            return (
              <li key={role} className='bg-card flex min-w-0 flex-col gap-3 rounded-lg border p-3 @lg:last:col-span-2 @3xl:last:col-span-1'>
                <div className='flex items-start justify-between gap-2'>
                  <div className='flex min-w-0 flex-col gap-0.5'>
                    <p className='font-medium'>{ROLE_LABELS[role]}</p>
                    <p className='text-muted-foreground text-xs'>{ROLE_DESCRIPTIONS[role]}</p>
                  </div>
                  <div className='flex h-7 shrink-0 items-center'>
                    <span className='sr-only'>{ROLE_LABELS[role]} holders:</span>
                    <Count state={state} value={people.length} />
                  </div>
                </div>
                {state.isLoading ? (
                  <div className='flex flex-col gap-1.5' aria-busy>
                    <Skeleton className='h-5 w-full' />
                    <Skeleton className='h-5 w-2/3' />
                  </div>
                ) : state.error || !state.members ? null : people.length === 0 ? (
                  <div className='flex flex-wrap items-center justify-between gap-1 text-sm'>
                    <span className='text-muted-foreground'>No one yet</span>
                    {canManage && role !== 'owner' && (
                      <Link
                        href='/app/workspace/members'
                        className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), '-mr-2')}
                      >
                        Invite <LearnMoreChevron />
                      </Link>
                    )}
                  </div>
                ) : (
                  <ul className='-mx-1 flex flex-col'>
                    {people.map((member) => (
                      <HolderRow
                        key={member.userId}
                        member={member}
                        editable={editable(member)}
                        tour={member.userId === firstEditable}
                        justSaved={member.userId === justSaved}
                        onEdit={onEdit}
                      />
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {alone && canManage && (
        <Empty className='border'>
          <EmptyHeader>
            <EmptyTitle>You’re the only member</EmptyTitle>
            <EmptyDescription>
              Invite someone from Members and pick the role that matches what they should do: an approver for whoever signs off, an
              editor for whoever drafts, a viewer for whoever only needs to read.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Link href='/app/workspace/members' className={cn('t-learn', buttonVariants({ variant: 'outline' }))}>
              Invite someone <LearnMoreChevron />
            </Link>
          </EmptyContent>
        </Empty>
      )}
    </section>
  );
}
