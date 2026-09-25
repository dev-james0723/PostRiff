'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { DigitSwap } from '@/components/motion/digit-swap';
import { StateMessage, Surface } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { SuccessCheck } from '@/components/ui/success-check';
import type { Member } from '@/lib/api/types';
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { cn } from '@/lib/utils';
import type { WorkspaceRole } from '@/types';
import { FLAGS, ROLES, shortId } from './access-model';
import { SectionHeading, StatusChip } from './rafii-parts';

export interface MembersState {
  members: Member[] | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => void;
}

function HolderRow({ member, editable, tour, justSaved, onEdit }: { member: Member; editable: boolean; tour: boolean; justSaved: boolean; onEdit: (member: Member) => void }) {
  // Grants change nothing for an owner (holds every right) or a viewer (cannot carry them), so only show them where they apply.
  const grants = member.role === 'viewer' || member.role === 'owner' ? [] : FLAGS.filter((flag) => member[flag.key]);
  const body = (
    <>
      <span className='rafii-quiet text-muted-foreground flex size-7 shrink-0 items-center justify-center rounded-full' aria-hidden>
        <Icons.user className='size-3.5' />
      </span>
      <span className='flex min-w-0 flex-1 flex-col gap-1'>
        <span className='flex flex-wrap items-center gap-1.5'>
          <span className='text-foreground font-mono text-xs'>{shortId(member.userId)}</span>
          {member.you && (
            <StatusChip icon={null} className='h-6 px-2 text-xs'>
              you
            </StatusChip>
          )}
        </span>
        {grants.length > 0 && (
          <span className='flex flex-wrap gap-1'>
            {grants.map((flag) => (
              <StatusChip key={flag.key} icon={null} className='h-6 px-2 text-xs font-normal' title={flag.label}>
                {flag.short}
              </StatusChip>
            ))}
          </span>
        )}
      </span>
      {justSaved && <SuccessCheck className='text-foreground size-4 shrink-0' />}
      {editable && !justSaved && <Icons.chevronRight className='text-muted-foreground size-4 shrink-0' aria-hidden />}
    </>
  );
  if (!editable) {
    return <li className='flex min-h-11 items-center gap-2 px-2 py-1.5'>{body}</li>;
  }
  return (
    <li>
      <button
        type='button'
        onClick={() => onEdit(member)}
        data-tour={tour ? 'roles-holder' : undefined}
        aria-label={`Change access for ${shortId(member.userId)}`}
        className='rafii-focus hover:rafii-glass flex min-h-11 w-full items-center gap-2 rounded-[var(--rafii-radius-control)] px-2 py-1.5 text-left transition-colors'
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
  return <DigitSwap value={value} className='text-foreground text-xl font-semibold tabular-nums' />;
}

/** One quiet panel per role with the people who hold it right now (active members only). */
export function RoleCards({ state, canManage, justSaved, onEdit }: { state: MembersState; canManage: boolean; justSaved: string | null; onEdit: (member: Member) => void }) {
  const active = (state.members ?? []).filter((member) => member.status === 'active');
  const holders = (role: WorkspaceRole) => active.filter((member) => member.role === role);
  const editable = (member: Member) => canManage && !member.you && member.role !== 'owner';
  // The tour points at the first person a manager can select, in card order.
  const firstEditable = ROLES.flatMap(holders).find(editable)?.userId ?? null;
  const alone = !state.isLoading && !state.error && state.members !== undefined && active.length === 1;

  return (
    <section className='flex flex-col gap-3' aria-labelledby='roles-cards-heading'>
      <SectionHeading id='roles-cards-heading' title='Roles' description={canManage ? 'Select a person to change their access.' : undefined} />

      {Boolean(state.error) && (
        <StateMessage
          kind='error'
          title='Couldn’t load members'
          description={state.error instanceof Error ? state.error.message : undefined}
          action={
            <Button size='default' variant='glass' onClick={() => state.refetch()}>
              <Icons.refresh /> Retry
            </Button>
          }
        />
      )}

      <div className='@container' data-tour='roles-cards'>
        <ul className='grid grid-cols-1 gap-3 @lg:grid-cols-2 @3xl:grid-cols-3 @5xl:grid-cols-5'>
          {ROLES.map((role) => {
            const people = holders(role);
            return (
              <Surface key={role} as='li' material='quiet' padding='sm' className='flex flex-col gap-3 p-4 @lg:last:col-span-2 @3xl:last:col-span-1'>
                <div className='flex items-start justify-between gap-2'>
                  <div className='flex min-w-0 flex-col gap-0.5'>
                    <p className='text-foreground font-medium'>{ROLE_LABELS[role]}</p>
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
                      <Link href='/app/workspace/members' className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'default' }), '-mr-2')}>
                        Invite <LearnMoreChevron />
                      </Link>
                    )}
                  </div>
                ) : (
                  <ul className='-mx-2 flex flex-col'>
                    {people.map((member) => (
                      <HolderRow key={member.userId} member={member} editable={editable(member)} tour={member.userId === firstEditable} justSaved={member.userId === justSaved} onEdit={onEdit} />
                    ))}
                  </ul>
                )}
              </Surface>
            );
          })}
        </ul>
      </div>

      {alone && canManage && (
        <StateMessage
          kind='empty'
          title='You’re the only member'
          action={
            <Link href='/app/workspace/members' className={cn('t-learn', buttonVariants({ variant: 'glass', size: 'control' }))}>
              Invite someone <LearnMoreChevron />
            </Link>
          }
        />
      )}
    </section>
  );
}
