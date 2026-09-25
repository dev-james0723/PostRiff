'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { useFlash } from '@/hooks/use-flash';
import { useMembers } from '@/lib/api/hooks';
import type { Member, Membership } from '@/lib/api/types';
import { ALL_PERMISSIONS, checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { useAuth } from '@/lib/auth/session';
import { cn } from '@/lib/utils';
import { useWorkspace } from '@/lib/workspace/provider';
import { ASSIGNABLE_ROLES, canAssignRole, FLAGS, flagsOf, howToGetMore, PERMISSION_LABELS, STEP_UP_ACTIONS } from './access-model';
import { MemberAccessSheet } from './member-access-sheet';
import { PermissionMatrix } from './permission-matrix';
import { Panel, SectionHeading, StatusChip } from './rafii-parts';
import { RecentAccessChanges } from './recent-access-changes';
import { RoleCards } from './role-cards';

const infoContent = {
  title: 'Roles and grants',
  sections: [
    {
      title: 'Five roles, four grants',
      description: 'A grant adds one right (approve, reply, moderate, manage connections) without changing someone’s role. It never applies to a viewer.',
      links: [{ title: 'Members', url: '/app/workspace/members' }]
    },
    {
      title: 'Who can change access',
      description: 'Only the owner or an admin. Nobody can change their own access, and you can only hand out grants you hold.'
    },
    {
      title: 'Recent sign-in needed',
      description: 'Sensitive changes need a recent sign-in. Every change is recorded in the audit log.',
      links: [{ title: 'Audit log', url: '/app/workspace/audit' }]
    }
  ]
};

function sameMembership(a: Membership, b: Membership) {
  const fa = flagsOf(a);
  const fb = flagsOf(b);
  return a.role === b.role && FLAGS.every((flag) => fa[flag.key] === fb[flag.key]);
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className='text-muted-foreground text-xs font-medium'>{children}</span>;
}

/** Where the signed-in member stands, from the workspace membership the menus and page gates use. */
function YourAccess({ membership, fresh, canManage }: { membership: Membership; fresh: Membership | null; canManage: boolean }) {
  const access = useWorkspaceAccess();
  const workspace = useWorkspace();
  const role = membership.role;
  const owner = role === 'owner';
  const flags = flagsOf(membership);
  const held = FLAGS.filter((flag) => flags[flag.key]);
  const permissions = ALL_PERMISSIONS.filter((permission) => access.permissions.includes(permission));
  const more = howToGetMore(membership);
  // The members endpoint reports the caller's membership as the API sees it now; the provider loaded earlier.
  const drifted = fresh !== null && !sameMembership(membership, fresh);
  const roles = ASSIGNABLE_ROLES.filter((r) => canAssignRole(membership, r));

  return (
    <Panel material='glass' data-tour='roles-you' title='Your access' titleId='roles-you-heading' bodyClassName='gap-5'>
      <div className='grid gap-4 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_minmax(0,14rem)]'>
        <div className='flex flex-col gap-1.5'>
          <FieldLabel>Your role</FieldLabel>
          <StatusChip icon='user' className='w-fit'>
            {ROLE_LABELS[role]}
          </StatusChip>
          <p className='text-muted-foreground text-xs'>{ROLE_DESCRIPTIONS[role]}</p>
        </div>
        <div className='flex flex-col gap-1.5'>
          <FieldLabel>What you can do</FieldLabel>
          {permissions.length === 0 ? (
            <p className='text-muted-foreground text-sm'>Nothing in this workspace.</p>
          ) : (
            <ul className='flex flex-wrap gap-1.5'>
              {permissions.map((permission) => (
                <li key={permission}>
                  <StatusChip icon='check' title={PERMISSION_LABELS[permission].label}>
                    {PERMISSION_LABELS[permission].short}
                  </StatusChip>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className='flex flex-col gap-1.5'>
          <FieldLabel>Your extra grants</FieldLabel>
          {owner ? (
            <p className='text-muted-foreground text-sm'>Not needed as owner</p>
          ) : held.length === 0 ? (
            <p className='text-muted-foreground text-sm'>None</p>
          ) : (
            <>
              <ul className='flex flex-wrap gap-1.5'>
                {held.map((flag) => (
                  <li key={flag.key}>
                    <StatusChip icon={null} className={role === 'viewer' ? 'line-through' : undefined} title={flag.label}>
                      {flag.short}
                    </StatusChip>
                  </li>
                ))}
              </ul>
              {role === 'viewer' && <p className='text-muted-foreground text-xs'>Inactive: grants never apply to a viewer.</p>}
            </>
          )}
        </div>
      </div>

      <div className={cn('grid gap-4', canManage && 'md:grid-cols-2')}>
        <div className='flex flex-col gap-1.5'>
          <FieldLabel>{owner ? 'As the owner' : 'To do more'}</FieldLabel>
          {owner ? (
            <p className='text-foreground text-sm'>Every permission, billing and deletion.</p>
          ) : (
            <ul className='flex flex-col gap-1 text-sm'>
              {more.map((line) => (
                <li key={line} className='flex gap-2'>
                  <Icons.chevronRight className='text-muted-foreground mt-0.5 size-3.5 shrink-0' aria-hidden />
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {canManage && (
          <div className='flex flex-col gap-2' data-tour='roles-grants'>
            <FieldLabel>What you can hand out</FieldLabel>
            <div className='flex flex-wrap items-center gap-1.5'>
              <span className='text-muted-foreground text-xs'>Roles</span>
              {roles.map((r) => (
                <StatusChip key={r} icon={null}>
                  {ROLE_LABELS[r]}
                </StatusChip>
              ))}
            </div>
            <div className='flex flex-wrap items-center gap-1.5'>
              <span className='text-muted-foreground text-xs'>Grants</span>
              {FLAGS.map((flag) => {
                const yours = owner || flags[flag.key];
                return (
                  <StatusChip key={flag.key} icon={null} className={cn(!yours && 'text-muted-foreground line-through')} title={yours ? flag.label : `${flag.label}: you do not hold it`}>
                    {flag.short}
                    {!yours && <span className='sr-only'> (you do not hold it)</span>}
                  </StatusChip>
                );
              })}
            </div>
            <p className='text-muted-foreground text-xs'>Only grants you hold. Nobody can change their own access.</p>
          </div>
        )}
      </div>

      {drifted && (
        <StateMessage
          kind='stale'
          layout='inline'
          className='rafii-quiet rounded-[var(--rafii-radius-control)] px-4 py-3'
          title='Your access changed.'
          description='Reload to update the menus.'
          action={
            <Button size='default' variant='glass' onClick={() => void workspace.refresh()}>
              Reload access
            </Button>
          }
        />
      )}
    </Panel>
  );
}

/** Actions the API only accepts shortly after a fresh sign-in (`assert_fresh`), whatever the role. */
function SensitiveChanges() {
  return (
    <section className='flex flex-col gap-3' aria-labelledby='roles-stepup-heading' data-tour='roles-stepup'>
      <SectionHeading
        id='roles-stepup-heading'
        title='Sensitive changes'
        description='These need a recent sign-in. If yours is too old, sign in again and retry.'
      />
      <ul className='flex flex-wrap gap-1.5'>
        {STEP_UP_ACTIONS.map((action) => (
          <li key={action}>
            <StatusChip icon='lock' className='font-normal'>
              {action}
            </StatusChip>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RolesView() {
  const access = useWorkspaceAccess();
  const canManage = checkAccess(access, { permission: 'manage_members' });
  const workspace = useWorkspace();
  const auth = useAuth();
  const members = useMembers();
  const [target, setTarget] = useState<Member | null>(null);
  const [open, setOpen] = useState(false);
  const [justSaved, flashSaved] = useFlash<string>();

  // `isPending`, not `isLoading`: a query whose retries are paused (offline, hidden tab) has no data yet and must not read as empty.
  const list = members.data?.members;
  const you = list?.find((member) => member.you)?.userId ?? auth.user?.id ?? null;
  // The members endpoint returns the caller's membership as the API sees it now.
  const actor = members.data?.membership ?? workspace.membership;

  return (
    <PageContainer
      pageTitle='Roles'
      infoContent={infoContent}
      access={access.hasWorkspace}
      accessFallback={<StateMessage kind='permission' className='w-full max-w-md' title='Join or create a workspace first.' />}
      pageHeaderAction={
        canManage ? (
          <Link href='/app/workspace/members' className={cn('t-learn', buttonVariants({ variant: 'glass', size: 'control' }))}>
            Manage members <LearnMoreChevron />
          </Link>
        ) : undefined
      }
    >
      <div className='flex min-w-0 flex-col gap-6 md:gap-8'>
        {workspace.membership && <YourAccess membership={workspace.membership} fresh={members.data?.membership ?? null} canManage={canManage} />}
        <RoleCards
          state={{ members: list, isLoading: members.isPending, error: members.error, refetch: () => void members.refetch() }}
          canManage={canManage}
          justSaved={justSaved}
          onEdit={(member) => {
            setTarget(member);
            setOpen(true);
          }}
        />
        <PermissionMatrix yourRole={workspace.membership?.role ?? null} />
        <SensitiveChanges />
        {/* Any member may read the audit API, but who sees access history here is a product decision; managers only for now. */}
        {canManage && <RecentAccessChanges key={workspace.workspaceId ?? 'none'} you={you} />}
      </div>
      {canManage && <MemberAccessSheet member={target} actor={actor} open={open} onOpenChange={setOpen} onSaved={flashSaved} />}
    </PageContainer>
  );
}
